"""Simple mod: tool-calling'de zayıf küçük modeller için sabit retrieval + tek cevap çağrısı.

1. Sorudan anahtar kelime, kod terimi, yol, SHA/MR ve tarih aralığı basit kurallarla çıkarılır;
   kurallar kod terimi/yol bulamazsa tek bir küçük LLM çağrısıyla JSON olarak çıkarılır.
2. search_commits + pickaxe + file_history (+ search_mrs) sonuçları birleştirilir.
3. İlk N commit'in detayı bağlama konur ve cevap tek çağrıda üretilir.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from gitex.agent.citations import extract_mrs, extract_shas
from gitex.agent.loop import (
    AgentResult,
    EventFn,
    ToolCallLog,
    _add_usage,
    _noop,
    finalize,
    system_prompt,
)
from gitex.agent.prompts import EXTRACT_SYSTEM, SIMPLE_SYSTEM
from gitex.agent.tools import Toolbox, _parse_date
from gitex.git.pathmatch import has_glob
from gitex.llm.base import LLMProvider, Message
from gitex.textnorm import fold, tokens

_CODE_FENCE = re.compile(r"`([^`]+)`")
_QUOTED = re.compile(r"[\"“”]([^\"“”]{2,80})[\"“”]")
_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)(\(\))?")
_PATHLIKE = re.compile(r"(?<![\w/])([\w.\-]+(?:/[\w.\-*]+)+/?|[\w\-]+\.[A-Za-z]{1,5})(?![\w/])")
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}(?:-\d{2})?)\b")
_RELATIVE = re.compile(
    r"\b(?:son|last|past)\s+(\d+)\s*(gun|gunde|gunluk|hafta|haftada|ay|ayda|yil|yilda|days?|weeks?|months?|years?)"
)
_BEFORE_WORDS = ("once", "before", "until", "kadar")
_UNIT_DAYS = {
    "gun": 1,
    "day": 1,
    "hafta": 7,
    "week": 7,
    "ay": 30,
    "month": 30,
    "yil": 365,
    "year": 365,
}


@dataclass
class QueryPlan:
    keywords: list[str] = field(default_factory=list)
    code_terms: list[str] = field(default_factory=list)
    path: str | None = None
    since: date | None = None
    until: date | None = None
    shas: list[str] = field(default_factory=list)
    mrs: list[int] = field(default_factory=list)

    @property
    def has_anchor(self) -> bool:
        return bool(self.code_terms or self.path or self.shas or self.mrs)


def _is_code_ident(word: str, call: bool) -> bool:
    if call:
        return True
    if "_" in word.strip("_") and len(word) > 2:
        return True
    return bool(re.search(r"[a-z][A-Z]", word))  # camelCase


def rule_based_plan(question: str, toolbox: Toolbox, today: date | None = None) -> QueryPlan:
    today = today or date.today()
    plan = QueryPlan()
    consumed: list[str] = []

    for m in _CODE_FENCE.finditer(question):
        term = m.group(1).strip()
        consumed.append(term)
        if "/" in term or re.fullmatch(r"[\w\-]+\.[A-Za-z]{1,5}", term):
            plan.path = plan.path or term
        elif re.fullmatch(r"[0-9a-f]{7,40}", term):
            pass  # SHA olarak aşağıda yakalanır
        else:
            plan.code_terms.append(term)
    for m in _QUOTED.finditer(question):
        plan.code_terms.append(m.group(1).strip())
        consumed.append(m.group(1))

    for token in extract_shas(question):
        full = toolbox.repo.resolve(token)
        if full:
            plan.shas.append(full)
            consumed.append(token)
    plan.mrs = extract_mrs(question)

    if plan.path is None:
        for m in _PATHLIKE.finditer(question):
            candidate = m.group(1).rstrip(".")
            resolved = _resolve_path(candidate, toolbox)
            if resolved:
                plan.path = resolved
                consumed.append(candidate)
                break

    for m in _IDENT.finditer(question):
        word, call = m.group(1), bool(m.group(2))
        if any(word in c for c in consumed):
            continue
        if _is_code_ident(word, call) and word not in plan.code_terms:
            plan.code_terms.append(word)
            consumed.append(word)

    folded = fold(question)
    rel = _RELATIVE.search(folded)
    if rel:
        n, unit = int(rel.group(1)), rel.group(2)
        days = next(v for k, v in _UNIT_DAYS.items() if unit.startswith(k))
        plan.since = today - timedelta(days=n * days)
    for m in _ISO_DATE.finditer(question):
        d = _parse_date(m.group(1))
        before = folded[m.end() : m.end() + 25]
        if any(w in before for w in _BEFORE_WORDS):
            plan.until = d
        elif plan.since is None:
            plan.since = d
        else:
            plan.until = d

    rest = question
    for c in consumed:
        rest = rest.replace(c, " ")
    plan.keywords = [t for t in tokens(_ISO_DATE.sub(" ", rest)) if not t.isdigit()][:8]
    return plan


def _resolve_path(candidate: str, toolbox: Toolbox) -> str | None:
    if has_glob(candidate):
        return candidate if toolbox.repo.list_paths(candidate, limit=1) else None
    clean = candidate.strip("/")
    if clean in toolbox.repo.list_paths(clean, limit=50):
        return clean
    matches = toolbox.repo.list_paths(clean, limit=5)
    if len(matches) == 1:
        return matches[0]
    if toolbox.repo.path_exists_in_history(clean):
        return clean
    return None


def llm_plan(
    question: str, provider: LLMProvider, toolbox: Toolbox, result: AgentResult
) -> QueryPlan | None:
    """Kurallar yetersizse tek bir küçük LLM çağrısıyla JSON parametre çıkarımı."""
    resp = provider.chat([Message("system", EXTRACT_SYSTEM), Message("user", question)])
    _add_usage(result.usage, resp.usage)
    data = _loose_json(resp.text)
    if not isinstance(data, dict):
        return None
    plan = QueryPlan()
    plan.keywords = [str(k) for k in data.get("keywords") or [] if str(k).strip()][:6]
    plan.code_terms = [str(k) for k in data.get("code_terms") or [] if len(str(k).strip()) > 1][:4]
    raw_path = data.get("path")
    if isinstance(raw_path, str) and raw_path.strip():
        plan.path = _resolve_path(raw_path.strip(), toolbox)
    for key in ("since", "until"):
        with contextlib.suppress(ValueError):
            setattr(plan, key, _parse_date(data.get(key)))
    return plan


def _loose_json(text: str) -> Any:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def merge_plans(base: QueryPlan, extra: QueryPlan) -> QueryPlan:
    base.code_terms += [t for t in extra.code_terms if t not in base.code_terms]
    base.keywords += [t for t in extra.keywords if t not in base.keywords]
    base.path = base.path or extra.path
    base.since = base.since or extra.since
    base.until = base.until or extra.until
    return base


def gather_context(
    plan: QueryPlan,
    toolbox: Toolbox,
    *,
    top_n: int,
    budget: int,
    log: list[ToolCallLog],
    on_event: EventFn,
) -> str:
    sections: list[str] = []
    ranked: list[str] = list(plan.shas)

    def run(name: str, args: dict[str, Any], section_budget: int) -> str:
        on_event("tool_call", {"name": name, "arguments": args})
        old = toolbox.budget
        toolbox.budget = section_budget
        try:
            res = toolbox.execute(name, args)
        finally:
            toolbox.budget = old
        log.append(ToolCallLog(name, args, not res.is_error, res.truncated, len(res.text)))
        on_event(
            "tool_result",
            {
                "name": name,
                "ok": not res.is_error,
                "chars": len(res.text),
                "truncated": res.truncated,
            },
        )
        return res.text

    overview_budget = max(800, budget // 6)
    dates = {k: v.isoformat() for k, v in (("since", plan.since), ("until", plan.until)) if v}

    for term in plan.code_terms[:3]:
        args: dict[str, Any] = {"term": term, "limit": 10}
        if plan.path:
            args["path"] = plan.path
        text = run("pickaxe", args, overview_budget)
        sections.append(f"## pickaxe: {term}\n{text}")
        hits = _shas_in(text, toolbox)  # yeniden eskiye
        # İlk ortaya çıkış (en eski) en önemlisi; sonra en yeniler.
        for sha in [*reversed(hits[-1:]), *hits[:-1]]:
            if sha not in ranked:
                ranked.append(sha)

    if plan.keywords or not plan.code_terms:
        args = {"query": " ".join(plan.keywords), "limit": 10, **dates}
        if plan.path:
            args["path"] = plan.path
        text = run("search_commits", args, overview_budget)
        if text.startswith("Sonuç yok") and plan.path:
            args.pop("path")
            text = run("search_commits", args, overview_budget)
        sections.append(f"## commit mesajı araması\n{text}")
        ranked += [s for s in _shas_in(text, toolbox) if s not in ranked]

    if plan.path:
        text = run("file_history", {"path": plan.path, "limit": 15, **dates}, overview_budget)
        sections.append(f"## dosya geçmişi: {plan.path}\n{text}")
        ranked += [s for s in _shas_in(text, toolbox) if s not in ranked]

    if toolbox.gitlab_enabled:
        query = " ".join(plan.keywords + plan.code_terms) or " ".join(plan.code_terms)
        mr_iids = list(plan.mrs)
        if query.strip():
            text = run("search_mrs", {"query": query, **dates}, overview_budget)
            sections.append(f"## merge request araması\n{text}")
            mr_iids += [m for m in extract_mrs(text) if m not in mr_iids]
        for sha in ranked[:top_n]:
            mr_iids += [m.iid for m in toolbox.search.mrs_for_commit(sha) if m.iid not in mr_iids]
        for iid in mr_iids[:2]:
            sections.append(f"## MR !{iid}\n" + run("get_mr", {"iid": iid}, overview_budget))

    used = sum(len(s) for s in sections)
    remaining = max(1500, budget - used)
    top = ranked[:top_n]
    per_commit = max(800, remaining // max(1, len(top)))
    for sha in top:
        sections.append(f"## commit {sha[:7]}\n" + run("get_commit", {"sha": sha}, per_commit))
    if not top and not sections:
        sections.append("(İlgili commit bulunamadı.)")
    return "\n\n".join(sections)


def _shas_in(text: str, toolbox: Toolbox) -> list[str]:
    out: list[str] = []
    for token in extract_shas(text):
        full = toolbox.search.commit_exists(token)
        if full and full not in out:
            out.append(full)
    return out


def run_simple(
    question: str,
    provider: LLMProvider,
    toolbox: Toolbox,
    *,
    top_n: int = 6,
    context_chars: int = 40000,
    use_llm_extract: bool = True,
    path: str | None = None,
    since: date | None = None,
    until: date | None = None,
    on_event: EventFn = _noop,
) -> AgentResult:
    result = AgentResult(answer="", mode="simple", model=provider.model)
    plan = rule_based_plan(question, toolbox)
    # CLI'dan açıkça verilen kapsam kurallardan önceliklidir.
    plan.path = path or plan.path
    plan.since = since or plan.since
    plan.until = until or plan.until
    if not plan.has_anchor and use_llm_extract:
        on_event("llm_call", {"purpose": "parametre çıkarımı"})
        extra = llm_plan(question, provider, toolbox, result)
        if extra is not None:
            plan = merge_plans(plan, extra)
    on_event("plan", {"keywords": plan.keywords, "code_terms": plan.code_terms, "path": plan.path})
    context = gather_context(
        plan, toolbox, top_n=top_n, budget=context_chars, log=result.tool_calls, on_event=on_event
    )
    messages = [
        Message("system", system_prompt(toolbox, SIMPLE_SYSTEM)),
        Message("user", f"Soru: {question}\n\nBağlam:\n{context}\n\nSoru (tekrar): {question}"),
    ]
    on_event("llm_call", {"purpose": "cevap"})
    resp = provider.chat(messages)
    _add_usage(result.usage, resp.usage)
    answer = resp.text.strip() or "Bir cevap üretilemedi (model boş yanıt döndü)."
    return finalize(provider, toolbox, messages, answer, result, on_event)
