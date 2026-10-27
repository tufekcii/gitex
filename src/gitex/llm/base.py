"""Sağlayıcıdan bağımsız LLM arayüzü.

Araç şemaları tek yerde (JSON Schema, `ToolSpec`) tanımlanır; her adaptör bunları kendi
formatına çevirir. Mesaj geçmişi de nötr `Message` listesidir. Asistan mesajları
sağlayıcının ham içeriğini (`raw`) taşıyabilir; aynı sağlayıcı bunu değiştirmeden geri
gönderir (ör. Anthropic thinking blokları).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    parse_error: str | None = None


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    is_error: bool = False
    raw: Any = None  # sağlayıcıya özgü asistan içeriği (yalnızca aynı sağlayıcı kullanır)
    raw_provider: str | None = None


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    raw: Any = None
    usage: dict[str, int] = field(default_factory=dict)

    def as_message(self, provider: str) -> Message:
        return Message(
            role="assistant",
            content=self.text,
            tool_calls=list(self.tool_calls),
            raw=self.raw,
            raw_provider=provider,
        )


class LLMProvider(Protocol):
    name: str
    model: str

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        """Mesajları ve (opsiyonel) araç tanımlarını gönderir; metin ve/veya araç çağrısı döner."""
        ...
