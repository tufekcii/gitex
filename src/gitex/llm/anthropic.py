"""Anthropic Claude API adaptörü (native tool use)."""

from __future__ import annotations

from typing import Any

from gitex.config import LLMConfig
from gitex.errors import LLMError
from gitex.llm.base import LLMResponse, Message, ToolCall, ToolSpec

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_TOKENS = 16000
# Güvenlik sınıflandırıcısı bir isteği reddederse sunucu tarafında yedek modele devreder.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def to_anthropic_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
    ]


def to_anthropic_messages(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Nötr mesajları (system, messages) çiftine çevirir.

    Asistan mesajlarının ham içerik blokları (thinking dahil) değiştirilmeden geri gönderilir;
    ardışık araç sonuçları tek bir `user` mesajında birleştirilir.
    """
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    pending_results: list[dict[str, Any]] = []

    def flush() -> None:
        if pending_results:
            out.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
            continue
        if m.role == "tool":
            pending_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": m.content,
                    "is_error": m.is_error,
                }
            )
            continue
        flush()
        if m.role == "assistant":
            if m.raw is not None and m.raw_provider == AnthropicProvider.name:
                out.append({"role": "assistant", "content": m.raw})
                continue
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            blocks += [
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                for tc in m.tool_calls
            ]
            out.append({"role": "assistant", "content": blocks or m.content})
        else:
            out.append({"role": "user", "content": m.content})
    flush()
    return "\n\n".join(system_parts), out


def _block_to_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, dict):
        return block
    dumped: dict[str, Any] = block.model_dump(exclude_none=True)
    return dumped


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, cfg: LLMConfig, client: Any = None) -> None:
        self.cfg = cfg
        self.model = cfg.model or DEFAULT_MODEL
        # Sunucu tarafı yedek yalnızca doğrudan Claude API'de; özel base_url'de kapalı.
        self.use_fallbacks = cfg.anthropic_fallbacks and not cfg.base_url
        if client is None:
            import anthropic

            kwargs: dict[str, Any] = {"timeout": cfg.timeout, "max_retries": 2}
            if key := cfg.api_key():
                kwargs["api_key"] = key
            if cfg.base_url:
                kwargs["base_url"] = cfg.base_url
            try:
                client = anthropic.Anthropic(**kwargs)
            except anthropic.AnthropicError as exc:
                raise LLMError(
                    "Claude API istemcisi oluşturulamadı (kimlik bilgisi yok).",
                    hint=f"`{cfg.api_key_env}` ya da ANTHROPIC_API_KEY ortam değişkenini ayarlayın.",
                ) from exc
        self.client = client

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        import anthropic

        system, msgs = to_anthropic_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.cfg.max_tokens or DEFAULT_MAX_TOKENS,
            "messages": msgs,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = to_anthropic_tools(tools)
        if self.use_fallbacks:
            kwargs["extra_headers"] = {"anthropic-beta": FALLBACK_BETA}
            kwargs["extra_body"] = {"fallbacks": "default"}
        try:
            resp = self.client.messages.create(**kwargs)
        except anthropic.APIConnectionError as exc:
            raise LLMError(
                "Claude API'ye ulaşılamıyor.",
                hint="Ağ bağlantısını ve `llm.base_url` ayarını kontrol edin.",
            ) from exc
        except anthropic.AuthenticationError as exc:
            raise LLMError(
                "Claude API kimlik doğrulaması başarısız.",
                hint=f"`{self.cfg.api_key_env}` (ya da ANTHROPIC_API_KEY) ortam değişkenini kontrol edin.",
            ) from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(
                f"Model bulunamadı: {self.model}", hint="`llm.model` ayarını kontrol edin."
            ) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API hatası ({exc.status_code}): {exc.message}") from exc

        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise LLMError(f"Model isteği reddetti (kategori: {category or 'belirtilmedi'}).")

        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(args)))
        usage = {
            "input_tokens": getattr(resp.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(resp.usage, "output_tokens", 0) or 0,
        }
        return LLMResponse(
            text="".join(texts),
            tool_calls=calls,
            stop_reason=resp.stop_reason,
            raw=[_block_to_dict(b) for b in resp.content],
            usage=usage,
        )
