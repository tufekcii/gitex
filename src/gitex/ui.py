"""CLI modüllerinin paylaştığı konsol, global seçenek durumu ve hata gösterimi."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console

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
