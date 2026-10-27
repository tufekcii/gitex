"""gitex komut satırı arayüzü."""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gitex import __version__
from gitex.agent.loop import AgentResult, EventFn
from gitex.config import GITLAB_TOKEN_ENV, Config, index_path, repo_dir, sample_config
from gitex.errors import GitexError
from gitex.git.models import Commit, PickaxeHit
from gitex.git.reader import GitRepo
from gitex.gitlab.client import GitLabClient
from gitex.gitlab.sync import sync_gitlab
from gitex.i18n import apply_to_typer, t
from gitex.index.db import Database
from gitex.index.indexer import index_repo, is_stale, open_index
from gitex.index.search import FTSSearch
from gitex.llm.base import LLMProvider, LLMResponse, Message, ToolSpec
from gitex.llm.factory import make_provider
from gitex.manage import auth_app, config_app, doctor, setup
from gitex.session import Session
from gitex.ui import Activity, console, err_console, fail, state

apply_to_typer()

app = typer.Typer(
    name="gitex",
    help=t(
        "Git geçmişini doğal dilde sorgula: ne değişti, ne zaman, kim, neden.",
        "Ask your Git history in plain language: what changed, when, who and why.",
    ),
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


app.command(
    help=t(
        "Adım adım kurulum: dil, model, API anahtarı, (opsiyonel) GitLab ve indeks.",
        "Guided setup: language, model, API key, (optional) GitLab and index.",
    )
)(setup)
app.command(
    help=t(
        "Kurulumu kontrol eder: git, ayarlar, indeks, model ve GitLab bağlantısı.",
        "Check the setup: git, settings, index, model and GitLab connectivity.",
    )
)(doctor)
app.add_typer(config_app, name="config")
app.add_typer(auth_app, name="auth")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"gitex {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    repo: Path = typer.Option(
        Path("."),
        "--repo",
        "-C",
        help=t(
            "Git deposunun yolu (varsayılan: bulunulan dizin).",
            "Path to the Git repository (default: current directory).",
        ),
    ),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help=t("Sürümü göster.", "Show the version."),
    ),
) -> None:
    state.repo_path = repo


_fail = fail


# ---------------------------------------------------------------------- init


@app.command(
    help=t(
        "`.gitex/` oluşturur ve `.gitignore`'a ekler (tam kurulum için: gitex setup).",
        "Create `.gitex/` and add it to `.gitignore` (full setup: gitex setup).",
    )
)
def init() -> None:
    try:
        repo = state.repo()
    except GitexError as exc:
        raise _fail(exc) from exc
    cfg = repo_dir(repo.root) / "config.toml"
    if cfg.exists():
        console.print(
            t(
                "[yellow]Repo ayar dosyası zaten var:[/] {p}",
                "[yellow]Repository settings file already exists:[/] {p}",
                p=cfg,
            )
        )
    else:
        cfg.parent.mkdir(exist_ok=True)
        cfg.write_text(sample_config(), encoding="utf-8")
        console.print(
            t(
                "[green]Repo ayar dosyası oluşturuldu:[/] {p}",
                "[green]Repository settings file created:[/] {p}",
                p=cfg,
            )
        )
    ensure_gitignore(repo)
    console.print(
        t(
            "Sonraki adım: [bold]gitex setup[/] (model, anahtar, GitLab) ya da [bold]gitex index[/]",
            "Next: [bold]gitex setup[/] (model, key, GitLab) or [bold]gitex index[/]",
        )
    )


def ensure_gitignore(repo: GitRepo) -> None:
    """`.gitex/` satırını `.gitignore`'a (yoksa) ekler."""
    repo_dir(repo.root).mkdir(exist_ok=True)
    gitignore = repo.root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if not any(line.strip() in (".gitex", ".gitex/") for line in existing.splitlines()):
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}.gitex/\n")
        console.print(
            t(
                "[green].gitignore güncellendi[/] (.gitex/)",
                "[green].gitignore updated[/] (.gitex/)",
            )
        )


# ---------------------------------------------------------------------- index


def run_index(repo: GitRepo, db: Database, *, quiet: bool = False) -> None:
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    with Progress(
        TextColumn(t("[bold blue]İndeksleniyor", "[bold blue]Indexing")),
        BarColumn(),
        MofNCompleteColumn(),
        console=err_console,
        transient=True,
        disable=quiet,
    ) as progress:
        task = progress.add_task("index", total=None)

        def _cb(done: int, total: int) -> None:
            progress.update(task, completed=done, total=total)

        stats = index_repo(repo, db, progress=_cb)
    if not quiet:
        err_console.print(
            t(
                "[green]İndeks hazır:[/] +{a} yeni, -{r} kaldırılan, toplam {n} commit ({s:.1f} sn)",
                "[green]Index ready:[/] +{a} new, -{r} removed, {n} commits in total ({s:.1f}s)",
                a=stats.added,
                r=stats.removed,
                n=stats.total,
                s=stats.elapsed,
            )
        )


@app.command(
    help=t(
        "Yerel git geçmişini artımlı olarak indeksler.", "Index local Git history incrementally."
    )
)
def index(
    rebuild: bool = typer.Option(
        False, "--rebuild", help=t("İndeksi sıfırdan kur.", "Rebuild the index from scratch.")
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help=t("İlerleme gösterme.", "Don't show progress.")
    ),
) -> None:
    try:
        repo = state.repo()
        with open_index(repo, rebuild=rebuild) as db:
            run_index(repo, db, quiet=quiet)
    except GitexError as exc:
        raise _fail(exc) from exc


# ---------------------------------------------------------------------- sync


def make_gitlab_client(cfg: Config) -> GitLabClient:
    return GitLabClient(cfg.gitlab, cfg.gitlab.token())


@app.command(
    help=t(
        "GitLab MR / yorum / issue senkronizasyonu (gerekirse önce yerel indeksi günceller).",
        "Sync GitLab merge requests, review notes and issues (updates the local index first if needed).",
    )
)
def sync(
    full: bool = typer.Option(
        False,
        "--full",
        help=t(
            "İmleci yok say, tüm MR'ları yeniden çek.",
            "Ignore the cursor and fetch every MR again.",
        ),
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help=t("İlerleme gösterme.", "Don't show progress.")
    ),
) -> None:
    try:
        repo = state.repo()
        cfg = state.config(repo)
        if not cfg.gitlab.enabled:
            raise GitexError(
                t("GitLab ayarlanmamış.", "GitLab is not configured."),
                hint=t(
                    "Kurulum: gitex setup  ·  ya da: gitex config set gitlab.project grup/proje",
                    "Set it up: gitex setup  ·  or: gitex config set gitlab.project group/project",
                ),
            )
        if not cfg.gitlab.token():
            err_console.print(
                t(
                    "[yellow]Uyarı:[/] GitLab token'ı yok ({e} ya da gitex auth login gitlab); yalnızca herkese açık projeler okunabilir.",
                    "[yellow]Warning:[/] no GitLab token ({e} or gitex auth login gitlab); only public projects can be read.",
                    e=GITLAB_TOKEN_ENV,
                )
            )
        with open_index(repo) as db:
            if is_stale(repo, db):
                run_index(repo, db, quiet=quiet)
            with Activity(
                t("GitLab'dan MR'lar alınıyor…", "Fetching merge requests from GitLab…"),
                enabled=not quiet,
            ) as activity:
                client = make_gitlab_client(cfg)

                def _progress(n: int) -> None:
                    activity.update(detail=f"{n} MR")

                stats = sync_gitlab(client, db, full=full, progress=_progress)
    except GitexError as exc:
        raise _fail(exc) from exc
    if not quiet:
        err_console.print(
            t(
                "[green]GitLab senkronu ({k}):[/] {s} MR güncellendi, {r} kaldırıldı, {n} yorum, {i} issue bağı ({e:.1f} sn)",
                "[green]GitLab sync ({k}):[/] {s} MRs updated, {r} removed, {n} notes, {i} issue links ({e:.1f}s)",
                k=t("tam", "full") if stats.full else t("artımlı", "incremental"),
                s=stats.synced,
                r=stats.removed,
                n=stats.notes,
                i=stats.issues,
                e=stats.elapsed,
            )
        )


# ---------------------------------------------------------------------- status


@app.command(
    help=t(
        "İndeks durumu, son senkron ve ayar özeti.", "Index state, last sync and settings summary."
    )
)
def status() -> None:
    try:
        repo = state.repo()
        cfg = state.config(repo)
    except GitexError as exc:
        raise _fail(exc) from exc
    yes, no = t("evet", "yes"), t("hayır", "no")
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold")
    table.add_column()
    table.add_row(t("Depo", "Repository"), str(repo.root))
    path = index_path(repo.root)
    if path.exists():
        with Database(path) as db:
            table.add_row(t("İndeks", "Index"), str(path))
            table.add_row("Commit", str(db.count("commits")))
            table.add_row(t("Son indeks", "Last indexed"), db.get_meta("last_indexed_at") or "-")
            head = db.get_meta("last_indexed_head") or ""
            table.add_row(t("İndekslenen HEAD", "Indexed HEAD"), head[:7] or "-")
            table.add_row(
                t("Güncel mi", "Up to date"), yes if not is_stale(repo, db) else f"[yellow]{no}[/]"
            )
            table.add_row("MR / issue", f"{db.count('merge_requests')} / {db.count('issues')}")
            table.add_row(
                t("Son GitLab senkronu", "Last GitLab sync"), db.get_meta("gitlab_last_sync") or "-"
            )
    else:
        table.add_row(
            t("İndeks", "Index"), t("[yellow]yok[/] (gitex index)", "[yellow]none[/] (gitex index)")
        )
    table.add_row("LLM", f"{cfg.llm.provider} / {cfg.llm.model} ({cfg.llm.mode})")
    if cfg.llm.base_url and cfg.llm.provider == "openai_compat":
        table.add_row(t("LLM uç noktası", "LLM endpoint"), cfg.llm.base_url)
    table.add_row(
        t("LLM API anahtarı", "LLM API key"),
        t("tanımlı", "set") if cfg.llm.api_key() else t("tanımsız", "not set"),
    )
    table.add_row(
        t("Diff gönderimi", "Send diffs"),
        t("açık", "on") if cfg.privacy.send_diffs else t("kapalı", "off"),
    )
    if cfg.gitlab.enabled:
        token = (
            t("tanımlı", "set")
            if cfg.gitlab.token()
            else t("[yellow]tanımsız[/]", "[yellow]not set[/]")
        )
        table.add_row("GitLab", f"{cfg.gitlab.url} / {cfg.gitlab.project} (token {token})")
    else:
        table.add_row(
            "GitLab", t("ayarlanmamış (yalnızca yerel git)", "not configured (local git only)")
        )
    table.add_row(
        t("Ayarlar", "Settings"), ", ".join(cfg.sources) or t("varsayılanlar", "defaults")
    )
    console.print(table)


# ---------------------------------------------------------------------- soru-cevap


class ContextPrinter:
    """`--show-context`: LLM'e gidecek mesajları göndermeden önce ekrana basar."""

    def __init__(self, inner: LLMProvider, out: Console) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model
        self.out = out
        self._shown: set[int] = set()

    def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        for m in messages:
            if id(m) in self._shown:
                continue
            self._shown.add(id(m))
            title = m.role + (f" ({m.name})" if m.name else "")
            body = m.content
            if m.tool_calls:
                body += "\n" + "\n".join(
                    f"→ {tc.name}({json.dumps(tc.arguments, ensure_ascii=False)})"
                    for tc in m.tool_calls
                )
            self.out.print(
                Panel(
                    Text(body or t("(boş)", "(empty)")),
                    title=title,
                    title_align="left",
                    border_style="dim",
                )
            )
        if tools:
            self.out.print(
                t("[dim]araçlar: {x}[/]", "[dim]tools: {x}[/]", x=", ".join(s.name for s in tools))
            )
        return self.inner.chat(messages, tools)


def _make_provider(cfg: Config) -> LLMProvider:
    return make_provider(cfg.llm)


# Testler sahte sağlayıcı enjekte etmek için bunu değiştirir.
provider_factory: Callable[[Config], LLMProvider] = _make_provider


def _thinking() -> str:
    return t("Model düşünüyor…", "Thinking…")


def _event_printer(quiet: bool, activity: Activity | None = None) -> EventFn:
    def on_event(kind: str, data: dict[str, Any]) -> None:
        if activity is not None:
            if kind in ("llm_call", "tool_result"):
                activity.update(_thinking())
            elif kind == "tool_call":
                activity.update(t("Geçmiş taranıyor…", "Searching history…"), detail=data["name"])
            elif kind == "citation_retry":
                activity.update(t("Kaynaklar düzeltiliyor…", "Fixing sources…"))
        if quiet:
            return
        if kind == "tool_call":
            args = ", ".join(f"{k}={v!r}" for k, v in data["arguments"].items())
            err_console.print(f"[dim]  → {data['name']}({args})[/]", highlight=False)
        elif kind == "tool_result" and not data["ok"]:
            err_console.print(
                t(
                    "[yellow]    ✗ {n} hata döndü[/]",
                    "[yellow]    ✗ {n} returned an error[/]",
                    n=data["name"],
                )
            )
        elif kind == "plan":
            err_console.print(
                t(
                    "[dim]  plan: kelimeler={k} kod={c} yol={p}[/]",
                    "[dim]  plan: keywords={k} code={c} path={p}[/]",
                    k=data["keywords"],
                    c=data["code_terms"],
                    p=data["path"],
                ),
                highlight=False,
            )
        elif kind == "citation_retry":
            refs = data["shas"] + [f"!{m}" for m in data["mrs"]]
            err_console.print(
                t(
                    "[yellow]  ⚠ doğrulanamayan referans ({r}); düzeltme isteniyor[/]",
                    "[yellow]  ⚠ unverifiable reference ({r}); asking for a correction[/]",
                    r=", ".join(refs),
                )
            )

    return on_event


def _open_session(*, show_context: bool, quiet: bool, activity: Activity | None = None) -> Session:
    if activity is not None:
        activity.update(t("Depo ve model hazırlanıyor…", "Preparing the repository and model…"))
    repo = state.repo()
    cfg = state.config(repo)
    if repo.head() is None and not repo.all_commit_shas():
        raise GitexError(
            t("Depo boş: henüz hiç commit yok.", "The repository is empty: no commits yet.")
        )

    def progress(done: int, total: int) -> None:
        if activity is not None:
            activity.update(
                t("İndeks güncelleniyor…", "Updating the index…"), detail=f"{done}/{total} commit"
            )
        if not quiet and done == total:
            err_console.print(
                t(
                    "[dim]İndeks güncellendi: {n} yeni commit[/]",
                    "[dim]Index updated: {n} new commits[/]",
                    n=total,
                )
            )

    session = Session.open(repo, cfg, provider_factory=provider_factory, progress=progress)
    if show_context:
        session.provider = ContextPrinter(session.provider, err_console)
    return session


def _print_result(result: AgentResult, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return
    console.print(Markdown(result.answer))
    if result.unverified:
        err_console.print(
            t(
                "[yellow]⚠ Doğrulanamayan referanslar: {r}[/]",
                "[yellow]⚠ Unverified references: {r}[/]",
                r=", ".join(result.unverified),
            )
        )
    else:
        err_console.print(
            t(
                "[dim]✓ {n} kaynak doğrulandı ({m}, {model})[/]",
                "[dim]✓ {n} sources verified ({m}, {model})[/]",
                n=len(result.sources),
                m=result.mode,
                model=result.model,
            )
        )


def _parse_cli_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise GitexError(
            t("--{n} için geçersiz tarih: {v}", "Invalid date for --{n}: {v}", n=name, v=value),
            hint=t("Biçim: YYYY-AA-GG", "Format: YYYY-MM-DD"),
        ) from exc


def _check_mode(mode: str | None) -> None:
    if mode not in (None, "agent", "simple"):
        raise GitexError(
            t("Geçersiz mod: {m}", "Invalid mode: {m}", m=mode),
            hint=t("agent ya da simple", "agent or simple"),
        )


def _answer(
    question: str,
    *,
    mode: str | None,
    path: str | None = None,
    since: str | None = None,
    until: str | None = None,
    show_context: bool = False,
    as_json: bool = False,
    quiet: bool = False,
) -> None:
    _check_mode(mode)
    since_d, until_d = _parse_cli_date(since, "since"), _parse_cli_date(until, "until")
    # Gösterge ilk anda açılır: model kütüphanesinin yüklenmesi bile birkaç saniye sürebilir.
    with Activity(t("Hazırlanıyor…", "Getting ready…")) as activity:
        session = _open_session(
            show_context=show_context, quiet=quiet or as_json, activity=activity
        )
        try:
            result = session.ask(
                question,
                mode=mode,  # type: ignore[arg-type]
                path=path,
                since=since_d,
                until=until_d,
                on_event=_event_printer(quiet or as_json, activity),
            )
        finally:
            session.close()
    _print_result(result, as_json=as_json)


_MODE_OPT = typer.Option(
    None,
    "--mode",
    "-m",
    help=t("agent (araç kullanır) ya da simple.", "agent (uses tools) or simple."),
)
_SHOW_OPT = typer.Option(
    False,
    "--show-context",
    help=t(
        "LLM'e gönderilecek bağlamı göndermeden önce bas.",
        "Print what will be sent to the LLM before sending it.",
    ),
)
_JSON_OPT = typer.Option(
    False, "--json", help=t("Makine-okunur çıktı.", "Machine-readable output.")
)
_QUIET_OPT = typer.Option(
    False, "--quiet", "-q", help=t("Araç çağrılarını gösterme.", "Don't show tool calls.")
)


@app.command(
    help=t(
        "Repo geçmişi hakkında soru sor (ne, ne zaman, kim, neden).",
        "Ask about the repository's history (what, when, who, why).",
    )
)
def ask(
    question: str = typer.Argument(
        ..., help=t("Doğal dilde soru.", "Your question in plain language.")
    ),
    path: str | None = typer.Option(
        None, "--path", "-p", help=t("Aramayı bir yola daralt.", "Limit the search to a path.")
    ),
    since: str | None = typer.Option(
        None, "--since", help=t("Başlangıç tarihi (YYYY-AA-GG).", "Start date (YYYY-MM-DD).")
    ),
    until: str | None = typer.Option(
        None, "--until", help=t("Bitiş tarihi (YYYY-AA-GG).", "End date (YYYY-MM-DD).")
    ),
    mode: str | None = _MODE_OPT,
    show_context: bool = _SHOW_OPT,
    as_json: bool = _JSON_OPT,
    quiet: bool = _QUIET_OPT,
) -> None:
    try:
        _answer(
            question,
            mode=mode,
            path=path,
            since=since,
            until=until,
            show_context=show_context,
            as_json=as_json,
            quiet=quiet,
        )
    except GitexError as exc:
        raise _fail(exc) from exc


def _chat_help() -> str:
    return t(
        "[bold]gitex chat[/] — takip soruları önceki bağlamı korur.\n"
        "Komutlar: [bold]/yeni[/] konuşmayı sıfırla · [bold]/mod agent|simple[/] · "
        "[bold]/json[/] son cevabın kaynakları · [bold]/çık[/] (ya da Ctrl+D)",
        "[bold]gitex chat[/] — follow-up questions keep the context.\n"
        "Commands: [bold]/new[/] reset the conversation · [bold]/mode agent|simple[/] · "
        "[bold]/json[/] sources of the last answer · [bold]/exit[/] (or Ctrl+D)",
    )


@app.command(
    help=t(
        "Etkileşimli oturum; takip soruları bağlamı korur.",
        "Interactive session; follow-up questions keep the context.",
    )
)
def chat(
    mode: str | None = _MODE_OPT,
    show_context: bool = _SHOW_OPT,
    quiet: bool = _QUIET_OPT,
) -> None:
    try:
        _check_mode(mode)
        with Activity(t("Hazırlanıyor…", "Getting ready…")) as activity:
            session = _open_session(show_context=show_context, quiet=quiet, activity=activity)
    except GitexError as exc:
        raise _fail(exc) from exc
    current_mode = mode or session.config.llm.mode
    last: AgentResult | None = None
    console.print(_chat_help())
    try:
        while True:
            try:
                line = console.input("[bold cyan]›[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if not line:
                continue
            low = line.lower()
            if low in ("/çık", "/cik", "/exit", "/quit", "/q"):
                break
            if low in ("/yeni", "/new"):
                session.reset()
                console.print(t("[dim]Konuşma sıfırlandı.[/]", "[dim]Conversation reset.[/]"))
                continue
            if low.startswith(("/mode", "/mod")):
                choice = low.removeprefix("/mode").removeprefix("/mod").strip()
                if choice in ("agent", "simple"):
                    current_mode = choice
                    console.print(t("[dim]Mod: {m}[/]", "[dim]Mode: {m}[/]", m=current_mode))
                else:
                    console.print(
                        t(
                            "[yellow]Kullanım: /mod agent|simple[/]",
                            "[yellow]Usage: /mode agent|simple[/]",
                        )
                    )
                continue
            if low == "/json":
                if last is not None:
                    typer.echo(json.dumps(last.to_dict(), ensure_ascii=False, indent=2))
                continue
            if line.startswith("/"):
                console.print(t("[yellow]Bilinmeyen komut.[/]", "[yellow]Unknown command.[/]"))
                continue
            try:
                with Activity(_thinking()) as activity:
                    last = session.ask(
                        line,
                        mode=current_mode,  # type: ignore[arg-type]
                        keep_history=True,
                        on_event=_event_printer(quiet, activity),
                    )
            except GitexError as exc:
                err_console.print(t("[bold red]Hata:[/] {e}", "[bold red]Error:[/] {e}", e=exc))
                if exc.hint:
                    err_console.print(t("[dim]İpucu: {h}[/]", "[dim]Hint: {h}[/]", h=exc.hint))
                continue
            _print_result(last, as_json=False)
    finally:
        session.close()


@app.command(help=t("Bir commit'i ya da MR'ı açıklar.", "Explain a commit or a merge request."))
def explain(
    target: str = typer.Argument(
        ..., help=t("Commit SHA'sı ya da !MR numarası.", "Commit SHA or !MR number.")
    ),
    mode: str | None = _MODE_OPT,
    show_context: bool = _SHOW_OPT,
    as_json: bool = _JSON_OPT,
    quiet: bool = _QUIET_OPT,
) -> None:
    try:
        repo = state.repo()
        if target.startswith("!"):
            iid = target[1:]
            if not iid.isdigit():
                raise GitexError(t("Geçersiz MR numarası: {x}", "Invalid MR number: {x}", x=target))
            if not state.config(repo).gitlab.enabled:
                raise GitexError(
                    t(
                        "MR açıklamak için GitLab ayarlanmalı.",
                        "GitLab must be configured to explain an MR.",
                    ),
                    hint=t(
                        "Kurulum: gitex setup, ardından gitex sync",
                        "Set it up: gitex setup, then gitex sync",
                    ),
                )
            question = t(
                "!{i} numaralı merge request'i açıkla: ne değiştirdi, neden yapıldı, kim yaptı, "
                "hangi commit'leri içeriyor ve review'da ne tartışıldı?",
                "Explain merge request !{i}: what it changed, why it was made, who made it, "
                "which commits it contains and what was discussed in review.",
                i=iid,
            )
        else:
            sha = repo.resolve(target)
            if sha is None:
                raise GitexError(t("Commit bulunamadı: {x}", "Commit not found: {x}", x=target))
            question = t(
                "{s} commit'ini açıkla: ne yaptı, neden yapıldı, kim ne zaman yaptı, "
                "hangi MR ile geldi ve review'da ne tartışıldı?",
                "Explain commit {s}: what it did, why, who made it and when, "
                "which MR brought it in and what was discussed in review.",
                s=sha[:12],
            )
        _answer(question, mode=mode, show_context=show_context, as_json=as_json, quiet=quiet)
    except GitexError as exc:
        raise _fail(exc) from exc


_KIND_CODE = {"eklendi": "added", "kaldırıldı": "removed", "değişti": "changed"}


def _kind_label(hit: PickaxeHit) -> str:
    code = _KIND_CODE.get(hit.kind, "changed")
    return {
        "added": t("eklendi", "added"),
        "removed": t("kaldırıldı", "removed"),
        "changed": t("değişti", "changed"),
    }[code]


@app.command(
    help=t(
        "Bir ifadenin kodda ne zaman eklendiğini/kaldırıldığını gösterir (pickaxe, LLM gerekmez).",
        "Show when an expression was added to or removed from the code (pickaxe, no LLM needed).",
    )
)
def when(
    expression: str = typer.Argument(
        ..., help=t("Kodda aranacak ifade.", "Expression to search for in the code.")
    ),
    path: str | None = typer.Option(
        None, "--path", "-p", help=t("Yola daralt.", "Limit to a path.")
    ),
    regex: bool = typer.Option(
        False,
        "--regex",
        "-E",
        help=t(
            "İfadeyi regex olarak ara (git log -G).",
            "Treat the expression as a regex (git log -G).",
        ),
    ),
    limit: int = typer.Option(
        30,
        "--limit",
        "-n",
        min=1,
        max=500,
        help=t("En fazla sonuç sayısı.", "Maximum number of results."),
    ),
    as_json: bool = _JSON_OPT,
) -> None:
    try:
        repo = state.repo()
        with Activity(
            t("Geçmiş taranıyor…", "Searching history…"), enabled=not as_json
        ) as activity:
            activity.update(detail=expression)
            hits = repo.pickaxe(expression, regex=regex, path=path, limit=limit)
            mr_map: dict[str, list[str]] = {}
            cfg = state.config(repo)
            if cfg.gitlab.enabled and index_path(repo.root).exists():
                with Database(index_path(repo.root)) as db:
                    search = FTSSearch(db)
                    for h in hits:
                        mr_map[h.commit.sha] = [
                            f"!{m.iid}" for m in search.mrs_for_commit(h.commit.sha)
                        ]
    except GitexError as exc:
        raise _fail(exc) from exc
    if as_json:
        payload = [
            {
                "sha": h.commit.sha,
                "date": h.commit.author_date.date().isoformat(),
                "author": h.commit.author_name,
                "subject": h.commit.subject,
                "kind": _KIND_CODE.get(h.kind, "changed"),
                "added": h.added,
                "removed": h.removed,
                "mrs": mr_map.get(h.commit.sha, []),
            }
            for h in hits
        ]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not hits:
        console.print(
            t(
                "'{e}' için ekleme/kaldırma yapan commit bulunamadı.",
                "No commit added or removed '{e}'.",
                e=expression,
            )
        )
        raise typer.Exit(code=0)
    table = Table(title=t("'{e}' geçmişi", "History of '{e}'", e=expression), show_lines=False)
    for col in (
        t("Tarih", "Date"),
        "SHA",
        t("Yazar", "Author"),
        t("Ne oldu", "What happened"),
        t("Konu", "Subject"),
        "MR",
    ):
        table.add_column(col)
    for h in reversed(hits):
        c = h.commit
        table.add_row(
            c.author_date.date().isoformat(),
            c.short_sha,
            c.author_name,
            f"{_kind_label(h)} (+{h.added}/-{h.removed})",
            c.subject,
            ", ".join(mr_map.get(c.sha, [])),
        )
    console.print(table)
    first = hits[-1].commit
    console.print(
        t("İlk ortaya çıkış:", "First appeared:")
        + f" [bold]{first.short_sha}[/] {first.author_date.date()} {first.author_name} — {first.subject}"
    )
    last = hits[0]
    if _KIND_CODE.get(last.kind) == "removed":
        console.print(
            t(
                "Son durum: [bold]{s}[/] {d} ile kaldırıldı.",
                "Current state: removed in [bold]{s}[/] on {d}.",
                s=last.commit.short_sha,
                d=last.commit.author_date.date(),
            )
        )


@app.command(
    "file",
    help=t(
        "Bir dosyanın özet evrimi: kimler, ne zaman, ne sıklıkla, yeniden adlandırmalar.",
        "How a file evolved: who, when, how often, renames.",
    ),
)
def file_cmd(
    path: str = typer.Argument(..., help=t("Dosya yolu.", "File path.")),
    llm: bool = typer.Option(
        False,
        "--llm",
        help=t(
            "Ek olarak LLM ile anlatımlı özet üret.", "Also write a narrative summary with the LLM."
        ),
    ),
    mode: str | None = _MODE_OPT,
    as_json: bool = _JSON_OPT,
) -> None:
    try:
        repo = state.repo()
        with Activity(
            t("Dosya geçmişi okunuyor…", "Reading the file's history…"), enabled=not as_json
        ):
            commits = repo.file_history(path)
        if not commits:
            raise GitexError(
                t("'{p}' için geçmiş bulunamadı.", "No history found for '{p}'.", p=path),
                hint=t(
                    "Yolu depo köküne göre verin (ör. src/app.py).",
                    "Give the path relative to the repository root (e.g. src/app.py).",
                ),
            )
        summary = summarize_file(path, commits)
        if as_json and not llm:
            typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
            return
        if not as_json:
            _print_file_summary(summary)
        if llm:
            _answer(
                t(
                    "`{p}` dosyasının evrimini özetle: hangi önemli değişiklikler oldu, kimler yaptı, "
                    "neden bu kadar değişti?",
                    "Summarize how `{p}` evolved: what the important changes were, who made them "
                    "and why it changed so much.",
                    p=path,
                ),
                mode=mode,
                path=path,
                as_json=as_json,
            )
    except GitexError as exc:
        raise _fail(exc) from exc


def summarize_file(path: str, commits: list[Commit]) -> dict[str, Any]:
    authors = Counter(c.author_name for c in commits)
    added = sum((f.additions or 0) for c in commits for f in c.files[:1])
    deleted = sum((f.deletions or 0) for c in commits for f in c.files[:1])
    renames = [
        {"sha": c.sha, "date": c.author_date.date().isoformat(), "from": f.old_path, "to": f.path}
        for c in commits
        for f in c.files[:1]
        if f.status == "R"
    ]
    months = Counter(c.author_date.strftime("%Y-%m") for c in commits)
    return {
        "path": path,
        "commits": len(commits),
        "first": {"sha": commits[-1].sha, "date": commits[-1].author_date.date().isoformat(),
                  "author": commits[-1].author_name, "subject": commits[-1].subject},
        "last": {"sha": commits[0].sha, "date": commits[0].author_date.date().isoformat(),
                 "author": commits[0].author_name, "subject": commits[0].subject},
        "authors": dict(authors.most_common()),
        "lines_added": added,
        "lines_deleted": deleted,
        "renames": renames,
        "by_month": dict(sorted(months.items())),
        "recent": [
            {"sha": c.sha, "date": c.author_date.date().isoformat(), "author": c.author_name,
             "subject": c.subject}
            for c in commits[:10]
        ],
    }  # fmt: skip


def _print_file_summary(s: dict[str, Any]) -> None:
    console.print(
        t(
            "[bold]{p}[/] — {n} commit, +{a}/-{d} satır",
            "[bold]{p}[/] — {n} commits, +{a}/-{d} lines",
            p=s["path"],
            n=s["commits"],
            a=s["lines_added"],
            d=s["lines_deleted"],
        )
    )
    f, last = s["first"], s["last"]
    console.print(
        t("İlk:", "First:") + f" {f['sha'][:7]} {f['date']} {f['author']} — {f['subject']}"
    )
    console.print(
        t("Son:", "Last:")
        + f" {last['sha'][:7]} {last['date']} {last['author']} — {last['subject']}"
    )
    console.print(
        t("Yazarlar: ", "Authors: ") + ", ".join(f"{a} ({n})" for a, n in s["authors"].items())
    )
    for r in s["renames"]:
        console.print(
            t("Yeniden adlandırma:", "Renamed:")
            + f" {r['from']} → {r['to']} ({r['sha'][:7]}, {r['date']})"
        )
    peak = max(s["by_month"].values())
    console.print(t("Aylık aktivite:", "Monthly activity:"))
    for month, n in s["by_month"].items():
        console.print(f"  {month} {'█' * max(1, round(20 * n / peak))} {n}")
    table = Table(title=t("Son değişiklikler", "Recent changes"), show_header=True)
    for col in (t("Tarih", "Date"), "SHA", t("Yazar", "Author"), t("Konu", "Subject")):
        table.add_column(col)
    for c in s["recent"]:
        table.add_row(c["date"], c["sha"][:7], c["author"], c["subject"])
    console.print(table)


def run() -> None:  # pragma: no cover - giriş noktası
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure:
                reconfigure(encoding="utf-8")
    try:
        app()
    except KeyboardInterrupt:
        err_console.print(t("[dim]İptal edildi.[/]", "[dim]Cancelled.[/]"))
        sys.exit(130)
