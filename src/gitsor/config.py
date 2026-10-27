"""Config yükleme: kullanıcı (`~/.config/gitsor/config.toml`) + repo (`.gitsor/config.toml`) + env.

Öncelik (düşükten yükseğe): varsayılanlar → kullanıcı config'i → repo config'i → ortam değişkenleri.
Sırlar (API anahtarı, GitLab token'ı) yalnızca ortam değişkenlerinden okunur, dosyaya yazılmaz.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from gitsor.errors import ConfigError

GITSOR_DIR = ".gitsor"
CONFIG_FILE = "config.toml"
INDEX_FILE = "index.db"
GITLAB_TOKEN_ENV = "GITSOR_GITLAB_TOKEN"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMConfig(_Section):
    provider: Literal["openai_compat", "anthropic"] = "openai_compat"
    model: str = "qwen2.5-7b-instruct"
    base_url: str | None = "http://localhost:8000/v1"
    api_key_env: str = "GITSOR_LLM_API_KEY"
    mode: Literal["agent", "simple"] = "agent"
    max_tool_calls: int = Field(default=12, ge=1, le=100)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=64)
    timeout: float = Field(default=120.0, gt=0)
    context_chars: int = Field(default=60000, ge=2000)

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or None


class PrivacyConfig(_Section):
    send_diffs: bool = True
    max_diff_chars: int = Field(default=12000, ge=0)
    exclude_paths: list[str] = Field(
        default_factory=lambda: ["*.env", "*.pem", "*.key", "secrets/**", "*.lock"]
    )


class GitLabConfig(_Section):
    url: str = "https://gitlab.com"
    project: str | None = None
    per_page: int = Field(default=100, ge=1, le=100)
    max_retries: int = Field(default=5, ge=0)

    @field_validator("url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def enabled(self) -> bool:
        return bool(self.project)

    @staticmethod
    def token() -> str | None:
        return os.environ.get(GITLAB_TOKEN_ENV) or None


class Config(_Section):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    gitlab: GitLabConfig = Field(default_factory=GitLabConfig)
    sources: list[str] = Field(default_factory=list, exclude=True)


_ENV_OVERRIDES: dict[str, tuple[str, str]] = {
    "GITSOR_LLM_PROVIDER": ("llm", "provider"),
    "GITSOR_LLM_MODEL": ("llm", "model"),
    "GITSOR_LLM_BASE_URL": ("llm", "base_url"),
    "GITSOR_LLM_MODE": ("llm", "mode"),
    "GITSOR_GITLAB_URL": ("gitlab", "url"),
    "GITSOR_GITLAB_PROJECT": ("gitlab", "project"),
}


def user_config_path() -> Path:
    if env := os.environ.get("GITSOR_CONFIG"):
        return Path(env)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "gitsor" / CONFIG_FILE


def repo_dir(repo_root: Path) -> Path:
    return repo_root / GITSOR_DIR


def index_path(repo_root: Path) -> Path:
    return repo_dir(repo_root) / INDEX_FILE


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config dosyası okunamadı: {path}: {exc}") from exc


def load_config(repo_root: Path | None = None, *, use_env: bool = True) -> Config:
    data: dict[str, Any] = {}
    sources: list[str] = []
    candidates = [user_config_path()]
    if repo_root is not None:
        candidates.append(repo_dir(repo_root) / CONFIG_FILE)
    for path in candidates:
        if path.is_file():
            data = _deep_merge(data, _read_toml(path))
            sources.append(str(path))
    if use_env:
        for env_name, (section, key) in _ENV_OVERRIDES.items():
            if value := os.environ.get(env_name):
                data.setdefault(section, {})[key] = value
    try:
        cfg = Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            f"Config geçersiz:\n{exc}", hint=f"Kontrol edin: {', '.join(sources) or 'env'}"
        ) from exc
    cfg.sources = sources
    return cfg


SAMPLE_CONFIG = """\
# gitsor yapılandırması. Sırlar (API anahtarı, token) bu dosyaya YAZILMAZ;
# ortam değişkenlerinden okunur.

[llm]
provider = "openai_compat"        # veya "anthropic"
model = "qwen2.5-7b-instruct"
base_url = "http://localhost:8000/v1"
api_key_env = "GITSOR_LLM_API_KEY"
mode = "agent"                    # "agent" (tool-use) veya "simple"
max_tool_calls = 12
temperature = 0.1

[privacy]
send_diffs = true                 # false ise LLM'e sadece metadata + mesajlar gider
max_diff_chars = 12000
exclude_paths = ["*.env", "*.pem", "*.key", "secrets/**", "*.lock"]

[gitlab]
url = "https://gitlab.com"
# project = "grup/proje"          # token: GITSOR_GITLAB_TOKEN ortam değişkeni
"""
