"""Config yükleme: kullanıcı (`~/.config/gitex/config.toml`) + repo (`.gitex/config.toml`) + env.

Öncelik (düşükten yükseğe): varsayılanlar → kullanıcı config'i → repo config'i → ortam değişkenleri.
Sırlar (API anahtarı, GitLab token'ı) dosyaya yazılmaz: önce ortam değişkeninden, yoksa işletim
sisteminin anahtar kasasından okunur (`gitex auth login`). Dosyalar `gitex config set` ile yazılır.
"""

from __future__ import annotations

import json
import os
import tomllib
import typing
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from gitex import credentials
from gitex.errors import ConfigError

GITEX_DIR = ".gitex"
CONFIG_FILE = "config.toml"
INDEX_FILE = "index.db"
GITLAB_TOKEN_ENV = "GITEX_GITLAB_TOKEN"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMConfig(_Section):
    provider: Literal["openai_compat", "anthropic"] = "openai_compat"
    model: str = "qwen2.5-7b-instruct"
    base_url: str | None = None
    api_key_env: str = "GITEX_LLM_API_KEY"
    mode: Literal["agent", "simple"] = "agent"
    max_tool_calls: int = Field(default=12, ge=1, le=100)
    # Yalnızca openai_compat'a gönderilir; güncel Claude API örnekleme parametrelerini kabul etmez.
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=64)  # None: sağlayıcı varsayılanı
    timeout: float = Field(default=120.0, gt=0)
    # Bir araç çıktısının ve simple moddaki toplam bağlamın karakter bütçesi.
    tool_output_chars: int = Field(default=8000, ge=500)
    context_chars: int = Field(default=40000, ge=2000)
    simple_top_n: int = Field(default=6, ge=1, le=30)
    # Claude reddederse sunucu tarafı yedek modele devret (yalnızca doğrudan Claude API'de).
    anthropic_fallbacks: bool = True

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) or credentials.get_secret(self.key_name)

    @property
    def key_name(self) -> str:
        return credentials.llm_key_name(self.provider, self.base_url)


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

    def token(self) -> str | None:
        return os.environ.get(GITLAB_TOKEN_ENV) or credentials.get_secret(self.key_name)

    @property
    def key_name(self) -> str:
        return credentials.gitlab_key_name(self.url)


class Config(_Section):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    gitlab: GitLabConfig = Field(default_factory=GitLabConfig)
    sources: list[str] = Field(default_factory=list, exclude=True)


_ENV_OVERRIDES: dict[str, tuple[str, str]] = {
    "GITEX_LLM_PROVIDER": ("llm", "provider"),
    "GITEX_LLM_MODEL": ("llm", "model"),
    "GITEX_LLM_BASE_URL": ("llm", "base_url"),
    "GITEX_LLM_MODE": ("llm", "mode"),
    "GITEX_GITLAB_URL": ("gitlab", "url"),
    "GITEX_GITLAB_PROJECT": ("gitlab", "project"),
}


def user_config_path() -> Path:
    if env := os.environ.get("GITEX_CONFIG"):
        return Path(env)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "gitex" / CONFIG_FILE


def repo_dir(repo_root: Path) -> Path:
    return repo_root / GITEX_DIR


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


# ---------------------------------------------------------------------- yazma (gitex config)

SECTIONS: dict[str, type[_Section]] = {
    "llm": LLMConfig,
    "privacy": PrivacyConfig,
    "gitlab": GitLabConfig,
}
_TRUE = {"1", "true", "yes", "on", "evet", "e", "açık", "acik"}
_FALSE = {"0", "false", "no", "off", "hayır", "hayir", "h", "kapalı", "kapali"}


def config_path(scope: Literal["global", "repo"], repo_root: Path | None) -> Path:
    if scope == "global":
        return user_config_path()
    if repo_root is None:
        raise ConfigError(
            "Bir git deposunun içinde değilsiniz.",
            hint="Tüm depolar için ayar yapmak üzere --global kullanın.",
        )
    return repo_dir(repo_root) / CONFIG_FILE


def all_keys() -> list[str]:
    return [f"{sec}.{name}" for sec, model in SECTIONS.items() for name in model.model_fields]


def split_key(key: str) -> tuple[str, str]:
    section, _, field = key.partition(".")
    if section not in SECTIONS or field not in SECTIONS[section].model_fields:
        raise ConfigError(
            f"Bilinmeyen ayar: {key}", hint="Geçerli ayarlar için: gitex config list-keys"
        )
    return section, field


def _coerce(section: str, field: str, raw: str) -> Any:
    annotation = SECTIONS[section].model_fields[field].annotation
    args = typing.get_args(annotation)
    text = raw.strip()
    if annotation is bool:
        if text.lower() in _TRUE:
            return True
        if text.lower() in _FALSE:
            return False
        raise ConfigError(f"{section}.{field} için evet/hayır (true/false) bekleniyor: {raw}")
    if typing.get_origin(annotation) is list or list in args:
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"Geçersiz liste: {raw}") from exc
            return [str(v) for v in value]
        return [part.strip() for part in text.split(",") if part.strip()]
    return text


def _load_doc(path: Path) -> Any:
    import tomlkit

    if path.is_file():
        try:
            return tomlkit.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ConfigError(f"Config dosyası okunamadı: {path}: {exc}") from exc
    return tomlkit.document()


def set_value(path: Path, key: str, raw: str) -> Any:
    """Değeri doğrulayıp TOML dosyasına yazar (yorumlar korunur); yazılan değeri döner."""
    import tomlkit

    section, field = split_key(key)
    doc = _load_doc(path)
    current = dict(doc.get(section, {}))
    current[field] = _coerce(section, field, raw)
    try:
        model = SECTIONS[section].model_validate(current)
    except ValidationError as exc:
        msg = "; ".join(e["msg"] for e in exc.errors())
        raise ConfigError(f"{key} için geçersiz değer '{raw}': {msg}") from exc
    value = getattr(model, field)
    if value is None:
        raise ConfigError(f"{key} boş bırakılamaz; kaldırmak için: gitex config unset {key}")
    if section not in doc:
        doc[section] = tomlkit.table()
    doc[section][field] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return value


def unset_value(path: Path, key: str) -> bool:
    import tomlkit

    section, field = split_key(key)
    if not path.is_file():
        return False
    doc = _load_doc(path)
    if section not in doc or field not in doc[section]:
        return False
    del doc[section][field]
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return True


def value_sources(repo_root: Path | None) -> dict[str, str]:
    """Her ayarın etkin değerinin nereden geldiği: varsayılan | global | repo | env."""
    origin = dict.fromkeys(all_keys(), "varsayılan")
    layers: list[tuple[str, Path]] = [("global", user_config_path())]
    if repo_root is not None:
        layers.append(("repo", repo_dir(repo_root) / CONFIG_FILE))
    for name, path in layers:
        if path.is_file():
            for section, values in _read_toml(path).items():
                if isinstance(values, dict):
                    for field in values:
                        origin[f"{section}.{field}"] = name
    for env_name, (section, field) in _ENV_OVERRIDES.items():
        if os.environ.get(env_name):
            origin[f"{section}.{field}"] = f"env ({env_name})"
    return origin


SAMPLE_CONFIG = """# gitex repo ayarları. Bu dosyayı elle düzenlemeniz gerekmez:
#   gitex setup                         # adım adım kurulum
#   gitex config set llm.model <ad>     # tek bir ayar (--global: tüm depolar)
#   gitex config show                   # etkin ayarlar ve kaynakları
# Buraya yazılan ayarlar yalnızca bu depo için geçerlidir ve global ayarları ezer.
# Sırlar (API anahtarı, token) bu dosyaya YAZILMAZ: gitex auth login
"""
