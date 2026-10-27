"""Config'ten LLM sağlayıcısı üretir."""

from __future__ import annotations

from gitex.config import LLMConfig
from gitex.errors import ConfigError
from gitex.llm.base import LLMProvider


def make_provider(cfg: LLMConfig) -> LLMProvider:
    if cfg.provider == "openai_compat":
        from gitex.llm.openai_compat import OpenAICompatProvider

        if not cfg.base_url:
            raise ConfigError(
                "openai_compat sağlayıcısı için `llm.base_url` gerekli.",
                hint="Kurulum için: gitex setup  ·  ya da: gitex config set llm.base_url "
                "http://localhost:11434/v1",
            )
        return OpenAICompatProvider(cfg)
    if cfg.provider == "anthropic":
        from gitex.llm.anthropic import AnthropicProvider

        return AnthropicProvider(cfg)
    raise ConfigError(f"Bilinmeyen LLM sağlayıcısı: {cfg.provider}")
