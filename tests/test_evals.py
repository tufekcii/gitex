from __future__ import annotations

from pathlib import Path

import pytest

from gitsor.agent.prompts import EXTRACT_SYSTEM
from gitsor.config import Config
from gitsor.evals.__main__ import main as eval_main
from gitsor.evals.fixture import FixtureRepo, build_fixture_repo
from gitsor.evals.runner import Case, CaseResult, default_questions_path, load_cases, run_evals
from gitsor.llm.base import LLMResponse, Message, ToolSpec

QUESTIONS = Path(__file__).resolve().parents[1] / "evals" / "questions.toml"


def test_question_set_is_valid(fixture_repo: FixtureRepo) -> None:
    cases = load_cases(QUESTIONS)
    assert 15 <= len(cases) <= 20
    for c in cases:
        assert all(k in fixture_repo.shas for k in c.expected), c.id
        assert c.expected or c.expect_not_found, c.id
    assert default_questions_path().is_file()


def test_fixture_is_deterministic(fixture_repo: FixtureRepo, tmp_path: Path) -> None:
    other = build_fixture_repo(tmp_path / "again")
    assert other.shas == fixture_repo.shas


class OracleProvider:
    """Beklenen SHA'ları bilen sahte model; bir soruda bilerek SHA uydurur."""

    name = "oracle"
    model = "oracle-1"

    def __init__(self, cases: list[Case], fx: FixtureRepo, liar: str) -> None:
        self.cases = cases
        self.fx = fx
        self.liar = liar

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        if messages[0].content == EXTRACT_SYSTEM:
            return LLMResponse(text="{}")
        prompt = messages[-1].content if messages[-1].role == "user" else messages[1].content
        if "doğrulanamadı" in prompt:  # düzeltme isteği: yine yanlış kalsın
            return LLMResponse(text="Kaynak: 9999abc")
        case = next(c for c in self.cases if c.question.split("{")[0][:25] in prompt)
        if case.expect_not_found:
            return LLMResponse(text="Bunu depoda bulamadım; commit mesajlarında ve kodda aradım.")
        if case.id == self.liar:
            return LLMResponse(text="Kaynak: 9999abc")
        refs = ", ".join(self.fx.sha(k)[:7] for k in case.expected)
        return LLMResponse(text=f"Kaynaklar: {refs}. {' '.join(case.expect_text[:1])}")


def test_run_evals_scores(fixture_repo: FixtureRepo, tmp_path: Path) -> None:
    cases = [
        c
        for c in load_cases(QUESTIONS)
        if c.id in {"rate-limit-added", "rename", "legacy-delete", "not-found-paypal"}
    ]
    provider = OracleProvider(cases, fixture_repo, liar="legacy-delete")
    report = run_evals(Config(), cases, mode="simple", provider=provider, workdir=tmp_path / "eval")
    by_id = {r.case.id: r for r in report.results}
    assert by_id["rate-limit-added"].full_hit
    assert by_id["rate-limit-added"].text_ok is True
    assert by_id["legacy-delete"].recall == 0.0
    assert by_id["legacy-delete"].unverified == ["9999abc"]
    assert by_id["legacy-delete"].corrected
    assert by_id["not-found-paypal"].not_found_ok is True
    s = report.summary()
    assert s["cases"] == 4
    assert s["source_recall"] == pytest.approx(2 / 3, abs=0.01)
    assert s["fabricated_ref_rate"] == pytest.approx(1 / 3, abs=0.01)
    assert s["not_found_accuracy"] == 1.0


def test_case_result_metrics() -> None:
    case = Case(id="x", question="?", expected=["a", "b"], expect_text=["foo"])
    r = CaseResult(case, ["a" * 40, "b" * 40], ["a" * 40], ["1234abc"], True, "FOO bar", 2, 1.0, 10)
    assert r.recall == 0.5
    assert not r.full_hit
    assert r.text_ok is True
    assert r.refs_total == 2
    nf = CaseResult(
        Case(id="n", question="?", expect_not_found=True),
        [],
        ["c" * 40],
        [],
        False,
        "bulamadım",
        0,
        0,
        0,
    )
    assert nf.not_found_ok is False  # bulamadım dedi ama SHA da verdi


def test_cli_entry_reports_config_error(capsys: pytest.CaptureFixture[str]) -> None:
    # openai_compat + base_url yok: ağa çıkmadan anlamlı hata vermeli.
    code = eval_main(["--case", "rename", "--json"])
    assert code == 1
    assert "base_url" in capsys.readouterr().err
