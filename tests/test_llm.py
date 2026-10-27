"""Adaptör dönüşümleri; gerçek SDK istemcisi yerine sahte istemci kullanılır (ağ yok)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from gitsor.config import LLMConfig
from gitsor.errors import ConfigError, LLMError
from gitsor.llm.anthropic import AnthropicProvider, to_anthropic_messages, to_anthropic_tools
from gitsor.llm.base import Message, ToolCall, ToolSpec
from gitsor.llm.factory import make_provider
from gitsor.llm.openai_compat import OpenAICompatProvider, parse_tool_calls, to_openai_messages

SPEC = ToolSpec("pickaxe", "desc", {"type": "object", "properties": {"term": {"type": "string"}}})


class _Recorder:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


def _history() -> list[Message]:
    return [
        Message("system", "sys"),
        Message("user", "soru"),
        Message(
            "assistant",
            "",
            tool_calls=[
                ToolCall("t1", "pickaxe", {"term": "x"}),
                ToolCall("t2", "blame", {"path": "a"}),
            ],
        ),
        Message("tool", "sonuç1", tool_call_id="t1", name="pickaxe"),
        Message("tool", "sonuç2", tool_call_id="t2", name="blame", is_error=True),
    ]


def test_anthropic_message_conversion() -> None:
    system, msgs = to_anthropic_messages(_history())
    assert system == "sys"
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert [b["type"] for b in msgs[1]["content"]] == ["tool_use", "tool_use"]
    results = msgs[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert results[1]["is_error"] is True
    assert to_anthropic_tools([SPEC])[0]["input_schema"] == SPEC.parameters


def test_anthropic_raw_blocks_passthrough() -> None:
    raw = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": "x"}]
    _, msgs = to_anthropic_messages(
        [Message("user", "q"), Message("assistant", "x", raw=raw, raw_provider="anthropic")]
    )
    assert msgs[1]["content"] is raw


def test_anthropic_provider_request_and_parse() -> None:
    response = SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(
                type="text",
                text="bakıyorum",
                model_dump=lambda **_: {"type": "text", "text": "bakıyorum"},
            ),
            SimpleNamespace(
                type="tool_use",
                id="tu1",
                name="pickaxe",
                input={"term": "x"},
                model_dump=lambda **_: {
                    "type": "tool_use",
                    "id": "tu1",
                    "name": "pickaxe",
                    "input": {"term": "x"},
                },
            ),
        ],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    rec = _Recorder(response)
    provider = AnthropicProvider(
        LLMConfig(provider="anthropic", model="claude-opus-5-5"),
        client=SimpleNamespace(messages=rec),
    )
    out = provider.chat(_history()[:2], tools=[SPEC])
    assert out.text == "bakıyorum"
    assert out.tool_calls == [ToolCall("tu1", "pickaxe", {"term": "x"})]
    assert out.raw[1]["type"] == "tool_use"
    assert "temperature" not in rec.kwargs  # güncel Claude API örnekleme parametresi kabul etmez
    assert "tool_choice" not in rec.kwargs
    assert rec.kwargs["system"] == "sys"
    assert rec.kwargs["extra_body"] == {"fallbacks": "default"}


def test_anthropic_refusal() -> None:
    response = SimpleNamespace(
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber"),
        content=[],
        usage=None,
    )
    provider = AnthropicProvider(
        LLMConfig(provider="anthropic"), client=SimpleNamespace(messages=_Recorder(response))
    )
    with pytest.raises(LLMError, match="cyber"):
        provider.chat([Message("user", "q")])


def test_openai_message_conversion() -> None:
    msgs = to_openai_messages(_history())
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "pickaxe"
    assert msgs[3] == {"role": "tool", "tool_call_id": "t1", "content": "sonuç1"}


def test_openai_tool_call_parsing() -> None:
    raw = [
        SimpleNamespace(
            id="a", function=SimpleNamespace(name="pickaxe", arguments='{"term": "ödeme"}')
        ),
        SimpleNamespace(id="b", function=SimpleNamespace(name="blame", arguments="{bozuk")),
    ]
    calls = parse_tool_calls(raw)
    assert calls[0].arguments == {"term": "ödeme"}
    assert calls[1].parse_error is not None


def test_openai_provider_request() -> None:
    message = SimpleNamespace(content="cevap", tool_calls=None)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4),
    )
    rec = _Recorder(response)
    cfg = LLMConfig(base_url="http://localhost:8000/v1", temperature=0.2)
    provider = OpenAICompatProvider(
        cfg, client=SimpleNamespace(chat=SimpleNamespace(completions=rec))
    )
    out = provider.chat([Message("user", "q")], tools=[SPEC])
    assert out.text == "cevap"
    assert rec.kwargs["temperature"] == 0.2
    assert rec.kwargs["tools"][0]["function"]["name"] == "pickaxe"
    assert out.usage == {"input_tokens": 3, "output_tokens": 4}


def test_factory_requires_base_url_for_openai_compat() -> None:
    with pytest.raises(ConfigError):
        make_provider(LLMConfig(provider="openai_compat", base_url=None))
