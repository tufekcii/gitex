from __future__ import annotations

import pytest

from gitsor.agent.citations import WARNING, extract_mrs, extract_shas
from gitsor.agent.loop import run_agent
from gitsor.agent.simple import rule_based_plan, run_simple
from gitsor.agent.tools import Toolbox
from gitsor.config import Config
from gitsor.evals.fixture import FAKE_API_KEY, FixtureRepo
from gitsor.git.reader import GitRepo
from gitsor.index.db import Database
from tests.fakes import ScriptedProvider, call, text


@pytest.fixture
def toolbox(repo: GitRepo, indexed_db: Database) -> Toolbox:
    return Toolbox(repo, indexed_db, Config())


def _short(fx: FixtureRepo, key: str) -> str:
    return fx.sha(key)[:7]


def test_agent_loop_uses_tools_and_cites(toolbox: Toolbox, fixture_repo: FixtureRepo) -> None:
    add, rem = _short(fixture_repo, "debug_add"), _short(fixture_repo, "debug_remove")
    provider = ScriptedProvider(
        [
            call("pickaxe", term="debug_dump"),
            text(
                f"`debug_dump` {add} (2026-02-10, Mehmet Demir) ile eklendi, {rem} ile kaldırıldı.\n\n"
                f"Kaynaklar:\n- {add}\n- {rem}"
            ),
        ]
    )
    events: list[str] = []
    result, messages = run_agent(
        "debug_dump ne zaman eklendi?", provider, toolbox, on_event=lambda k, d: events.append(k)
    )
    assert result.unverified == []
    assert not result.corrected
    assert {s.ref for s in result.sources} == {
        fixture_repo.sha("debug_add"),
        fixture_repo.sha("debug_remove"),
    }
    assert [t.name for t in result.tool_calls] == ["pickaxe"]
    # Araç sonucu ikinci çağrıda modele gitmiş olmalı.
    second_call_messages = provider.calls[1][0]
    tool_msgs = [m for m in second_call_messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert add in tool_msgs[0].content
    assert "tool_call" in events
    assert messages[-1].role == "assistant"


def test_gitlab_tools_hidden_without_config(toolbox: Toolbox) -> None:
    names = {s.name for s in toolbox.specs()}
    assert "search_mrs" not in names
    assert "get_mr" not in names
    assert {
        "search_commits",
        "pickaxe",
        "file_history",
        "line_history",
        "blame",
        "get_commit",
        "list_paths",
    } <= names
    assert toolbox.execute("get_mr", {"iid": 1}).is_error


def test_fabricated_sha_corrected(toolbox: Toolbox, fixture_repo: FixtureRepo) -> None:
    good = _short(fixture_repo, "rate_limit")
    provider = ScriptedProvider(
        [
            call("search_commits", query="rate limit"),
            text("Rate limit 1234abc ile eklendi."),
            text(f"Rate limit {good} (2026-01-20, Mehmet Demir) ile eklendi."),
        ]
    )
    result, _ = run_agent("Rate limit ne zaman eklendi?", provider, toolbox)
    assert result.corrected
    assert result.unverified == []
    assert good in result.answer
    correction = provider.calls[2][0][-1]
    assert correction.role == "user"
    assert "1234abc" in correction.content


def test_fabricated_sha_marked_when_still_wrong(toolbox: Toolbox) -> None:
    provider = ScriptedProvider(
        [text("Bu 1234abc ile oldu, bkz. !42."), text("Hâlâ 1234abc, bkz. !42.")]
    )
    result, _ = run_agent("ne oldu?", provider, toolbox)
    assert "1234abc" in result.unverified
    assert f"1234abc ({WARNING})" in result.answer
    # GitLab yokken MR referansı da doğrulanamaz.
    assert "!42" in result.unverified


def test_tool_budget_enforced(toolbox: Toolbox) -> None:
    provider = ScriptedProvider([call("list_paths", pattern="*")], repeat_last=True)
    result, _ = run_agent("sonsuz döngü", provider, toolbox, max_tool_calls=2)
    executed = [t for t in result.tool_calls if t.ok]
    assert len(executed) == 2
    assert "üretilemedi" in result.answer
    assert len(provider.calls) <= 2 + 2 + 1


def test_invalid_tool_arguments_reported(toolbox: Toolbox) -> None:
    provider = ScriptedProvider([call("line_history", path="auth/login.py"), text("Bulamadım.")])
    result, _ = run_agent("?", provider, toolbox)
    assert result.tool_calls[0].ok is False
    tool_msg = next(m for m in provider.calls[1][0] if m.role == "tool")
    assert tool_msg.is_error


def test_tool_outputs_are_redacted(toolbox: Toolbox, fixture_repo: FixtureRepo) -> None:
    out = toolbox.execute("get_commit", {"sha": fixture_repo.sha("settings")})
    assert FAKE_API_KEY not in out.text
    assert "s3cr3t" not in out.text
    assert "[REDACTED]" in out.text
    assert "config/prod.env" in out.text  # dosya listesinde görünür, diff'i gönderilmez
    assert "SECRET_TOKEN" not in out.text


def test_send_diffs_false(repo: GitRepo, indexed_db: Database, fixture_repo: FixtureRepo) -> None:
    cfg = Config.model_validate({"privacy": {"send_diffs": False}})
    tb = Toolbox(repo, indexed_db, cfg)
    out = tb.execute("get_commit", {"sha": fixture_repo.sha("retry"), "include_diff": True}).text
    assert "def charge_with_retry" not in out
    assert "diff gönderimi config ile kapalı" in out
    blame = tb.execute("blame", {"path": "auth/login.py", "start": 5, "end": 5}).text
    assert "RATE_LIMIT" not in blame
    lh = tb.execute("line_history", {"path": "auth/login.py", "start": 5, "end": 5}).text
    assert "+RATE_LIMIT" not in lh


def test_tool_output_truncation(repo: GitRepo, indexed_db: Database) -> None:
    cfg = Config.model_validate({"llm": {"tool_output_chars": 500}})
    tb = Toolbox(repo, indexed_db, cfg)
    out = tb.execute("search_commits", {"query": "", "limit": 50})
    assert out.truncated
    assert "kırpıldı" in out.text
    assert len(out.text) < 700


def test_get_commit_details(toolbox: Toolbox, fixture_repo: FixtureRepo) -> None:
    out = toolbox.execute("get_commit", {"sha": _short(fixture_repo, "rate_limit")}).text
    assert "Mehmet Demir" in out
    assert "ilk yer aldığı tag: v1.0" in out
    assert "Brute-force" in out
    assert "+RATE_LIMIT = 5" in out
    missing = toolbox.execute("get_commit", {"sha": "0000000"})
    assert "bulunamadı" in missing.text


# ---------------------------------------------------------------------- simple mod


def test_rule_based_plan(toolbox: Toolbox) -> None:
    plan = rule_based_plan("`debug_dump` ne zaman eklendi?", toolbox)
    assert plan.code_terms == ["debug_dump"]
    plan = rule_based_plan("payment/service.py son 3 ayda neden bu kadar değişti?", toolbox)
    assert plan.path == "payment/service.py"
    assert plan.since is not None
    plan = rule_based_plan("check_rate_limit() fonksiyonunu kim yazdı?", toolbox)
    assert "check_rate_limit" in plan.code_terms
    plan = rule_based_plan("login.py dosyasında 2026-02-01 öncesi ne oldu?", toolbox)
    assert plan.path == "auth/login.py"
    assert plan.until is not None
    assert plan.since is None


def test_simple_mode_single_call(toolbox: Toolbox, fixture_repo: FixtureRepo) -> None:
    add = _short(fixture_repo, "debug_add")
    provider = ScriptedProvider([text(f"{add} ile eklendi (2026-02-10, Mehmet Demir).")])
    result = run_simple("`debug_dump` ne zaman eklendi?", provider, toolbox)
    assert len(provider.calls) == 1
    user_msg = provider.calls[0][0][-1].content
    assert "pickaxe: debug_dump" in user_msg
    assert f"commit {add}" in user_msg
    assert result.mode == "simple"
    assert result.unverified == []
    assert [s.ref for s in result.sources] == [fixture_repo.sha("debug_add")]


def test_simple_mode_llm_extraction(toolbox: Toolbox, fixture_repo: FixtureRepo) -> None:
    refund = _short(fixture_repo, "refund")
    provider = ScriptedProvider(
        [
            text('Tabii: {"keywords": ["iade"], "code_terms": ["def refund"], "path": null}'),
            text(f"İade desteği {refund} ile geldi."),
        ]
    )
    result = run_simple("Para iadesi özelliği ne zaman geldi?", provider, toolbox)
    assert len(provider.calls) == 2
    context = provider.calls[1][0][-1].content
    assert refund in context
    assert result.unverified == []


# ---------------------------------------------------------------------- referans çıkarma


def test_extract_refs() -> None:
    assert extract_shas("bkz. 6b1285f ve deadbeef1 ama facade değil, 1234567 de değil?") == [
        "6b1285f",
        "deadbeef1",
        "1234567",
    ]
    assert extract_shas("https://x/commit/6b1285f") == []
    assert extract_mrs("!12 ve https://gitlab.com/g/p/-/merge_requests/34, &5 değil") == [12, 34]
