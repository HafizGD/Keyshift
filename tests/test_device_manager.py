"""Tests for keyboard device discovery and the CLI."""

import json
from types import SimpleNamespace

import evdev
import pytest
from typer.testing import CliRunner

from keyshift import cli, device_manager


class FakeDevice:
    """Minimal evdev.InputDevice stand-in for tests."""

    def __init__(
        self,
        path: str,
        *,
        name: str = "Test Keyboard",
        keys: list[int] | None = None,
    ) -> None:
        self.path = path
        self.name = name
        self.phys = "usb-test"
        self.info = SimpleNamespace(vendor=0x1234, product=0x5678, bustype=3)
        self._keys = (
            [evdev.ecodes.KEY_A, evdev.ecodes.KEY_Z, evdev.ecodes.KEY_ENTER]
            if keys is None
            else keys
        )
        self.closed = False

    def capabilities(self) -> dict[int, list[int]]:
        return {evdev.ecodes.EV_KEY: self._keys}

    def close(self) -> None:
        self.closed = True


def patch_devices(monkeypatch, devices: dict[str, FakeDevice | Exception]) -> None:
    """Replace evdev's device opener with a path-indexed fake."""

    def open_device(path: str) -> FakeDevice:
        result = devices[path]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(evdev, "InputDevice", open_device)


def test_list_keyboards_finds_valid_keyboard(monkeypatch) -> None:
    keyboard = FakeDevice("/dev/input/event4")
    patch_devices(monkeypatch, {keyboard.path: keyboard})

    result = device_manager.list_keyboards(lambda: [keyboard.path])

    assert result == [
        device_manager.DeviceInfo(
            path="/dev/input/event4",
            name="Test Keyboard",
            phys="usb-test",
            vendor=0x1234,
            product=0x5678,
            bustype=3,
        )
    ]
    assert keyboard.closed


def test_list_keyboards_ignores_mouse_without_letter_keys(monkeypatch) -> None:
    mouse = FakeDevice("/dev/input/event5", name="Mouse", keys=[])
    patch_devices(monkeypatch, {mouse.path: mouse})

    assert device_manager.list_keyboards(lambda: [mouse.path]) == []
    assert mouse.closed


def test_list_keyboards_excludes_own_virtual_device(monkeypatch) -> None:
    virtual = FakeDevice(
        "/dev/input/event6",
        name=device_manager.VIRTUAL_DEVICE_NAME,
    )
    patch_devices(monkeypatch, {virtual.path: virtual})

    assert device_manager.list_keyboards(lambda: [virtual.path]) == []
    assert virtual.closed


def test_permission_error_does_not_hide_other_keyboards(monkeypatch) -> None:
    keyboard = FakeDevice("/dev/input/event7")
    patch_devices(
        monkeypatch,
        {
            "/dev/input/event8": PermissionError("not allowed"),
            keyboard.path: keyboard,
        },
    )
    failures: list[str] = []

    result = device_manager.list_keyboards(
        lambda: ["/dev/input/event8", keyboard.path],
        failed_devices=failures,
    )

    assert [device.path for device in result] == [keyboard.path]
    assert failures == ["/dev/input/event8"]


def test_default_enumerator_reports_unreadable_event_nodes(monkeypatch) -> None:
    event_path = "/dev/input/event20"
    monkeypatch.setattr(evdev, "list_devices", lambda: [])
    monkeypatch.setattr(device_manager.glob, "glob", lambda pattern: [event_path])
    patch_devices(monkeypatch, {event_path: PermissionError("not allowed")})
    failures: list[str] = []

    with pytest.raises(device_manager.DevicePermissionError) as error:
        device_manager.list_keyboards(failed_devices=failures)

    assert failures == [event_path]
    assert event_path in str(error.value)


def test_find_device_by_path_index_and_name(monkeypatch) -> None:
    first = FakeDevice("/dev/input/event9", name="Alpha Keyboard")
    second = FakeDevice("/dev/input/event10", name="Beta Keyboard")
    devices = {first.path: first, second.path: second}
    patch_devices(monkeypatch, devices)
    enumerator = lambda: list(devices)

    assert device_manager.find_device(first.path, enumerator).path == first.path
    assert device_manager.find_device("2", enumerator).path == second.path
    assert device_manager.find_device("beta", enumerator).path == second.path


def test_find_device_raises_for_ambiguous_or_missing_selector(monkeypatch) -> None:
    first = FakeDevice("/dev/input/event11", name="Office Keyboard")
    second = FakeDevice("/dev/input/event12", name="Office Keyboard Pro")
    devices = {first.path: first, second.path: second}
    patch_devices(monkeypatch, devices)
    enumerator = lambda: list(devices)

    with pytest.raises(device_manager.AmbiguousDeviceError, match="multiple"):
        device_manager.find_device("office keyboard", enumerator)
    with pytest.raises(device_manager.DeviceNotFoundError, match="No keyboard"):
        device_manager.find_device("/dev/input/event99", enumerator)


def test_cli_lists_devices_in_table_and_json(monkeypatch) -> None:
    keyboard = device_manager.DeviceInfo(
        path="/dev/input/event13",
        name="CLI Keyboard",
        phys="usb-cli",
        vendor=0xABCD,
        product=0x1234,
        bustype=3,
    )
    monkeypatch.setattr(device_manager, "list_keyboards", lambda **kwargs: [keyboard])
    runner = CliRunner()

    table_result = runner.invoke(cli.app, ["list-devices"])
    json_result = runner.invoke(cli.app, ["list-devices", "--json"])

    assert table_result.exit_code == 0
    assert "Vendor:Product" in table_result.output
    assert "/dev/input/event13" in table_result.output
    assert "abcd:1234" in table_result.output
    assert json_result.exit_code == 0
    assert json.loads(json_result.output) == [
        {
            "path": "/dev/input/event13",
            "name": "CLI Keyboard",
            "phys": "usb-cli",
            "vendor": 0xABCD,
            "product": 0x1234,
            "bustype": 3,
        }
    ]


def test_cli_explains_when_no_keyboard_is_found(monkeypatch) -> None:
    monkeypatch.setattr(device_manager, "list_keyboards", lambda **kwargs: [])

    result = CliRunner().invoke(cli.app, ["list-devices"])

    assert result.exit_code == 0
    assert "No keyboard devices found." in result.output


def test_cli_permission_failure_has_guidance_and_nonzero_exit(monkeypatch) -> None:
    def fail_with_permission(
        *, failed_devices: list[str]
    ) -> list[device_manager.DeviceInfo]:
        failed_devices.append("/dev/input/event14")
        raise device_manager.DevicePermissionError(failed_devices)

    monkeypatch.setattr(device_manager, "list_keyboards", fail_with_permission)
    result = CliRunner().invoke(cli.app, ["list-devices"])

    assert result.exit_code == 1
    assert "input" in result.output
    assert "log out and back in" in result.output
