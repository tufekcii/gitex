"""CLI modüllerinin paylaştığı konsol, global seçenek durumu ve hata gösterimi."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console, RenderableType
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from gitex.config import Config, load_config
from gitex.errors import GitexError, NotAGitRepoError
from gitex.git.reader import GitRepo
from gitex.i18n import t

console = Console()
err_console = Console(stderr=True)


@dataclass
class State:
    """`-C/--repo` gibi global seçeneklerin taşıdığı durum."""

    repo_path: Path = Path(".")

    def repo(self) -> GitRepo:
        return GitRepo(self.repo_path)

    def repo_or_none(self) -> GitRepo | None:
        try:
            return GitRepo(self.repo_path)
        except NotAGitRepoError:
            return None

    def config(self, repo: GitRepo | None) -> Config:
        return load_config(repo.root if repo else None)


state = State()


def fail(exc: GitexError) -> typer.Exit:
    err_console.print(t("[bold red]Hata:[/] {e}", "[bold red]Error:[/] {e}", e=exc))
    if exc.hint:
        err_console.print(t("[dim]İpucu: {h}[/]", "[dim]Hint: {h}[/]", h=exc.hint))
    return typer.Exit(code=1)


# ---------------------------------------------------------------------- yükleniyor göstergesi

# gitex'e özel gösterge: bir commit çizgisi üzerinde ilerleyen nokta.
SPINNER_FRAMES = ["●───○───○", "○───●───○", "○───○───●", "○───●───○"]
SPINNER_INTERVAL_MS = 110.0


def _elapsed(seconds: float) -> str:
    if seconds < 60:
        return t("{s} sn", "{s}s", s=int(seconds))
    return t("{m} dk {s} sn", "{m}m {s}s", m=int(seconds // 60), s=int(seconds % 60))


class Activity:
    """Kullanıcı beklerken hep görünen tek satırlık gösterge: ne yapıldığı ve geçen süre.

    stderr'e yazar (stdout'taki `--json` çıktısına karışmaz), iş bitince kendini siler ve terminal
    değilse (boru, betik, test) hiç çizilmez. Aktifken basılan satırlar göstergenin üstüne düşer.
    """

    def __init__(self, message: str, *, out: Console | None = None, enabled: bool = True) -> None:
        self.message = message
        self.detail = ""
        self.out = out or err_console
        self.enabled = enabled and self.out.is_terminal
        self._started = time.monotonic()
        self._spinner = Spinner("dots", style="bold cyan")
        self._spinner.frames = list(SPINNER_FRAMES)
        self._spinner.interval = SPINNER_INTERVAL_MS
        self._live: Live | None = None

    def __rich__(self) -> RenderableType:
        line = Text()
        line.append(self.message, style="bold")
        if self.detail:
            line.append(f"  {self.detail}", style="cyan")
        line.append(f"  {_elapsed(time.monotonic() - self._started)}", style="dim")
        self._spinner.update(text=line)
        return self._spinner

    def update(self, message: str | None = None, *, detail: str | None = None) -> None:
        if message is not None:
            self.message = message
            self.detail = ""
        if detail is not None:
            self.detail = detail

    def __enter__(self) -> Activity:
        if self.enabled:
            self._live = Live(self, console=self.out, transient=True, refresh_per_second=12)
            self._live.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
