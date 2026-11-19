"""Tests for keyboard event listening without physical input devices."""

import errno
import signal
from types import SimpleNamespace

import evdev
import pytest
from typer.testing import CliRunner

from keyshift import cli, device_manager, listener


def raw_event(event_type: int, code: int, value: int) -> SimpleNamespace:
    """Build a minimal evdev event with a deterministic timestamp."""
    return SimpleNamespace(
        type=event_type,
        code=code,
        value=value,
        sec=10,
        usec=250_000,
    )


class FakeInputDevice:
    """Fake evdev device for exercising listener cleanup and event flow."""

    def __init__(self, events: list[object], name: str = "Fake Keyboard") -> None:
        self.path = "/dev/input/event-test"
        self.name = name
        self.events = events
        self.closed = False
        self.grab_count = 0
        self.ungrab_count = 0

    def read_loop(self):
        for event in self.events:
            if isinstance(event, BaseException):
                raise event
            yield event

    def grab(self) -> None:
        self.grab_count += 1

    def ungrab(self) -> None:
        self.ungrab_count += 1

    def close(self) -> None:
        self.closed = True


def make_listener(monkeypatch, fake: FakeInputDevice, *, grab: bool = False):
    """Patch evdev device opening and return a listener plus its fake device."""
    monkeypatch.setattr(evdev, "InputDevice", lambda path: fake)
    info = device_manager.DeviceInfo(
        path=fake.path,
        name=fake.name,
        phys=None,
        vendor=1,
        product=2,
        bustype=3,
    )
    return listener.KeyboardListener(info, grab=grab)


def test_listener_emits_press_release_and_ignores_sync(monkeypatch) -> None:
    fake = FakeInputDevice(
        [
            raw_event(evdev.ecodes.EV_SYN, 0, 0),
            raw_event(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1),
            raw_event(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 0),
        ]
    )
    keyboard_listener = make_listener(monkeypatch, fake)

    with keyboard_listener:
        events = list(keyboard_listener.start())

    assert [(event.name, event.value) for event in events] == [
        ("KEY_A", 1),
        ("KEY_A", 0),
    ]
    assert events[0].timestamp == 10.25
    assert fake.grab_count == 0
    assert fake.closed


def test_listener_forwards_repeat_events(monkeypatch) -> None:
    fake = FakeInputDevice(
        [raw_event(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 2)]
    )
    keyboard_listener = make_listener(monkeypatch, fake)

    assert [event.value for event in keyboard_listener.start()] == [2]
    assert fake.closed


def test_listener_invokes_callback_for_yielded_events(monkeypatch) -> None:
    fake = FakeInputDevice(
        [raw_event(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1)]
    )
    keyboard_listener = make_listener(monkeypatch, fake)
    callbacks = []

    events = list(keyboard_listener.start(callbacks.append))

    assert callbacks == events
    assert len(callbacks) == 1


def test_listener_timeout_stops_polling(monkeypatch) -> None:
    class PollDevice(FakeInputDevice):
        fd = 123

        def read(self):
            return []

    fake = PollDevice([])
    keyboard_listener = make_listener(monkeypatch, fake)
    clock_values = iter([0.0, 0.2, 0.4, 0.6])
    waits = []
    monkeypatch.setattr(
        listener,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock_values)),
    )

    def fake_select(readers, writers, errors, timeout):
        waits.append(timeout)
        return [], [], []

    monkeypatch.setattr(listener.select, "select", fake_select)

    assert list(keyboard_listener.start(timeout=0.5)) == []
    assert waits == pytest.approx([0.2, 0.1])
    assert fake.closed


def test_listener_ungrabs_and_closes_after_device_disconnect(monkeypatch) -> None:
    fake = FakeInputDevice(
        [
            raw_event(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1),
            OSError(errno.ENODEV, "device removed"),
        ]
    )
    keyboard_listener = make_listener(monkeypatch, fake, grab=True)

    with pytest.raises(listener.DeviceDisconnectedError, match="disconnected"):
        with keyboard_listener:
            list(keyboard_listener.start(timeout=1))

    assert fake.grab_count == 1
    assert fake.ungrab_count == 1
    assert fake.closed


def test_listener_closes_device_even_when_ungrab_fails(monkeypatch) -> None:
    class UngrabErrorDevice(FakeInputDevice):
        def ungrab(self) -> None:
            super().ungrab()
            raise OSError(errno.EIO, "ungrab failed")

    fake = UngrabErrorDevice([])
    keyboard_listener = make_listener(monkeypatch, fake, grab=True)

    with pytest.raises(OSError, match="ungrab failed"):
        list(keyboard_listener.start())

    assert fake.ungrab_count == 1
    assert fake.closed


def test_listener_handles_sigterm_and_cleans_up(monkeypatch) -> None:
    class SigtermDevice(FakeInputDevice):
        def read_loop(self):
            signal.raise_signal(signal.SIGTERM)
            yield raw_event(evdev.ecodes.EV_KEY, evdev.ecodes.KEY_A, 1)

    fake = SigtermDevice([])
    keyboard_listener = make_listener(monkeypatch, fake)

    assert list(keyboard_listener.start()) == []
    assert fake.closed


def test_listener_ignores_its_own_virtual_device(monkeypatch) -> None:
    info = device_manager.DeviceInfo(
        path="/dev/input/event-virtual",
        name=device_manager.VIRTUAL_DEVICE_NAME,
        phys=None,
        vendor=0,
        product=0,
        bustype=0,
    )
    monkeypatch.setattr(
        evdev,
        "InputDevice",
        lambda path: pytest.fail("virtual devices must not be opened"),
    )

    with pytest.raises(device_manager.DeviceError, match="Ignoring virtual"):
        list(listener.KeyboardListener(info).start())


def test_monitor_cli_prints_events_without_grab(monkeypatch) -> None:
    info = device_manager.DeviceInfo(
        path="/dev/input/event-test",
        name="CLI Keyboard",
        phys=None,
        vendor=1,
        product=2,
        bustype=3,
    )
    monkeypatch.setattr(
        device_manager,
        "find_device",
        lambda selector: info if selector == "2" else pytest.fail(selector),
    )

    class FakeListener:
        def __init__(self, device_info, grab=False) -> None:
            assert device_info == info
            assert grab is False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> bool:
            return False

        def start(self, timeout=None):
            assert timeout == 15
            yield listener.KeyEvent(
                code=evdev.ecodes.KEY_A,
                name="KEY_A",
                value=1,
                timestamp=10.25,
            )

    monkeypatch.setattr(cli.listener, "KeyboardListener", FakeListener)
    result = CliRunner().invoke(
        cli.app,
        ["monitor", "--device", "2", "--timeout", "15"],
    )

    assert result.exit_code == 0
    assert "without grab" in result.output
    assert "KEY_A press" in result.output
    assert "Monitor stopped." in result.output
