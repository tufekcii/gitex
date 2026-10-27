"""gitsor komut satırı arayüzü."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from gitsor import __version__
from gitsor.config import SAMPLE_CONFIG, Config, index_path, load_config, repo_dir
from gitsor.errors import GitsorError
from gitsor.git.reader import GitRepo
from gitsor.index.db import Database
from gitsor.index.indexer import index_repo, is_stale, open_index

app = typer.Typer(
    name="gitsor",
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
        typer.echo(f"gitsor {__version__}")
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
    """gitsor ana komutu."""
    state.repo_path = repo


def _fail(exc: GitsorError) -> typer.Exit:
    err_console.print(f"[bold red]Hata:[/] {exc}")
    if exc.hint:
        err_console.print(f"[dim]İpucu: {exc.hint}[/]")
    return typer.Exit(code=1)


# ---------------------------------------------------------------------- init


@app.command()
def init() -> None:
    """`.gitsor/` oluşturur, örnek config yazar ve `.gitignore`'a ekler."""
    try:
        repo = state.repo()
    except GitsorError as exc:
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
    if not any(line.strip() in (".gitsor", ".gitsor/") for line in existing.splitlines()):
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}.gitsor/\n")
        console.print("[green].gitignore güncellendi[/] (.gitsor/)")
    console.print("Sonraki adım: [bold]gitsor index[/]")


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
    except GitsorError as exc:
        raise _fail(exc) from exc


# ---------------------------------------------------------------------- status


@app.command()
def status() -> None:
    """İndeks durumu, son senkron ve config özeti."""
    try:
        repo = state.repo()
        cfg = state.config(repo)
    except GitsorError as exc:
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
        table.add_row("İndeks", "[yellow]yok[/] (gitsor index)")
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


def run() -> None:  # pragma: no cover - giriş noktası
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure:
                reconfigure(encoding="utf-8")
    app()
