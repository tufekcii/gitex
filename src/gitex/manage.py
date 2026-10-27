"""Yönetim komutları: `setup`, `config`, `auth`, `doctor`.

Kullanıcı hiçbir dosyayı elle düzenlemeden gitex'i bu komutlarla kurar ve yönetir. Ayarlar TOML
dosyalarına (`gitex config`), sırlar işletim sisteminin anahtar kasasına (`gitex auth`) yazılır.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import typer
from rich.table import Table

from gitex import __version__, credentials
from gitex.config import (
    GITLAB_TOKEN_ENV,
    SECTIONS,
    Config,
    LLMConfig,
    all_keys,
    config_path,
    index_path,
    set_value,
    split_key,
    unset_value,
    value_sources,
)
from gitex.errors import ConfigError, GitexError
from gitex.git.reader import GitRepo
from gitex.llm.catalog import PRESETS, ProviderPreset, is_free, list_models, preset_for
from gitex.ui import console, err_console, fail, state

Scope = Literal["global", "repo"]

config_app = typer.Typer(
    help="Ayarları görüntüle ve değiştir (dosya düzenlemeye gerek yok).", no_args_is_help=True
)
auth_app = typer.Typer(
    help="API anahtarı ve token'ları işletim sisteminin anahtar kasasında yönet.",
    no_args_is_help=True,
)


def _repo_root() -> Path | None:
    repo = state.repo_or_none()
    return repo.root if repo else None


def _default_scope(key: str) -> Scope:
    # LLM ve gizlilik ayarları genelde tüm depolar için aynıdır; GitLab projesi depoya özgüdür.
    return "repo" if key.startswith("gitlab.") and _repo_root() is not None else "global"


def _resolve_scope(key: str, global_: bool, repo: bool) -> Scope:
    if global_ and repo:
        raise ConfigError("--global ve --repo birlikte kullanılamaz.")
    if global_:
        return "global"
    if repo:
        return "repo"
    return _default_scope(key)


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "evet" if value else "hayır"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "(boş)"
    return "-" if value is None else str(value)


# ---------------------------------------------------------------------- config


@config_app.command("show")
def config_show() -> None:
    """Etkin ayarları ve her birinin nereden geldiğini gösterir."""
    try:
        root = _repo_root()
        cfg = state.config(state.repo_or_none())
        origins = value_sources(root)
    except GitexError as exc:
        raise fail(exc) from exc
    table = Table(show_lines=False)
    table.add_column("Ayar", style="bold")
    table.add_column("Değer")
    table.add_column("Kaynak", style="dim")
    for key in all_keys():
        section, field = split_key(key)
        value = getattr(getattr(cfg, section), field)
        source = origins[key]
        style = "" if source == "varsayılan" else "cyan"
        table.add_row(key, f"[{style}]{_display(value)}[/]" if style else _display(value), source)
    console.print(table)
    console.print(f"[dim]Global: {config_path('global', None)}[/]")
    if root is not None:
        console.print(f"[dim]Repo:   {config_path('repo', root)}[/]")
    console.print(
        "[dim]Değiştirmek için: gitex config set <ayar> <değer>   ·   sırlar: gitex auth status[/]"
    )


@config_app.command("get")
def config_get(key: str = typer.Argument(..., help="Ör. llm.model")) -> None:
    """Tek bir ayarın etkin değerini yazar."""
    try:
        section, field = split_key(key)
        cfg = state.config(state.repo_or_none())
    except GitexError as exc:
        raise fail(exc) from exc
    typer.echo(_display(getattr(getattr(cfg, section), field)))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Ör. llm.model, privacy.send_diffs, gitlab.project"),
    value: str = typer.Argument(..., help="Yeni değer (listeler virgülle: '*.env,*.pem')"),
    global_: bool = typer.Option(
        False, "--global", "-g", help="Tüm depolar için (kullanıcı config'i)."
    ),
    repo: bool = typer.Option(False, "--repo", "-r", help="Yalnızca bu depo için."),
) -> None:
    """Bir ayarı değiştirir. Varsayılan kapsam: gitlab.* → bu depo, diğerleri → global."""
    try:
        scope = _resolve_scope(key, global_, repo)
        path = config_path(scope, _repo_root())
        written = set_value(path, key, value)
    except GitexError as exc:
        raise fail(exc) from exc
    where = "tüm depolar" if scope == "global" else "bu depo"
    console.print(f"[green]✓[/] {key} = [bold]{_display(written)}[/] [dim]({where}: {path})[/]")


@config_app.command("unset")
def config_unset(
    key: str = typer.Argument(...),
    global_: bool = typer.Option(False, "--global", "-g"),
    repo: bool = typer.Option(False, "--repo", "-r"),
) -> None:
    """Bir ayarı kaldırır; değer bir üst katmana ya da varsayılana döner."""
    try:
        scope = _resolve_scope(key, global_, repo)
        path = config_path(scope, _repo_root())
        removed = unset_value(path, key)
    except GitexError as exc:
        raise fail(exc) from exc
    if removed:
        console.print(f"[green]✓[/] {key} kaldırıldı [dim]({path})[/]")
    else:
        console.print(f"[yellow]{key} bu kapsamda zaten ayarlı değil[/] [dim]({path})[/]")


@config_app.command("list-keys")
def config_list_keys() -> None:
    """Ayarlanabilir tüm anahtarları, türlerini ve varsayılanlarını listeler."""
    table = Table()
    table.add_column("Ayar", style="bold")
    table.add_column("Tür")
    table.add_column("Varsayılan", style="dim")
    for section, model in SECTIONS.items():
        default = model()
        for name, info in model.model_fields.items():
            ann = (
                str(info.annotation)
                .replace("typing.", "")
                .replace("<class '", "")
                .replace("'>", "")
            )
            table.add_row(f"{section}.{name}", ann, _display(getattr(default, name)))
    console.print(table)


@config_app.command("path")
def config_path_cmd() -> None:
    """Config dosyalarının yollarını gösterir."""
    console.print(f"Global: {config_path('global', None)}")
    root = _repo_root()
    console.print(f"Repo:   {config_path('repo', root) if root else '(git deposu dışında)'}")


# ---------------------------------------------------------------------- auth

Target = Literal["llm", "gitlab"]


def _secret_info(cfg: Config, target: str) -> tuple[str, str | None, str | None]:
    """(kasadaki ad, env değişkeni adı, ortamdaki değer)."""
    import os

    if target == "llm":
        return cfg.llm.key_name, cfg.llm.api_key_env, os.environ.get(cfg.llm.api_key_env)
    if target == "gitlab":
        return cfg.gitlab.key_name, GITLAB_TOKEN_ENV, os.environ.get(GITLAB_TOKEN_ENV)
    raise ConfigError(f"Bilinmeyen hedef: {target}", hint="llm ya da gitlab")


@auth_app.command("login")
def auth_login(
    target: str = typer.Argument("llm", help="llm ya da gitlab"),
    stdin: bool = typer.Option(
        False, "--stdin", help="Değeri standart girdiden oku (betikler için)."
    ),
) -> None:
    """API anahtarını / token'ı gizli girişle alıp anahtar kasasına kaydeder."""
    try:
        cfg = state.config(state.repo_or_none())
        name, env_name, _ = _secret_info(cfg, target)
        if stdin:
            value = sys.stdin.readline().strip()
        else:
            label = "API anahtarı" if target == "llm" else "GitLab token'ı (read_api)"
            value = typer.prompt(f"{label} (yazdıkların görünmez)", hide_input=True).strip()
        if not value:
            raise GitexError("Boş değer kaydedilmedi.")
        credentials.set_secret(name, value)
    except GitexError as exc:
        raise fail(exc) from exc
    console.print(
        f"[green]✓[/] Kaydedildi: {name} [dim]({credentials.mask(value)}, anahtar kasası)[/]"
    )
    if env_name and _secret_info(cfg, target)[2]:
        console.print(
            f"[yellow]Not:[/] {env_name} ortam değişkeni tanımlı ve kasadaki değerden önceliklidir."
        )


@auth_app.command("logout")
def auth_logout(target: str = typer.Argument("llm", help="llm ya da gitlab")) -> None:
    """Kasadaki anahtarı siler."""
    try:
        cfg = state.config(state.repo_or_none())
        name, _, _ = _secret_info(cfg, target)
        removed = credentials.delete_secret(name)
    except GitexError as exc:
        raise fail(exc) from exc
    console.print(
        f"[green]✓[/] {name} silindi" if removed else f"[yellow]{name} kasada zaten yok[/]"
    )


@auth_app.command("status")
def auth_status() -> None:
    """Hangi sırrın nereden okunduğunu gösterir (değerler maskelenir)."""
    try:
        cfg = state.config(state.repo_or_none())
    except GitexError as exc:
        raise fail(exc) from exc
    backend = credentials.backend_name()
    console.print(
        f"Anahtar kasası: {backend or '[yellow]yok[/] — sırları ortam değişkeniyle verin'}"
    )
    table = Table()
    for col in ("Hedef", "Kasa adı", "Kaynak", "Değer"):
        table.add_column(col)
    for target in ("llm", "gitlab"):
        if target == "gitlab" and not cfg.gitlab.enabled:
            table.add_row("gitlab", "-", "[dim]GitLab ayarlanmamış[/]", "-")
            continue
        name, env_name, env_value = _secret_info(cfg, target)
        stored = credentials.get_secret(name)
        value: str | None
        if env_value:
            source, value = f"env ({env_name})", env_value
        elif stored:
            source, value = "anahtar kasası", stored
        elif target == "llm" and cfg.llm.provider == "anthropic" and _env("ANTHROPIC_API_KEY"):
            source, value = "env (ANTHROPIC_API_KEY)", _env("ANTHROPIC_API_KEY")
        else:
            needed = (
                target == "gitlab"
                or cfg.llm.provider == "anthropic"
                or not _is_local(cfg.llm.base_url)
            )
            source = (
                "[red]yok[/] — gitex auth login " + target
                if needed
                else "[dim]gerekmiyor (yerel sunucu)[/]"
            )
            value = None
        table.add_row(target, name, source, credentials.mask(value))
    console.print(table)


def _env(name: str) -> str | None:
    import os

    return os.environ.get(name) or None


def _is_local(url: str | None) -> bool:
    return bool(url) and bool(
        re.search(r"//(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)[:/]", url or "")
    )


# ---------------------------------------------------------------------- setup

# Sihirbazda en fazla bu kadar model numaralı listelenir; fazlası için arama sorulur.
MAX_LISTED_MODELS = 25

# Testler ağa çıkmamak için bunu değiştirir.
model_lister: Callable[[LLMConfig], list[str]] = list_models


def parse_gitlab_remote(url: str) -> tuple[str, str] | None:
    """`git@host:grup/proje.git` ya da `https://host/grup/proje.git` → (https://host, grup/proje)."""
    url = url.strip()
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", url)
    if m:
        return f"https://{m.group(1)}", m.group(2)
    m = re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", url)
    if m:
        return f"https://{m.group(1)}", m.group(2)
    return None


def _origin_remote(repo: GitRepo) -> str | None:
    try:
        out = repo.run(["remote", "get-url", "origin"], ok_codes=(0, 2, 128))
    except GitexError:
        return None
    return out.strip() or None


def _choose(
    prompt: str, options: list[str], default: int = 1, hints: list[str] | None = None
) -> int:
    """Numaralı seçim; 1'den başlayan sıra numarasını döner."""
    for i, opt in enumerate(options, 1):
        hint = hints[i - 1] if hints and i - 1 < len(hints) and hints[i - 1] else ""
        marker = " [dim](önerilen)[/]" if i == default and len(options) > 1 else ""
        console.print(
            f"  [bold cyan]{i:>2}[/]) {opt}" + (f"  [dim]— {hint}[/]" if hint else "") + marker
        )
    while True:
        raw = typer.prompt(prompt, default=str(default)).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw)
        console.print(f"[yellow]1 ile {len(options)} arasında bir sayı girin.[/]")


def _yes_no(prompt: str, *, default: bool) -> bool:
    return _choose(prompt, ["Evet", "Hayır"], 1 if default else 2) == 1


def setup(
    skip_check: bool = typer.Option(False, "--no-check", help="Sonda bağlantı testini atla."),
) -> None:
    """Adım adım kurulum: model, API anahtarı, (opsiyonel) GitLab ve indeks."""
    try:
        _run_setup(skip_check=skip_check)
    except GitexError as exc:
        raise fail(exc) from exc
    except (typer.Abort, KeyboardInterrupt) as exc:
        err_console.print(
            "\n[dim]Kurulum iptal edildi; o ana kadar yapılan seçimler kaydedildi.[/]"
        )
        raise typer.Exit(code=1) from exc


def _run_setup(*, skip_check: bool) -> None:
    repo = state.repo_or_none()
    global_path = config_path("global", None)
    console.print(
        f"[bold]gitex {__version__} kurulumu[/]  [dim](istediğin zaman tekrar çalıştırabilirsin)[/]\n"
    )

    # 1. Sağlayıcı
    console.print("[bold]1. Hangi yapay zekâ servisini kullanacaksın?[/]")
    current = preset_for(state.config(repo).llm)
    default = PRESETS.index(current) + 1 if current else 1
    preset = PRESETS[
        _choose("Seçim", [p.label for p in PRESETS], default, hints=[p.note for p in PRESETS]) - 1
    ]
    base_url = _pick_base_url(preset)
    llm = LLMConfig(provider=preset.provider, base_url=base_url)

    # 2. Anahtar (model listesini çekebilmek için modelden önce)
    console.print("\n[bold]2. API anahtarı[/]")
    _ask_api_key(preset, llm, base_url)

    # 3. Model
    console.print("\n[bold]3. Model[/]")
    model = _pick_model(preset, llm)

    # 4. Mod
    console.print("\n[bold]4. Çalışma modu[/]")
    mode_idx = _choose(
        "Seçim",
        ["agent", "simple"],
        1 if preset.mode == "agent" else 2,
        hints=[
            "model araçları kendisi çağırır; güçlü modeller için",
            "sabit arama + tek çağrı; küçük/ücretsiz modellerde daha isabetli",
        ],
    )
    mode = "agent" if mode_idx == 1 else "simple"

    set_value(global_path, "llm.provider", preset.provider)
    set_value(global_path, "llm.model", model)
    if base_url:
        set_value(global_path, "llm.base_url", base_url)
    else:
        unset_value(global_path, "llm.base_url")
    set_value(global_path, "llm.mode", mode)
    console.print(
        f"[green]✓[/] {preset.label} / {model} ({mode}) kaydedildi [dim]({global_path}, tüm depolar)[/]\n"
    )

    if repo is None:
        console.print(
            "[dim]Bir git deposunun içinde olmadığın için GitLab ve indeks adımları atlandı.[/]"
        )
    else:
        _setup_gitlab(repo)
        console.print("[bold]6. İndeks[/]")
        from gitex.cli import ensure_gitignore, run_index
        from gitex.index.indexer import open_index

        with open_index(repo) as db:
            run_index(repo, db)
        ensure_gitignore(repo)
        console.print()

    if not skip_check and _yes_no("Bağlantı test edilsin mi?", default=True):
        try:
            doctor(offline=False)
        except typer.Exit:
            console.print(
                "[yellow]Sorunları düzelttikten sonra `gitex doctor` ile tekrar kontrol edebilirsin.[/]"
            )
    console.print('\n[bold green]Hazır![/] Dene: [bold]gitex ask "Son değişiklikler neler?"[/]')


def _pick_base_url(preset: ProviderPreset) -> str | None:
    if not preset.base_url_editable:
        return preset.base_url
    choice = _choose(
        "Sunucu adresi",
        [preset.base_url or "", "Başka bir adres"],
        1,
        hints=["varsayılan", "ör. başka bir makinedeki sunucu"],
    )
    if choice == 1:
        return preset.base_url
    return (
        typer.prompt("Adres (ör. http://192.168.1.10:11434/v1)").strip().rstrip("/")
        or preset.base_url
    )


def _ask_api_key(preset: ProviderPreset, llm: LLMConfig, base_url: str | None) -> None:
    if not preset.needs_key and _is_local(base_url):
        console.print("[dim]Yerel sunucu için anahtar gerekmiyor.[/]")
        return
    existing = llm.api_key() or (
        _env("ANTHROPIC_API_KEY") if preset.provider == "anthropic" else None
    )
    if existing and (
        _choose(
            "Seçim",
            [f"Kayıtlı anahtarı kullan ({credentials.mask(existing)})", "Yeni anahtar gir"],
            1,
        )
        == 1
    ):
        return
    if preset.key_url:
        console.print(f"Anahtar almak için: [link={preset.key_url}]{preset.key_url}[/link]")
    value = typer.prompt(
        "API anahtarını yapıştır (görünmez; boş bırakırsan atlanır)",
        default="",
        hide_input=True,
        show_default=False,
    ).strip()
    if value:
        credentials.set_secret(llm.key_name, value)
        console.print(
            f"[green]✓[/] Anahtar işletim sisteminin anahtar kasasına kaydedildi ({credentials.mask(value)})"
        )
    else:
        console.print(
            f"[yellow]Atlandı.[/] Sonra: [bold]gitex auth login[/] ya da {llm.api_key_env} ortam değişkeni"
        )


def _pick_model(preset: ProviderPreset, llm: LLMConfig) -> str:
    with console.status("Model listesi alınıyor…"):
        try:
            ids = model_lister(llm)
            error = None
        except Exception as exc:
            ids, error = [], _short_error(exc)
    if not ids:
        if error:
            console.print(f"[yellow]Model listesi alınamadı:[/] {error}")
        if preset.key == "ollama":
            console.print("[dim]Ollama'da yüklü model yoksa önce: ollama pull qwen2.5:7b[/]")
        if preset.default_model:
            return str(typer.prompt("Model adı", default=preset.default_model)).strip()
        return str(typer.prompt("Model adı")).strip()

    shown = ids
    if len(ids) > MAX_LISTED_MODELS:
        query = (
            typer.prompt(
                f"{len(ids)} model var. Aramak için bir kelime yaz (boş = ilk {MAX_LISTED_MODELS})",
                default="",
                show_default=False,
            )
            .strip()
            .lower()
        )
        if query:
            matches = [m for m in ids if query in m.lower()]
            if matches:
                shown = matches
            else:
                console.print(
                    f"[yellow]'{query}' ile eşleşen model yok; ilk {MAX_LISTED_MODELS} gösteriliyor.[/]"
                )
    shown = shown[:MAX_LISTED_MODELS]
    manual = "Listede yok — adını elle yazacağım"
    default = shown.index(preset.default_model) + 1 if preset.default_model in shown else 1
    hints = ["ücretsiz" if is_free(m) else "" for m in shown]
    choice = _choose("Seçim", [*shown, manual], default, hints=hints)
    if choice == len(shown) + 1:
        return str(typer.prompt("Model adı")).strip()
    return shown[choice - 1]


def _setup_gitlab(repo: GitRepo) -> None:
    console.print(
        "[bold]5. GitLab (opsiyonel)[/] [dim]— MR'lar, review yorumları ve issue'lar için[/]"
    )
    remote = _origin_remote(repo)
    detected = parse_gitlab_remote(remote) if remote else None
    looks_gitlab = bool(detected and "gitlab" in detected[0])
    if not _yes_no("GitLab bağlansın mı?", default=looks_gitlab):
        console.print()
        return

    url_options: list[str] = []
    url_hints: list[str] = []
    if detected:
        url_options.append(detected[0])
        url_hints.append("git remote'tan algılandı")
    if "https://gitlab.com" not in url_options:
        url_options.append("https://gitlab.com")
        url_hints.append("")
    url_options.append("Başka bir adres")
    url_hints.append("ör. şirket içi GitLab")
    idx = _choose("GitLab adresi", url_options, 1, hints=url_hints)
    url = (
        typer.prompt("Adres (ör. https://gitlab.sirket.com)").strip().rstrip("/")
        if idx == len(url_options)
        else url_options[idx - 1]
    )

    if detected and detected[0] == url:
        pidx = _choose(
            "Proje", [detected[1], "Başka bir proje"], 1, hints=["git remote'tan algılandı", ""]
        )
        project = detected[1] if pidx == 1 else typer.prompt("Proje (grup/proje ya da ID)").strip()
    else:
        project = typer.prompt("Proje (grup/proje ya da ID)").strip()

    repo_cfg = config_path("repo", repo.root)
    set_value(repo_cfg, "gitlab.url", url)
    set_value(repo_cfg, "gitlab.project", project)
    console.print(f"[green]✓[/] GitLab ayarları kaydedildi [dim]({repo_cfg}, bu depo)[/]")
    console.print(
        f"Token almak için: {url}/-/user_settings/personal_access_tokens  [dim](read_api yetkisi yeter)[/]"
    )
    token = typer.prompt(
        "Token'ı yapıştır (görünmez; boş bırakırsan atlanır)",
        default="",
        hide_input=True,
        show_default=False,
    ).strip()
    if token:
        credentials.set_secret(credentials.gitlab_key_name(url), token)
        console.print("[green]✓[/] Token anahtar kasasına kaydedildi")
    if _yes_no("MR'lar şimdi senkronlansın mı?", default=bool(token)):
        from gitex.cli import sync as sync_cmd

        try:
            sync_cmd(full=False, quiet=False)
        except typer.Exit:
            console.print(
                "[yellow]Senkron başarısız; sonra `gitex sync` ile tekrar deneyebilirsin.[/]"
            )
    console.print()


# ---------------------------------------------------------------------- doctor

Status = Literal["ok", "warn", "fail", "info"]
_ICON = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "fail": "[red]✗[/]", "info": "[dim]·[/]"}


@dataclass
class Check:
    name: str
    status: Status
    detail: str
    hint: str | None = None


def ping_llm(cfg: LLMConfig) -> str:
    """Ücretsiz bir uç noktayla (model listesi/detayı) bağlantıyı ve anahtarı doğrular."""
    if cfg.provider == "anthropic":
        import anthropic

        kwargs: dict[str, Any] = {"timeout": 20, "max_retries": 0}
        if key := cfg.api_key():
            kwargs["api_key"] = key
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        client = anthropic.Anthropic(**kwargs)
        info = client.models.retrieve(cfg.model)
        return f"{getattr(info, 'display_name', None) or cfg.model} erişilebilir"
    import openai

    client_o = openai.OpenAI(
        base_url=cfg.base_url, api_key=cfg.api_key() or "not-needed", timeout=10, max_retries=0
    )
    ids = [m.id for m in client_o.models.list()]
    if ids and cfg.model not in ids:
        raise LookupError(f"sunucuda '{cfg.model}' yok; mevcut: {', '.join(ids[:5])}")
    return f"{cfg.base_url} yanıt veriyor"


def ping_gitlab(cfg: Config) -> str:
    import gitlab

    gl = gitlab.Gitlab(cfg.gitlab.url, private_token=cfg.gitlab.token(), timeout=15)
    project = gl.projects.get(cfg.gitlab.project or "")
    return f"{project.attributes.get('path_with_namespace', cfg.gitlab.project)} okunabiliyor"


# Testler ağa çıkmamak için bunları değiştirir.
llm_pinger: Callable[[LLMConfig], str] = ping_llm
gitlab_pinger: Callable[[Config], str] = ping_gitlab


def run_checks(*, offline: bool) -> list[Check]:
    checks: list[Check] = []
    git = shutil.which("git")
    if git:
        version = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, check=False
        ).stdout.strip()
        checks.append(Check("git", "ok", version))
    else:
        checks.append(
            Check("git", "fail", "bulunamadı", "git'i kurun: https://git-scm.com/downloads")
        )
    checks.append(Check("Python", "info", f"{platform.python_version()} ({sys.executable})"))

    repo = state.repo_or_none()
    try:
        cfg = state.config(repo)
        checks.append(Check("Ayarlar", "ok", ", ".join(cfg.sources) or "varsayılanlar"))
    except GitexError as exc:
        checks.append(Check("Ayarlar", "fail", str(exc), exc.hint or "gitex setup"))
        return checks

    if repo is None:
        checks.append(
            Check(
                "Depo", "info", "git deposu dışında", "Bir deponun içinde çalıştırın ya da -C <yol>"
            )
        )
    else:
        checks.append(Check("Depo", "ok", str(repo.root)))
        path = index_path(repo.root)
        if not path.exists():
            checks.append(
                Check("İndeks", "warn", "henüz yok", "gitex index (ya da ilk `gitex ask` kurar)")
            )
        else:
            from gitex.index.db import Database
            from gitex.index.indexer import is_stale

            with Database(path) as db:
                stale = is_stale(repo, db)
                count = db.count("commits")
            checks.append(
                Check(
                    "İndeks",
                    "warn" if stale else "ok",
                    f"{count} commit" + (", güncel değil" if stale else ""),
                    "gitex index" if stale else None,
                )
            )

    llm = cfg.llm
    if not cfg.sources and llm.provider == "openai_compat" and not llm.base_url:
        checks.append(Check("Model", "fail", "yapılandırılmamış", "gitex setup"))
    elif llm.provider == "openai_compat" and not llm.base_url:
        checks.append(
            Check(
                "Model",
                "fail",
                f"{llm.model}: base_url eksik",
                "gitex config set llm.base_url http://localhost:11434/v1",
            )
        )
    else:
        where = f" @ {llm.base_url}" if llm.base_url else ""
        checks.append(Check("Model", "ok", f"{llm.provider} / {llm.model}{where} ({llm.mode})"))
        key = llm.api_key() or (_env("ANTHROPIC_API_KEY") if llm.provider == "anthropic" else None)
        needs_key = llm.provider == "anthropic" or not _is_local(llm.base_url)
        if key:
            checks.append(Check("API anahtarı", "ok", credentials.mask(key)))
        elif needs_key:
            checks.append(Check("API anahtarı", "fail", "bulunamadı", "gitex auth login"))
        else:
            checks.append(Check("API anahtarı", "info", "yerel sunucu, gerekmiyor"))
        if not offline:
            try:
                checks.append(Check("Model bağlantısı", "ok", llm_pinger(llm)))
            except Exception as exc:
                checks.append(
                    Check(
                        "Model bağlantısı",
                        "fail",
                        _short_error(exc),
                        "Sunucunun çalıştığını, model adını ve anahtarı kontrol edin",
                    )
                )

    if not cfg.gitlab.enabled:
        checks.append(
            Check(
                "GitLab",
                "info",
                "ayarlanmamış (opsiyonel)",
                "gitex setup ya da gitex config set gitlab.project grup/proje",
            )
        )
    else:
        token = cfg.gitlab.token()
        checks.append(Check("GitLab", "ok", f"{cfg.gitlab.url} / {cfg.gitlab.project}"))
        if not token:
            checks.append(
                Check(
                    "GitLab token",
                    "warn",
                    "yok (yalnızca herkese açık projeler)",
                    "gitex auth login gitlab",
                )
            )
        if not offline:
            try:
                checks.append(Check("GitLab bağlantısı", "ok", gitlab_pinger(cfg)))
            except Exception as exc:
                checks.append(
                    Check("GitLab bağlantısı", "fail", _short_error(exc), "gitex auth login gitlab")
                )

    backend = credentials.backend_name()
    checks.append(
        Check("Anahtar kasası", "ok", backend)
        if backend
        else Check(
            "Anahtar kasası",
            "warn",
            "yok",
            "Sırları ortam değişkenleriyle verin (gitex auth status)",
        )
    )
    return checks


def _short_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:160]


def doctor(
    offline: bool = typer.Option(False, "--offline", help="Ağ bağlantısı testlerini atla."),
) -> None:
    """Kurulumu kontrol eder: git, ayarlar, indeks, model ve GitLab bağlantısı."""
    checks = run_checks(offline=offline)
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(width=2)
    table.add_column(style="bold")
    table.add_column()
    for c in checks:
        detail = c.detail + (
            f"\n[dim]→ {c.hint}[/]" if c.hint and c.status in ("fail", "warn") else ""
        )
        table.add_row(_ICON[c.status], c.name, detail)
    console.print(table)
    failed = [c for c in checks if c.status == "fail"]
    if failed:
        console.print(
            f"\n[red]{len(failed)} sorun var.[/] Yukarıdaki önerileri uygulayın ya da [bold]gitex setup[/] çalıştırın."
        )
        raise typer.Exit(code=1)
    console.print("\n[green]Her şey hazır.[/]")
