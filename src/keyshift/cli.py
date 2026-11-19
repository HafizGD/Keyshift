"""Typer command-line interface for keyshift."""

import json
import math
import re
from dataclasses import asdict
from typing import Any

import typer

from keyshift import __version__
from keyshift.config_manager import ConfigError, ConfigManager
from keyshift import device_manager
from keyshift import listener
from keyshift.mapping_engine import resolve_key
from keyshift.service import KeyshiftService, ProcessLock, ServiceError

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


@app.command("remap")
def remap(
    source: str,
    target: str,
    for_duration: str | None = typer.Option(
        None,
        "--for",
        help="Temporarily map for a duration such as 10m or 30s.",
    ),
    toggle: str | None = typer.Option(None, "--toggle"),
    while_held: str | None = typer.Option(None, "--while-held"),
) -> None:
    """Save a permanent or temporary key remapping."""
    try:
        manager = ConfigManager()
        config = manager.load_active_config()
        temporary_modes = sum(
            (for_duration is not None, toggle is not None, while_held is not None)
        )
        if temporary_modes > 1:
            raise ConfigError("Choose only one temporary remapping mode.")
        if for_duration is not None:
            duration = _parse_duration(for_duration)
            _replace_temporary_mapping(
                config,
                source,
                {
                    "mode": "duration",
                    "source": source,
                    "target": target,
                    "duration": duration,
                },
            )
        elif toggle is not None:
            _replace_temporary_mapping(
                config,
                source,
                {
                    "mode": "toggle",
                    "source": source,
                    "target": target,
                    "trigger": toggle,
                },
            )
        elif while_held is not None:
            _replace_temporary_mapping(
                config,
                source,
                {
                    "mode": "layer",
                    "source": source,
                    "target": target,
                    "trigger": while_held,
                },
            )
        else:
            remaps = dict(config["remaps"])
            remaps[source] = target
            config["remaps"] = remaps
        _save_active_config(manager, config)
    except (ConfigError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    if for_duration is not None:
        typer.echo(f"Temporarily mapped {source} to {target} for {for_duration}.")
    elif toggle is not None:
        typer.echo(f"Mapped {source} to {target}, toggled by {toggle}.")
    elif while_held is not None:
        typer.echo(f"Mapped {source} to {target} while {while_held} is held.")
    else:
        typer.echo(f"Mapped {source} to {target}.")


@app.command("unmap")
def unmap(key: str) -> None:
    """Remove a key remapping from the active profile or global config."""
    try:
        manager = ConfigManager()
        config = manager.load_active_config()
        code = resolve_key(key)
        remaps = dict(config["remaps"])
        matching = [
            source
            for source in remaps
            if resolve_key(source) == code
        ]
        old_temporary = list(config["temporary_mappings"])
        temporary = [
            rule
            for rule in old_temporary
            if resolve_key(rule["source"]) != code
        ]
        if not matching and len(temporary) == len(old_temporary):
            typer.echo(f"No remapping configured for {key}.")
            return
        for source in matching:
            remaps.pop(source)
        config["remaps"] = remaps
        config["temporary_mappings"] = temporary
        _save_active_config(manager, config)
    except (ConfigError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Removed remapping for {key}.")


@app.command("profile")
def profile(
    name: str | None = typer.Argument(None),
    list_profiles: bool = typer.Option(False, "--list", help="List saved profiles."),
    create: bool = typer.Option(False, "--create", help="Create a profile."),
    delete: bool = typer.Option(False, "--delete", help="Delete a profile."),
    force: bool = typer.Option(
        False,
        "--force",
        help="Confirm deletion of an active profile or a full reset.",
    ),
    description: str = typer.Option("", "--description"),
) -> None:
    """List, create, activate, or delete profiles."""
    actions = sum((list_profiles, create, delete))
    if actions > 1:
        raise typer.BadParameter("Choose only one of --list, --create, or --delete.")

    manager = ConfigManager()
    try:
        if list_profiles:
            profiles = manager.list_profiles()
            typer.echo("\n".join(profiles) if profiles else "No profiles found.")
            return
        if name is None:
            raise ConfigError("A profile name is required.")
        if create:
            manager.create_profile(name, description=description)
            typer.echo(f"Created profile '{name}'.")
        elif delete:
            manager.delete_profile(name, force=force)
            typer.echo(f"Deleted profile '{name}'.")
        else:
            manager.activate_profile(name)
            typer.echo(f"Activated profile '{name}'.")
    except ConfigError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error


@app.command("select-device")
def select_device(selector: str) -> None:
    """Save the preferred keyboard device by path, number, or name."""
    try:
        selected = device_manager.find_device(selector)
        ConfigManager().select_device(selected.path)
    except device_manager.DeviceError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Selected {selected.name} ({selected.path}).")


@app.command("run")
def run_service(
    device: str | None = typer.Option(
        None,
        "--device",
        help="Device path, list number, or name fragment.",
    ),
    profile_name: str | None = typer.Option(None, "--profile"),
    timeout: float | None = typer.Option(
        None,
        "--timeout",
        min=0.1,
        help="Stop the service after this many seconds.",
    ),
    reconnect: bool = typer.Option(
        False,
        "--reconnect",
        help="Wait for the selected physical keyboard to reconnect.",
    ),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    """Run remapping with exclusive input grab and virtual output."""
    manager = ConfigManager()
    try:
        if timeout is None or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(
                "A finite --timeout greater than zero is required for safety."
            )
        state = manager.load_state()
        config = manager.load_profile(profile_name) if profile_name else manager.load_active_config()
        selector = device or state["selected_device"] or config.get("device") or "1"
        selected = device_manager.find_device(selector)
        typer.echo(
            "Starting remapping service. It will grab the selected input device; "
            "use an emergency exit and a finite timeout."
        )
        KeyshiftService(manager).run(
            selected,
            timeout=timeout,
            profile=profile_name,
            debug=debug,
            reconnect=reconnect,
        )
    except (
        ConfigError,
        device_manager.DeviceError,
        ServiceError,
        OSError,
        ValueError,
    ) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error


@app.command("status")
def status() -> None:
    """Show configured profile, device, and feature counts."""
    manager = ConfigManager()
    state = manager.load_state()
    config = manager.load_active_config()
    typer.echo(f"Active profile: {state['active_profile'] or 'default'}")
    typer.echo(
        f"Selected device: {state['selected_device'] or config.get('device') or 'automatic'}"
    )
    typer.echo(f"Remaps: {len(config['remaps'])}")
    typer.echo(f"Temporary mappings: {len(config['temporary_mappings'])}")
    typer.echo(f"Shortcuts: {len(config['shortcuts'])}")
    typer.echo(f"Macros: {len(config['macros'])}")
    typer.echo(f"Service running: {'yes' if ProcessLock.is_locked() else 'no'}")


@app.command("reset")
def reset(force: bool = typer.Option(False, "--force")) -> None:
    """Restore default global settings and clear active/device selection."""
    if not force:
        typer.confirm("Reset global settings and selected device?", abort=True)
    ConfigManager().reset_all()
    typer.echo("Configuration reset to defaults. Saved profiles were kept.")


def _save_active_config(manager: ConfigManager, config: dict) -> None:
    active_profile = manager.load_state()["active_profile"]
    if active_profile:
        manager.save_profile(active_profile, config)
    else:
        manager.save_global(config)


def _parse_duration(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)(s|m|h)", value.strip().casefold())
    if match is None:
        raise ConfigError("Duration must use a positive value with s, m, or h.")
    amount = int(match.group(1))
    seconds = amount * {"s": 1, "m": 60, "h": 3600}[match.group(2)]
    if seconds > 86_400:
        raise ConfigError("Temporary duration cannot exceed 24 hours.")
    return seconds


def _replace_temporary_mapping(
    config: dict[str, Any],
    source: str,
    rule: dict[str, Any],
) -> None:
    source_code = resolve_key(source)
    config["temporary_mappings"] = [
        item
        for item in config["temporary_mappings"]
        if resolve_key(item["source"]) != source_code
    ]
    config["temporary_mappings"].append(rule)
