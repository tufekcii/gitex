"""Ağa çıkmayan, önceden yazılmış yanıtları sırayla dönen LLM sağlayıcısı."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from gitex.llm.base import LLMResponse, Message, ToolCall, ToolSpec

Step = LLMResponse | Callable[[list[Message], list[ToolSpec] | None], LLMResponse]


def text(content: str) -> LLMResponse:
    return LLMResponse(text=content, stop_reason="stop")


def call(name: str, call_id: str = "c1", **arguments: object) -> LLMResponse:
    return LLMResponse(
        text="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=dict(arguments))],
        stop_reason="tool_calls",
    )


@dataclass
class ScriptedProvider:
    steps: list[Step]
    name: str = "scripted"
    model: str = "scripted-model"
    calls: list[tuple[list[Message], list[ToolSpec] | None]] = field(default_factory=list)
    repeat_last: bool = False

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        self.calls.append((list(messages), tools))
        if not self.steps:
            raise AssertionError("ScriptedProvider: beklenmeyen ek çağrı")
        step = self.steps[0] if (self.repeat_last and len(self.steps) == 1) else self.steps.pop(0)
        return step(messages, tools) if callable(step) else step
