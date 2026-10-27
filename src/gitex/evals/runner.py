"""Değerlendirme: fixture deposunda soru setini çalıştırır, kaynak isabetini ve uydurmayı ölçer.

Metrikler:
- kaynak isabeti: beklenen commit'lerden cevapta (doğrulanmış kaynak olarak) geçenlerin oranı
- tam isabet: beklenen commit'lerin hepsi geçen soru oranı
- uydurma referans oranı: doğrulanamayan referans / cevaptaki tüm referanslar
- "bulamadım" doğruluğu: cevabı olmayan sorularda model bulamadığını söyleyip SHA vermedi mi
- metin: `expect_text` ifadelerinden en az biri cevapta geçiyor mu
"""

from __future__ import annotations

import re
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gitex.config import Config
from gitex.errors import GitexError
from gitex.evals.fixture import FixtureRepo, build_fixture_repo
from gitex.git.reader import GitRepo
from gitex.llm.base import LLMProvider
from gitex.session import Mode, Session

NOT_FOUND_RE = re.compile(
    r"bulamad|bulunamad|bulunmuyor|yer almıyor|kayıt yok|iz yok|"
    r"not find|couldn't find|could not find|no (?:record|commit|evidence|mention)|not found|"
    r"does not appear|doesn't appear|no such",
    re.IGNORECASE,
)


@dataclass
class Case:
    id: str
    question: str
    expected: list[str] = field(default_factory=list)
    expect_text: list[str] = field(default_factory=list)
    expect_not_found: bool = False


@dataclass
class CaseResult:
    case: Case
    expected_shas: list[str]
    cited_shas: list[str]
    unverified: list[str]
    corrected: bool
    answer: str
    tool_calls: int
    seconds: float
    tokens: int
    error: str | None = None

    @property
    def recall(self) -> float:
        if not self.expected_shas:
            return 1.0
        return len(set(self.expected_shas) & set(self.cited_shas)) / len(self.expected_shas)

    @property
    def full_hit(self) -> bool:
        return self.error is None and self.recall == 1.0

    @property
    def text_ok(self) -> bool | None:
        if not self.case.expect_text:
            return None
        low = self.answer.lower()
        return any(t.lower() in low for t in self.case.expect_text)

    @property
    def not_found_ok(self) -> bool | None:
        if not self.case.expect_not_found:
            return None
        return (
            bool(NOT_FOUND_RE.search(self.answer)) and not self.cited_shas and not self.unverified
        )

    @property
    def refs_total(self) -> int:
        return len(self.cited_shas) + len(self.unverified)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "question": self.case.question,
            "expected": self.expected_shas,
            "cited": self.cited_shas,
            "unverified": self.unverified,
            "recall": round(self.recall, 3),
            "full_hit": self.full_hit,
            "text_ok": self.text_ok,
            "not_found_ok": self.not_found_ok,
            "corrected": self.corrected,
            "tool_calls": self.tool_calls,
            "seconds": round(self.seconds, 2),
            "tokens": self.tokens,
            "error": self.error,
            "answer": self.answer,
        }


@dataclass
class Report:
    model: str
    mode: str
    results: list[CaseResult]

    def summary(self) -> dict[str, Any]:
        rs = self.results
        n = len(rs) or 1
        refs = sum(r.refs_total for r in rs)
        unverified = sum(len(r.unverified) for r in rs)
        texts = [r.text_ok for r in rs if r.text_ok is not None]
        nf = [r.not_found_ok for r in rs if r.not_found_ok is not None]
        answerable = [r for r in rs if not r.case.expect_not_found]
        return {
            "model": self.model,
            "mode": self.mode,
            "cases": len(rs),
            "errors": sum(1 for r in rs if r.error),
            "source_recall": round(sum(r.recall for r in answerable) / (len(answerable) or 1), 3),
            "full_hit_rate": round(sum(r.full_hit for r in answerable) / (len(answerable) or 1), 3),
            "fabricated_ref_rate": round(unverified / refs, 3) if refs else 0.0,
            "corrected_cases": sum(1 for r in rs if r.corrected),
            "text_match_rate": round(sum(texts) / len(texts), 3) if texts else None,
            "not_found_accuracy": round(sum(nf) / len(nf), 3) if nf else None,
            "avg_tool_calls": round(sum(r.tool_calls for r in rs) / n, 2),
            "total_tokens": sum(r.tokens for r in rs),
            "total_seconds": round(sum(r.seconds for r in rs), 1),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary(), "cases": [r.to_dict() for r in self.results]}


def default_questions_path() -> Path:
    candidates = [
        Path.cwd() / "evals" / "questions.toml",
        Path(__file__).resolve().parents[3] / "evals" / "questions.toml",
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise GitexError(
        "evals/questions.toml bulunamadı.", hint="Repo kökünden çalıştırın ya da --questions verin."
    )


def load_cases(path: Path) -> list[Case]:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    cases = [Case(**raw) for raw in data.get("case", [])]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise GitexError("Değerlendirme setinde yinelenen id var.")
    return cases


def render_question(case: Case, fx: FixtureRepo) -> str:
    return re.sub(r"\{sha:(\w+)\}", lambda m: fx.sha(m.group(1))[:7], case.question)


def run_case(session: Session, case: Case, fx: FixtureRepo, mode: Mode | None) -> CaseResult:
    for key in case.expected:
        if key not in fx.shas:
            raise GitexError(f"{case.id}: bilinmeyen fixture adımı '{key}'")
    expected = [fx.sha(k) for k in case.expected]
    session.toolbox.seen_shas.clear()
    session.toolbox.seen_mrs.clear()
    start = time.monotonic()
    try:
        result = session.ask(render_question(case, fx), mode=mode)
    except GitexError as exc:
        return CaseResult(
            case, expected, [], [], False, "", 0, time.monotonic() - start, 0, str(exc)
        )
    cited = [s.ref for s in result.sources if s.kind == "commit"]
    return CaseResult(
        case=case,
        expected_shas=expected,
        cited_shas=cited,
        unverified=list(result.unverified),
        corrected=result.corrected,
        answer=result.answer,
        tool_calls=len(result.tool_calls),
        seconds=time.monotonic() - start,
        tokens=sum(result.usage.values()),
    )


def run_evals(
    config: Config,
    cases: list[Case],
    *,
    mode: Mode | None = None,
    provider: LLMProvider | None = None,
    workdir: Path | None = None,
    on_case: Any = None,
) -> Report:
    # Windows'ta git nesneleri salt-okunur olabilir; temizlik hatası sonucu etkilemesin.
    with tempfile.TemporaryDirectory(prefix="gitex-eval-", ignore_cleanup_errors=True) as tmp:
        base = workdir or Path(tmp)
        fx = build_fixture_repo(base / "repo")
        repo = GitRepo(fx.path)
        session = Session.open(repo, config, provider=provider)
        try:
            results: list[CaseResult] = []
            for case in cases:
                res = run_case(session, case, fx, mode)
                results.append(res)
                if on_case:
                    on_case(res)
        finally:
            session.close()
        return Report(model=session.provider.model, mode=mode or config.llm.mode, results=results)
