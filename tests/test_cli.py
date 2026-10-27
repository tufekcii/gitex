from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from gitex.cli import app
from gitex.evals.fixture import FixtureRepo

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "gitex" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_init_creates_config_and_gitignore(fixture_repo: FixtureRepo) -> None:
    result = runner.invoke(app, ["-C", str(fixture_repo.path), "init"])
    assert result.exit_code == 0, result.output
    assert (fixture_repo.path / ".gitex" / "config.toml").is_file()
    gitignore = (fixture_repo.path / ".gitignore").read_text(encoding="utf-8")
    assert ".gitex/" in gitignore
    # İkinci çalıştırma tekrar eklememeli.
    runner.invoke(app, ["-C", str(fixture_repo.path), "init"])
    gitignore = (fixture_repo.path / ".gitignore").read_text(encoding="utf-8")
    assert gitignore.count(".gitex/") == 1


def test_index_and_status(fixture_repo: FixtureRepo) -> None:
    result = runner.invoke(app, ["-C", str(fixture_repo.path), "index", "-q"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["-C", str(fixture_repo.path), "status"])
    assert result.exit_code == 0, result.output
    assert str(len(fixture_repo.shas)) in result.output
    assert "yalnızca yerel git" in result.output


def test_not_a_repo_message(tmp_path: Path) -> None:
    result = runner.invoke(app, ["-C", str(tmp_path), "status"])
    assert result.exit_code == 1
    assert "git deposu değil" in result.output


# ---------------------------------------------------------------------- soru komutları


def _use_provider(monkeypatch, provider) -> None:
    import gitex.cli as cli

    monkeypatch.setattr(cli, "provider_factory", lambda _cfg: provider)


def test_ask_json_auto_indexes(fixture_repo: FixtureRepo, monkeypatch) -> None:
    import json

    from tests.fakes import ScriptedProvider, call, text

    sha = fixture_repo.sha("rate_limit")
    provider = ScriptedProvider(
        [call("search_commits", query="rate limit"), text(f"Rate limit {sha[:7]} ile eklendi.")]
    )
    _use_provider(monkeypatch, provider)
    result = runner.invoke(
        app, ["-C", str(fixture_repo.path), "ask", "Rate limit ne zaman eklendi?", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["sources"][0]["ref"] == sha
    assert data["tool_calls"][0]["name"] == "search_commits"
    assert (fixture_repo.path / ".gitex" / "index.db").exists()


def test_ask_show_context(fixture_repo: FixtureRepo, monkeypatch) -> None:
    from tests.fakes import ScriptedProvider, text

    _use_provider(monkeypatch, ScriptedProvider([text("Bulamadım.")]))
    result = runner.invoke(
        app,
        [
            "-C",
            str(fixture_repo.path),
            "ask",
            "`debug_dump` ne zaman?",
            "--mode",
            "simple",
            "--show-context",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "pickaxe: debug_dump" in result.output
    assert "Bulamadım" in result.output


def test_explain_commit(fixture_repo: FixtureRepo, monkeypatch) -> None:
    from tests.fakes import ScriptedProvider, text

    sha = fixture_repo.sha("soft_delete")
    provider = ScriptedProvider([text(f"{sha[:7]} soft-delete'e geçti.")])
    _use_provider(monkeypatch, provider)
    result = runner.invoke(app, ["-C", str(fixture_repo.path), "explain", sha[:7], "-q"])
    assert result.exit_code == 0, result.output
    assert sha[:12] in provider.calls[0][0][1].content


def test_explain_mr_without_gitlab(fixture_repo: FixtureRepo) -> None:
    result = runner.invoke(app, ["-C", str(fixture_repo.path), "explain", "!3"])
    assert result.exit_code == 1
    assert "GitLab" in result.output


def test_when(fixture_repo: FixtureRepo) -> None:
    result = runner.invoke(app, ["-C", str(fixture_repo.path), "when", "debug_dump"])
    assert result.exit_code == 0, result.output
    assert fixture_repo.sha("debug_add")[:7] in result.output
    assert "kaldırıldı" in result.output


def test_when_json(fixture_repo: FixtureRepo) -> None:
    import json

    result = runner.invoke(
        app, ["-C", str(fixture_repo.path), "when", "RATE_LIMIT = [0-9]+", "-E", "--json"]
    )
    data = json.loads(result.stdout)
    assert [d["sha"] for d in data] == [
        fixture_repo.sha("rate_limit_10"),
        fixture_repo.sha("rate_limit"),
    ]


def test_file_summary(fixture_repo: FixtureRepo) -> None:
    import json

    result = runner.invoke(app, ["-C", str(fixture_repo.path), "file", "app/helpers.py", "--json"])
    data = json.loads(result.stdout)
    assert data["commits"] == 2
    assert data["renames"][0]["from"] == "app/utils.py"
    result = runner.invoke(app, ["-C", str(fixture_repo.path), "file", "payment/service.py"])
    assert result.exit_code == 0
    assert "Zeynep Kaya" in result.output


def test_llm_unreachable_message(fixture_repo: FixtureRepo, monkeypatch) -> None:
    from gitex.errors import LLMError

    class Down:
        name = "down"
        model = "m"

        def chat(self, messages, tools=None):
            raise LLMError("LLM'e ulaşılamıyor (http://localhost:9).", hint="Sunucuyu başlatın.")

    _use_provider(monkeypatch, Down())
    result = runner.invoke(app, ["-C", str(fixture_repo.path), "ask", "x?"])
    assert result.exit_code == 1
    assert "ulaşılamıyor" in result.output


def test_sync_command(fixture_repo: FixtureRepo, monkeypatch) -> None:
    import responses

    from tests.gitlab_mock import BASE, PROJECT, GitLabMock, scenario

    cfg_dir = fixture_repo.path / ".gitex"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text(
        f'[gitlab]\nurl = "{BASE}"\nproject = "{PROJECT}"\n', encoding="utf-8"
    )
    monkeypatch.setenv("GITEX_GITLAB_TOKEN", "dummy")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        GitLabMock(scenario(fixture_repo)).install(rsps)
        result = runner.invoke(app, ["-C", str(fixture_repo.path), "sync"])
    assert result.exit_code == 0, result.output
    assert "3 MR" in result.output
    status = runner.invoke(app, ["-C", str(fixture_repo.path), "status"])
    assert "3 / 2" in status.output  # MR / issue
    assert "grup/proje" in status.output


def test_sync_without_gitlab(fixture_repo: FixtureRepo) -> None:
    result = runner.invoke(app, ["-C", str(fixture_repo.path), "sync"])
    assert result.exit_code == 1
    assert "GitLab ayarlanmamış" in result.output


def test_chat_keeps_context(fixture_repo: FixtureRepo, monkeypatch) -> None:
    from tests.fakes import ScriptedProvider, text

    sha = fixture_repo.sha("soft_delete")[:7]
    provider = ScriptedProvider(
        [text(f"{sha} ile soft-delete'e geçti."), text("Zeynep Kaya yaptı.")]
    )
    _use_provider(monkeypatch, provider)
    result = runner.invoke(
        app,
        ["-C", str(fixture_repo.path), "chat", "-q"],
        input="Kullanıcı silme ne zaman soft-delete oldu?\nKim yaptı?\n/çık\n",
    )
    assert result.exit_code == 0, result.output
    assert "Zeynep Kaya yaptı" in result.output
    second = provider.calls[1][0]
    contents = [m.content for m in second]
    assert "Kullanıcı silme ne zaman soft-delete oldu?" in contents
    assert any(sha in c for c in contents)


def test_chat_simple_mode_followup(fixture_repo: FixtureRepo, monkeypatch) -> None:
    from tests.fakes import ScriptedProvider, text

    provider = ScriptedProvider([text("Bulamadım."), text("{}"), text("Yine bulamadım.")])
    _use_provider(monkeypatch, provider)
    result = runner.invoke(
        app,
        ["-C", str(fixture_repo.path), "chat", "--mode", "simple", "-q"],
        input="`debug_dump` ne zaman?\n/yeni\n/mod simple\nPeki neden?\n",
    )
    assert result.exit_code == 0, result.output
    assert "Konuşma sıfırlandı" in result.output
    # /yeni sonrası önceki tur eklenmemeli.
    assert "Önceki konuşma" not in provider.calls[-1][0][-1].content
