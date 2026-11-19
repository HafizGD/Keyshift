"""Typer command-line interface for keyshift."""

import json
from dataclasses import asdict

import typer

from keyshift import __version__
from keyshift import device_manager

app = typer.Typer(
    help="Remap and manipulate keyboard input on Linux.",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    """Print the package version and exit when requested."""
    if value:
        typer.echo(f"keyshift {__version__}")
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
def list_devices(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print device information as JSON.",
    ),
) -> None:
    """List available keyboard devices."""
    failed_devices: list[str] = []
    try:
        devices = device_manager.list_keyboards(failed_devices=failed_devices)
    except device_manager.DevicePermissionError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

    if not devices:
        typer.echo("No keyboard devices found.")
        if failed_devices:
            typer.echo(
                f"Skipped {len(failed_devices)} unreadable device(s): "
                f"{', '.join(failed_devices)}"
            )
        return

    if json_output:
        typer.echo(json.dumps([asdict(device) for device in devices], indent=2))
    else:
        typer.echo("No  Path                 Name                         Vendor:Product")
        for number, device in enumerate(devices, start=1):
            vendor_product = f"{device.vendor:04x}:{device.product:04x}"
            typer.echo(
                f"{number:<3} {device.path:<20} {device.name:<28} "
                f"{vendor_product}"
            )

    if failed_devices:
        typer.echo(
            f"Warning: skipped {len(failed_devices)} unreadable device(s): "
            f"{', '.join(failed_devices)}",
            err=True,
        )
