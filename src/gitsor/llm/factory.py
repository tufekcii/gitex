"""Config'ten LLM sağlayıcısı üretir."""

from __future__ import annotations

from gitsor.config import LLMConfig
from gitsor.errors import ConfigError
from gitsor.llm.base import LLMProvider


def make_provider(cfg: LLMConfig) -> LLMProvider:
    if cfg.provider == "openai_compat":
        from gitsor.llm.openai_compat import OpenAICompatProvider

        if not cfg.base_url:
            raise ConfigError(
                "openai_compat sağlayıcısı için `llm.base_url` gerekli.",
                hint='Örn. base_url = "http://localhost:8000/v1" (vLLM) ya da '
                '"http://localhost:11434/v1" (Ollama).',
            )
        return OpenAICompatProvider(cfg)
    if cfg.provider == "anthropic":
        from gitsor.llm.anthropic import AnthropicProvider

        return AnthropicProvider(cfg)
    raise ConfigError(f"Bilinmeyen LLM sağlayıcısı: {cfg.provider}")
