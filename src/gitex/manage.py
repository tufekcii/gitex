"""Yönetim komutları: `setup`, `config`, `auth`, `doctor`.

Kullanıcı hiçbir dosyayı elle düzenlemeden gitex'i bu komutlarla kurar ve yönetir. Ayarlar TOML
dosyalarına (`gitex config`), sırlar işletim sisteminin anahtar kasasına (`gitex auth`) yazılır.
Tüm metinler seçili arayüz dilindedir (`gitex.i18n`).
"""

from __future__ import annotations

import os
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

from gitex import __version__, credentials, i18n
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
from gitex.i18n import LANG_NAMES, LANGS, Lang, t
from gitex.llm.catalog import PRESETS, ProviderPreset, is_free, list_models, preset_for
from gitex.ui import console, err_console, fail, state

Scope = Literal["global", "repo"]

config_app = typer.Typer(
    help=t(
        "Ayarları görüntüle ve değiştir (dosya düzenlemeye gerek yok).",
        "View and change settings (no file editing needed).",
    ),
    no_args_is_help=True,
)
auth_app = typer.Typer(
    help=t(
        "API anahtarı ve token'ları işletim sisteminin anahtar kasasında yönet.",
        "Manage API keys and tokens in your operating system's keychain.",
    ),
    no_args_is_help=True,
)


def _repo_root() -> Path | None:
    repo = state.repo_or_none()
    return repo.root if repo else None


def _resolve_scope(key: str, global_: bool, repo: bool) -> Scope:
    if global_ and repo:
        raise ConfigError(
            t(
                "--global ve --repo birlikte kullanılamaz.",
                "--global and --repo cannot be used together.",
            )
        )
    if key.startswith("ui."):
        # Arayüz dili kullanıcıya özgüdür; yalnızca global config'ten okunur.
        if repo:
            raise ConfigError(
                t(
                    "{k} yalnızca global olarak ayarlanabilir.",
                    "{k} can only be set globally.",
                    k=key,
                )
            )
        return "global"
    if global_:
        return "global"
    if repo:
        return "repo"
    # LLM ve gizlilik ayarları genelde tüm depolar için aynıdır; GitLab projesi depoya özgüdür.
    return "repo" if key.startswith("gitlab.") and _repo_root() is not None else "global"


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return t("evet", "yes") if value else t("hayır", "no")
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or t("(boş)", "(empty)")
    return "-" if value is None else str(value)


def _source_label(source: str) -> str:
    return {"default": t("varsayılan", "default")}.get(source, source)


# ---------------------------------------------------------------------- config


@config_app.command(
    "show",
    help=t(
        "Etkin ayarları ve her birinin nereden geldiğini gösterir.",
        "Show effective settings and where each one comes from.",
    ),
)
def config_show() -> None:
    try:
        root = _repo_root()
        cfg = state.config(state.repo_or_none())
        origins = value_sources(root)
    except GitexError as exc:
        raise fail(exc) from exc
    table = Table(show_lines=False)
    table.add_column(t("Ayar", "Setting"), style="bold")
    table.add_column(t("Değer", "Value"))
    table.add_column(t("Kaynak", "Source"), style="dim")
    for key in all_keys():
        section, field = split_key(key)
        value = getattr(getattr(cfg, section), field)
        if key == "ui.language" and value is None:
            value = t("sistem ({l})", "system ({l})", l=LANG_NAMES[i18n.current()])
        source = origins[key]
        shown = _display(value)
        table.add_row(
            key, shown if source == "default" else f"[cyan]{shown}[/]", _source_label(source)
        )
    console.print(table)
    console.print(f"[dim]Global: {config_path('global', None)}[/]")
    if root is not None:
        console.print(f"[dim]Repo:   {config_path('repo', root)}[/]")
    console.print(
        t(
            "[dim]Değiştirmek için: gitex config set <ayar> <değer>   ·   sırlar: gitex auth status[/]",
            "[dim]To change: gitex config set <setting> <value>   ·   secrets: gitex auth status[/]",
        )
    )


@config_app.command(
    "get",
    help=t("Tek bir ayarın etkin değerini yazar.", "Print the effective value of one setting."),
)
def config_get(key: str = typer.Argument(..., help=t("Ör. llm.model", "E.g. llm.model"))) -> None:
    try:
        section, field = split_key(key)
        cfg = state.config(state.repo_or_none())
    except GitexError as exc:
        raise fail(exc) from exc
    typer.echo(_display(getattr(getattr(cfg, section), field)))


@config_app.command(
    "set",
    help=t(
        "Bir ayarı değiştirir. Varsayılan kapsam: gitlab.* → bu depo, diğerleri → tüm depolar.",
        "Change a setting. Default scope: gitlab.* → this repository, everything else → all repositories.",
    ),
)
def config_set(
    key: str = typer.Argument(
        ...,
        help=t(
            "Ör. llm.model, ui.language, gitlab.project",
            "E.g. llm.model, ui.language, gitlab.project",
        ),
    ),
    value: str = typer.Argument(
        ...,
        help=t(
            "Yeni değer (listeler virgülle: '*.env,*.pem')",
            "New value (lists comma-separated: '*.env,*.pem')",
        ),
    ),
    global_: bool = typer.Option(
        False, "--global", "-g", help=t("Tüm depolar için.", "For all repositories.")
    ),
    repo: bool = typer.Option(
        False, "--repo", "-r", help=t("Yalnızca bu depo için.", "For this repository only.")
    ),
) -> None:
    try:
        scope = _resolve_scope(key, global_, repo)
        path = config_path(scope, _repo_root())
        written = set_value(path, key, value)
    except GitexError as exc:
        raise fail(exc) from exc
    if key == "ui.language":
        i18n.reset()
    where = (
        t("tüm depolar", "all repositories")
        if scope == "global"
        else t("bu depo", "this repository")
    )
    console.print(f"[green]✓[/] {key} = [bold]{_display(written)}[/] [dim]({where}: {path})[/]")


@config_app.command(
    "unset",
    help=t(
        "Bir ayarı kaldırır; değer bir üst katmana ya da varsayılana döner.",
        "Remove a setting; it falls back to the layer above or the default.",
    ),
)
def config_unset(
    key: str = typer.Argument(...),
    global_: bool = typer.Option(
        False, "--global", "-g", help=t("Tüm depolar için.", "For all repositories.")
    ),
    repo: bool = typer.Option(
        False, "--repo", "-r", help=t("Yalnızca bu depo için.", "For this repository only.")
    ),
) -> None:
    try:
        scope = _resolve_scope(key, global_, repo)
        path = config_path(scope, _repo_root())
        removed = unset_value(path, key)
    except GitexError as exc:
        raise fail(exc) from exc
    if key == "ui.language":
        i18n.reset()
    if removed:
        console.print(
            t(
                "[green]✓[/] {k} kaldırıldı [dim]({p})[/]",
                "[green]✓[/] {k} removed [dim]({p})[/]",
                k=key,
                p=path,
            )
        )
    else:
        console.print(
            t(
                "[yellow]{k} bu kapsamda zaten ayarlı değil[/] [dim]({p})[/]",
                "[yellow]{k} is not set in this scope[/] [dim]({p})[/]",
                k=key,
                p=path,
            )
        )


@config_app.command(
    "list-keys",
    help=t(
        "Ayarlanabilir tüm anahtarları, türlerini ve varsayılanlarını listeler.",
        "List every setting with its type and default.",
    ),
)
def config_list_keys() -> None:
    table = Table()
    table.add_column(t("Ayar", "Setting"), style="bold")
    table.add_column(t("Tür", "Type"))
    table.add_column(t("Varsayılan", "Default"), style="dim")
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


@config_app.command(
    "path", help=t("Ayar dosyalarının yollarını gösterir.", "Show where the settings files are.")
)
def config_path_cmd() -> None:
    console.print(f"Global: {config_path('global', None)}")
    root = _repo_root()
    console.print(
        f"Repo:   {config_path('repo', root) if root else t('(git deposu dışında)', '(outside a git repository)')}"
    )


# ---------------------------------------------------------------------- auth


def _secret_info(cfg: Config, target: str) -> tuple[str, str | None, str | None]:
    """(kasadaki ad, env değişkeni adı, ortamdaki değer)."""
    if target == "llm":
        return cfg.llm.key_name, cfg.llm.api_key_env, os.environ.get(cfg.llm.api_key_env)
    if target == "gitlab":
        return cfg.gitlab.key_name, GITLAB_TOKEN_ENV, os.environ.get(GITLAB_TOKEN_ENV)
    raise ConfigError(
        t("Bilinmeyen hedef: {x}", "Unknown target: {x}", x=target),
        hint=t("llm ya da gitlab", "llm or gitlab"),
    )


@auth_app.command(
    "login",
    help=t(
        "API anahtarını / token'ı gizli girişle alıp anahtar kasasına kaydeder.",
        "Read an API key / token with hidden input and store it in the keychain.",
    ),
)
def auth_login(
    target: str = typer.Argument("llm", help=t("llm ya da gitlab", "llm or gitlab")),
    stdin: bool = typer.Option(
        False,
        "--stdin",
        help=t(
            "Değeri standart girdiden oku (betikler için).",
            "Read the value from standard input (for scripts).",
        ),
    ),
) -> None:
    try:
        cfg = state.config(state.repo_or_none())
        name, env_name, _ = _secret_info(cfg, target)
        if stdin:
            value = sys.stdin.readline().strip()
        else:
            label = (
                t("API anahtarı", "API key")
                if target == "llm"
                else t("GitLab token'ı (read_api)", "GitLab token (read_api)")
            )
            value = str(
                typer.prompt(
                    t("{l} (yazdıkların görünmez)", "{l} (input is hidden)", l=label),
                    hide_input=True,
                )
            ).strip()
        if not value:
            raise GitexError(t("Boş değer kaydedilmedi.", "Empty value was not saved."))
        credentials.set_secret(name, value)
    except GitexError as exc:
        raise fail(exc) from exc
    console.print(
        t(
            "[green]✓[/] Kaydedildi: {n} [dim]({m}, anahtar kasası)[/]",
            "[green]✓[/] Saved: {n} [dim]({m}, keychain)[/]",
            n=name,
            m=credentials.mask(value),
        )
    )
    if env_name and _secret_info(cfg, target)[2]:
        console.print(
            t(
                "[yellow]Not:[/] {e} ortam değişkeni tanımlı ve kasadaki değerden önceliklidir.",
                "[yellow]Note:[/] the {e} environment variable is set and takes precedence over the keychain.",
                e=env_name,
            )
        )


@auth_app.command("logout", help=t("Kasadaki anahtarı siler.", "Remove the key from the keychain."))
def auth_logout(
    target: str = typer.Argument("llm", help=t("llm ya da gitlab", "llm or gitlab")),
) -> None:
    try:
        cfg = state.config(state.repo_or_none())
        name, _, _ = _secret_info(cfg, target)
        removed = credentials.delete_secret(name)
    except GitexError as exc:
        raise fail(exc) from exc
    console.print(
        t("[green]✓[/] {n} silindi", "[green]✓[/] {n} removed", n=name)
        if removed
        else t("[yellow]{n} kasada zaten yok[/]", "[yellow]{n} is not in the keychain[/]", n=name)
    )


@auth_app.command(
    "status",
    help=t(
        "Hangi sırrın nereden okunduğunu gösterir (değerler maskelenir).",
        "Show which secret is used and from where (values are masked).",
    ),
)
def auth_status() -> None:
    try:
        cfg = state.config(state.repo_or_none())
    except GitexError as exc:
        raise fail(exc) from exc
    backend = credentials.backend_name()
    console.print(
        t("Anahtar kasası: ", "Keychain: ")
        + (
            backend
            or t(
                "[yellow]yok[/] — sırları ortam değişkeniyle verin",
                "[yellow]none[/] — provide secrets via environment variables",
            )
        )
    )
    table = Table()
    for col in (
        t("Hedef", "Target"),
        t("Kasa adı", "Keychain name"),
        t("Kaynak", "Source"),
        t("Değer", "Value"),
    ):
        table.add_column(col)
    for target in ("llm", "gitlab"):
        if target == "gitlab" and not cfg.gitlab.enabled:
            table.add_row(
                "gitlab",
                "-",
                t("[dim]GitLab ayarlanmamış[/]", "[dim]GitLab not configured[/]"),
                "-",
            )
            continue
        name, env_name, env_value = _secret_info(cfg, target)
        stored = credentials.get_secret(name)
        value: str | None
        if env_value:
            source, value = f"env ({env_name})", env_value
        elif stored:
            source, value = t("anahtar kasası", "keychain"), stored
        elif target == "llm" and cfg.llm.provider == "anthropic" and _env("ANTHROPIC_API_KEY"):
            source, value = "env (ANTHROPIC_API_KEY)", _env("ANTHROPIC_API_KEY")
        else:
            needed = (
                target == "gitlab"
                or cfg.llm.provider == "anthropic"
                or not _is_local(cfg.llm.base_url)
            )
            source = (
                t(
                    "[red]yok[/] — gitex auth login {x}",
                    "[red]missing[/] — gitex auth login {x}",
                    x=target,
                )
                if needed
                else t("[dim]gerekmiyor (yerel sunucu)[/]", "[dim]not needed (local server)[/]")
            )
            value = None
        table.add_row(target, name, source, credentials.mask(value))
    console.print(table)


def _env(name: str) -> str | None:
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


def _ask(prompt: str, **kwargs: Any) -> str:
    return str(typer.prompt(prompt, **kwargs)).strip()


def _choose(
    prompt: str, options: list[str], default: int = 1, hints: list[str] | None = None
) -> int:
    """Numaralı seçim; 1'den başlayan sıra numarasını döner."""
    for i, opt in enumerate(options, 1):
        hint = hints[i - 1] if hints and i - 1 < len(hints) and hints[i - 1] else ""
        marker = (
            t(" [dim](önerilen)[/]", " [dim](recommended)[/]")
            if i == default and len(options) > 1
            else ""
        )
        console.print(
            f"  [bold cyan]{i:>2}[/]) {opt}" + (f"  [dim]— {hint}[/]" if hint else "") + marker
        )
    while True:
        raw = _ask(prompt, default=str(default))
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw)
        console.print(
            t(
                "[yellow]1 ile {n} arasında bir sayı girin.[/]",
                "[yellow]Enter a number between 1 and {n}.[/]",
                n=len(options),
            )
        )


def _yes_no(prompt: str, *, default: bool) -> bool:
    return _choose(prompt, [t("Evet", "Yes"), t("Hayır", "No")], 1 if default else 2) == 1


class _Steps:
    """Sihirbaz adım numarası (dil adımı atlanınca numaralar kaymasın diye)."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self, title: str) -> None:
        self.n += 1
        console.print(f"\n[bold]{self.n}. {title}[/]")


def setup(
    lang: str | None = typer.Option(
        None,
        "--lang",
        help=t(
            "Arayüz dili: tr ya da en (verilirse sorulmaz).",
            "Interface language: tr or en (skips the question).",
        ),
    ),
    skip_check: bool = typer.Option(
        False,
        "--no-check",
        help=t("Sonda bağlantı testini atla.", "Skip the connection test at the end."),
    ),
) -> None:
    try:
        _run_setup(lang=lang, skip_check=skip_check)
    except GitexError as exc:
        raise fail(exc) from exc
    except (typer.Abort, KeyboardInterrupt) as exc:
        err_console.print(
            t(
                "\n[dim]Kurulum iptal edildi; o ana kadar yapılan seçimler kaydedildi.[/]",
                "\n[dim]Setup cancelled; choices made so far were saved.[/]",
            )
        )
        raise typer.Exit(code=1) from exc


def _choose_language(lang: str | None, global_path: Path) -> None:
    chosen: Lang | None = None
    if lang is not None:
        normalized = lang.strip().lower()[:2]
        if normalized not in LANGS:
            raise GitexError(
                t("Geçersiz dil: {l}", "Invalid language: {l}", l=lang), hint="tr | en"
            )
        chosen = normalized
    else:
        # İki dilde birden sorulur; henüz hangisinin okunacağını bilmiyoruz.
        console.print("[bold]Dil / Language[/]")
        default = LANGS.index(i18n.current()) + 1
        chosen = LANGS[_choose("Seçim / Choice", [LANG_NAMES[x] for x in LANGS], default) - 1]
    set_value(global_path, "ui.language", chosen)
    i18n.set_language(chosen)


def _run_setup(*, lang: str | None, skip_check: bool) -> None:
    repo = state.repo_or_none()
    global_path = config_path("global", None)
    _choose_language(lang, global_path)
    step = _Steps()
    console.print(
        t(
            "\n[bold]gitex {v} kurulumu[/]  [dim](istediğin zaman tekrar çalıştırabilirsin: gitex setup)[/]",
            "\n[bold]gitex {v} setup[/]  [dim](run it again any time: gitex setup)[/]",
            v=__version__,
        )
    )

    step(t("Hangi yapay zekâ servisini kullanacaksın?", "Which AI service do you want to use?"))
    current = preset_for(state.config(repo).llm)
    default = PRESETS.index(current) + 1 if current else 1
    preset = PRESETS[
        _choose(
            t("Seçim", "Choice"),
            [p.label for p in PRESETS],
            default,
            hints=[p.note for p in PRESETS],
        )
        - 1
    ]
    base_url = _pick_base_url(preset)
    llm = LLMConfig(provider=preset.provider, base_url=base_url)

    # Anahtar, model listesini çekebilmek için modelden önce sorulur.
    step(t("API anahtarı", "API key"))
    _ask_api_key(preset, llm, base_url)

    step(t("Model", "Model"))
    model = _pick_model(preset, llm)

    step(t("Çalışma modu", "Mode"))
    mode_idx = _choose(
        t("Seçim", "Choice"),
        ["agent", "simple"],
        1 if preset.mode == "agent" else 2,
        hints=[
            t(
                "model araçları kendisi çağırır; güçlü modeller için",
                "the model calls the tools itself; for capable models",
            ),
            t(
                "sabit arama + tek çağrı; küçük/ücretsiz modellerde daha isabetli",
                "fixed retrieval + a single call; more accurate on small/free models",
            ),
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
        t(
            "[green]✓[/] {p} / {m} ({mode}) kaydedildi [dim]({path}, tüm depolar)[/]",
            "[green]✓[/] {p} / {m} ({mode}) saved [dim]({path}, all repositories)[/]",
            p=preset.label,
            m=model,
            mode=mode,
            path=global_path,
        )
    )

    if repo is None:
        console.print(
            t(
                "\n[dim]Bir git deposunun içinde olmadığın için GitLab ve indeks adımları atlandı.[/]",
                "\n[dim]You are not inside a git repository, so the GitLab and index steps were skipped.[/]",
            )
        )
    else:
        _setup_gitlab(repo, step)
        step(t("İndeks", "Index"))
        from gitex.cli import ensure_gitignore, run_index
        from gitex.index.indexer import open_index

        with open_index(repo) as db:
            run_index(repo, db)
        ensure_gitignore(repo)

    console.print()
    if not skip_check and _yes_no(
        t("Bağlantı test edilsin mi?", "Test the connection now?"), default=True
    ):
        try:
            doctor(offline=False)
        except typer.Exit:
            console.print(
                t(
                    "[yellow]Sorunları düzelttikten sonra `gitex doctor` ile tekrar kontrol edebilirsin.[/]",
                    "[yellow]After fixing the issues, check again with `gitex doctor`.[/]",
                )
            )
    console.print(
        t(
            '\n[bold green]Hazır![/] Dene: [bold]gitex ask "Son değişiklikler neler?"[/]',
            '\n[bold green]All set![/] Try: [bold]gitex ask "What changed recently?"[/]',
        )
    )


def _pick_base_url(preset: ProviderPreset) -> str | None:
    if not preset.base_url_editable:
        return preset.base_url
    choice = _choose(
        t("Sunucu adresi", "Server address"),
        [preset.base_url or "", t("Başka bir adres", "Another address")],
        1,
        hints=[
            t("varsayılan", "default"),
            t("ör. başka bir makinedeki sunucu", "e.g. a server on another machine"),
        ],
    )
    if choice == 1:
        return preset.base_url
    return (
        _ask(
            t(
                "Adres (ör. http://192.168.1.10:11434/v1)",
                "Address (e.g. http://192.168.1.10:11434/v1)",
            )
        ).rstrip("/")
        or preset.base_url
    )


def _ask_api_key(preset: ProviderPreset, llm: LLMConfig, base_url: str | None) -> None:
    if not preset.needs_key and _is_local(base_url):
        console.print(
            t(
                "[dim]Yerel sunucu için anahtar gerekmiyor.[/]",
                "[dim]No key needed for a local server.[/]",
            )
        )
        return
    existing = llm.api_key() or (
        _env("ANTHROPIC_API_KEY") if preset.provider == "anthropic" else None
    )
    if existing:
        keep = _choose(
            t("Seçim", "Choice"),
            [
                t(
                    "Kayıtlı anahtarı kullan ({m})",
                    "Use the saved key ({m})",
                    m=credentials.mask(existing),
                ),
                t("Yeni anahtar gir", "Enter a new key"),
            ],
            1,
        )
        if keep == 1:
            return
    if preset.key_url:
        console.print(
            t("Anahtar almak için: ", "Get a key at: ")
            + f"[link={preset.key_url}]{preset.key_url}[/link]"
        )
    value = _ask(
        t(
            "API anahtarını yapıştır (görünmez; boş bırakırsan atlanır)",
            "Paste your API key (hidden; leave empty to skip)",
        ),
        default="",
        hide_input=True,
        show_default=False,
    )
    if value:
        credentials.set_secret(llm.key_name, value)
        console.print(
            t(
                "[green]✓[/] Anahtar işletim sisteminin anahtar kasasına kaydedildi ({m})",
                "[green]✓[/] Key saved to your operating system's keychain ({m})",
                m=credentials.mask(value),
            )
        )
    else:
        console.print(
            t(
                "[yellow]Atlandı.[/] Sonra: [bold]gitex auth login[/] ya da {e} ortam değişkeni",
                "[yellow]Skipped.[/] Later: [bold]gitex auth login[/] or the {e} environment variable",
                e=llm.api_key_env,
            )
        )


def _pick_model(preset: ProviderPreset, llm: LLMConfig) -> str:
    with console.status(t("Model listesi alınıyor…", "Fetching the model list…")):
        try:
            ids = model_lister(llm)
            error = None
        except Exception as exc:
            ids, error = [], _short_error(exc)
    name_prompt = t("Model adı", "Model name")
    if not ids:
        if error:
            console.print(
                t(
                    "[yellow]Model listesi alınamadı:[/] {e}",
                    "[yellow]Could not fetch the model list:[/] {e}",
                    e=error,
                )
            )
        if preset.key == "ollama":
            console.print(
                t(
                    "[dim]Ollama'da yüklü model yoksa önce: ollama pull qwen2.5:7b[/]",
                    "[dim]If Ollama has no models yet, first run: ollama pull qwen2.5:7b[/]",
                )
            )
        if preset.default_model:
            return _ask(name_prompt, default=preset.default_model)
        return _ask(name_prompt)

    shown = ids
    if len(ids) > MAX_LISTED_MODELS:
        query = _ask(
            t(
                "{n} model var. Aramak için bir kelime yaz (boş = ilk {k})",
                "{n} models available. Type a word to search (empty = first {k})",
                n=len(ids),
                k=MAX_LISTED_MODELS,
            ),
            default="",
            show_default=False,
        ).lower()
        if query:
            matches = [m for m in ids if query in m.lower()]
            if matches:
                shown = matches
            else:
                console.print(
                    t(
                        "[yellow]'{q}' ile eşleşen model yok; ilk {k} gösteriliyor.[/]",
                        "[yellow]No model matches '{q}'; showing the first {k}.[/]",
                        q=query,
                        k=MAX_LISTED_MODELS,
                    )
                )
    shown = shown[:MAX_LISTED_MODELS]
    manual = t("Listede yok — adını elle yazacağım", "Not listed — I'll type the name")
    default = shown.index(preset.default_model) + 1 if preset.default_model in shown else 1
    hints = [t("ücretsiz", "free") if is_free(m) else "" for m in shown]
    choice = _choose(t("Seçim", "Choice"), [*shown, manual], default, hints=hints)
    if choice == len(shown) + 1:
        return _ask(name_prompt)
    return shown[choice - 1]


def _setup_gitlab(repo: GitRepo, step: _Steps) -> None:
    step(t("GitLab (opsiyonel)", "GitLab (optional)"))
    console.print(
        t(
            "[dim]MR'lar, review yorumları ve issue'lar için[/]",
            "[dim]For merge requests, review notes and issues[/]",
        )
    )
    remote = _origin_remote(repo)
    detected = parse_gitlab_remote(remote) if remote else None
    looks_gitlab = bool(detected and "gitlab" in detected[0])
    if not _yes_no(t("GitLab bağlansın mı?", "Connect GitLab?"), default=looks_gitlab):
        return

    from_remote = t("git remote'tan algılandı", "detected from your git remote")
    url_options: list[str] = []
    url_hints: list[str] = []
    if detected:
        url_options.append(detected[0])
        url_hints.append(from_remote)
    if "https://gitlab.com" not in url_options:
        url_options.append("https://gitlab.com")
        url_hints.append("")
    url_options.append(t("Başka bir adres", "Another address"))
    url_hints.append(t("ör. şirket içi GitLab", "e.g. self-hosted GitLab"))
    idx = _choose(t("GitLab adresi", "GitLab address"), url_options, 1, hints=url_hints)
    url = (
        _ask(
            t("Adres (ör. https://gitlab.sirket.com)", "Address (e.g. https://gitlab.company.com)")
        ).rstrip("/")
        if idx == len(url_options)
        else url_options[idx - 1]
    )

    project_prompt = t("Proje (grup/proje ya da ID)", "Project (group/project or ID)")
    if detected and detected[0] == url:
        pidx = _choose(
            t("Proje", "Project"),
            [detected[1], t("Başka bir proje", "Another project")],
            1,
            hints=[from_remote, ""],
        )
        project = detected[1] if pidx == 1 else _ask(project_prompt)
    else:
        project = _ask(project_prompt)

    repo_cfg = config_path("repo", repo.root)
    set_value(repo_cfg, "gitlab.url", url)
    set_value(repo_cfg, "gitlab.project", project)
    console.print(
        t(
            "[green]✓[/] GitLab ayarları kaydedildi [dim]({p}, bu depo)[/]",
            "[green]✓[/] GitLab settings saved [dim]({p}, this repository)[/]",
            p=repo_cfg,
        )
    )
    console.print(
        t("Token almak için: ", "Get a token at: ")
        + f"{url}/-/user_settings/personal_access_tokens  "
        + t("[dim](read_api yetkisi yeter)[/]", "[dim](read_api scope is enough)[/]")
    )
    token = _ask(
        t(
            "Token'ı yapıştır (görünmez; boş bırakırsan atlanır)",
            "Paste the token (hidden; leave empty to skip)",
        ),
        default="",
        hide_input=True,
        show_default=False,
    )
    if token:
        credentials.set_secret(credentials.gitlab_key_name(url), token)
        console.print(
            t(
                "[green]✓[/] Token anahtar kasasına kaydedildi",
                "[green]✓[/] Token saved to the keychain",
            )
        )
    if _yes_no(
        t("MR'lar şimdi senkronlansın mı?", "Sync merge requests now?"), default=bool(token)
    ):
        from gitex.cli import sync as sync_cmd

        try:
            sync_cmd(full=False, quiet=False)
        except typer.Exit:
            console.print(
                t(
                    "[yellow]Senkron başarısız; sonra `gitex sync` ile tekrar deneyebilirsin.[/]",
                    "[yellow]Sync failed; you can retry later with `gitex sync`.[/]",
                )
            )


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
        return t(
            "{m} erişilebilir",
            "{m} is reachable",
            m=getattr(info, "display_name", None) or cfg.model,
        )
    import openai

    client_o = openai.OpenAI(
        base_url=cfg.base_url, api_key=cfg.api_key() or "not-needed", timeout=10, max_retries=0
    )
    ids = [m.id for m in client_o.models.list()]
    if ids and cfg.model not in ids:
        raise LookupError(
            t(
                "sunucuda '{m}' yok; mevcut: {a}",
                "the server has no '{m}'; available: {a}",
                m=cfg.model,
                a=", ".join(ids[:5]),
            )
        )
    return t("{u} yanıt veriyor", "{u} is responding", u=cfg.base_url)


def ping_gitlab(cfg: Config) -> str:
    import gitlab

    gl = gitlab.Gitlab(cfg.gitlab.url, private_token=cfg.gitlab.token(), timeout=15)
    project = gl.projects.get(cfg.gitlab.project or "")
    return t(
        "{p} okunabiliyor",
        "{p} is readable",
        p=project.attributes.get("path_with_namespace", cfg.gitlab.project),
    )


# Testler ağa çıkmamak için bunları değiştirir.
llm_pinger: Callable[[LLMConfig], str] = ping_llm
gitlab_pinger: Callable[[Config], str] = ping_gitlab


def run_checks(*, offline: bool) -> list[Check]:
    checks: list[Check] = []
    if shutil.which("git"):
        version = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, check=False
        ).stdout.strip()
        checks.append(Check("git", "ok", version))
    else:
        checks.append(
            Check(
                "git",
                "fail",
                t("bulunamadı", "not found"),
                t("git'i kurun: ", "Install git: ") + "https://git-scm.com/downloads",
            )
        )
    checks.append(Check("Python", "info", f"{platform.python_version()} ({sys.executable})"))
    checks.append(Check(t("Dil", "Language"), "info", LANG_NAMES[i18n.current()], None))

    repo = state.repo_or_none()
    settings = t("Ayarlar", "Settings")
    try:
        cfg = state.config(repo)
        checks.append(
            Check(settings, "ok", ", ".join(cfg.sources) or t("varsayılanlar", "defaults"))
        )
    except GitexError as exc:
        checks.append(Check(settings, "fail", str(exc), exc.hint or "gitex setup"))
        return checks

    repo_label, index_label = t("Depo", "Repository"), t("İndeks", "Index")
    if repo is None:
        checks.append(
            Check(
                repo_label,
                "info",
                t("git deposu dışında", "outside a git repository"),
                t(
                    "Bir deponun içinde çalıştırın ya da -C <yol>",
                    "Run inside a repository or use -C <path>",
                ),
            )
        )
    else:
        checks.append(Check(repo_label, "ok", str(repo.root)))
        path = index_path(repo.root)
        if not path.exists():
            checks.append(
                Check(
                    index_label,
                    "warn",
                    t("henüz yok", "not built yet"),
                    t(
                        "gitex index (ya da ilk `gitex ask` kurar)",
                        "gitex index (or the first `gitex ask` builds it)",
                    ),
                )
            )
        else:
            from gitex.index.db import Database
            from gitex.index.indexer import is_stale

            with Database(path) as db:
                stale = is_stale(repo, db)
                count = db.count("commits")
            checks.append(
                Check(
                    index_label,
                    "warn" if stale else "ok",
                    f"{count} commit" + (t(", güncel değil", ", out of date") if stale else ""),
                    "gitex index" if stale else None,
                )
            )

    llm = cfg.llm
    key_label = t("API anahtarı", "API key")
    if not cfg.sources and llm.provider == "openai_compat" and not llm.base_url:
        checks.append(
            Check("Model", "fail", t("yapılandırılmamış", "not configured"), "gitex setup")
        )
    elif llm.provider == "openai_compat" and not llm.base_url:
        checks.append(
            Check(
                "Model",
                "fail",
                t("{m}: base_url eksik", "{m}: base_url missing", m=llm.model),
                "gitex config set llm.base_url http://localhost:11434/v1",
            )
        )
    else:
        where = f" @ {llm.base_url}" if llm.base_url else ""
        checks.append(Check("Model", "ok", f"{llm.provider} / {llm.model}{where} ({llm.mode})"))
        key = llm.api_key() or (_env("ANTHROPIC_API_KEY") if llm.provider == "anthropic" else None)
        needs_key = llm.provider == "anthropic" or not _is_local(llm.base_url)
        if key:
            checks.append(Check(key_label, "ok", credentials.mask(key)))
        elif needs_key:
            checks.append(
                Check(key_label, "fail", t("bulunamadı", "not found"), "gitex auth login")
            )
        else:
            checks.append(
                Check(key_label, "info", t("yerel sunucu, gerekmiyor", "local server, not needed"))
            )
        if not offline:
            conn = t("Model bağlantısı", "Model connection")
            try:
                checks.append(Check(conn, "ok", llm_pinger(llm)))
            except Exception as exc:
                checks.append(
                    Check(
                        conn,
                        "fail",
                        _short_error(exc),
                        t(
                            "Sunucunun çalıştığını, model adını ve anahtarı kontrol edin",
                            "Check that the server is running, the model name and the key",
                        ),
                    )
                )

    if not cfg.gitlab.enabled:
        checks.append(
            Check(
                "GitLab",
                "info",
                t("ayarlanmamış (opsiyonel)", "not configured (optional)"),
                t(
                    "gitex setup ya da gitex config set gitlab.project grup/proje",
                    "gitex setup or gitex config set gitlab.project group/project",
                ),
            )
        )
    else:
        checks.append(Check("GitLab", "ok", f"{cfg.gitlab.url} / {cfg.gitlab.project}"))
        if not cfg.gitlab.token():
            checks.append(
                Check(
                    "GitLab token",
                    "warn",
                    t("yok (yalnızca herkese açık projeler)", "missing (public projects only)"),
                    "gitex auth login gitlab",
                )
            )
        if not offline:
            conn = t("GitLab bağlantısı", "GitLab connection")
            try:
                checks.append(Check(conn, "ok", gitlab_pinger(cfg)))
            except Exception as exc:
                checks.append(Check(conn, "fail", _short_error(exc), "gitex auth login gitlab"))

    keychain = t("Anahtar kasası", "Keychain")
    backend = credentials.backend_name()
    checks.append(
        Check(keychain, "ok", backend)
        if backend
        else Check(
            keychain,
            "warn",
            t("yok", "none"),
            t(
                "Sırları ortam değişkenleriyle verin (gitex auth status)",
                "Provide secrets via environment variables (gitex auth status)",
            ),
        )
    )
    return checks


def _short_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:160]


def doctor(
    offline: bool = typer.Option(
        False, "--offline", help=t("Ağ bağlantısı testlerini atla.", "Skip network checks.")
    ),
) -> None:
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
            t(
                "\n[red]{n} sorun var.[/] Yukarıdaki önerileri uygulayın ya da [bold]gitex setup[/] çalıştırın.",
                "\n[red]{n} problem(s) found.[/] Apply the suggestions above or run [bold]gitex setup[/].",
                n=len(failed),
            )
        )
        raise typer.Exit(code=1)
    console.print(t("\n[green]Her şey hazır.[/]", "\n[green]Everything is ready.[/]"))
