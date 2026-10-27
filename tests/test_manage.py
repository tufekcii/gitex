"""setup / config / auth / doctor: kullanıcı hiçbir dosyayı elle düzenlemeden her şeyi yönetebilmeli."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

import gitex.manage as manage
from gitex.cli import app
from gitex.config import LLMConfig, load_config, user_config_path
from gitex.evals.fixture import FixtureRepo
from gitex.llm.catalog import PRESETS, clean_models, preset_for
from tests.conftest import MemoryKeyring

runner = CliRunner()


def _run(repo: Path, *args: str, input: str | None = None):
    return runner.invoke(app, ["-C", str(repo), *args], input=input)


def _all_text_under(*paths: Path) -> str:
    out = []
    for base in paths:
        for p in base.rglob("*") if base.is_dir() else [base]:
            if p.is_file() and p.suffix in (".toml", ".md", ".txt", ""):
                with contextlib.suppress(UnicodeDecodeError):
                    out.append(p.read_text(encoding="utf-8"))
    return "\n".join(out)


# ---------------------------------------------------------------------- config


def test_config_set_get_unset_global(fixture_repo: FixtureRepo) -> None:
    r = _run(fixture_repo.path, "config", "set", "llm.model", "claude-opus-5-5")
    assert r.exit_code == 0, r.output
    assert "tüm depolar" in r.output  # llm.* varsayılan olarak global
    assert user_config_path().is_file()
    assert _run(fixture_repo.path, "config", "get", "llm.model").output.strip() == "claude-opus-5-5"

    r = _run(fixture_repo.path, "config", "unset", "llm.model")
    assert r.exit_code == 0
    assert load_config(fixture_repo.path).llm.model == "qwen2.5-7b-instruct"


def test_config_types_are_coerced(fixture_repo: FixtureRepo) -> None:
    assert _run(fixture_repo.path, "config", "set", "llm.max_tool_calls", "20").exit_code == 0
    assert _run(fixture_repo.path, "config", "set", "privacy.send_diffs", "hayır").exit_code == 0
    assert (
        _run(
            fixture_repo.path, "config", "set", "privacy.exclude_paths", "*.env, secrets/**"
        ).exit_code
        == 0
    )
    cfg = load_config(fixture_repo.path)
    assert cfg.llm.max_tool_calls == 20
    assert cfg.privacy.send_diffs is False
    assert cfg.privacy.exclude_paths == ["*.env", "secrets/**"]
    text = user_config_path().read_text(encoding="utf-8")
    assert "max_tool_calls = 20" in text  # tırnaksız, gerçek tamsayı olarak yazılır


def test_config_rejects_invalid(fixture_repo: FixtureRepo) -> None:
    r = _run(fixture_repo.path, "config", "set", "llm.mode", "turbo")
    assert r.exit_code == 1
    assert "geçersiz değer" in r.output
    r = _run(fixture_repo.path, "config", "set", "llm.nope", "x")
    assert r.exit_code == 1
    assert "Bilinmeyen ayar" in r.output
    r = _run(fixture_repo.path, "config", "set", "llm.max_tool_calls", "0")
    assert r.exit_code == 1
    assert not user_config_path().exists() or "max_tool_calls" not in user_config_path().read_text(
        encoding="utf-8"
    )


def test_gitlab_settings_default_to_repo_scope(fixture_repo: FixtureRepo) -> None:
    r = _run(fixture_repo.path, "config", "set", "gitlab.project", "grup/proje")
    assert r.exit_code == 0, r.output
    repo_cfg = fixture_repo.path / ".gitex" / "config.toml"
    assert 'project = "grup/proje"' in repo_cfg.read_text(encoding="utf-8")
    assert not user_config_path().exists()


def test_repo_overrides_global_and_show(fixture_repo: FixtureRepo) -> None:
    _run(fixture_repo.path, "config", "set", "llm.mode", "agent")
    _run(fixture_repo.path, "config", "set", "llm.mode", "simple", "--repo")
    assert load_config(fixture_repo.path).llm.mode == "simple"
    r = _run(fixture_repo.path, "config", "show")
    assert r.exit_code == 0
    line = next(ln for ln in r.output.splitlines() if "llm.mode " in ln)
    assert "simple" in line
    assert "repo" in line


def test_set_preserves_comments(fixture_repo: FixtureRepo) -> None:
    assert _run(fixture_repo.path, "init").exit_code == 0
    _run(fixture_repo.path, "config", "set", "gitlab.project", "a/b")
    text = (fixture_repo.path / ".gitex" / "config.toml").read_text(encoding="utf-8")
    assert "gitex config set" in text  # örnek dosyadaki açıklamalar korunur
    assert 'project = "a/b"' in text


def test_sample_config_does_not_shadow_global(fixture_repo: FixtureRepo) -> None:
    _run(fixture_repo.path, "config", "set", "llm.provider", "anthropic")
    _run(fixture_repo.path, "init")
    assert load_config(fixture_repo.path).llm.provider == "anthropic"


# ---------------------------------------------------------------------- auth


def test_auth_login_stores_in_keyring_not_files(
    fixture_repo: FixtureRepo, memory_keyring: MemoryKeyring
) -> None:
    _run(fixture_repo.path, "config", "set", "llm.provider", "anthropic")
    secret = "sk-ant-" + "x" * 30
    r = _run(fixture_repo.path, "auth", "login", input=secret + "\n")
    assert r.exit_code == 0, r.output
    assert ("gitex", "llm:anthropic") in memory_keyring.store
    assert secret not in r.output
    assert load_config(fixture_repo.path).llm.api_key() == secret
    assert secret not in _all_text_under(user_config_path(), fixture_repo.path / ".gitex")

    status = _run(fixture_repo.path, "auth", "status")
    assert "anahtar kasası" in status.output
    assert secret not in status.output

    assert _run(fixture_repo.path, "auth", "logout").exit_code == 0
    assert load_config(fixture_repo.path).llm.api_key() is None


def test_env_takes_precedence_over_keyring(
    fixture_repo: FixtureRepo, memory_keyring: MemoryKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory_keyring.store[("gitex", "llm:openai_compat")] = "from-keyring"
    monkeypatch.setenv("GITEX_LLM_API_KEY", "from-env")
    assert load_config(fixture_repo.path).llm.api_key() == "from-env"


def test_auth_login_stdin_and_gitlab(
    fixture_repo: FixtureRepo, memory_keyring: MemoryKeyring
) -> None:
    _run(fixture_repo.path, "config", "set", "gitlab.url", "https://gitlab.example.com")
    _run(fixture_repo.path, "config", "set", "gitlab.project", "a/b")
    r = _run(fixture_repo.path, "auth", "login", "gitlab", "--stdin", input="glpat-dummy\n")
    assert r.exit_code == 0, r.output
    assert memory_keyring.store[("gitex", "gitlab:gitlab.example.com")] == "glpat-dummy"
    assert load_config(fixture_repo.path).gitlab.token() == "glpat-dummy"


def test_keys_are_per_endpoint(fixture_repo: FixtureRepo, memory_keyring: MemoryKeyring) -> None:
    _run(fixture_repo.path, "config", "set", "llm.base_url", "https://api.openai.com/v1")
    _run(fixture_repo.path, "auth", "login", "--stdin", input="k1\n")
    assert ("gitex", "llm:openai_compat@api.openai.com") in memory_keyring.store


# ---------------------------------------------------------------------- setup

# Sihirbazdaki sağlayıcı numaraları (PRESETS sırası).
GROQ, GEMINI, OPENROUTER, OLLAMA, CLAUDE, OPENAI, CUSTOM = (str(i) for i in range(1, 8))


def _answers(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _fake_lister(models: list[str], seen: list[LLMConfig] | None = None):
    def lister(llm: LLMConfig) -> list[str]:
        if seen is not None:
            seen.append(llm)
        return list(models)

    return lister


def test_setup_claude_wizard(
    fixture_repo: FixtureRepo, memory_keyring: MemoryKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        manage,
        "model_lister",
        _fake_lister(["claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5"]),
    )
    secret = "sk-ant-" + "y" * 30
    answers = _answers(
        CLAUDE,
        secret,  # anahtar
        "",  # model: önerilen (claude-opus-5-5)
        "",  # mod: önerilen (agent)
        "",  # GitLab: önerilen (Hayır; remote yok)
    )
    r = _run(fixture_repo.path, "setup", "--no-check", input=answers)
    assert r.exit_code == 0, r.output
    cfg = load_config(fixture_repo.path)
    assert (cfg.llm.provider, cfg.llm.model, cfg.llm.mode) == (
        "anthropic",
        "claude-opus-5-5",
        "agent",
    )
    assert cfg.llm.base_url is None
    assert memory_keyring.store[("gitex", "llm:anthropic")] == secret
    assert (fixture_repo.path / ".gitex" / "index.db").exists()
    assert ".gitex/" in (fixture_repo.path / ".gitignore").read_text(encoding="utf-8")
    assert secret not in _all_text_under(user_config_path(), fixture_repo.path / ".gitex")
    assert "1) Evet" in r.output  # evet/hayır soruları da numaralı
    assert "Hazır" in r.output


def test_setup_groq_lists_models_after_key(
    fixture_repo: FixtureRepo, memory_keyring: MemoryKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[LLMConfig] = []
    models = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "qwen-qwq-32b"]
    monkeypatch.setattr(manage, "model_lister", _fake_lister(models, seen))
    r = _run(
        fixture_repo.path,
        "setup",
        "--no-check",
        input=_answers(GROQ, "gsk_" + "z" * 20, "2", "", ""),
    )
    assert r.exit_code == 0, r.output
    assert "https://console.groq.com/keys" in r.output
    for i, m in enumerate(models, 1):
        assert f"{i}) {m}" in r.output
    cfg = load_config(fixture_repo.path)
    assert cfg.llm.base_url == "https://api.groq.com/openai/v1"
    assert cfg.llm.model == "llama-3.3-70b-versatile"
    # Model listesi, az önce girilen anahtarla çekildi.
    assert seen[0].api_key() == "gsk_" + "z" * 20
    assert ("gitex", "llm:openai_compat@api.groq.com") in memory_keyring.store


def test_setup_model_list_failure_falls_back_to_manual(
    fixture_repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(llm: LLMConfig) -> list[str]:
        raise ConnectionError("401 Invalid API Key")

    monkeypatch.setattr(manage, "model_lister", broken)
    r = _run(
        fixture_repo.path,
        "setup",
        "--no-check",
        input=_answers(GEMINI, "", "gemini-elle", "", ""),
    )
    assert r.exit_code == 0, r.output
    assert "Model listesi alınamadı" in r.output
    assert "401 Invalid API Key" in r.output
    assert load_config(fixture_repo.path).llm.model == "gemini-elle"


def test_setup_many_models_search_and_manual(
    fixture_repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = [f"vendor/model-{i}b" for i in range(40)] + ["meta/llama-70b:free"]
    monkeypatch.setattr(manage, "model_lister", _fake_lister(models))
    r = _run(
        fixture_repo.path,
        "setup",
        "--no-check",
        input=_answers(OPENROUTER, "or-key", "70b", "1", "", ""),
    )
    assert r.exit_code == 0, r.output
    assert "41 model var" in r.output
    assert load_config(fixture_repo.path).llm.model == "meta/llama-70b:free"

    # "Listede yok" seçeneği elle yazmaya geçer; kayıtlı anahtar tekrar sorulmaz.
    r = _run(
        fixture_repo.path,
        "setup",
        "--no-check",
        input=_answers(
            OPENROUTER,
            "",
            "",
            str(min(len(models), manage.MAX_LISTED_MODELS) + 1),
            "ozel/model",
            "",
            "",
        ),
    )
    assert r.exit_code == 0, r.output
    assert "Kayıtlı anahtarı kullan" in r.output
    assert load_config(fixture_repo.path).llm.model == "ozel/model"


def test_setup_ollama_with_gitlab_detected_from_remote(
    fixture_repo: FixtureRepo, memory_keyring: MemoryKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    monkeypatch.setattr(manage, "model_lister", _fake_lister(["llama3.2", "qwen2.5:7b"]))
    subprocess.run(
        ["git", "remote", "add", "origin", "git@gitlab.example.com:ekip/servis.git"],
        cwd=fixture_repo.path,
        check=True,
    )
    answers = _answers(
        OLLAMA,
        "",  # adres: varsayılan
        "",  # model: önerilen (qwen2.5:7b)
        "",  # mod: önerilen (simple)
        "",  # GitLab bağlansın mı: remote gitlab → önerilen Evet
        "",  # adres: remote'tan
        "",  # proje: remote'tan
        "",  # token atla
        "",  # senkron: önerilen Hayır (token yok)
    )
    r = _run(fixture_repo.path, "setup", "--no-check", input=answers)
    assert r.exit_code == 0, r.output
    cfg = load_config(fixture_repo.path)
    assert cfg.llm.base_url == "http://localhost:11434/v1"
    assert cfg.llm.model == "qwen2.5:7b"
    assert cfg.llm.mode == "simple"
    assert cfg.gitlab.url == "https://gitlab.example.com"
    assert cfg.gitlab.project == "ekip/servis"
    assert memory_keyring.store == {}
    assert "anahtar gerekmiyor" in r.output


def test_choose_rejects_out_of_range(
    fixture_repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(manage, "model_lister", _fake_lister(["m1"]))
    r = _run(
        fixture_repo.path,
        "setup",
        "--no-check",
        input=_answers("99", "abc", OLLAMA, "", "", "", ""),
    )
    assert r.exit_code == 0, r.output
    assert "1 ile 7 arasında" in r.output
    assert load_config(fixture_repo.path).llm.model == "m1"


def test_clean_models() -> None:
    raw = [
        "models/gemini-2.5-flash",
        "text-embedding-3-small",
        "whisper-large-v3",
        "b-model",
        "a-model:free",
        "meta-llama/llama-guard-4-12b",
        "b-model",
    ]
    assert clean_models(raw) == ["a-model:free", "b-model", "gemini-2.5-flash"]


def test_preset_for_matches_current_config() -> None:
    groq = next(p for p in PRESETS if p.key == "groq")
    assert preset_for(LLMConfig(provider="openai_compat", base_url=groq.base_url)) is groq
    assert preset_for(LLMConfig(provider="anthropic")).key == "anthropic"  # type: ignore[union-attr]
    assert preset_for(LLMConfig(provider="openai_compat", base_url="http://x:1/v1")) is None


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("git@gitlab.com:grup/alt/proje.git", ("https://gitlab.com", "grup/alt/proje")),
        ("https://gitlab.com/grup/proje.git", ("https://gitlab.com", "grup/proje")),
        ("https://oauth2:tok@git.sirket.com/a/b", ("https://git.sirket.com", "a/b")),
        ("ssh://git@gitlab.local/a/b.git", ("https://gitlab.local", "a/b")),
        ("/yerel/yol", None),
    ],
)
def test_parse_gitlab_remote(remote: str, expected: tuple[str, str] | None) -> None:
    assert manage.parse_gitlab_remote(remote) == expected


# ---------------------------------------------------------------------- doctor


def test_doctor_unconfigured(fixture_repo: FixtureRepo) -> None:
    r = _run(fixture_repo.path, "doctor", "--offline")
    assert r.exit_code == 1
    assert "yapılandırılmamış" in r.output
    assert "gitex setup" in r.output


def test_doctor_all_good(fixture_repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    _run(fixture_repo.path, "config", "set", "llm.base_url", "http://localhost:11434/v1")
    _run(fixture_repo.path, "index", "-q")
    monkeypatch.setattr(manage, "llm_pinger", lambda cfg: "yanıt veriyor")
    r = _run(fixture_repo.path, "doctor")
    assert r.exit_code == 0, r.output
    assert "Her şey hazır" in r.output
    assert "yanıt veriyor" in r.output


def test_doctor_reports_llm_failure(
    fixture_repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(fixture_repo.path, "config", "set", "llm.base_url", "http://localhost:9/v1")

    def down(cfg):
        raise ConnectionError("Connection refused")

    monkeypatch.setattr(manage, "llm_pinger", down)
    r = _run(fixture_repo.path, "doctor")
    assert r.exit_code == 1
    assert "Connection refused" in r.output


def test_missing_setup_hint_on_ask(fixture_repo: FixtureRepo) -> None:
    r = _run(fixture_repo.path, "ask", "x?")
    assert r.exit_code == 1
    assert "gitex setup" in r.output


def test_no_secret_env_leaks_into_process() -> None:
    # Testler gerçek anahtarlara erişmemeli (conftest izolasyonu).
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_list_models_uses_provider_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import openai

    from gitex.llm.catalog import list_models

    created: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)
            ids = ["whisper-large-v3", "llama-3.3-70b-versatile"]
            self.models = SimpleNamespace(list=lambda: [SimpleNamespace(id=i) for i in ids])

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("GITEX_LLM_API_KEY", "gsk-test")
    llm = LLMConfig(provider="openai_compat", base_url="https://api.groq.com/openai/v1")
    assert list_models(llm) == ["llama-3.3-70b-versatile"]
    assert created["base_url"] == "https://api.groq.com/openai/v1"
    assert created["api_key"] == "gsk-test"
