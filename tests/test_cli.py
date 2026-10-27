from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from gitsor.cli import app
from gitsor.evals.fixture import FixtureRepo

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "gitsor" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_init_creates_config_and_gitignore(fixture_repo: FixtureRepo) -> None:
    result = runner.invoke(app, ["-C", str(fixture_repo.path), "init"])
    assert result.exit_code == 0, result.output
    assert (fixture_repo.path / ".gitsor" / "config.toml").is_file()
    gitignore = (fixture_repo.path / ".gitignore").read_text(encoding="utf-8")
    assert ".gitsor/" in gitignore
    # İkinci çalıştırma tekrar eklememeli.
    runner.invoke(app, ["-C", str(fixture_repo.path), "init"])
    gitignore = (fixture_repo.path / ".gitignore").read_text(encoding="utf-8")
    assert gitignore.count(".gitsor/") == 1


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
