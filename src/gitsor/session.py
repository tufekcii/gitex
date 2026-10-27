"""Soru-cevap oturumu: repo + config + indeks + araçlar + LLM'i bir araya getirir.

CLI (`ask`, `explain`, `chat`) ve değerlendirme betiği bu katmanı kullanır.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from gitsor.agent.loop import AgentResult, EventFn, _noop, run_agent
from gitsor.agent.simple import run_simple
from gitsor.agent.tools import Toolbox
from gitsor.config import Config
from gitsor.git.reader import GitRepo
from gitsor.index.db import Database
from gitsor.index.indexer import ProgressFn, ensure_index
from gitsor.llm.base import LLMProvider, Message
from gitsor.llm.factory import make_provider

Mode = Literal["agent", "simple"]


def scope_note(path: str | None, since: date | None, until: date | None) -> str:
    parts = []
    if path:
        parts.append(f"yalnızca `{path}` yolu")
    if since:
        parts.append(f"{since.isoformat()} ve sonrası")
    if until:
        parts.append(f"{until.isoformat()} ve öncesi")
    return f"\n\n(Kapsam: {'; '.join(parts)}.)" if parts else ""


@dataclass
class Session:
    repo: GitRepo
    config: Config
    db: Database
    provider: LLMProvider
    toolbox: Toolbox = field(init=False)
    history: list[Message] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.toolbox = Toolbox(self.repo, self.db, self.config)

    @classmethod
    def open(
        cls,
        repo: GitRepo,
        config: Config,
        *,
        provider: LLMProvider | None = None,
        provider_factory: Callable[[Config], LLMProvider] | None = None,
        progress: ProgressFn | None = None,
    ) -> Session:
        db, _stats = ensure_index(repo, progress=progress)
        if provider is None:
            provider = (provider_factory or (lambda c: make_provider(c.llm)))(config)
        return cls(repo=repo, config=config, db=db, provider=provider)

    def close(self) -> None:
        self.db.close()

    def ask(
        self,
        question: str,
        *,
        mode: Mode | None = None,
        path: str | None = None,
        since: date | None = None,
        until: date | None = None,
        keep_history: bool = False,
        on_event: EventFn = _noop,
    ) -> AgentResult:
        mode = mode or self.config.llm.mode
        full_question = question + scope_note(path, since, until)
        if mode == "simple":
            return run_simple(
                full_question,
                self.provider,
                self.toolbox,
                top_n=self.config.llm.simple_top_n,
                context_chars=self.config.llm.context_chars,
                path=path,
                since=since,
                until=until,
                on_event=on_event,
            )
        result, messages = run_agent(
            full_question,
            self.provider,
            self.toolbox,
            max_tool_calls=self.config.llm.max_tool_calls,
            history=self.history if keep_history and self.history else None,
            on_event=on_event,
        )
        if keep_history:
            self.history = messages
        return result
