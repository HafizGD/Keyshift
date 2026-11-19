"""Read-only checks for keyshift dependencies, permissions, and configuration."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from keyshift import device_manager
from keyshift.config_manager import (
    ConfigError,
    ConfigManager,
    default_config,
    load_config,
)
from keyshift.device_manager import DevicePermissionError
from keyshift.service import ProcessLock

CheckStatus = Literal["OK", "WARN", "FAIL"]


@dataclass(frozen=True)
class Diagnostic:
    """One named diagnostic check and its user-facing result."""

    name: str
    status: CheckStatus
    detail: str


def run_diagnostics(
    *,
    keyboard_lister: Callable[..., list[device_manager.DeviceInfo]] | None = None,
    config_path: Path | None = None,
    uinput_path: Path = Path("/dev/uinput"),
    uinput_module_path: Path = Path("/sys/module/uinput"),
    lock_checker: Callable[[], bool] | None = None,
) -> list[Diagnostic]:
    """Run non-invasive checks; never read key events or modify configuration."""
    results: list[Diagnostic] = []
    python_ok = sys.version_info >= (3, 10)
    results.append(
        Diagnostic(
            "Python",
            "OK" if python_ok else "FAIL",
            f"{sys.version_info.major}.{sys.version_info.minor}"
            + ("" if python_ok else "; Python 3.10 or newer is required"),
        )
    )

    for package in ("evdev", "yaml"):
        try:
            available = importlib.util.find_spec(package) is not None
        except (ImportError, ValueError):
            available = False
        results.append(
            Diagnostic(
                package,
                "OK" if available else "FAIL",
                (
                    "installed"
                    if available
                    else "not installed; install keyshift dependencies"
                ),
            )
        )

    lister = keyboard_lister or device_manager.list_keyboards
    failed_devices: list[str] = []
    try:
        devices = lister(failed_devices=failed_devices)
    except DevicePermissionError as error:
        results.append(Diagnostic("Input devices", "WARN", str(error)))
    except (ImportError, OSError) as error:
        results.append(
            Diagnostic(
                "Input devices",
                "WARN",
                f"Could not inspect devices: {error}",
            )
        )
    else:
        if devices:
            detail = f"{len(devices)} keyboard device(s) readable"
            status: CheckStatus = "OK"
            if failed_devices:
                status = "WARN"
                detail += f"; skipped {len(failed_devices)} unreadable device(s)"
            results.append(Diagnostic("Input devices", status, detail))
        else:
            results.append(
                Diagnostic(
                    "Input devices",
                    "WARN",
                    "No readable keyboard event devices found.",
                )
            )

    if uinput_path.exists() and os.access(uinput_path, os.R_OK | os.W_OK):
        results.append(
            Diagnostic("uinput device", "OK", f"read/write access to {uinput_path}")
        )
    elif not uinput_path.exists():
        results.append(
            Diagnostic(
                "uinput device",
                "WARN",
                f"{uinput_path} is missing; load the uinput kernel module.",
            )
        )
    else:
        results.append(
            Diagnostic(
                "uinput device",
                "WARN",
                f"No read/write access to {uinput_path}; check the input group and udev rule.",
            )
        )

    results.append(
        Diagnostic(
            "uinput module",
            "OK" if uinput_module_path.exists() else "WARN",
            (
                "loaded"
                if uinput_module_path.exists()
                else "not detected under /sys/module; check whether uinput is loaded"
            ),
        )
    )

    manager = ConfigManager()
    path = config_path or manager.config_path
    try:
        config = load_config(path) if path.exists() else default_config()
        if not isinstance(config, dict):
            raise ConfigError("Configuration root must be a YAML mapping.")
        detail = f"valid configuration at {path}"
        if config_path is None and manager.state_path.exists():
            try:
                with manager.state_path.open("r", encoding="utf-8") as state_file:
                    state = yaml.safe_load(state_file)
            except yaml.YAMLError as error:
                raise ConfigError(f"Invalid YAML in state file: {error}") from error
            if not isinstance(state, dict):
                raise ConfigError("State file root must be a YAML mapping.")
            active_profile = state.get("active_profile")
            if active_profile is not None:
                if (
                    not isinstance(active_profile, str)
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", active_profile)
                    is None
                ):
                    raise ConfigError("State file contains an invalid active profile.")
                profile_path = manager.profiles_path / f"{active_profile}.yaml"
                load_config(profile_path)
                detail += f"; active profile '{active_profile}' is valid"
    except (ConfigError, OSError) as error:
        results.append(Diagnostic("Configuration", "FAIL", str(error)))
    else:
        results.append(Diagnostic("Configuration", "OK", detail))

    checker = lock_checker or ProcessLock.is_locked
    try:
        active = checker()
    except OSError as error:
        results.append(        Diagnostic(
            "Service lock",
            "WARN",
            f"Could not inspect lock: {error}",
        ))
    else:
        results.append(
            Diagnostic(
                "Service lock",
                "WARN" if active else "OK",
                "a keyshift service is running" if active else "no service is running",
            )
        )
    return results
