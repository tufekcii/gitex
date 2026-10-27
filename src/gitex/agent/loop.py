"""Tool-use döngüsü ve iki modun (agent/simple) ortak cevap sonlandırma adımı."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gitex.agent.citations import CitationReport, CitationVerifier, mark_unverified
from gitex.agent.prompts import (
    AGENT_SYSTEM,
    BUDGET_EXHAUSTED,
    GITLAB_HINT,
    NO_GITLAB_HINT,
    correction_message,
)
from gitex.agent.tools import Toolbox
from gitex.llm.base import LLMProvider, Message

# (olay türü, veri) — CLI bunları sade satırlar olarak gösterir.
EventFn = Callable[[str, dict[str, Any]], None]


def _noop(_kind: str, _data: dict[str, Any]) -> None:
    return None


@dataclass
class ToolCallLog:
    name: str
    arguments: dict[str, Any]
    ok: bool
    truncated: bool
    chars: int


@dataclass
class Source:
    kind: str  # commit | mr
    ref: str
    date: str | None = None
    author: str | None = None
    title: str | None = None
    url: str | None = None
    mrs: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [])}


@dataclass
class AgentResult:
    answer: str
    mode: str
    model: str
    sources: list[Source] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallLog] = field(default_factory=list)
    corrected: bool = False
    usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "mode": self.mode,
            "model": self.model,
            "sources": [s.to_dict() for s in self.sources],
            "unverified": self.unverified,
            "corrected": self.corrected,
            "tool_calls": [
                {"name": t.name, "arguments": t.arguments, "ok": t.ok, "truncated": t.truncated}
                for t in self.tool_calls
            ],
            "usage": self.usage,
        }


def system_prompt(toolbox: Toolbox, base: str = AGENT_SYSTEM) -> str:
    return base + "\n" + (GITLAB_HINT if toolbox.gitlab_enabled else NO_GITLAB_HINT)


def _add_usage(total: dict[str, int], usage: dict[str, int]) -> None:
    for k, v in usage.items():
        total[k] = total.get(k, 0) + v


def build_sources(toolbox: Toolbox, report: CitationReport) -> list[Source]:
    sources: list[Source] = []
    seen: set[str] = set()
    for full in report.valid_shas.values():
        if full in seen:
            continue
        seen.add(full)
        row = toolbox.db.conn.execute(
            "SELECT author_name, author_date, subject FROM commits WHERE sha = ?", (full,)
        ).fetchone()
        mrs = [m.iid for m in toolbox.search.mrs_for_commit(full)] if toolbox.gitlab_enabled else []
        if row is not None:
            sources.append(
                Source(
                    "commit",
                    full,
                    row["author_date"][:10],
                    row["author_name"],
                    row["subject"],
                    mrs=mrs,
                )
            )
        else:
            commit = toolbox.repo.get_commit(full)
            sources.append(
                Source(
                    "commit",
                    full,
                    commit.author_date.date().isoformat() if commit else None,
                    commit.author_name if commit else None,
                    commit.subject if commit else None,
                    mrs=mrs,
                )
            )
    for iid in report.valid_mrs:
        mr = toolbox.search.get_mr(iid)
        if mr is not None:
            sources.append(
                Source(
                    "mr",
                    f"!{iid}",
                    (mr.merged_at or mr.created_at or "")[:10] or None,
                    mr.author,
                    mr.title,
                    mr.web_url,
                )
            )
    return sources


def finalize(
    provider: LLMProvider,
    toolbox: Toolbox,
    messages: list[Message],
    answer: str,
    result: AgentResult,
    on_event: EventFn = _noop,
) -> AgentResult:
    """Kaynakları doğrular; uydurma referans varsa LLM'den bir kez düzeltme ister."""
    verifier = CitationVerifier(toolbox.repo, toolbox.search, gitlab_enabled=toolbox.gitlab_enabled)
    report = verifier.verify(answer)
    if not report.ok:
        on_event("citation_retry", {"shas": report.invalid_shas, "mrs": report.invalid_mrs})
        messages.append(Message(role="assistant", content=answer))
        messages.append(
            Message(
                role="user", content=correction_message(report.invalid_shas, report.invalid_mrs)
            )
        )
        # Geçmişte araç çağrısı varsa bazı sağlayıcılar (Anthropic) araç tanımlarını da ister.
        has_tools = any(m.tool_calls for m in messages)
        resp = provider.chat(messages, tools=toolbox.specs() if has_tools else None)
        _add_usage(result.usage, resp.usage)
        if resp.text.strip():
            answer = resp.text
            result.corrected = True
        report = verifier.verify(answer)
        if not report.ok:
            answer = mark_unverified(answer, report)
            result.unverified = report.invalid_shas + [f"!{m}" for m in report.invalid_mrs]
            on_event("citation_unverified", {"refs": result.unverified})
    result.answer = answer.strip()
    result.sources = build_sources(toolbox, report)
    return result


def run_agent(
    question: str,
    provider: LLMProvider,
    toolbox: Toolbox,
    *,
    max_tool_calls: int = 12,
    history: list[Message] | None = None,
    on_event: EventFn = _noop,
) -> tuple[AgentResult, list[Message]]:
    """Tool-use döngüsü. Güncellenmiş konuşma geçmişini de döner (chat modu için)."""
    messages: list[Message] = (
        list(history) if history else [Message("system", system_prompt(toolbox))]
    )
    messages.append(Message("user", question))
    result = AgentResult(answer="", mode="agent", model=provider.model)
    specs = toolbox.specs()
    calls_left = max_tool_calls
    answer = ""
    budget_noted = False
    # Her turda en az bir araç çağrısı olur; bütçe dolunca bir tur daha araçsız cevap istenir.
    for _ in range(max_tool_calls + 2):
        # Bütçe dolsa da araç tanımları gönderilir (geçmişteki tool_use blokları için gerekli);
        # model yine de çağırırsa hata sonucu döner.
        on_event("llm_call", {"calls_left": calls_left})
        resp = provider.chat(messages, tools=specs)
        _add_usage(result.usage, resp.usage)
        if not resp.tool_calls:
            answer = resp.text
            messages.append(resp.as_message(provider.name))
            break
        messages.append(resp.as_message(provider.name))
        for call in resp.tool_calls:
            if calls_left <= 0:
                messages.append(
                    Message(
                        "tool",
                        "Araç bütçesi doldu; çağrı yapılmadı.",
                        tool_call_id=call.id,
                        name=call.name,
                        is_error=True,
                    )
                )
                continue
            calls_left -= 1
            if call.parse_error:
                tr_text, ok, truncated = f"Argümanlar okunamadı: {call.parse_error}", False, False
            else:
                on_event("tool_call", {"name": call.name, "arguments": call.arguments})
                tr = toolbox.execute(call.name, call.arguments)
                tr_text, ok, truncated = tr.text, not tr.is_error, tr.truncated
            on_event(
                "tool_result",
                {"name": call.name, "ok": ok, "chars": len(tr_text), "truncated": truncated},
            )
            result.tool_calls.append(
                ToolCallLog(call.name, call.arguments, ok, truncated, len(tr_text))
            )
            messages.append(
                Message("tool", tr_text, tool_call_id=call.id, name=call.name, is_error=not ok)
            )
        if calls_left <= 0 and not budget_noted:
            messages.append(Message("user", BUDGET_EXHAUSTED))
            budget_noted = True
    if not answer.strip():
        answer = "Bir cevap üretilemedi (model boş yanıt döndü ya da araç bütçesi aşıldı)."
    finalize(provider, toolbox, messages, answer, result, on_event)
    # Chat geçmişinde düzeltme turu yerine son (doğrulanmış) cevap kalsın.
    if messages and messages[-1].role == "user" and result.corrected:
        messages.append(Message("assistant", result.answer))
    return result, messages
