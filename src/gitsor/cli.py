"""gitsor komut satırı arayüzü."""

from __future__ import annotations

import typer

from gitsor import __version__

app = typer.Typer(
    name="gitsor",
    help="Git geçmişini doğal dilde sorgula: ne değişti, ne zaman, kim, neden.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"gitsor {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Sürümü göster."
    ),
) -> None:
    """gitsor ana komutu."""


@app.command()
def status() -> None:
    """İndeks durumu, son senkron ve config özeti."""
    typer.echo("Henüz indeks yok.")
