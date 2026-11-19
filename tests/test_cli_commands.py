"""Tests for persisted configuration commands and service invocation."""

from typer.testing import CliRunner

from keyshift import cli, device_manager
from keyshift.config_manager import ConfigManager
from keyshift.diagnostics import Diagnostic


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


def test_temporary_remap_command_supports_duration_toggle_and_unmap(
    monkeypatch, tmp_path
) -> None:
    use_xdg(monkeypatch, tmp_path)
    runner = CliRunner()

    duration = runner.invoke(cli.app, ["remap", "A", "B", "--for", "10m"])
    duration_config = ConfigManager().load_global()["temporary_mappings"]
    toggled = runner.invoke(cli.app, ["remap", "A", "C", "--toggle", "F1"])
    toggle_config = ConfigManager().load_global()["temporary_mappings"]
    layered = runner.invoke(
        cli.app,
        ["remap", "A", "D", "--while-held", "CapsLock"],
    )
    layer_config = ConfigManager().load_global()["temporary_mappings"]
    removed = runner.invoke(cli.app, ["unmap", "A"])

    assert duration.exit_code == 0
    assert duration_config == [
        {"mode": "duration", "source": "A", "target": "B", "duration": 600}
    ]
    assert toggled.exit_code == 0
    assert toggle_config == [
        {"mode": "toggle", "source": "A", "target": "C", "trigger": "F1"}
    ]
    assert layered.exit_code == 0
    assert layer_config == [
        {"mode": "layer", "source": "A", "target": "D", "trigger": "CapsLock"}
    ]
    assert removed.exit_code == 0
    assert ConfigManager().load_global()["temporary_mappings"] == []


def test_temporary_remap_rejects_invalid_duration(monkeypatch, tmp_path) -> None:
    use_xdg(monkeypatch, tmp_path)

    result = CliRunner().invoke(cli.app, ["remap", "A", "B", "--for", "0m"])

    assert result.exit_code == 1
    assert "Duration must use a positive value" in result.output


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
    monkeypatch.setattr(cli, "configure_logging", lambda *, debug: None)
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

        def run(self, device_info, *, timeout, profile, debug, reconnect) -> None:
            received.update(
                device=device_info,
                timeout=timeout,
                profile=profile,
                debug=debug,
                reconnect=reconnect,
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
        "reconnect": False,
    }


def test_run_requires_a_finite_timeout(monkeypatch, tmp_path) -> None:
    use_xdg(monkeypatch, tmp_path)

    runner = CliRunner()
    missing = runner.invoke(cli.app, ["run"])
    infinite = runner.invoke(cli.app, ["run", "--timeout", "inf"])

    assert missing.exit_code == 1
    assert "--timeout greater than zero is required" in missing.output
    assert infinite.exit_code == 1
    assert "finite --timeout" in infinite.output


def test_doctor_command_reports_checks_and_fails_on_invalid_configuration(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        cli.diagnostics,
        "run_diagnostics",
        lambda: [
            Diagnostic("Input devices", "WARN", "No readable keyboards."),
            Diagnostic("Configuration", "FAIL", "Invalid YAML."),
        ],
    )

    result = CliRunner().invoke(cli.app, ["doctor"])

    assert result.exit_code == 1
    assert "[WARN] Input devices: No readable keyboards." in result.output
    assert "[FAIL] Configuration: Invalid YAML." in result.output
