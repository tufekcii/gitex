"""Yükleniyor göstergesi: kullanıcı beklerken her an ne olduğunu gösterir, sonra kendini siler."""

from __future__ import annotations

import io
import time

import pytest
from rich.console import Console
from typer.testing import CliRunner

import gitex.cli as cli
import gitex.ui as ui
from gitex.evals.fixture import FixtureRepo
from gitex.llm.base import LLMResponse, Message, ToolSpec
from gitex.ui import SPINNER_FRAMES, Activity
from tests.fakes import ScriptedProvider, call, text

runner = CliRunner()


def _terminal() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, force_terminal=True, width=100, color_system=None), buf


def test_activity_renders_message_detail_and_elapsed() -> None:
    con, buf = _terminal()
    with Activity("Model düşünüyor…", out=con) as a:
        time.sleep(0.3)
        a.update(detail="pickaxe")
        time.sleep(0.3)
    out = buf.getvalue()
    assert any(frame in out for frame in SPINNER_FRAMES)
    assert "Model düşünüyor…" in out
    assert "pickaxe" in out
    assert "0 sn" in out


def test_activity_is_silent_without_terminal() -> None:
    buf = io.StringIO()
    con = Console(file=buf, force_terminal=False)
    with Activity("x", out=con) as a:
        assert not a.enabled
    assert buf.getvalue() == ""


def test_activity_can_be_disabled() -> None:
    con, buf = _terminal()
    with Activity("x", out=con, enabled=False):
        pass
    assert buf.getvalue() == ""


class SlowProvider(ScriptedProvider):
    """Her çağrıda biraz bekler ki gösterge çizilebilsin."""

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        time.sleep(0.35)
        return super().chat(messages, tools)


def test_events_drive_activity_messages() -> None:
    activity = Activity("Hazırlanıyor…", enabled=False)
    on_event = cli._event_printer(True, activity)
    on_event("llm_call", {})
    assert activity.message == "Model düşünüyor…"
    on_event("tool_call", {"name": "pickaxe", "arguments": {"term": "x"}})
    assert (activity.message, activity.detail) == ("Geçmiş taranıyor…", "pickaxe")
    on_event("tool_result", {"name": "pickaxe", "ok": True, "chars": 10, "truncated": False})
    assert (activity.message, activity.detail) == ("Model düşünüyor…", "")
    on_event("citation_retry", {"shas": ["1234abc"], "mrs": []})
    assert activity.message == "Kaynaklar düzeltiliyor…"


def test_ask_shows_activity_while_waiting(
    fixture_repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    con, buf = _terminal()
    monkeypatch.setattr(ui, "err_console", con)
    sha = fixture_repo.sha("rate_limit")[:7]
    provider = SlowProvider(
        [call("search_commits", query="rate limit"), text(f"{sha} ile eklendi.")]
    )
    monkeypatch.setattr(cli, "provider_factory", lambda _cfg: provider)
    r = runner.invoke(cli.app, ["-C", str(fixture_repo.path), "ask", "Rate limit ne zaman?", "-q"])
    assert r.exit_code == 0, r.output
    shown = buf.getvalue()
    assert any(frame in shown for frame in SPINNER_FRAMES)
    assert "Depo ve model hazırlanıyor…" in shown
    assert "Model düşünüyor…" in shown
    # Cevap stdout'ta; gösterge oraya karışmaz.
    assert sha in r.stdout
    assert not any(frame in r.stdout for frame in SPINNER_FRAMES)
