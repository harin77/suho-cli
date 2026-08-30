"""ModelRouter — selects the appropriate LLM provider based on config and availability."""

from __future__ import annotations

from typing import Optional

import structlog

from suho_agent.config import AgentConfig
from suho_agent.models.base import LLMProvider, ModelInfo

log = structlog.get_logger(__name__)


class ModelRouter:
    """
    Selects and instantiates the appropriate LLM provider.

    Priority:
    1. Config-specified provider
    2. Ollama if running locally
    3. OpenAI-compat if API key present
    4. Error if none available
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._provider: Optional[LLMProvider] = None

    async def get_provider(self) -> LLMProvider:
        """Get the active LLM provider, with health-check and fallback."""
        if self._provider is not None:
            return self._provider

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
            f"No LLM provider available. "
            f"Configured: {self.config.model.provider}. "
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

        if provider_name == "ollama":
            from suho_agent.models.ollama import OllamaProvider
            return OllamaProvider(
                model=cfg.model,
                base_url=cfg.api_base or "http://localhost:11434",
                timeout=cfg.request_timeout_secs,
                temperature=cfg.temperature,
            )

        if provider_name in ("openai", "openai_compat"):
            api_key = self.config.get_api_key()
            if not api_key and provider_name == "openai":
                log.warning("No API key found for OpenAI provider")
                return None

            from suho_agent.models.openai_compat import OpenAICompatProvider
            return OpenAICompatProvider(
                model=cfg.model,
                api_key=api_key,
                base_url=cfg.api_base if provider_name == "openai_compat" else None,
                timeout=cfg.request_timeout_secs,
                temperature=cfg.temperature,
            )

        log.error("Unknown provider", provider=provider_name)
        return None
