//! Sandbox abstraction — wraps subprocess execution with optional isolation.

use crate::config::Config;
use crate::security::gate::ExecutionConstraints;

/// Available sandbox backends
#[derive(Debug, Clone, PartialEq)]
pub enum SandboxBackend {
    None,
    Firejail,
    Bubblewrap,
    Docker,
}

pub struct SandboxConfig {
    pub backend: SandboxBackend,
    pub network_allowed: bool,
    pub allowed_paths: Vec<std::path::PathBuf>,
    pub timeout_ms: u64,
    pub max_output_bytes: usize,
}

impl SandboxConfig {
    pub fn from_constraints(constraints: &ExecutionConstraints, config: &Config) -> Self {
        let backend = if !constraints.sandbox {
            SandboxBackend::None
        } else {
            match config.security.sandbox_backend.as_str() {
                "firejail" => SandboxBackend::Firejail,
                "bubblewrap" | "bwrap" => SandboxBackend::Bubblewrap,
                "docker" => SandboxBackend::Docker,
                _ => SandboxBackend::None,
            }
        };

        Self {
            backend,
            network_allowed: constraints.network_allowed,
            allowed_paths: constraints.allowed_paths.clone(),
            timeout_ms: constraints.timeout_ms,
            max_output_bytes: constraints.max_output_bytes,
        }
    }

    /// Wrap a command with sandbox args if needed.
    /// Returns (program, args) ready for subprocess spawn.
    pub fn wrap_command(&self, program: &str, args: &[String]) -> (String, Vec<String>) {
        match &self.backend {
            SandboxBackend::None => (program.to_string(), args.to_vec()),

            SandboxBackend::Firejail => {
                let mut firejail_args = vec![
                    "--quiet".to_string(),
                    "--noroot".to_string(),
                    "--private-tmp".to_string(),
                ];
                if !self.network_allowed {
                    firejail_args.push("--net=none".to_string());
                }
                firejail_args.push("--".to_string());
                firejail_args.push(program.to_string());
                firejail_args.extend_from_slice(args);
                ("firejail".to_string(), firejail_args)
            }

            SandboxBackend::Bubblewrap => {
                let mut bwrap_args = vec![
                    "--unshare-all".to_string(),
                    "--share-net".to_string(), // conditionally removed below
                    "--ro-bind".to_string(), "/usr".to_string(), "/usr".to_string(),
                    "--ro-bind".to_string(), "/lib".to_string(), "/lib".to_string(),
                    "--proc".to_string(), "/proc".to_string(),
                    "--dev".to_string(), "/dev".to_string(),
                    "--tmpfs".to_string(), "/tmp".to_string(),
                ];
                if !self.network_allowed {
                    bwrap_args.retain(|a| a != "--share-net");
                    bwrap_args.push("--unshare-net".to_string());
                }
                bwrap_args.push("--".to_string());
                bwrap_args.push(program.to_string());
                bwrap_args.extend_from_slice(args);
                ("bwrap".to_string(), bwrap_args)
            }

            SandboxBackend::Docker => {
                // Docker sandbox — future implementation
                ("docker".to_string(), vec![
                    "run".to_string(),
                    "--rm".to_string(),
                    "--network=none".to_string(),
                    "suho-sandbox:latest".to_string(),
                    program.to_string(),
                ])
            }
        }
    }
}
