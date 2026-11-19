"""Tests for persisted configuration commands and service invocation."""

from typer.testing import CliRunner

from keyshift import cli, device_manager
from keyshift.config_manager import ConfigManager


def use_xdg(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def test_remap_and_unmap_commands_update_configuration(monkeypatch, tmp_path) -> None:
    use_xdg(monkeypatch, tmp_path)
    runner = CliRunner()

    remap_result = runner.invoke(cli.app, ["remap", "CapsLock", "Ctrl"])
    after_remap = ConfigManager().load_global()["remaps"]
    unmap_result = runner.invoke(cli.app, ["unmap", "capslock"])

    assert remap_result.exit_code == 0
    assert "Mapped CapsLock to Ctrl" in remap_result.output
    assert after_remap == {"CapsLock": "Ctrl"}
    assert unmap_result.exit_code == 0
    assert ConfigManager().load_global()["remaps"] == {}


def test_profile_create_list_activate_and_protected_delete(
    monkeypatch, tmp_path
) -> None:
    use_xdg(monkeypatch, tmp_path)
    runner = CliRunner()

    created = runner.invoke(cli.app, ["profile", "--create", "work"])
    listed = runner.invoke(cli.app, ["profile", "--list"])
    activated = runner.invoke(cli.app, ["profile", "work"])
    blocked_delete = runner.invoke(cli.app, ["profile", "--delete", "work"])
    deleted = runner.invoke(
        cli.app,
        ["profile", "--delete", "work", "--force"],
    )

    assert created.exit_code == 0
    assert "work" in listed.output
    assert activated.exit_code == 0
    assert blocked_delete.exit_code == 1
    assert "is active" in blocked_delete.output
    assert deleted.exit_code == 0


def test_select_device_and_status_commands(monkeypatch, tmp_path) -> None:
    use_xdg(monkeypatch, tmp_path)
    info = device_manager.DeviceInfo(
        path="/dev/input/event7",
        name="Test Keyboard",
        phys=None,
        vendor=1,
        product=2,
        bustype=3,
    )
    monkeypatch.setattr(device_manager, "find_device", lambda selector: info)
    runner = CliRunner()

    selected = runner.invoke(cli.app, ["select-device", "Test"])
    status_result = runner.invoke(cli.app, ["status"])

    assert selected.exit_code == 0
    assert "/dev/input/event7" in selected.output
    assert ConfigManager().load_state()["selected_device"] == info.path
    assert status_result.exit_code == 0
    assert "Selected device: /dev/input/event7" in status_result.output


def test_reset_requires_explicit_force_in_noninteractive_use(
    monkeypatch, tmp_path
) -> None:
    use_xdg(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli.app, ["reset", "--force"])

    assert result.exit_code == 0
    assert "reset to defaults" in result.output


def test_run_command_passes_options_to_service(monkeypatch, tmp_path) -> None:
    use_xdg(monkeypatch, tmp_path)
    info = device_manager.DeviceInfo(
        path="/dev/input/event8",
        name="Test Keyboard",
        phys=None,
        vendor=1,
        product=2,
        bustype=3,
    )
    monkeypatch.setattr(device_manager, "find_device", lambda selector: info)
    received = {}

    class FakeService:
        def __init__(self, config_manager) -> None:
            pass

        def run(self, device_info, *, timeout, profile, debug) -> None:
            received.update(
                device=device_info,
                timeout=timeout,
                profile=profile,
                debug=debug,
            )

    monkeypatch.setattr(cli, "KeyshiftService", FakeService)
    result = CliRunner().invoke(
        cli.app,
        ["run", "--device", "2", "--timeout", "5", "--debug"],
    )

    assert result.exit_code == 0
    assert received == {
        "device": info,
        "timeout": 5.0,
        "profile": None,
        "debug": True,
    }
