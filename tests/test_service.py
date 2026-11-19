"""Integration tests for the service pipeline with fake devices."""

import signal

from keyshift.config_manager import ConfigManager
from keyshift.device_manager import DeviceInfo
from keyshift.listener import KeyEvent
from keyshift.mapping_engine import resolve_key
from keyshift.service import KeyshiftService


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
    ) -> None:
        assert grab is True
        self.calls = calls
        self.events = events
        self.device_info = device_info
        self.before_events = before_events
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
        yield from self.events

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
            )

    service = KeyshiftService(
        manager,
        keyboard_factory=lambda **kwargs: FakeOutput(calls, **kwargs),
        listener_factory=ListenerFactory,
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
