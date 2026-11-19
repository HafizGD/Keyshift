"""Tests for bounded, cancellable macro execution."""

import threading

import pytest

from keyshift.macro_engine import (
    MacroAlreadyRunningError,
    MacroEngine,
    MacroExecutionError,
    MacroValidationError,
)
from keyshift.mapping_engine import resolve_key


class FakeKeyboardOutput:
    """Record virtual keyboard calls made by the macro worker."""

    def __init__(self) -> None:
        self.events: list[tuple[str, int, int]] = []
        self.thread_names: list[str] = []

    def _record(self, operation: str, code: int, value: int) -> None:
        self.events.append((operation, code, value))
        self.thread_names.append(threading.current_thread().name)

    def press(self, code: int) -> None:
        self._record("press", code, 1)

    def release(self, code: int) -> None:
        self._record("release", code, 0)

    def tap(self, code: int) -> None:
        self._record("tap", code, 1)
        self._record("tap", code, 0)

    def emit(self, code: int, value: int) -> None:
        self._record("emit", code, value)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def wait(self, cancel_event: threading.Event, seconds: float) -> bool:
        self.now += seconds
        return cancel_event.is_set()


def test_macro_executes_steps_and_ascii_text_in_worker_thread() -> None:
    output = FakeKeyboardOutput()
    clock = FakeClock()
    engine = MacroEngine(
        output,
        clock=clock.monotonic,
        waiter=clock.wait,
    )
    handle = engine.play(
        "demo",
        [
            {"type": "down", "key": "A"},
            {"type": "delay_ms", "ms": 50},
            {"type": "tap", "key": "B"},
            {"type": "text", "text": "A!"},
            {"type": "up", "key": "A"},
        ],
    )

    handle.join(timeout=1)

    assert handle.done
    assert handle.error is None
    assert output.events == [
        ("press", resolve_key("A"), 1),
        ("tap", resolve_key("B"), 1),
        ("tap", resolve_key("B"), 0),
        ("press", resolve_key("LEFTSHIFT"), 1),
        ("emit", resolve_key("A"), 2),
        ("release", resolve_key("LEFTSHIFT"), 0),
        ("press", resolve_key("LEFTSHIFT"), 1),
        ("tap", resolve_key("1"), 1),
        ("tap", resolve_key("1"), 0),
        ("release", resolve_key("LEFTSHIFT"), 0),
        ("release", resolve_key("A"), 0),
    ]
    assert all(name.startswith("keyshift-macro-") for name in output.thread_names)


def test_cancel_releases_keys_held_by_macro() -> None:
    output = FakeKeyboardOutput()
    waiting = threading.Event()

    def blocking_waiter(cancel_event: threading.Event, seconds: float) -> bool:
        waiting.set()
        return cancel_event.wait(timeout=1)

    engine = MacroEngine(output, waiter=blocking_waiter)
    handle = engine.play(
        "cancel-me",
        [
            {"type": "press", "key": "A"},
            {"type": "delay_ms", "ms": 10_000},
        ],
    )

    assert waiting.wait(timeout=1)
    handle.cancel()
    handle.join(timeout=1)

    assert handle.done
    assert output.events == [
        ("press", resolve_key("A"), 1),
        ("release", resolve_key("A"), 0),
    ]


def test_same_macro_cannot_overlap_without_explicit_opt_in() -> None:
    waiting = threading.Event()

    def blocking_waiter(cancel_event: threading.Event, seconds: float) -> bool:
        waiting.set()
        return cancel_event.wait(timeout=1)

    engine = MacroEngine(FakeKeyboardOutput(), waiter=blocking_waiter)
    first = engine.play("same", [{"type": "delay_ms", "ms": 1000}])
    assert waiting.wait(timeout=1)

    with pytest.raises(MacroAlreadyRunningError, match="already running"):
        engine.play("same", [{"type": "tap", "key": "A"}])

    first.cancel()
    first.join(timeout=1)


def test_macro_step_and_duration_limits_are_enforced() -> None:
    engine = MacroEngine(
        FakeKeyboardOutput(),
        max_steps=1,
        max_duration=0.1,
    )

    with pytest.raises(MacroValidationError, match="steps"):
        engine.play(
            "too-many",
            [
                {"type": "tap", "key": "A"},
                {"type": "tap", "key": "B"},
            ],
        )
    with pytest.raises(MacroValidationError, match="duration limit"):
        engine.play("too-long", [{"type": "delay_ms", "ms": 101}])


def test_macro_rejects_recursion_non_ascii_and_invalid_steps() -> None:
    engine = MacroEngine(FakeKeyboardOutput())

    with pytest.raises(MacroValidationError, match="Nested macro"):
        engine.play("recursive", [{"type": "macro", "name": "recursive"}])
    with pytest.raises(MacroValidationError, match="ASCII"):
        engine.play("unicode", [{"type": "text", "text": "café"}])
    with pytest.raises(MacroValidationError, match="non-negative"):
        engine.play("negative-delay", [{"type": "delay_ms", "ms": -1}])


def test_worker_errors_are_reported_by_join() -> None:
    class BrokenOutput(FakeKeyboardOutput):
        def tap(self, code: int) -> None:
            raise OSError("output failed")

    handle = MacroEngine(BrokenOutput()).play(
        "broken",
        [{"type": "tap", "key": "A"}],
    )

    with pytest.raises(MacroExecutionError, match="output failed"):
        handle.join(timeout=1)
    assert isinstance(handle.error, OSError)
