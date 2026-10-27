"""gitex komut satırı arayüzü."""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
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
from gitex.config import (
    GITLAB_TOKEN_ENV,
    SAMPLE_CONFIG,
    Config,
    index_path,
    load_config,
    repo_dir,
)
from gitex.errors import GitexError
from gitex.git.models import Commit
from gitex.git.reader import GitRepo
from gitex.gitlab.client import GitLabClient
from gitex.gitlab.sync import sync_gitlab
from gitex.index.db import Database
from gitex.index.indexer import index_repo, is_stale, open_index
from gitex.index.search import FTSSearch
from gitex.llm.base import LLMProvider, LLMResponse, Message, ToolSpec
from gitex.llm.factory import make_provider
from gitex.session import Session

app = typer.Typer(
    name="gitex",
    help="Git geçmişini doğal dilde sorgula: ne değişti, ne zaman, kim, neden.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

console = Console()
err_console = Console(stderr=True)


@dataclass
class State:
    repo_path: Path = Path(".")

    def repo(self) -> GitRepo:
        return GitRepo(self.repo_path)

    def config(self, repo: GitRepo) -> Config:
        return load_config(repo.root)


state = State()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"gitex {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    repo: Path = typer.Option(
        Path("."), "--repo", "-C", help="Git deposunun yolu (varsayılan: bulunulan dizin)."
    ),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Sürümü göster."
    ),
) -> None:
    """gitex ana komutu."""
    state.repo_path = repo


def _fail(exc: GitexError) -> typer.Exit:
    err_console.print(f"[bold red]Hata:[/] {exc}")
    if exc.hint:
        err_console.print(f"[dim]İpucu: {exc.hint}[/]")
    return typer.Exit(code=1)


# ---------------------------------------------------------------------- init


@app.command()
def init() -> None:
    """`.gitex/` oluşturur, örnek config yazar ve `.gitignore`'a ekler."""
    try:
        repo = state.repo()
    except GitexError as exc:
        raise _fail(exc) from exc
    target = repo_dir(repo.root)
    target.mkdir(exist_ok=True)
    cfg = target / "config.toml"
    if cfg.exists():
        console.print(f"[yellow]Config zaten var:[/] {cfg}")
    else:
        cfg.write_text(SAMPLE_CONFIG, encoding="utf-8")
        console.print(f"[green]Örnek config yazıldı:[/] {cfg}")
    gitignore = repo.root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if not any(line.strip() in (".gitex", ".gitex/") for line in existing.splitlines()):
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}.gitex/\n")
        console.print("[green].gitignore güncellendi[/] (.gitex/)")
    console.print("Sonraki adım: [bold]gitex index[/]")


# ---------------------------------------------------------------------- index


def run_index(repo: GitRepo, db: Database, *, quiet: bool = False) -> None:
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    with Progress(
        TextColumn("[bold blue]İndeksleniyor"),
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
            f"[green]İndeks hazır:[/] +{stats.added} yeni, -{stats.removed} kaldırılan, "
            f"toplam {stats.total} commit ({stats.elapsed:.1f} sn)"
        )


@app.command()
def index(
    rebuild: bool = typer.Option(False, "--rebuild", help="İndeksi sıfırdan kur."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="İlerleme gösterme."),
) -> None:
    """Yerel git geçmişini artımlı olarak indeksler."""
    try:
        repo = state.repo()
        with open_index(repo, rebuild=rebuild) as db:
            run_index(repo, db, quiet=quiet)
    except GitexError as exc:
        raise _fail(exc) from exc


# ---------------------------------------------------------------------- sync


def make_gitlab_client(cfg: Config) -> GitLabClient:
    return GitLabClient(cfg.gitlab, cfg.gitlab.token())


@app.command()
def sync(
    full: bool = typer.Option(False, "--full", help="İmleci yok say, tüm MR'ları yeniden çek."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="İlerleme gösterme."),
) -> None:
    """GitLab MR / yorum / issue senkronizasyonu (gerekirse önce yerel indeksi günceller)."""
    try:
        repo = state.repo()
        cfg = state.config(repo)
        if not cfg.gitlab.enabled:
            raise GitexError(
                "GitLab ayarlanmamış.",
                hint='`.gitex/config.toml` içinde [gitlab] project = "grup/proje" ayarlayın.',
            )
        if not cfg.gitlab.token():
            err_console.print(
                f"[yellow]Uyarı:[/] {GITLAB_TOKEN_ENV} tanımlı değil; yalnızca herkese açık projeler okunabilir."
            )
        with open_index(repo) as db:
            if is_stale(repo, db):
                run_index(repo, db, quiet=quiet)
            client = make_gitlab_client(cfg)

            def _progress(n: int) -> None:
                if not quiet and n % 50 == 0:
                    err_console.print(f"[dim]  {n} MR senkronlandı…[/]")

            stats = sync_gitlab(client, db, full=full, progress=_progress)
    except GitexError as exc:
        raise _fail(exc) from exc
    if not quiet:
        kind = "tam" if stats.full else "artımlı"
        err_console.print(
            f"[green]GitLab senkronu ({kind}):[/] {stats.synced} MR güncellendi, {stats.removed} kaldırıldı, "
            f"{stats.notes} yorum, {stats.issues} issue bağı ({stats.elapsed:.1f} sn)"
        )


# ---------------------------------------------------------------------- status


@app.command()
def status() -> None:
    """İndeks durumu, son senkron ve config özeti."""
    try:
        repo = state.repo()
        cfg = state.config(repo)
    except GitexError as exc:
        raise _fail(exc) from exc
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Repo", str(repo.root))
    path = index_path(repo.root)
    if path.exists():
        with Database(path) as db:
            table.add_row("İndeks", str(path))
            table.add_row("Commit", str(db.count("commits")))
            table.add_row("Son indeks", db.get_meta("last_indexed_at") or "-")
            head = db.get_meta("last_indexed_head") or ""
            table.add_row("İndekslenen HEAD", head[:7] or "-")
            table.add_row("Güncel mi", "evet" if not is_stale(repo, db) else "[yellow]hayır[/]")
            table.add_row("MR / issue", f"{db.count('merge_requests')} / {db.count('issues')}")
            table.add_row("Son GitLab senkronu", db.get_meta("gitlab_last_sync") or "-")
    else:
        table.add_row("İndeks", "[yellow]yok[/] (gitex index)")
    table.add_row("LLM", f"{cfg.llm.provider} / {cfg.llm.model} ({cfg.llm.mode})")
    if cfg.llm.base_url and cfg.llm.provider == "openai_compat":
        table.add_row("LLM uç noktası", cfg.llm.base_url)
    table.add_row(
        "LLM API anahtarı",
        f"{cfg.llm.api_key_env}: " + ("tanımlı" if cfg.llm.api_key() else "tanımsız"),
    )
    table.add_row("Diff gönderimi", "açık" if cfg.privacy.send_diffs else "kapalı")
    if cfg.gitlab.enabled:
        token = "tanımlı" if cfg.gitlab.token() else "[yellow]tanımsız[/]"
        table.add_row("GitLab", f"{cfg.gitlab.url} / {cfg.gitlab.project} (token {token})")
    else:
        table.add_row("GitLab", "ayarlanmamış (yalnızca yerel git)")
    table.add_row("Config", ", ".join(cfg.sources) or "varsayılanlar")
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
                Panel(Text(body or "(boş)"), title=title, title_align="left", border_style="dim")
            )
        if tools:
            self.out.print(f"[dim]araçlar: {', '.join(t.name for t in tools)}[/]")
        return self.inner.chat(messages, tools)


def _make_provider(cfg: Config) -> LLMProvider:
    return make_provider(cfg.llm)


# Testler sahte sağlayıcı enjekte etmek için bunu değiştirir.
provider_factory: Callable[[Config], LLMProvider] = _make_provider


def _event_printer(quiet: bool) -> EventFn:
    def on_event(kind: str, data: dict[str, Any]) -> None:
        if quiet:
            return
        if kind == "tool_call":
            args = ", ".join(f"{k}={v!r}" for k, v in data["arguments"].items())
            err_console.print(f"[dim]  → {data['name']}({args})[/]", highlight=False)
        elif kind == "tool_result" and not data["ok"]:
            err_console.print(f"[yellow]    ✗ {data['name']} hata döndü[/]")
        elif kind == "plan":
            err_console.print(
                f"[dim]  plan: kelimeler={data['keywords']} kod={data['code_terms']} yol={data['path']}[/]",
                highlight=False,
            )
        elif kind == "citation_retry":
            refs = data["shas"] + [f"!{m}" for m in data["mrs"]]
            err_console.print(
                f"[yellow]  ⚠ doğrulanamayan referans ({', '.join(refs)}); düzeltme isteniyor[/]"
            )

    return on_event


def _open_session(*, show_context: bool, quiet: bool) -> Session:
    repo = state.repo()
    cfg = state.config(repo)
    if repo.head() is None and not repo.all_commit_shas():
        raise GitexError("Depo boş: henüz hiç commit yok.")

    def progress(done: int, total: int) -> None:
        if not quiet and done == total:
            err_console.print(f"[dim]İndeks güncellendi: {total} yeni commit[/]")

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
            f"[yellow]⚠ Doğrulanamayan referanslar: {', '.join(result.unverified)}[/]"
        )
    else:
        err_console.print(
            f"[dim]✓ {len(result.sources)} kaynak doğrulandı ({result.mode}, {result.model})[/]"
        )


def _parse_cli_date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise GitexError(
            f"--{name} için geçersiz tarih: {value}", hint="Biçim: YYYY-AA-GG"
        ) from exc


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
    if mode not in (None, "agent", "simple"):
        raise GitexError(f"Geçersiz mod: {mode}", hint="agent ya da simple")
    since_d, until_d = _parse_cli_date(since, "since"), _parse_cli_date(until, "until")
    session = _open_session(show_context=show_context, quiet=quiet or as_json)
    try:
        result = session.ask(
            question,
            mode=mode,  # type: ignore[arg-type]
            path=path,
            since=since_d,
            until=until_d,
            on_event=_event_printer(quiet or as_json),
        )
    finally:
        session.close()
    _print_result(result, as_json=as_json)


_MODE_OPT = typer.Option(None, "--mode", "-m", help="agent (tool-use) ya da simple.")
_SHOW_OPT = typer.Option(
    False, "--show-context", help="LLM'e gönderilen bağlamı göndermeden önce bas."
)
_JSON_OPT = typer.Option(False, "--json", help="Makine-okunur çıktı (cevap + kaynaklar).")
_QUIET_OPT = typer.Option(False, "--quiet", "-q", help="Araç çağrılarını gösterme.")


@app.command()
def ask(
    question: str = typer.Argument(..., help="Doğal dilde soru."),
    path: str | None = typer.Option(None, "--path", "-p", help="Aramayı bir yola daralt."),
    since: str | None = typer.Option(None, "--since", help="Başlangıç tarihi (YYYY-AA-GG)."),
    until: str | None = typer.Option(None, "--until", help="Bitiş tarihi (YYYY-AA-GG)."),
    mode: str | None = _MODE_OPT,
    show_context: bool = _SHOW_OPT,
    as_json: bool = _JSON_OPT,
    quiet: bool = _QUIET_OPT,
) -> None:
    """Repo geçmişi hakkında soru sor (ne, ne zaman, kim, neden)."""
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


_CHAT_HELP = """\
[bold]gitex chat[/] — takip soruları önceki bağlamı korur.
Komutlar: [bold]/yeni[/] konuşmayı sıfırla · [bold]/mod agent|simple[/] · [bold]/json[/] son cevabın
kaynakları · [bold]/çık[/] (ya da Ctrl+D)"""


@app.command()
def chat(
    mode: str | None = _MODE_OPT,
    show_context: bool = _SHOW_OPT,
    quiet: bool = _QUIET_OPT,
) -> None:
    """Etkileşimli oturum; takip soruları bağlamı korur."""
    try:
        if mode not in (None, "agent", "simple"):
            raise GitexError(f"Geçersiz mod: {mode}", hint="agent ya da simple")
        session = _open_session(show_context=show_context, quiet=quiet)
    except GitexError as exc:
        raise _fail(exc) from exc
    current_mode = mode or session.config.llm.mode
    last: AgentResult | None = None
    console.print(_CHAT_HELP)
    try:
        while True:
            try:
                line = console.input("[bold cyan]›[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if not line:
                continue
            if line.lower() in ("/çık", "/cik", "/exit", "/quit", "/q"):
                break
            if line == "/yeni":
                session.reset()
                console.print("[dim]Konuşma sıfırlandı.[/]")
                continue
            if line.startswith("/mod"):
                choice = line.removeprefix("/mod").strip()
                if choice in ("agent", "simple"):
                    current_mode = choice
                    console.print(f"[dim]Mod: {current_mode}[/]")
                else:
                    console.print("[yellow]Kullanım: /mod agent|simple[/]")
                continue
            if line == "/json":
                if last is not None:
                    typer.echo(json.dumps(last.to_dict(), ensure_ascii=False, indent=2))
                continue
            if line.startswith("/"):
                console.print("[yellow]Bilinmeyen komut.[/]")
                continue
            try:
                last = session.ask(
                    line,
                    mode=current_mode,  # type: ignore[arg-type]
                    keep_history=True,
                    on_event=_event_printer(quiet),
                )
            except GitexError as exc:
                err_console.print(f"[bold red]Hata:[/] {exc}")
                if exc.hint:
                    err_console.print(f"[dim]İpucu: {exc.hint}[/]")
                continue
            _print_result(last, as_json=False)
    finally:
        session.close()


@app.command()
def explain(
    target: str = typer.Argument(..., help="Commit SHA'sı ya da !MR numarası."),
    mode: str | None = _MODE_OPT,
    show_context: bool = _SHOW_OPT,
    as_json: bool = _JSON_OPT,
    quiet: bool = _QUIET_OPT,
) -> None:
    """Bir commit'i ya da MR'ı açıklar."""
    try:
        repo = state.repo()
        if target.startswith("!"):
            iid = target[1:]
            if not iid.isdigit():
                raise GitexError(f"Geçersiz MR numarası: {target}")
            if not state.config(repo).gitlab.enabled:
                raise GitexError(
                    "MR açıklamak için GitLab ayarlanmalı.",
                    hint="`.gitex/config.toml` içinde [gitlab] project ayarlayıp `gitex sync` çalıştırın.",
                )
            question = (
                f"!{iid} numaralı merge request'i açıkla: ne değiştirdi, neden yapıldı, kim yaptı, "
                "hangi commit'leri içeriyor ve review'da ne tartışıldı?"
            )
        else:
            sha = repo.resolve(target)
            if sha is None:
                raise GitexError(f"Commit bulunamadı: {target}")
            question = (
                f"{sha[:12]} commit'ini açıkla: ne yaptı, neden yapıldı, kim ne zaman yaptı, "
                "hangi MR ile geldi ve review'da ne tartışıldı?"
            )
        _answer(question, mode=mode, show_context=show_context, as_json=as_json, quiet=quiet)
    except GitexError as exc:
        raise _fail(exc) from exc


@app.command()
def when(
    expression: str = typer.Argument(..., help="Kodda aranacak ifade."),
    path: str | None = typer.Option(None, "--path", "-p", help="Yola daralt."),
    regex: bool = typer.Option(
        False, "--regex", "-E", help="İfadeyi regex olarak ara (git log -G)."
    ),
    limit: int = typer.Option(30, "--limit", "-n", min=1, max=500),
    as_json: bool = _JSON_OPT,
) -> None:
    """Bir ifadenin kodda ne zaman eklendiğini/kaldırıldığını gösterir (pickaxe, LLM gerekmez)."""
    try:
        repo = state.repo()
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
                "kind": h.kind,
                "added": h.added,
                "removed": h.removed,
                "mrs": mr_map.get(h.commit.sha, []),
            }
            for h in hits
        ]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not hits:
        console.print(f"'{expression}' için ekleme/kaldırma yapan commit bulunamadı.")
        raise typer.Exit(code=0)
    table = Table(title=f"'{expression}' geçmişi", show_lines=False)
    for col in ("Tarih", "SHA", "Yazar", "Ne oldu", "Konu", "MR"):
        table.add_column(col)
    for h in reversed(hits):
        c = h.commit
        table.add_row(
            c.author_date.date().isoformat(),
            c.short_sha,
            c.author_name,
            f"{h.kind} (+{h.added}/-{h.removed})",
            c.subject,
            ", ".join(mr_map.get(c.sha, [])),
        )
    console.print(table)
    first = hits[-1].commit
    console.print(
        f"İlk ortaya çıkış: [bold]{first.short_sha}[/] {first.author_date.date()} {first.author_name} — {first.subject}"
    )
    last = hits[0]
    if last.kind == "kaldırıldı":
        console.print(
            f"Son durum: [bold]{last.commit.short_sha}[/] {last.commit.author_date.date()} ile kaldırıldı."
        )


@app.command("file")
def file_cmd(
    path: str = typer.Argument(..., help="Dosya yolu."),
    llm: bool = typer.Option(False, "--llm", help="Ek olarak LLM ile anlatımlı özet üret."),
    mode: str | None = _MODE_OPT,
    as_json: bool = _JSON_OPT,
) -> None:
    """Bir dosyanın özet evrimi: kimler, ne zaman, ne sıklıkla, yeniden adlandırmalar."""
    try:
        repo = state.repo()
        commits = repo.file_history(path)
        if not commits:
            raise GitexError(
                f"'{path}' için geçmiş bulunamadı.",
                hint="Yolu repo köküne göre verin; `gitex ask` ile list_paths kullanılabilir.",
            )
        summary = summarize_file(path, commits)
        if as_json and not llm:
            typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
            return
        if not as_json:
            _print_file_summary(summary)
        if llm:
            _answer(
                f"`{path}` dosyasının evrimini özetle: hangi önemli değişiklikler oldu, kimler yaptı, "
                "neden bu kadar değişti?",
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
        f"[bold]{s['path']}[/] — {s['commits']} commit, +{s['lines_added']}/-{s['lines_deleted']} satır"
    )
    f, last = s["first"], s["last"]
    console.print(f"İlk: {f['sha'][:7]} {f['date']} {f['author']} — {f['subject']}")
    console.print(f"Son: {last['sha'][:7]} {last['date']} {last['author']} — {last['subject']}")
    console.print("Yazarlar: " + ", ".join(f"{a} ({n})" for a, n in s["authors"].items()))
    for r in s["renames"]:
        console.print(f"Yeniden adlandırma: {r['from']} → {r['to']} ({r['sha'][:7]}, {r['date']})")
    peak = max(s["by_month"].values())
    console.print("Aylık aktivite:")
    for month, n in s["by_month"].items():
        console.print(f"  {month} {'█' * max(1, round(20 * n / peak))} {n}")
    table = Table(title="Son değişiklikler", show_header=True)
    for col in ("Tarih", "SHA", "Yazar", "Konu"):
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
        err_console.print("[dim]İptal edildi.[/]")
        sys.exit(130)
