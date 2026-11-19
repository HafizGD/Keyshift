"""Validated YAML configuration, profile, and state management."""

from __future__ import annotations

import math
import os
import re
import shutil
import tempfile
import warnings
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from keyshift.mapping_engine import resolve_key
from keyshift.shortcut_manager import ShortcutManager

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "device": None,
    "remaps": {},
    "shortcuts": {},
    "macros": {},
    "temporary_mappings": [],
    "emergency_exit": "LeftCtrl+LeftAlt+LeftShift+Esc",
}
DEFAULT_STATE: dict[str, str | None] = {
    "active_profile": None,
    "selected_device": None,
}
_CONFIG_KEYS = {
    "version",
    "device",
    "remaps",
    "shortcuts",
    "macros",
    "temporary_mappings",
    "emergency_exit",
    "metadata",
}
_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class ConfigError(ValueError):
    """Raised when configuration cannot be read, validated, or updated."""


class ConfigRecoveryWarning(UserWarning):
    """Warn that corrupt configuration was backed up and reset."""


def default_config() -> dict[str, Any]:
    """Return a fresh mutable copy of the default configuration."""
    return deepcopy(DEFAULT_CONFIG)


def config_directory() -> Path:
    """Return the XDG configuration directory for keyshift."""
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    root = (
        Path(xdg_home)
        if xdg_home and Path(xdg_home).is_absolute()
        else Path.home() / ".config"
    )
    return root / "keyshift"


def validate_config(config: object) -> dict[str, Any]:
    """Validate the supported configuration schema and return a safe copy."""
    if not isinstance(config, dict):
        raise ConfigError("Configuration root must be a YAML mapping.")
    unknown = set(config) - _CONFIG_KEYS
    if unknown:
        raise ConfigError(f"Unknown configuration key(s): {', '.join(sorted(unknown))}.")

    version = config.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise ConfigError(f"Unsupported configuration version: {version!r}.")

    device = config.get("device")
    if device is not None and (not isinstance(device, str) or not device.strip()):
        raise ConfigError("device must be null or a non-empty device selector.")

    remaps = config.get("remaps", {})
    if not isinstance(remaps, dict):
        raise ConfigError("remaps must be a mapping of source keys to target keys.")
    for source, target in remaps.items():
        if not isinstance(source, str) or not isinstance(target, str):
            raise ConfigError("remaps keys and values must be key-name strings.")
        try:
            resolve_key(source)
            resolve_key(target)
        except ValueError as error:
            raise ConfigError(f"Invalid remap '{source}': {error}") from error

    shortcuts = config.get("shortcuts", {})
    if not isinstance(shortcuts, dict):
        raise ConfigError("shortcuts must be a mapping.")
    for trigger, output in shortcuts.items():
        if not isinstance(trigger, str) or not trigger.strip():
            raise ConfigError("Shortcut triggers must be non-empty strings.")
        if not isinstance(output, str) or not output.strip():
            raise ConfigError(f"Shortcut '{trigger}' must have a non-empty string output.")
    try:
        ShortcutManager(shortcuts)
    except ValueError as error:
        raise ConfigError(f"Invalid shortcut configuration: {error}") from error

    macros = config.get("macros", {})
    if not isinstance(macros, dict):
        raise ConfigError("macros must be a mapping of names to step lists.")
    for name, steps in macros.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("Macro names must be non-empty strings.")
        _validate_macro_steps(name, steps)

    temporary_mappings = config.get("temporary_mappings", [])
    if not isinstance(temporary_mappings, list):
        raise ConfigError("temporary_mappings must be a list.")
    if len(temporary_mappings) > 128:
        raise ConfigError("temporary_mappings cannot contain more than 128 rules.")
    temporary_sources: set[int] = set()
    for index, rule in enumerate(temporary_mappings, start=1):
        location = f"temporary_mappings[{index}]"
        if not isinstance(rule, dict):
            raise ConfigError(f"{location} must be a mapping.")
        if any(not isinstance(key, str) for key in rule):
            raise ConfigError(f"{location} keys must be strings.")
        mode = rule.get("mode")
        if mode not in ("duration", "toggle", "layer"):
            raise ConfigError(f"{location}.mode must be duration, toggle, or layer.")
        required = {"mode", "source", "target"}
        if mode == "duration":
            allowed = required | {"duration"}
        else:
            allowed = required | {"trigger"}
        extra = set(rule) - allowed
        missing = allowed - set(rule)
        if extra or missing:
            details = []
            if missing:
                details.append(f"missing {', '.join(sorted(missing))}")
            if extra:
                details.append(f"unknown {', '.join(sorted(extra))}")
            raise ConfigError(f"{location}: {'; '.join(details)}.")
        for key in ("source", "target"):
            if not isinstance(rule[key], str):
                raise ConfigError(f"{location}.{key} must be a key-name string.")
            try:
                resolve_key(rule[key])
            except ValueError as error:
                raise ConfigError(f"{location}.{key}: {error}") from error
        source_code = resolve_key(rule["source"])
        if source_code in temporary_sources:
            raise ConfigError(
                f"{location}.source duplicates another temporary mapping source."
            )
        temporary_sources.add(source_code)
        if mode == "duration":
            duration = rule["duration"]
            if (
                not isinstance(duration, (int, float))
                or isinstance(duration, bool)
                or duration <= 0
                or duration > 86_400
                or not math.isfinite(duration)
            ):
                raise ConfigError(
                    f"{location}.duration must be greater than 0 and at most 86400 seconds."
                )
        else:
            if not isinstance(rule["trigger"], str):
                raise ConfigError(f"{location}.trigger must be a key-name string.")
            try:
                resolve_key(rule["trigger"])
            except ValueError as error:
                raise ConfigError(f"{location}.trigger: {error}") from error

    emergency_exit = config.get(
        "emergency_exit",
        DEFAULT_CONFIG["emergency_exit"],
    )
    if not isinstance(emergency_exit, str) or not emergency_exit.strip():
        raise ConfigError("emergency_exit must be a non-empty shortcut string.")
    emergency_keys = [part.strip() for part in emergency_exit.split("+")]
    if (
        len(emergency_keys) < 2
        or len(emergency_keys) > 8
        or any(not part for part in emergency_keys)
    ):
        raise ConfigError("emergency_exit must contain 2 to 8 key names.")
    try:
        resolved_emergency = [resolve_key(key) for key in emergency_keys]
    except ValueError as error:
        raise ConfigError(f"Invalid emergency_exit: {error}") from error
    if len(set(resolved_emergency)) != len(resolved_emergency):
        raise ConfigError("emergency_exit cannot repeat a key.")

    metadata = config.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ConfigError("metadata must be a mapping.")
        extra_metadata = set(metadata) - {"name", "description", "created_at"}
        if extra_metadata:
            raise ConfigError(
                f"Unknown metadata key(s): {', '.join(sorted(extra_metadata))}."
            )
        for key, value in metadata.items():
            if not isinstance(value, str):
                raise ConfigError(f"metadata.{key} must be a string.")

    validated = default_config()
    validated.update(deepcopy(config))
    validated["version"] = 1
    validated["device"] = device
    validated["remaps"] = deepcopy(remaps)
    validated["shortcuts"] = deepcopy(shortcuts)
    validated["macros"] = deepcopy(macros)
    validated["temporary_mappings"] = deepcopy(temporary_mappings)
    validated["emergency_exit"] = emergency_exit
    return validated


def _validate_macro_steps(name: str, steps: object) -> None:
    if not isinstance(steps, list):
        raise ConfigError(f"macros.{name} must be a list of steps.")
    if len(steps) > 256:
        raise ConfigError(f"macros.{name} has more than 256 steps.")
    allowed = {
        "press",
        "release",
        "tap",
        "down",
        "up",
        "key_down",
        "key_up",
        "delay_ms",
        "text",
    }
    delay_total = 0
    for index, step in enumerate(steps, start=1):
        location = f"macros.{name}[{index}]"
        if not isinstance(step, dict):
            raise ConfigError(f"{location} must be a mapping.")
        step_type = step.get("type")
        if not isinstance(step_type, str) or step_type not in allowed:
            raise ConfigError(f"{location}.type is unsupported: {step_type!r}.")
        if step_type in ("press", "release", "tap", "down", "up", "key_down", "key_up"):
            extra = set(step) - {"type", "key"}
            if extra:
                raise ConfigError(
                    f"{location} has unknown key(s): {', '.join(sorted(extra))}."
                )
            key = step.get("key")
            if not isinstance(key, (str, int)) or isinstance(key, bool):
                raise ConfigError(f"{location}.key must be a key name or code.")
            try:
                resolve_key(key)
            except ValueError as error:
                raise ConfigError(f"{location}.key: {error}") from error
        elif step_type == "delay_ms":
            extra = set(step) - {"type", "ms"}
            if extra:
                raise ConfigError(
                    f"{location} has unknown key(s): {', '.join(sorted(extra))}."
                )
            delay = step.get("ms")
            if not isinstance(delay, int) or isinstance(delay, bool) or delay < 0:
                raise ConfigError(f"{location}.ms must be a non-negative integer.")
            delay_total += delay
        elif step_type == "text":
            extra = set(step) - {"type", "text"}
            if extra:
                raise ConfigError(
                    f"{location} has unknown key(s): {', '.join(sorted(extra))}."
                )
            text = step.get("text")
            if (
                not isinstance(text, str)
                or not text.isascii()
                or len(text) > 4096
                or any(
                    not character.isprintable()
                    and character not in "\n\r\t"
                    for character in text
                )
            ):
                raise ConfigError(f"{location}.text must contain ASCII characters only.")
    if delay_total > 30_000:
        raise ConfigError(f"macros.{name} exceeds the 30 second delay limit.")


def load_config(path: Path) -> dict[str, Any]:
    """Load and validate one YAML config file."""
    try:
        with Path(path).open("r", encoding="utf-8") as config_file:
            data = yaml.safe_load(config_file)
    except yaml.YAMLError as error:
        raise ConfigError(f"Invalid YAML in '{path}': {error}") from error
    except OSError:
        raise
    return validate_config(data)


def save_config(path: Path, config: dict[str, Any]) -> None:
    """Validate and atomically save one YAML config file."""
    validated = validate_config(config)
    _atomic_write(Path(path), yaml.safe_dump(validated, sort_keys=False))


class ConfigManager:
    """Manage keyshift's XDG files, profiles, and selected-device state."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.directory = Path(base_dir) if base_dir is not None else config_directory()
        self.config_path = self.directory / "config.yaml"
        self.profiles_path = self.directory / "profiles"
        self.state_path = self.directory / "state.yaml"

    def load_global(self) -> dict[str, Any]:
        """Load global settings, recovering corrupt files from a .bak copy."""
        if not self.config_path.exists():
            return default_config()
        try:
            return load_config(self.config_path)
        except (ConfigError, yaml.YAMLError) as error:
            recovered = self._recover(self.config_path, default_config(), error)
            return validate_config(recovered)

    def save_global(self, config: dict[str, Any]) -> None:
        """Validate and atomically write global settings."""
        save_config(self.config_path, config)

    def load_state(self) -> dict[str, str | None]:
        """Load selected device and active profile state."""
        if not self.state_path.exists():
            return DEFAULT_STATE.copy()
        try:
            with self.state_path.open("r", encoding="utf-8") as state_file:
                state = yaml.safe_load(state_file)
            return self._validate_state(state)
        except (ConfigError, yaml.YAMLError) as error:
            return self._validate_state(
                self._recover(self.state_path, DEFAULT_STATE.copy(), error)
            )

    def select_device(self, selector: str | None) -> None:
        """Persist the preferred device selector."""
        state = self.load_state()
        state["selected_device"] = selector
        _atomic_write(self.state_path, yaml.safe_dump(state, sort_keys=False))

    def load_active_config(self) -> dict[str, Any]:
        """Load the active profile, or global config when no profile is active."""
        active = self.load_state()["active_profile"]
        return self.load_profile(active) if active else self.load_global()

    def create_profile(
        self,
        name: str,
        config: dict[str, Any] | None = None,
        *,
        description: str = "",
    ) -> Path:
        """Create a named profile without overwriting an existing one."""
        self._validate_profile_name(name)
        path = self._profile_path(name)
        if path.exists():
            raise ConfigError(f"Profile '{name}' already exists.")
        profile = validate_config(config or default_config())
        profile["metadata"] = {
            "name": name,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        save_config(path, profile)
        return path

    def save_profile(self, name: str, config: dict[str, Any]) -> Path:
        """Validate and save an existing or new profile."""
        self._validate_profile_name(name)
        profile = validate_config(config)
        metadata = dict(profile.get("metadata") or {})
        metadata["name"] = name
        metadata.setdefault(
            "created_at",
            datetime.now(timezone.utc).isoformat(),
        )
        profile["metadata"] = metadata
        path = self._profile_path(name)
        save_config(path, profile)
        return path

    def load_profile(self, name: str) -> dict[str, Any]:
        """Load and validate a named profile."""
        path = self._profile_path(name)
        try:
            profile = load_config(path)
        except FileNotFoundError as error:
            raise ConfigError(f"Profile '{name}' does not exist.") from error
        except (ConfigError, yaml.YAMLError) as error:
            fallback = default_config()
            fallback["metadata"] = {"name": name, "description": ""}
            profile = validate_config(self._recover(path, fallback, error))
        metadata = profile.get("metadata", {})
        if metadata.get("name") != name:
            raise ConfigError(
                f"Profile metadata name does not match file name '{name}'."
            )
        return profile

    def activate_profile(self, name: str) -> dict[str, Any]:
        """Set a profile active and return its validated configuration."""
        profile = self.load_profile(name)
        state = self.load_state()
        state["active_profile"] = name
        _atomic_write(self.state_path, yaml.safe_dump(state, sort_keys=False))
        return profile

    def delete_profile(self, name: str, *, force: bool = False) -> None:
        """Delete a profile, requiring force if it is currently active."""
        path = self._profile_path(name)
        if not path.exists():
            raise ConfigError(f"Profile '{name}' does not exist.")
        state = self.load_state()
        if state["active_profile"] == name:
            if not force:
                raise ConfigError(
                    f"Profile '{name}' is active; pass force=True to delete it."
                )
            state["active_profile"] = None
            _atomic_write(self.state_path, yaml.safe_dump(state, sort_keys=False))
        path.unlink()

    def list_profiles(self) -> list[str]:
        """Return profile names in deterministic order."""
        if not self.profiles_path.exists():
            return []
        return sorted(
            path.stem
            for path in self.profiles_path.glob("*.yaml")
            if path.is_file()
        )

    def reset_all(self) -> None:
        """Restore default global settings and clear selected/active state."""
        self.save_global(default_config())
        _atomic_write(
            self.state_path,
            yaml.safe_dump(DEFAULT_STATE, sort_keys=False),
        )

    def _recover(
        self,
        path: Path,
        fallback: dict[str, Any],
        error: Exception,
    ) -> dict[str, Any]:
        backup = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(path, backup)
            if path == self.config_path:
                save_config(path, fallback)
            else:
                _atomic_write(path, yaml.safe_dump(fallback, sort_keys=False))
        except OSError as backup_error:
            raise ConfigError(
                f"Could not back up corrupt file '{path}': {backup_error}"
            ) from backup_error
        warnings.warn(
            f"Configuration '{path}' was invalid ({error}); a backup was saved "
            f"to '{backup}' and defaults were restored.",
            ConfigRecoveryWarning,
            stacklevel=2,
        )
        return fallback

    @staticmethod
    def _validate_state(state: object) -> dict[str, str | None]:
        if not isinstance(state, dict):
            raise ConfigError("state.yaml must contain a mapping.")
        unknown = set(state) - set(DEFAULT_STATE)
        if unknown:
            raise ConfigError(f"Unknown state key(s): {', '.join(sorted(unknown))}.")
        validated = DEFAULT_STATE.copy()
        for key in DEFAULT_STATE:
            value = state.get(key)
            if value is not None and not isinstance(value, str):
                raise ConfigError(f"state.{key} must be a string or null.")
            validated[key] = value
        return validated

    def _profile_path(self, name: str) -> Path:
        self._validate_profile_name(name)
        return self.profiles_path / f"{name}.yaml"

    @staticmethod
    def _validate_profile_name(name: str) -> None:
        if not _PROFILE_NAME.fullmatch(name):
            raise ConfigError(
                "Profile name must start with a letter or digit and contain "
                "only letters, digits, '_' or '-' (max 64 characters)."
            )


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
