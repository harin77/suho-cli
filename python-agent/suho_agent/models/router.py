"""ModelRouter — selects the appropriate LLM provider based on config and availability."""

from __future__ import annotations

from typing import Optional

import structlog

from suho_agent.config import AgentConfig
from suho_agent.models.base import LLMProvider, ModelInfo

log = structlog.get_logger(__name__)

# Standard base URLs for OpenAI-compatible providers
PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "lmstudio": "http://localhost:1234/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}

PROVIDER_DEFAULT_MODELS = {
    "ollama": "llama3.2",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-20241022",
    "groq": "llama-3.3-70b-versatile",
    "deepseek": "deepseek-chat",
    "openrouter": "auto",
    "together": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
    "lmstudio": "local-model",
    "gemini": "gemini-2.5-flash",
}


class ModelRouter:
    """Selects and instantiates the appropriate LLM provider."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._provider: Optional[LLMProvider] = None

    async def get_provider(self) -> LLMProvider:
        """Get the active LLM provider, with health-check and fallback."""
        # Always reload config from disk to catch runtime changes from /models menu
        self.config = AgentConfig.load()

        provider = await self._create_provider(self.config.model.provider)
        if provider and await provider.health_check():
            log.info("LLM provider ready", provider=self.config.model.provider, model=self.config.model.model)
            self._provider = provider
            return provider

        # Fallback: try Ollama
        if self.config.model.provider != "ollama":
            log.warning("Primary provider unavailable, falling back to Ollama")
            from suho_agent.models.ollama import OllamaProvider
            ollama = OllamaProvider(model=self.config.model.model)
            if await ollama.health_check():
                self._provider = ollama
                return ollama

        raise RuntimeError(
            f"No LLM provider available for '{self.config.model.provider}'. "
            f"Make sure Ollama is running or API key is set."
        )

    async def list_available_models(self) -> list[ModelInfo]:
        """List all models available from configured provider."""
        try:
            provider = await self.get_provider()
            return await provider.list_models()
        except Exception as e:
            log.warning("Failed to list models", error=str(e))
            return []

    async def _create_provider(self, provider_name: str) -> Optional[LLMProvider]:
        cfg = self.config.model
        provider_name = provider_name.lower().strip()

        if provider_name == "ollama":
            from suho_agent.models.ollama import OllamaProvider
            return OllamaProvider(
                model=cfg.model or PROVIDER_DEFAULT_MODELS["ollama"],
                base_url=cfg.api_base or "http://localhost:11434",
                timeout=cfg.request_timeout_secs,
                temperature=cfg.temperature,
            )

        if provider_name == "anthropic":
            api_key = self.config.get_api_key()
            if not api_key:
                log.warning("No API key found for Anthropic provider")
                return None
            from suho_agent.models.anthropic import AnthropicProvider
            return AnthropicProvider(
                model=cfg.model or PROVIDER_DEFAULT_MODELS["anthropic"],
                api_key=api_key,
                timeout=cfg.request_timeout_secs,
                temperature=cfg.temperature,
            )

        # OpenAI-compatible providers
        if provider_name in PROVIDER_BASE_URLS or provider_name == "openai_compat":
            api_key = self.config.get_api_key()
            base_url = cfg.api_base or PROVIDER_BASE_URLS.get(provider_name)
            model = cfg.model or PROVIDER_DEFAULT_MODELS.get(provider_name, "gpt-4o-mini")

            from suho_agent.models.openai_compat import OpenAICompatProvider
            return OpenAICompatProvider(
                model=model,
                api_key=api_key or "sk-placeholder",
                base_url=base_url,
                timeout=cfg.request_timeout_secs,
                temperature=cfg.temperature,
            )

        log.error("Unknown provider", provider=provider_name)
        return None
