"""OpenAI uyumlu uç noktalar (vLLM, Ollama, OpenAI) için adaptör."""

from __future__ import annotations

import json
from typing import Any

from gitex.config import LLMConfig
from gitex.errors import LLMError
from gitex.i18n import t
from gitex.llm.base import LLMResponse, Message, ToolCall, ToolSpec

DEFAULT_MAX_TOKENS = 2048


def to_openai_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
    ]


def to_openai_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "assistant":
            item: dict[str, Any] = {"role": "assistant", "content": m.content or None}
            if m.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in m.tool_calls
                ]
            out.append(item)
        elif m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def parse_tool_calls(raw_calls: list[Any] | None) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for i, rc in enumerate(raw_calls or []):
        fn = rc.function
        args_text = fn.arguments or "{}"
        try:
            args = json.loads(args_text)
            error = None if isinstance(args, dict) else "argümanlar bir JSON nesnesi değil"
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError as exc:
            args, error = {}, f"geçersiz JSON: {exc}"
        calls.append(
            ToolCall(id=rc.id or f"call_{i}", name=fn.name, arguments=args, parse_error=error)
        )
    return calls


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, cfg: LLMConfig, client: Any = None) -> None:
        self.cfg = cfg
        self.model = cfg.model
        if client is None:
            import openai

            # Yerel sunucular (vLLM/Ollama) anahtar istemese de SDK boş olmayan bir değer bekler.
            client = openai.OpenAI(
                base_url=cfg.base_url,
                api_key=cfg.api_key() or "not-needed",
                timeout=cfg.timeout,
                max_retries=2,
            )
        self.client = client

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        import openai

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(messages),
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens or DEFAULT_MAX_TOKENS,
        }
        if tools:
            kwargs["tools"] = to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except openai.APIConnectionError as exc:
            raise LLMError(
                t("LLM'e ulaşılamıyor ({u}).", "Cannot reach the LLM ({u}).", u=self.cfg.base_url),
                hint=t(
                    "Sunucunun çalıştığını ve adresi kontrol edin: gitex doctor",
                    "Check that the server is running and the address is right: gitex doctor",
                ),
            ) from exc
        except openai.AuthenticationError as exc:
            raise LLMError(
                t(
                    "LLM kimlik doğrulaması başarısız (API anahtarı geçersiz).",
                    "LLM authentication failed (invalid API key).",
                ),
                hint=t("Anahtarı yenileyin: gitex auth login", "Update the key: gitex auth login"),
            ) from exc
        except openai.NotFoundError as exc:
            raise LLMError(
                t(
                    "Model ya da uç nokta bulunamadı: {m}",
                    "Model or endpoint not found: {m}",
                    m=self.model,
                ),
                hint=t("Modeli yeniden seçin: gitex setup", "Choose the model again: gitex setup"),
            ) from exc
        except openai.APIStatusError as exc:
            raise LLMError(
                t("LLM hatası ({c}): {m}", "LLM error ({c}): {m}", c=exc.status_code, m=exc.message)
            ) from exc
        if not resp.choices:
            raise LLMError(t("LLM boş yanıt döndü.", "The LLM returned an empty response."))
        choice = resp.choices[0]
        usage = {}
        if resp.usage is not None:
            usage = {
                "input_tokens": resp.usage.prompt_tokens or 0,
                "output_tokens": resp.usage.completion_tokens or 0,
            }
        return LLMResponse(
            text=choice.message.content or "",
            tool_calls=parse_tool_calls(choice.message.tool_calls),
            stop_reason=choice.finish_reason,
            usage=usage,
        )
