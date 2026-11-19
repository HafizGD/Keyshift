"""Typer command-line interface for keymapper."""

import typer

from keymapper import __version__
from keymapper import device_manager

app = typer.Typer(
    help="Remap and manipulate keyboard input on Linux.",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    """Print the package version and exit when requested."""
    if value:
        typer.echo(f"keymapper {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Manage keyboard remapping."""


@app.command("list-devices")
def list_devices() -> None:
    """List available keyboard devices."""
    try:
        devices = device_manager.list_devices()
    except NotImplementedError as error:
        typer.echo(str(error))
        return

    if not devices:
        typer.echo("No keyboard devices found.")
        return

    for device in devices:
        typer.echo(device)
