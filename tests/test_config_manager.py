"""Tests for XDG YAML configuration and profile lifecycle."""

import os
from pathlib import Path

import pytest

from keyshift import config_manager
from keyshift.config_manager import (
    ConfigError,
    ConfigManager,
    ConfigRecoveryWarning,
    default_config,
    load_config,
    save_config,
)


def test_config_directory_honors_absolute_xdg_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert config_manager.config_directory() == tmp_path / "xdg" / "keyshift"


def test_config_directory_ignores_relative_xdg_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert config_manager.config_directory() == tmp_path / ".config" / "keyshift"


def test_config_round_trip_and_strict_validation(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    config = default_config()
    config["remaps"] = {"CapsLock": "Ctrl"}

    save_config(path, config)

    assert load_config(path)["remaps"] == {"CapsLock": "Ctrl"}
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        save_config(path, {**config, "unexpected": True})
    with pytest.raises(ConfigError, match="Invalid remap"):
        save_config(path, {**config, "remaps": {"NOT_A_KEY": "A"}})
    with pytest.raises(ConfigError, match="Invalid shortcut"):
        save_config(
            path,
            {**config, "shortcuts": {"Ctrl": "Alt"}},
        )


def test_temporary_mapping_schema_validates_modes_duration_and_unique_sources(
    tmp_path,
) -> None:
    path = tmp_path / "config.yaml"
    config = default_config()
    config["temporary_mappings"] = [
        {
            "mode": "duration",
            "source": "A",
            "target": "B",
            "duration": 30,
        }
    ]

    save_config(path, config)
    assert load_config(path)["temporary_mappings"] == config["temporary_mappings"]

    with pytest.raises(ConfigError, match="duration must be greater than 0"):
        save_config(
            path,
            {
                **config,
                "temporary_mappings": [
                    {
                        "mode": "duration",
                        "source": "A",
                        "target": "B",
                        "duration": float("inf"),
                    }
                ],
            },
        )
    with pytest.raises(ConfigError, match="duplicates another temporary mapping"):
        save_config(
            path,
            {
                **config,
                "temporary_mappings": [
                    config["temporary_mappings"][0],
                    {
                        "mode": "toggle",
                        "source": "KEY_A",
                        "target": "C",
                        "trigger": "F1",
                    },
                ],
            },
        )


def test_corrupt_global_config_is_backed_up_and_reset(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    manager.directory.mkdir(parents=True, exist_ok=True)
    manager.config_path.write_text("remaps: [", encoding="utf-8")

    with pytest.warns(ConfigRecoveryWarning, match="defaults were restored"):
        loaded = manager.load_global()

    assert loaded == default_config()
    assert manager.config_path.with_suffix(".yaml.bak").read_text(
        encoding="utf-8"
    ) == "remaps: ["
    assert load_config(manager.config_path) == default_config()


def test_corrupt_state_is_backed_up_and_reset(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    manager.directory.mkdir(parents=True, exist_ok=True)
    manager.state_path.write_text("active_profile: [", encoding="utf-8")

    with pytest.warns(ConfigRecoveryWarning):
        state = manager.load_state()

    assert state == config_manager.DEFAULT_STATE
    assert manager.state_path.with_suffix(".yaml.bak").exists()


def test_atomic_write_uses_replace_in_same_directory(monkeypatch, tmp_path) -> None:
    path = tmp_path / "config.yaml"
    original_replace = os.replace
    calls = []

    def observe_replace(source, destination):
        calls.append((Path(source), Path(destination)))
        return original_replace(source, destination)

    monkeypatch.setattr(config_manager.os, "replace", observe_replace)
    save_config(path, default_config())

    assert len(calls) == 1
    assert calls[0][1] == path
    assert calls[0][0].parent == path.parent
    assert not calls[0][0].exists()


def test_profile_lifecycle_preserves_device_and_guards_active_delete(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    manager.select_device("/dev/input/event7")
    profile_path = manager.create_profile(
        "gaming",
        {"remaps": {"CapsLock": "Ctrl"}},
        description="Game controls",
    )

    assert profile_path.exists()
    assert manager.list_profiles() == ["gaming"]
    assert manager.load_profile("gaming")["metadata"]["description"] == "Game controls"
    manager.activate_profile("gaming")
    assert manager.load_active_config()["remaps"] == {"CapsLock": "Ctrl"}
    assert manager.load_state()["selected_device"] == "/dev/input/event7"

    with pytest.raises(ConfigError, match="is active"):
        manager.delete_profile("gaming")

    manager.delete_profile("gaming", force=True)
    assert manager.list_profiles() == []
    assert manager.load_state() == {
        "active_profile": None,
        "selected_device": "/dev/input/event7",
    }


def test_save_profile_updates_and_reset_restores_defaults(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    manager.create_profile("work")
    manager.save_profile("work", {"remaps": {"CapsLock": "Ctrl"}})
    manager.save_global({"remaps": {"A": "B"}})
    manager.activate_profile("work")
    manager.select_device("/dev/input/event3")

    manager.reset_all()

    assert manager.load_global() == default_config()
    assert manager.load_state() == {
        "active_profile": None,
        "selected_device": None,
    }
    assert manager.list_profiles() == ["work"]


def test_profile_name_cannot_escape_profiles_directory(tmp_path) -> None:
    manager = ConfigManager(tmp_path)

    with pytest.raises(ConfigError, match="Profile name"):
        manager.create_profile("../outside")


def test_corrupt_profile_is_backed_up_and_reset(tmp_path) -> None:
    manager = ConfigManager(tmp_path)
    profile_path = manager.create_profile("gaming")
    profile_path.write_text("remaps: [", encoding="utf-8")

    with pytest.warns(ConfigRecoveryWarning, match="defaults were restored"):
        profile = manager.load_profile("gaming")

    assert profile["metadata"]["name"] == "gaming"
    assert profile_path.with_suffix(".yaml.bak").exists()
