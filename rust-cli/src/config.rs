use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

/// Full SUHO Agent configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    pub agent: AgentConfig,
    pub model: ModelConfig,
    pub security: SecurityConfig,
    pub memory: MemoryConfig,
    pub ui: UiConfig,
    pub logging: LoggingConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct AgentConfig {
    /// Maximum agent loop iterations
    pub max_iterations: u32,
    /// Maximum total tool calls per task
    pub max_tool_calls: u32,
    /// Task timeout in seconds
    pub timeout_secs: u64,
    /// Maximum retries on tool failure
    pub max_retries: u32,
    /// Maximum output size per tool (bytes)
    pub max_output_bytes: usize,
    /// Python agent executable path (default: "python3 -m suho_agent")
    pub python_agent_cmd: Option<String>,
    /// Path to python-agent project root
    pub python_agent_dir: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ModelConfig {
    /// LLM provider: "ollama", "openai", "anthropic", "groq", "deepseek", "openrouter", "together", "gemini", "lmstudio"
    pub provider: String,
    /// Model name (e.g. "llama3.2", "gpt-4o-mini", "claude-3-5-sonnet-20241022")
    pub model: String,
    /// API base URL
    pub api_base: Option<String>,
    /// Stored API key
    pub api_key: Option<String>,
    /// API key env var name
    pub api_key_env: Option<String>,
    /// Request timeout in seconds
    pub request_timeout_secs: u64,
    /// Maximum context tokens
    pub max_context_tokens: usize,
    /// Temperature
    pub temperature: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct SecurityConfig {
    /// Enable sandbox for tool execution
    pub sandbox: bool,
    /// Sandbox backend: "none", "firejail", "bubblewrap", "docker"
    pub sandbox_backend: String,
    /// Require confirmation for MODERATE level operations
    pub confirm_moderate: bool,
    /// Require confirmation for DANGEROUS level operations (always true)
    pub confirm_dangerous: bool,
    /// Auto-deny CRITICAL operations without prompting
    pub auto_deny_critical: bool,
    /// Redact secrets from tool output before sending to LLM
    pub redact_secrets: bool,
    /// Allowed working directories (empty = CWD only)
    pub allowed_paths: Vec<PathBuf>,
    /// Maximum file size for read operations (bytes)
    pub max_file_read_bytes: usize,
    /// Maximum file size for write operations (bytes)
    pub max_file_write_bytes: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct MemoryConfig {
    /// Enable persistent memory
    pub enabled: bool,
    /// SQLite database path (default: ~/.local/share/suho/memory.db)
    pub db_path: Option<PathBuf>,
    /// Maximum working memory entries
    pub max_working_entries: usize,
    /// Maximum long-term memory entries
    pub max_longterm_entries: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct UiConfig {
    /// "default", "minimal", "rich"
    pub theme: String,
    /// Show token usage in UI
    pub show_token_usage: bool,
    /// Show timing information
    pub show_timing: bool,
    /// Show tool execution details
    pub show_tool_details: bool,
    /// Max lines to show in terminal output preview
    pub max_preview_lines: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct LoggingConfig {
    /// Log level: "debug", "info", "warn", "error"
    pub level: String,
    /// Log file path (None = stderr only)
    pub log_file: Option<PathBuf>,
    /// Enable structured JSON logs
    pub json_format: bool,
}

// ─── Defaults ────────────────────────────────────────────────────────────────

impl Default for Config {
    fn default() -> Self {
        Self {
            agent: AgentConfig::default(),
            model: ModelConfig::default(),
            security: SecurityConfig::default(),
            memory: MemoryConfig::default(),
            ui: UiConfig::default(),
            logging: LoggingConfig::default(),
        }
    }
}

impl Default for AgentConfig {
    fn default() -> Self {
        Self {
            max_iterations: 30,
            max_tool_calls: 100,
            timeout_secs: 300,
            max_retries: 3,
            max_output_bytes: 1024 * 1024, // 1 MB
            python_agent_cmd: None,
            python_agent_dir: None,
        }
    }
}

impl Default for ModelConfig {
    fn default() -> Self {
        Self {
            provider: "ollama".to_string(),
            model: "llama3.2".to_string(),
            api_base: Some("http://localhost:11434".to_string()),
            api_key: None,
            api_key_env: None,
            request_timeout_secs: 120,
            max_context_tokens: 8192,
            temperature: 0.1,
        }
    }
}

impl Default for SecurityConfig {
    fn default() -> Self {
        Self {
            sandbox: false,
            sandbox_backend: "none".to_string(),
            confirm_moderate: false,
            confirm_dangerous: true,
            auto_deny_critical: false,
            redact_secrets: true,
            allowed_paths: vec![],
            max_file_read_bytes: 10 * 1024 * 1024,  // 10 MB
            max_file_write_bytes: 5 * 1024 * 1024,  // 5 MB
        }
    }
}

impl Default for MemoryConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            db_path: None,
            max_working_entries: 100,
            max_longterm_entries: 1000,
        }
    }
}

impl Default for UiConfig {
    fn default() -> Self {
        Self {
            theme: "default".to_string(),
            show_token_usage: true,
            show_timing: true,
            show_tool_details: true,
            max_preview_lines: 50,
        }
    }
}

impl Default for LoggingConfig {
    fn default() -> Self {
        Self {
            level: "info".to_string(),
            log_file: None,
            json_format: false,
        }
    }
}

// ─── Loading ─────────────────────────────────────────────────────────────────

impl Config {
    /// Returns the default config file path: ~/.config/suho/config.toml
    pub fn config_path() -> Result<PathBuf> {
        let config_dir = dirs::config_dir()
            .ok_or_else(|| anyhow::anyhow!("Cannot determine config directory"))?;
        Ok(config_dir.join("suho").join("config.toml"))
    }

    /// Returns the default data directory: ~/.local/share/suho/
    pub fn data_dir() -> Result<PathBuf> {
        let data_dir = dirs::data_local_dir()
            .ok_or_else(|| anyhow::anyhow!("Cannot determine data directory"))?;
        Ok(data_dir.join("suho"))
    }

    /// Load config from file, falling back to defaults
    pub async fn load(override_path: Option<&Path>) -> Result<Self> {
        let path = match override_path {
            Some(p) => p.to_path_buf(),
            None => Self::config_path()?,
        };

        if !path.exists() {
            tracing::debug!("Config file not found at {:?}, using defaults", path);
            return Ok(Self::default());
        }

        let content = tokio::fs::read_to_string(&path).await?;
        let config: Config = toml::from_str(&content)
            .map_err(|e| anyhow::anyhow!("Config parse error in {:?}: {}", path, e))?;

        tracing::debug!("Loaded config from {:?}", path);
        Ok(config)
    }

    /// Save config to file
    pub async fn save(&self, override_path: Option<&Path>) -> Result<()> {
        let path = match override_path {
            Some(p) => p.to_path_buf(),
            None => Self::config_path()?,
        };

        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }

        let content = toml::to_string_pretty(self)?;
        tokio::fs::write(&path, content).await?;
        Ok(())
    }

    /// Write default config to the standard path if it doesn't exist
    pub async fn init_if_missing() -> Result<PathBuf> {
        let path = Self::config_path()?;
        if !path.exists() {
            let default = Self::default();
            default.save(None).await?;
            tracing::info!("Created default config at {:?}", path);
        }
        Ok(path)
    }
}
