"""Arayüz dili: kurulumda seçilir, tüm mesajlar ve yardım metinleri seçilen dilde olur."""

from __future__ import annotations

import locale
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import gitex.manage as manage
from gitex import i18n
from gitex.cli import app
from gitex.config import LLMConfig, load_config, user_config_path
from gitex.evals.fixture import FixtureRepo

runner = CliRunner()


def _run(repo: Path, *args: str, input: str | None = None):
    return runner.invoke(app, ["-C", str(repo), *args], input=input)


def _lister(models: list[str]):
    def lister(llm: LLMConfig) -> list[str]:
        return list(models)

    return lister


def test_setup_asks_language_first_and_switches_to_english(
    fixture_repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manage, "model_lister", _lister(["qwen2.5:7b"]))
    answers = "\n".join(
        [
            "2",  # Dil / Language: English
            "4",  # Ollama
            "",  # address: default
            "",  # model: recommended
            "",  # mode: recommended
            "",  # GitLab: No (no remote)
        ]
    )
    r = _run(fixture_repo.path, "setup", "--no-check", input=answers + "\n")
    assert r.exit_code == 0, r.output
    assert "Dil / Language" in r.output
    assert "1) Türkçe" in r.output
    assert "2) English" in r.output
    # Dil seçildikten sonra her şey İngilizce.
    assert "Which AI service do you want to use?" in r.output
    assert "runs on your own machine" in r.output
    assert "All set!" in r.output
    assert "Hangi yapay zekâ" not in r.output
    assert 'language = "en"' in user_config_path().read_text(encoding="utf-8")
    assert load_config(fixture_repo.path).ui.language == "en"


def test_setup_lang_option_skips_question(
    fixture_repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manage, "model_lister", _lister(["m"]))
    r = _run(fixture_repo.path, "setup", "--lang", "en", "--no-check", input="4\n\n\n\n\n")
    assert r.exit_code == 0, r.output
    assert "Dil / Language" not in r.output
    assert "1. Which AI service" in r.output  # adım numarası 1'den başlar


def test_setup_rejects_unknown_language(fixture_repo: FixtureRepo) -> None:
    r = _run(fixture_repo.path, "setup", "--lang", "de", "--no-check")
    assert r.exit_code == 1
    assert "tr | en" in r.output


def test_english_messages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITEX_LANG", "en")
    i18n.reset()
    r = _run(tmp_path, "status")
    assert r.exit_code == 1
    assert "is not a git repository" in r.output
    assert "Error:" in r.output
    assert "Hata" not in r.output


def test_config_set_language_is_global_only(
    fixture_repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITEX_LANG")  # aksi hâlde ortam değişkeni config'teki seçimi ezer
    r = _run(fixture_repo.path, "config", "set", "ui.language", "en")
    assert r.exit_code == 0, r.output
    assert "all repositories" in r.output  # yeni dil hemen uygulanır
    assert 'language = "en"' in user_config_path().read_text(encoding="utf-8")
    r = _run(fixture_repo.path, "config", "set", "ui.language", "tr", "--repo")
    assert r.exit_code == 1
    assert "only be set globally" in r.output


def test_language_resolution_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITEX_LANG", raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setattr(locale, "getlocale", lambda: ("English_United States", "1252"))
    i18n.reset()
    assert i18n.current() == "en"

    monkeypatch.setattr(locale, "getlocale", lambda: ("Turkish_Türkiye", "1254"))
    i18n.reset()
    assert i18n.current() == "tr"  # sistem dili

    user_config_path().parent.mkdir(parents=True, exist_ok=True)
    user_config_path().write_text('[ui]\nlanguage = "en"\n', encoding="utf-8")
    i18n.reset()
    assert i18n.current() == "en"  # config sistemden önce

    monkeypatch.setenv("GITEX_LANG", "tr")
    i18n.reset()
    assert i18n.current() == "tr"  # ortam değişkeni en önce


def test_t_formats_values() -> None:
    i18n.set_language("en")
    assert i18n.t("{n} commit", "{n} commits", n=3) == "3 commits"
    i18n.set_language("tr")
    assert i18n.t("{n} commit", "{n} commits", n=3) == "3 commit"


def test_help_text_follows_language(tmp_path: Path) -> None:
    # Yardım metinleri program yüklenirken oluşur; ayrı bir süreçte denenir.
    env = {
        **os.environ,
        "GITEX_LANG": "en",
        "GITEX_CONFIG": str(tmp_path / "c.toml"),
        "COLUMNS": "120",
        "PYTHONIOENCODING": "utf-8",
    }
    code = "from gitex.cli import app; app(['--help'])"
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8"
    )
    assert "Ask about the repository's history" in out.stdout
    assert "Commands" in out.stdout
    env["GITEX_LANG"] = "tr"
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8"
    )
    assert "Repo geçmişi hakkında soru sor" in out.stdout
    assert "Komutlar" in out.stdout
