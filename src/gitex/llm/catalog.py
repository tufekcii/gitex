"""Kurulum sihirbazının sunduğu sağlayıcılar ve sağlayıcının kendi model listesini çekme.

Model adları koda gömülmez: anahtar girildikten sonra sağlayıcının `/models` uç noktasından
güncel liste alınır, sohbet dışı modeller (embedding, ses, görsel…) ayıklanır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from gitex.config import LLMConfig
from gitex.i18n import t


@dataclass(frozen=True)
class ProviderPreset:
    key: str
    label_tr: str
    label_en: str
    note_tr: str
    note_en: str
    provider: Literal["openai_compat", "anthropic"]
    base_url: str | None
    mode: Literal["agent", "simple"]
    needs_key: bool
    key_url: str | None = None
    default_model: str | None = None
    base_url_editable: bool = False

    @property
    def label(self) -> str:
        return t(self.label_tr, self.label_en)

    @property
    def note(self) -> str:
        return t(self.note_tr, self.note_en)


PRESETS: list[ProviderPreset] = [
    ProviderPreset(
        "groq", "Groq", "Groq",
        "ücretsiz katmanı var (limitli), çok hızlı", "free tier (rate-limited), very fast",
        "openai_compat", "https://api.groq.com/openai/v1", "agent", True,
        key_url="https://console.groq.com/keys",
    ),
    ProviderPreset(
        "gemini", "Google Gemini", "Google Gemini",
        "ücretsiz katmanı var (limitli)", "free tier (rate-limited)",
        "openai_compat", "https://generativelanguage.googleapis.com/v1beta/openai/", "agent", True,
        key_url="https://aistudio.google.com/apikey",
    ),
    ProviderPreset(
        "openrouter", "OpenRouter", "OpenRouter",
        "tek anahtarla birçok model; adı ':free' ile bitenler ücretsiz",
        "one key, many models; those ending in ':free' cost nothing",
        "openai_compat", "https://openrouter.ai/api/v1", "agent", True,
        key_url="https://openrouter.ai/keys",
    ),
    ProviderPreset(
        "ollama", "Ollama", "Ollama",
        "kendi bilgisayarında çalışır, tamamen ücretsiz, anahtar gerekmez",
        "runs on your own machine, completely free, no key needed",
        "openai_compat", "http://localhost:11434/v1", "simple", False,
        default_model="qwen2.5:7b", base_url_editable=True,
    ),
    ProviderPreset(
        "anthropic", "Claude (Anthropic API)", "Claude (Anthropic API)",
        "ücretli; en isabetli cevaplar", "paid; the most accurate answers",
        "anthropic", None, "agent", True,
        key_url="https://console.anthropic.com/settings/keys", default_model="claude-opus-5-5",
    ),
    ProviderPreset(
        "openai", "OpenAI", "OpenAI",
        "ücretli", "paid",
        "openai_compat", "https://api.openai.com/v1", "agent", True,
        key_url="https://platform.openai.com/api-keys",
    ),
    ProviderPreset(
        "custom", "vLLM ya da başka OpenAI uyumlu sunucu", "vLLM or another OpenAI-compatible server",
        "kendi sunucun", "your own server",
        "openai_compat", "http://localhost:8000/v1", "agent", False,
        base_url_editable=True,
    ),
]  # fmt: skip

# Sohbet/araç çağırma için uygun olmayan model türleri (ad içinde geçen parçalar).
_NON_CHAT = (
    "embed", "whisper", "tts", "audio", "transcrib", "speech", "dall-e", "gpt-image", "imagen",
    "image-", "veo", "moderation", "realtime", "guard", "rerank", "aqa", "babbage", "davinci",
    "search", "learnlm", "playai",
)  # fmt: skip


def preset_for(llm: LLMConfig) -> ProviderPreset | None:
    """Mevcut ayarın hangi hazır sağlayıcıya karşılık geldiği (yoksa None)."""
    for p in PRESETS:
        if p.provider == llm.provider and (p.base_url or None) == (llm.base_url or None):
            return p
    return None


def is_free(model_id: str) -> bool:
    return model_id.endswith(":free")


def clean_models(ids: list[str]) -> list[str]:
    """Sohbet dışı modelleri ayıklar, `models/` önekini atar, ücretsizleri başa alır."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in ids:
        mid = raw.removeprefix("models/").strip()
        low = mid.lower()
        if not mid or mid in seen or any(part in low for part in _NON_CHAT):
            continue
        seen.add(mid)
        out.append(mid)
    return sorted(out, key=lambda m: (not is_free(m), m.lower()))


def list_models(llm: LLMConfig, *, timeout: float = 15.0) -> list[str]:
    """Sağlayıcının güncel model listesi (ücretsiz uç nokta; token harcamaz)."""
    ids: list[str]
    if llm.provider == "anthropic":
        import anthropic

        kwargs: dict[str, Any] = {"timeout": timeout, "max_retries": 0}
        if key := llm.api_key():
            kwargs["api_key"] = key
        if llm.base_url:
            kwargs["base_url"] = llm.base_url
        ids = [m.id for m in anthropic.Anthropic(**kwargs).models.list()]
    else:
        import openai

        client = openai.OpenAI(
            base_url=llm.base_url,
            api_key=llm.api_key() or "not-needed",
            timeout=timeout,
            max_retries=0,
        )
        ids = [m.id for m in client.models.list()]
    return clean_models(ids)
