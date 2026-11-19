"""Typer command-line interface for keyshift."""

import json
from dataclasses import asdict

import typer

from keyshift import __version__
from keyshift import device_manager
from keyshift import listener

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


@app.command("monitor")
def monitor(
    device: str | None = typer.Option(
        None,
        "--device",
        help="Device path, list number, or case-insensitive name fragment.",
    ),
    timeout: float | None = typer.Option(
        None,
        "--timeout",
        min=0.1,
        help="Stop monitoring after this many seconds.",
    ),
) -> None:
    """Print keyboard press, release, and repeat events without grabbing."""
    try:
        selected = device_manager.find_device(device or "1")
        typer.echo(
            f"Monitoring {selected.name} ({selected.path}) without grab. "
            "Press Ctrl+C to stop."
        )
        with listener.KeyboardListener(selected) as keyboard_listener:
            for event in keyboard_listener.start(timeout=timeout):
                state = {0: "release", 1: "press", 2: "repeat"}.get(
                    event.value, f"value={event.value}"
                )
                typer.echo(
                    f"{event.timestamp:.6f} {event.name} {state}"
                )
    except listener.DeviceDisconnectedError as error:
        typer.echo(f"Device disconnected: {error}", err=True)
        raise typer.Exit(code=1) from error
    except device_manager.DeviceError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    except OSError as error:
        typer.echo(f"Input device I/O error: {error}", err=True)
        raise typer.Exit(code=1) from error

    typer.echo("Monitor stopped.")
