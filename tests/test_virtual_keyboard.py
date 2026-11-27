"""Tests for uinput output using a mocked device."""

import evdev
import pytest

from keyshift.device_manager import DeviceInfo
from keyshift.virtual_keyboard import UinputPermissionError, VirtualKeyboard


class FakeUInput:
    """Capture writes made to a virtual keyboard."""

    def __init__(self, *, events, name) -> None:
        self.events = events
        self.name = name
        self.writes: list[tuple[int, int, int]] = []
        self.syn_count = 0
        self.closed = False

    def write(self, event_type: int, code: int, value: int) -> None:
        self.writes.append((event_type, code, value))

    def syn(self) -> None:
        self.syn_count += 1

    def close(self) -> None:
        self.closed = True


def patch_uinput(monkeypatch, factory=None):
    """Replace evdev.UInput and return the created fake instance."""
    devices: list[FakeUInput] = []

    def create_uinput(*, events, name):
        if factory is not None:
            return factory(events=events, name=name)
        device = FakeUInput(events=events, name=name)
        devices.append(device)
        return device

    monkeypatch.setattr(evdev, "UInput", create_uinput)
    return devices


def test_virtual_keyboard_press_release_and_tap(monkeypatch) -> None:
    devices = patch_uinput(monkeypatch)
    keyboard = VirtualKeyboard()

    with keyboard:
        keyboard.press(evdev.ecodes.KEY_A)
        keyboard.press(evdev.ecodes.KEY_A)
        keyboard.release(evdev.ecodes.KEY_A)
        keyboard.tap(evdev.ecodes.KEY_B)

    device = devices[0]
    assert device.name == "keyshift-virtual-keyboard"
    assert device.events[evdev.ecodes.EV_KEY]
    assert device.writes == [
        (evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1),
        (evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0),
        (evdev.ecodes.EV_KEY, evdev.ecodes.KEY_B, 1),
        (evdev.ecodes.EV_KEY, evdev.ecodes.KEY_B, 0),
    ]
    assert device.syn_count == 4
    assert device.closed


def test_close_releases_all_held_keys(monkeypatch) -> None:
    devices = patch_uinput(monkeypatch)
    keyboard = VirtualKeyboard()
    keyboard.press(evdev.ecodes.KEY_A)
    keyboard.press(evdev.ecodes.KEY_B)

    keyboard.close()

    assert devices[0].writes[-2:] == [
        (evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0),
        (evdev.ecodes.EV_KEY, evdev.ecodes.KEY_B, 0),
    ]
    assert devices[0].syn_count == 3
    assert devices[0].closed


def test_source_capabilities_are_copied_and_source_is_closed(monkeypatch) -> None:
    devices = patch_uinput(monkeypatch)
    copied = {
        evdev.ecodes.EV_SYN: [evdev.ecodes.SYN_CONFIG],
        evdev.ecodes.EV_KEY: [evdev.ecodes.KEY_A],
    }

    class SourceDevice:
        closed = False

        def capabilities(self):
            return copied

        def close(self) -> None:
            self.closed = True

    source_device = SourceDevice()
    monkeypatch.setattr(evdev, "InputDevice", lambda path: source_device)
    source = DeviceInfo(
        path="/dev/input/event-source",
        name="Source keyboard",
        phys=None,
        vendor=1,
        product=2,
        bustype=3,
    )

    with VirtualKeyboard(source=source):
        pass

    assert devices[0].events == {evdev.ecodes.EV_KEY: [evdev.ecodes.KEY_A]}
    assert evdev.ecodes.EV_SYN in copied
    assert source_device.closed


def test_uinput_error_preserves_cause_and_setup_guidance(monkeypatch) -> None:
    def denied(**kwargs):
        raise PermissionError("permission denied")

    patch_uinput(monkeypatch, factory=denied)

    with pytest.raises(UinputPermissionError, match="/dev/uinput") as error:
        VirtualKeyboard()._open()

    assert "account has access" in str(error.value)
    assert "permission denied" in str(error.value)


def test_uinput_error_preserves_underlying_error(monkeypatch) -> None:
    def invalid_argument(**kwargs):
        raise OSError(22, "Invalid argument")

    patch_uinput(monkeypatch, factory=invalid_argument)

    with pytest.raises(UinputPermissionError, match="Invalid argument"):
        VirtualKeyboard()._open()


def test_emit_rejects_invalid_key_values(monkeypatch) -> None:
    patch_uinput(monkeypatch)

    with pytest.raises(ValueError, match="0 .* 1 .* 2"):
        VirtualKeyboard().emit(evdev.ecodes.KEY_A, 3)
