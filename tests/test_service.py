"""Integration tests for the service pipeline with fake devices."""

import logging
import signal

import pytest

from keyshift import service as service_module
from keyshift.config_manager import ConfigManager
from keyshift.device_manager import DeviceInfo
from keyshift.listener import DeviceDisconnectedError, KeyEvent
from keyshift.mapping_engine import resolve_key
from keyshift.service import (
    EmergencyExitDetector,
    KeyshiftService,
    ProcessLock,
    ServiceError,
)


class FakeOutput:
    def __init__(self, calls: list[tuple], **kwargs) -> None:
        self.calls = calls
        self.kwargs = kwargs

    def __enter__(self):
        self.calls.append(("output-open", self.kwargs))
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False

    def emit(self, code: int, value: int) -> None:
        self.calls.append(("emit", code, value))

    def press(self, code: int) -> None:
        self.calls.append(("press", code))

    def release(self, code: int) -> None:
        self.calls.append(("release", code))

    def tap(self, code: int) -> None:
        self.calls.extend((("press", code), ("release", code)))

    def release_all(self) -> None:
        self.calls.append(("release-all",))

    def close(self) -> None:
        if ("output-close",) not in self.calls:
            self.calls.append(("output-close",))


class FakeListener:
    def __init__(
        self,
        calls: list[tuple],
        events: list[KeyEvent],
        device_info: DeviceInfo,
        *,
        grab: bool,
        before_events=None,
        after_events=None,
        after_first_event=None,
    ) -> None:
        assert grab is True
        self.calls = calls
        self.events = events
        self.device_info = device_info
        self.before_events = before_events
        self.after_events = after_events
        self.after_first_event = after_first_event
        self.stopped = False

    def __enter__(self):
        self.calls.append(("listener-open", self.device_info.path))
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.stop()
        return False

    def start(self, *, timeout, on_idle, close_on_finish):
        assert close_on_finish is False
        self.calls.append(("listener-start", timeout))
        if self.before_events is not None:
            self.before_events(on_idle)
        if self.after_first_event is not None and self.events:
            yield self.events[0]
            self.after_first_event(on_idle)
            yield from self.events[1:]
        else:
            yield from self.events
        if self.after_events is not None:
            self.after_events(on_idle)

    def stop(self) -> None:
        if not self.stopped:
            self.calls.append(("listener-ungrab-close",))
            self.stopped = True


def event(key: str, value: int) -> KeyEvent:
    return KeyEvent(
        code=resolve_key(key),
        name=f"KEY_{key.upper()}",
        value=value,
        timestamp=1.0,
    )


def make_service(
    monkeypatch,
    tmp_path,
    events: list[KeyEvent],
    *,
    before_events=None,
    after_events=None,
    after_first_event=None,
    clock=None,
):
    manager = ConfigManager(tmp_path)
    calls: list[tuple] = []
    device = DeviceInfo(
        path="/dev/input/event-fake",
        name="Fake Keyboard",
        phys=None,
        vendor=1,
        product=2,
        bustype=3,
    )

    class ListenerFactory(FakeListener):
        def __init__(self, device_info, *, grab):
            super().__init__(
                calls,
                events,
                device_info,
                grab=grab,
                before_events=before_events,
                after_events=after_events,
                after_first_event=after_first_event,
            )

    service_options = {"lock_path": tmp_path / "service.lock"}
    if clock is not None:
        service_options["clock"] = clock
    service = KeyshiftService(
        manager,
        keyboard_factory=lambda **kwargs: FakeOutput(calls, **kwargs),
        listener_factory=ListenerFactory,
        **service_options,
    )
    return manager, service, device, calls


def test_service_maps_events_and_cleans_up_in_safe_order(
    monkeypatch, tmp_path
) -> None:
    manager, service, device, calls = make_service(
        monkeypatch,
        tmp_path,
        [event("A", 1), event("A", 0)],
    )
    manager.save_global({"remaps": {"A": "B"}})

    service.run(device, timeout=1)

    assert ("emit", resolve_key("B"), 1) in calls
    assert ("emit", resolve_key("B"), 0) in calls
    assert calls.index(("output-open", calls[0][1])) < calls.index(
        ("listener-open", device.path)
    )
    assert calls.index(("release-all",)) < calls.index(("listener-ungrab-close",))
    assert calls.index(("listener-ungrab-close",)) < calls.index(("output-close",))
    assert service.status()["running"] is False


def test_debug_logs_never_include_individual_key_events(
    monkeypatch, tmp_path, caplog
) -> None:
    _, service, device, _ = make_service(
        monkeypatch,
        tmp_path,
        [event("A", 1), event("A", 0)],
    )

    with caplog.at_level(logging.DEBUG, logger="keyshift"):
        service.run(device, timeout=1, debug=True)

    assert "key event contents are not logged" in caplog.text
    assert "KEY_A" not in caplog.text
    assert "code=30" not in caplog.text


def test_service_reloads_configuration_on_sighup_without_restart(
    monkeypatch, tmp_path
) -> None:
    manager, service, device, calls = make_service(
        monkeypatch,
        tmp_path,
        [event("A", 1)],
        before_events=lambda on_idle: (
            manager.save_global({"remaps": {"A": "C"}}),
            signal.raise_signal(signal.SIGHUP),
            on_idle(),
        ),
    )
    manager.save_global({"remaps": {"A": "B"}})

    service.run(device, timeout=1)

    assert ("emit", resolve_key("C"), 1) in calls
    assert not any(
        call[0] == "emit" and call[1] == resolve_key("B")
        for call in calls
    )


def test_reload_preserves_mapping_for_key_already_held(monkeypatch, tmp_path) -> None:
    manager, service, device, calls = make_service(
        monkeypatch,
        tmp_path,
        [event("A", 1), event("A", 0)],
        after_first_event=lambda on_idle: (
            manager.save_global({"remaps": {"A": "C"}}),
            signal.raise_signal(signal.SIGHUP),
            on_idle(),
        ),
    )
    manager.save_global({"remaps": {"A": "B"}})

    service.run(device, timeout=1)

    assert ("emit", resolve_key("B"), 1) in calls
    assert ("emit", resolve_key("B"), 0) in calls
    assert not any(
        call[0] == "emit" and call[1] == resolve_key("C")
        for call in calls
    )


def test_temporary_layer_is_applied_by_service_and_consumes_trigger(
    monkeypatch, tmp_path
) -> None:
    manager, service, device, calls = make_service(
        monkeypatch,
        tmp_path,
        [
            event("CapsLock", 1),
            event("A", 1),
            event("A", 0),
            event("CapsLock", 0),
        ],
    )
    manager.save_global(
        {
            "temporary_mappings": [
                {
                    "mode": "layer",
                    "source": "A",
                    "target": "B",
                    "trigger": "CapsLock",
                }
            ]
        }
    )

    service.run(device, timeout=1)

    assert ("emit", resolve_key("B"), 1) in calls
    assert ("emit", resolve_key("B"), 0) in calls
    assert not any(
        call[0] == "emit" and call[1] == resolve_key("CapsLock")
        for call in calls
    )


def test_emergency_exit_requires_full_chord_held_for_one_second() -> None:
    now = [0.0]
    detector = EmergencyExitDetector(
        "Ctrl+Esc",
        hold_seconds=1,
        clock=lambda: now[0],
    )

    assert detector.process(event("Ctrl", 1)) == (False, True, ())
    assert detector.process(event("Esc", 1)) == (False, True, ())
    now[0] = 0.99
    assert detector.check_timeout() == (False, ())
    now[0] = 1.01
    assert detector.check_timeout() == (True, ())


def test_emergency_exit_flushes_incomplete_chord_after_timeout() -> None:
    now = [0.0]
    detector = EmergencyExitDetector(
        "Ctrl+Esc",
        hold_seconds=1,
        clock=lambda: now[0],
    )
    ctrl_press = event("Ctrl", 1)

    assert detector.process(ctrl_press) == (False, True, ())
    now[0] = 1.0
    assert detector.check_timeout() == (False, (ctrl_press,))


def test_emergency_exit_is_checked_on_repeating_key_events() -> None:
    now = [0.0]
    detector = EmergencyExitDetector(
        "Ctrl+Esc",
        hold_seconds=1,
        clock=lambda: now[0],
    )

    detector.process(event("Ctrl", 1))
    detector.process(event("Esc", 1))
    now[0] = 1.01

    assert detector.process(event("Esc", 2)) == (True, False, ())


def test_service_emergency_exit_releases_output_and_ungrabs(
    monkeypatch, tmp_path
) -> None:
    now = [0.0]
    manager, service, device, calls = make_service(
        monkeypatch,
        tmp_path,
        [event("Ctrl", 1), event("Esc", 1)],
        after_events=lambda on_idle: (now.__setitem__(0, 1.1), on_idle()),
        clock=lambda: now[0],
    )
    manager.save_global({"emergency_exit": "Ctrl+Esc"})

    service.run(device, timeout=5)

    assert calls.index(("release-all",)) < calls.index(("listener-ungrab-close",))
    assert calls.index(("listener-ungrab-close",)) < calls.index(("output-close",))
    assert not any(call[0] == "emit" for call in calls)


def test_process_lock_rejects_another_service(tmp_path) -> None:
    path = tmp_path / "service.lock"

    with ProcessLock(path):
        assert ProcessLock.is_locked(path)
        with pytest.raises(ServiceError, match="already running"):
            ProcessLock(path).__enter__()

    assert not ProcessLock.is_locked(path)


def test_service_reconnects_to_the_same_keyboard(
    monkeypatch, tmp_path
) -> None:
    manager, service, device, calls = make_service(
        monkeypatch,
        tmp_path,
        [event("A", 1)],
    )
    attempts = [0]
    monkeypatch.setattr(
        service_module.device_manager,
        "list_keyboards",
        lambda: [device],
    )

    class DisconnectOnce(FakeListener):
        def start(self, **kwargs):
            attempts[0] += 1
            if attempts[0] == 1:
                raise DeviceDisconnectedError("simulated disconnect")
            return super().start(**kwargs)

    service.listener_factory = lambda device_info, *, grab: DisconnectOnce(
        calls,
        [event("A", 1)],
        device_info,
        grab=grab,
    )
    manager.save_global({"remaps": {"A": "B"}})

    service.run(device, timeout=2, reconnect=True)

    assert attempts[0] == 2
    assert sum(call[0] == "listener-open" for call in calls) == 2
    assert ("emit", resolve_key("B"), 1) in calls


def test_retriggering_active_macro_keeps_service_processing_input(monkeypatch, tmp_path) -> None:
    from keyshift.macro_engine import MacroEngine

    # Keep the real worker active until service cleanup cancels it, without sleeps.
    monkeypatch.setattr(
        service_module, "MacroEngine",
        lambda output: MacroEngine(output, waiter=lambda cancel, seconds: cancel.wait()),
    )
    chord = [event("F1", 1), event("F2", 1), event("F2", 0), event("F1", 0)]
    manager, service, device, calls = make_service(
        monkeypatch, tmp_path, chord + chord + [event("A", 1), event("A", 0)],
    )
    manager.save_global({
        "shortcuts": {"F1+F2": "action:macro:slow"},
        "macros": {"slow": [{"type": "delay_ms", "ms": 1000}]},
    })
    service.run(device, timeout=3)
    emitted = [call for call in calls if call[0] == "emit"]
    assert emitted == [("emit", 30, 1), ("emit", 30, 0)]
    assert ("output-close",) in calls
    assert not ProcessLock.is_locked(tmp_path / "service.lock")


def test_service_does_not_release_shared_target_early(monkeypatch, tmp_path) -> None:
    manager, service, device, calls = make_service(
        monkeypatch, tmp_path,
        [event("A", 1), event("B", 1), event("A", 0), event("B", 2), event("B", 0)],
    )
    manager.save_global({"remaps": {"A": "B"}})
    service.run(device, timeout=1)
    emitted = [call for call in calls if call[0] == "emit"]
    assert emitted == [("emit", 48, 1), ("emit", 48, 2), ("emit", 48, 0)]


@pytest.mark.parametrize("interrupted", [False, True])
def test_service_reuse_starts_with_fresh_held_keys(
    monkeypatch, tmp_path, interrupted
) -> None:
    events = [event("A", 1)]
    first_run = True

    def finish_events(on_idle):
        if first_run and interrupted:
            raise DeviceDisconnectedError("simulated disconnect")

    manager, service, device, calls = make_service(
        monkeypatch, tmp_path, events, after_events=finish_events,
    )
    manager.save_global({"remaps": {"A": "B"}})

    # The first run ends without receiving the physical release.
    if interrupted:
        with pytest.raises(DeviceDisconnectedError, match="simulated disconnect"):
            service.run(device, timeout=1)
    else:
        service.run(device, timeout=1)
    assert [call for call in calls if call[0] == "emit"] == [("emit", 48, 1)]

    first_run = False
    events[:] = [event("A", 1), event("A", 0)]
    calls.clear()
    service.run(device, timeout=1)

    assert [call for call in calls if call[0] == "emit"] == [
        ("emit", 48, 1), ("emit", 48, 0),
    ]
    assert service.status()["running"] is False
    assert not ProcessLock.is_locked(tmp_path / "service.lock")
