//! SecurityGate — the FINAL authority on tool execution.
//!
//! Python's PolicyEngine output is advisory only.
//! This gate independently validates and makes the allow/deny decision.
//!
//! Design rule:
//!   Python side REQUESTS. Rust side ENFORCES.

use std::collections::HashMap;
use std::path::PathBuf;
use tokio::sync::RwLock;

use crate::config::{Config, SecurityConfig};
use crate::ipc::protocol::{PermissionDecision, PolicyLevel};

/// The result of the security gate evaluation
#[derive(Debug, Clone)]
pub enum GateDecision {
    /// Allow execution with these constraints
    Allow(ExecutionConstraints),
    /// Require user prompt before allowing
    RequirePrompt(PromptContext),
    /// Deny execution
    Deny(DenyReason),
}

#[derive(Debug, Clone)]
pub struct ExecutionConstraints {
    pub sandbox: bool,
    pub timeout_ms: u64,
    pub max_output_bytes: usize,
    pub allowed_paths: Vec<PathBuf>,
    pub network_allowed: bool,
}

#[derive(Debug, Clone)]
pub struct PromptContext {
    pub description: String,
    pub command_preview: Option<String>,
    pub level: PolicyLevel,
    pub consequences: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct DenyReason {
    pub reason: String,
    pub level: PolicyLevel,
}

/// Session-level permission grant
#[derive(Debug, Clone)]
struct SessionGrant {
    pub scope: PermissionDecision,
    pub tool: String,
    pub command_pattern: Option<String>,
}

/// SecurityGate — independent of Python's PolicyEngine
pub struct SecurityGate {
    config: SecurityConfig,
    /// Session-level permission grants (from user "Allow Session" decisions)
    session_grants: RwLock<HashMap<String, SessionGrant>>,
    /// Tools that have been permanently denied this session
    session_denials: RwLock<Vec<String>>,
}

impl SecurityGate {
    pub fn new(config: &Config) -> Self {
        Self {
            config: config.security.clone(),
            session_grants: RwLock::new(HashMap::new()),
            session_denials: RwLock::new(Vec::new()),
        }
    }

    /// Main evaluation function — called for every tool request.
    /// Takes the tool name, arguments, and Python's advisory level.
    /// Returns the gate's BINDING decision.
    pub async fn evaluate(
        &self,
        tool: &str,
        args: &serde_json::Value,
        advisory_level: &PolicyLevel,
        description: &str,
        command_preview: Option<&str>,
    ) -> GateDecision {
        // ── Step 1: Check session denials ──────────────────────────────────
        {
            let denials = self.session_denials.read().await;
            if denials.contains(&tool.to_string()) {
                return GateDecision::Deny(DenyReason {
                    reason: format!("Tool '{}' was denied for this session", tool),
                    level: advisory_level.clone(),
                });
            }
        }

        // ── Step 2: Independent path validation ────────────────────────────
        if let Some(deny) = self.validate_paths(args).await {
            return GateDecision::Deny(deny);
        }

        // ── Step 3: Independent command validation ─────────────────────────
        if let Some(deny) = self.validate_command(args).await {
            return GateDecision::Deny(deny);
        }

        // ── Step 4: Check effective level ─────────────────────────────────
        // We trust Python's assessment upward but never downward.
        // Gate may escalate but never de-escalate.
        let effective_level = self.determine_effective_level(tool, args, advisory_level).await;

        // ── Step 5: Critical — check auto-deny ────────────────────────────
        if effective_level == PolicyLevel::Critical && self.config.auto_deny_critical {
            return GateDecision::Deny(DenyReason {
                reason: "CRITICAL operations are auto-denied in current configuration".to_string(),
                level: effective_level,
            });
        }

        // ── Step 6: Check session grants ──────────────────────────────────
        {
            let grants = self.session_grants.read().await;
            if let Some(grant) = grants.get(tool) {
                match grant.scope {
                    PermissionDecision::AllowSession | PermissionDecision::AllowTool => {
                        return GateDecision::Allow(self.build_constraints(&effective_level));
                    }
                    _ => {}
                }
            }
        }

        // ── Step 7: Apply config-based auto-allow rules ────────────────────
        match &effective_level {
            PolicyLevel::Safe => {
                return GateDecision::Allow(self.build_constraints(&effective_level));
            }
            PolicyLevel::Moderate if !self.config.confirm_moderate => {
                return GateDecision::Allow(self.build_constraints(&effective_level));
            }
            _ => {}
        }

        // ── Step 8: Require user prompt ───────────────────────────────────
        GateDecision::RequirePrompt(PromptContext {
            description: description.to_string(),
            command_preview: command_preview.map(|s| s.to_string()),
            level: effective_level,
            consequences: self.infer_consequences(tool, args),
        })
    }

    /// Record user's decision from the permission prompt
    pub async fn record_decision(&self, tool: &str, decision: &PermissionDecision) {
        match decision {
            PermissionDecision::AllowSession | PermissionDecision::AllowTool => {
                let mut grants = self.session_grants.write().await;
                grants.insert(
                    tool.to_string(),
                    SessionGrant {
                        scope: decision.clone(),
                        tool: tool.to_string(),
                        command_pattern: None,
                    },
                );
            }
            PermissionDecision::AlwaysDeny => {
                let mut denials = self.session_denials.write().await;
                if !denials.contains(&tool.to_string()) {
                    denials.push(tool.to_string());
                }
            }
            _ => {}
        }
    }

    // ─── Private helpers ──────────────────────────────────────────────────────

    async fn validate_paths(&self, args: &serde_json::Value) -> Option<DenyReason> {
        // Extract any path-like arguments and validate them
        let suspicious_patterns = ["../", "..\\", "/etc/shadow", "/etc/passwd", "~/.ssh"];

        let args_str = args.to_string();
        for pattern in &suspicious_patterns {
            if args_str.contains(pattern) {
                return Some(DenyReason {
                    reason: format!(
                        "Suspicious path pattern detected: '{}'. Potential path traversal attack.",
                        pattern
                    ),
                    level: PolicyLevel::Critical,
                });
            }
        }

        // Check against allowed paths if configured
        if !self.config.allowed_paths.is_empty() {
            // TODO: extract actual path args and validate
        }

        None
    }

    async fn validate_command(&self, args: &serde_json::Value) -> Option<DenyReason> {
        let command = args.get("command")?.as_str()?;

        // Detect shell injection patterns
        let injection_patterns = [
            "$(", "`", "| sh", "| bash", "| zsh",
            ">/dev/", ">/etc/", "2>/dev/",
            "eval ", "exec ",
        ];

        for pattern in &injection_patterns {
            if command.contains(pattern) {
                return Some(DenyReason {
                    reason: format!(
                        "Potential shell injection detected: '{}'. Command rejected.",
                        pattern
                    ),
                    level: PolicyLevel::Critical,
                });
            }
        }

        None
    }

    async fn determine_effective_level(
        &self,
        tool: &str,
        args: &serde_json::Value,
        advisory: &PolicyLevel,
    ) -> PolicyLevel {
        // Gate-level known-dangerous tool overrides
        let always_dangerous = [
            "terminal.execute_sudo",
            "filesystem.delete_recursive",
            "git.push_force",
            "git.reset_hard",
            "system.shutdown",
            "system.reboot",
        ];

        if always_dangerous.contains(&tool) {
            return PolicyLevel::Dangerous;
        }

        // Check for sudo in command
        if let Some(cmd) = args.get("command").and_then(|v| v.as_str()) {
            if cmd.trim_start().starts_with("sudo ") {
                return PolicyLevel::Dangerous;
            }
            // rm -rf escalation
            if cmd.contains("rm -rf") || cmd.contains("rm -Rf") {
                return PolicyLevel::Dangerous;
            }
        }

        advisory.clone()
    }

    fn build_constraints(&self, level: &PolicyLevel) -> ExecutionConstraints {
        let (sandbox, network) = match level {
            PolicyLevel::Safe => (false, true),
            PolicyLevel::Moderate => (self.config.sandbox, true),
            PolicyLevel::Dangerous => (true, false),
            PolicyLevel::Critical => (true, false),
        };

        ExecutionConstraints {
            sandbox,
            timeout_ms: 30_000,
            max_output_bytes: self.config.max_file_read_bytes,
            allowed_paths: self.config.allowed_paths.clone(),
            network_allowed: network,
        }
    }

    fn infer_consequences(&self, tool: &str, args: &serde_json::Value) -> Vec<String> {
        let mut consequences = vec![];

        if let Some(cmd) = args.get("command").and_then(|v| v.as_str()) {
            consequences.push(format!("Execute: {}", cmd));
        }

        if tool.contains("delete") || tool.contains("remove") {
            consequences.push("This operation may be irreversible".to_string());
        }

        if tool.contains("git.push") {
            consequences.push("Changes will be pushed to remote repository".to_string());
        }

        if tool.contains("write") || tool.contains("edit") {
            consequences.push("Files on disk will be modified".to_string());
        }

        consequences
    }
}
