"""Configuration for Python agent — loaded from ~/.config/suho/config.toml."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ensure structlog never writes to stdout (stdout is reserved for IPC JSON)
structlog.configure(
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)

log = structlog.get_logger(__name__)


class AgentSection(BaseModel):
    max_iterations: int = 30
    max_tool_calls: int = 100
    timeout_secs: int = 300
    max_retries: int = 3
    max_output_bytes: int = 1024 * 1024  # 1 MB


class ModelSection(BaseModel):
    provider: str = "ollama"
    model: str = "llama3.2"
    api_base: Optional[str] = "http://localhost:11434"
    api_key_env: Optional[str] = None
    request_timeout_secs: int = 120
    max_context_tokens: int = 8192
    temperature: float = 0.1


class SecuritySection(BaseModel):
    sandbox: bool = False
    redact_secrets: bool = True
    max_file_read_bytes: int = 10 * 1024 * 1024
    max_file_write_bytes: int = 5 * 1024 * 1024


class MemorySection(BaseModel):
    enabled: bool = True
    db_path: Optional[Path] = None
    max_working_entries: int = 100
    max_longterm_entries: int = 1000


class LoggingSection(BaseModel):
    level: str = "info"


class AgentConfig(BaseModel):
    """Full agent configuration."""
    agent: AgentSection = Field(default_factory=AgentSection)
    model: ModelSection = Field(default_factory=ModelSection)
    security: SecuritySection = Field(default_factory=SecuritySection)
    memory: MemorySection = Field(default_factory=MemorySection)
    logging: LoggingSection = Field(default_factory=LoggingSection)

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "AgentConfig":
        """Load config from TOML file, falling back to defaults."""
        if config_path is None:
            config_dir = Path.home() / ".config" / "suho"
            config_path = config_dir / "config.toml"

        if not config_path.exists():
            log.debug("Config not found, using defaults", path=str(config_path))
            return cls()

        try:
            if sys.version_info >= (3, 11):
                import tomllib
                with open(config_path, "rb") as f:
                    data = tomllib.load(f)
            else:
                import tomli
                with open(config_path, "rb") as f:
                    data = tomli.load(f)

            return cls.model_validate(data)
        except Exception as e:
            log.warning("Config parse error, using defaults", error=str(e))
            return cls()

    def get_api_key(self) -> Optional[str]:
        """Retrieve API key from environment variable (never from config file)."""
        if self.model.api_key_env:
            return os.environ.get(self.model.api_key_env)
        # Common environment variables
        for env_var in ["OPENAI_API_KEY", "SUHO_API_KEY"]:
            val = os.environ.get(env_var)
            if val:
                return val
        return None

    def get_db_path(self) -> Path:
        """Resolve SQLite database path."""
        if self.memory.db_path:
            return self.memory.db_path
        data_dir = Path.home() / ".local" / "share" / "suho"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "memory.db"
