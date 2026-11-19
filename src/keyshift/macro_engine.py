"""Pure-Python validation and cancellable execution of keyboard macros."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from keyshift.mapping_engine import resolve_key


_SHIFTED_CHARACTERS = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "MINUS",
    "+": "EQUAL",
    "{": "LEFTBRACE",
    "}": "RIGHTBRACE",
    "|": "BACKSLASH",
    ":": "SEMICOLON",
    '"': "APOSTROPHE",
    "~": "GRAVE",
    "<": "COMMA",
    ">": "DOT",
    "?": "SLASH",
}

_PLAIN_CHARACTERS = {
    " ": "SPACE",
    "-": "MINUS",
    "=": "EQUAL",
    "[": "LEFTBRACE",
    "]": "RIGHTBRACE",
    "\\": "BACKSLASH",
    ";": "SEMICOLON",
    "'": "APOSTROPHE",
    "`": "GRAVE",
    ",": "COMMA",
    ".": "DOT",
    "/": "SLASH",
    "\n": "ENTER",
    "\r": "ENTER",
    "\t": "TAB",
}


class MacroError(RuntimeError):
    """Base exception for macro validation and execution errors."""


class MacroValidationError(MacroError, ValueError):
    """Raised when a macro exceeds supported or safe bounds."""


class MacroAlreadyRunningError(MacroError):
    """Raised when the same macro is already active."""


class MacroExecutionError(MacroError):
    """Raised by join() when a macro's worker thread failed."""


@dataclass(frozen=True)
class MacroStep:
    """One validated macro instruction."""

    type: str
    key: int | None = None
    ms: int | None = None
    text: str | None = None


class KeyboardOutput(Protocol):
    """The output operations required by the macro engine."""

    def press(self, code: int) -> None: ...

    def release(self, code: int) -> None: ...

    def tap(self, code: int) -> None: ...

    def emit(self, code: int, value: int) -> None: ...


class MacroHandle:
    """Control and observe one macro worker."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None

    @property
    def done(self) -> bool:
        """Whether the worker has finished."""
        return self._thread is not None and not self._thread.is_alive()

    @property
    def error(self) -> Exception | None:
        """The worker exception, if any."""
        return self._error

    def cancel(self) -> None:
        """Request cancellation; execution stops at the next safe boundary."""
        self._cancel_event.set()

    def join(self, timeout: float | None = None) -> None:
        """Wait for completion and re-raise worker errors with their cause."""
        if self._thread is None:
            return
        self._thread.join(timeout)
        if not self._thread.is_alive() and self._error is not None:
            raise MacroExecutionError(
                f"Macro '{self.name}' failed: {self._error}"
            ) from self._error


class MacroEngine:
    """Run bounded macros in background threads against a keyboard output."""

    def __init__(
        self,
        output: KeyboardOutput,
        *,
        max_steps: int = 256,
        max_duration: float = 30.0,
        max_text_length: int = 4096,
        clock: Callable[[], float] | None = None,
        waiter: Callable[[threading.Event, float], bool] | None = None,
    ) -> None:
        if max_steps < 1 or max_duration <= 0 or max_text_length < 0:
            raise ValueError("Macro safety limits must be positive.")
        self.output = output
        self.max_steps = max_steps
        self.max_duration = max_duration
        self.max_text_length = max_text_length
        self._clock = clock or time.monotonic
        self._waiter = waiter or (lambda event, seconds: event.wait(seconds))
        self._lock = threading.Lock()
        self._active: dict[str, list[MacroHandle]] = {}

    def play(
        self,
        name: str,
        steps: Sequence[MacroStep | Mapping[str, object]],
        *,
        allow_overlap: bool = False,
    ) -> MacroHandle:
        """Validate a macro and start it in a daemon worker thread."""
        normalized = self._normalize_steps(steps)
        delay_seconds = sum(
            step.ms / 1000
            for step in normalized
            if step.type == "delay_ms" and step.ms is not None
        )
        if delay_seconds > self.max_duration:
            raise MacroValidationError(
                f"Macro '{name}' exceeds the {self.max_duration:g}s duration limit."
            )
        if not name.strip():
            raise MacroValidationError("Macro name cannot be empty.")

        with self._lock:
            active = [
                handle
                for handle in self._active.get(name, [])
                if not handle.done
            ]
            if active and not allow_overlap:
                raise MacroAlreadyRunningError(
                    f"Macro '{name}' is already running."
                )
            handle = MacroHandle(name)
            self._active[name] = [*active, handle]
            thread = threading.Thread(
                target=self._run,
                args=(handle, normalized),
                name=f"keyshift-macro-{name}",
                daemon=True,
            )
            handle._thread = thread
            thread.start()
        return handle

    def cancel(self, name: str) -> None:
        """Cancel all active workers for a macro name."""
        with self._lock:
            handles = tuple(self._active.get(name, ()))
        for handle in handles:
            handle.cancel()

    def _normalize_steps(
        self,
        steps: Sequence[MacroStep | Mapping[str, object]],
    ) -> tuple[MacroStep, ...]:
        if len(steps) > self.max_steps:
            raise MacroValidationError(
                f"Macro has {len(steps)} steps; limit is {self.max_steps}."
            )

        normalized: list[MacroStep] = []
        for index, raw_step in enumerate(steps, start=1):
            if isinstance(raw_step, MacroStep):
                step_data: Mapping[str, object] = {
                    "type": raw_step.type,
                    "key": raw_step.key,
                    "ms": raw_step.ms,
                    "text": raw_step.text,
                }
            elif isinstance(raw_step, Mapping):
                step_data = raw_step
            else:
                raise MacroValidationError(
                    f"Step {index} must be a mapping or MacroStep."
                )

            step_type = str(step_data.get("type", "")).casefold()
            if step_type in ("down", "key_down"):
                step_type = "press"
            elif step_type in ("up", "key_up"):
                step_type = "release"

            if step_type in ("press", "release", "tap"):
                try:
                    code = resolve_key(step_data["key"])
                except (KeyError, TypeError, ValueError) as error:
                    raise MacroValidationError(
                        f"Step {index} has an invalid or missing key."
                    ) from error
                normalized.append(MacroStep(step_type, key=code))
            elif step_type == "delay_ms":
                delay = step_data.get("ms")
                if (
                    not isinstance(delay, int)
                    or isinstance(delay, bool)
                    or delay < 0
                ):
                    raise MacroValidationError(
                        f"Step {index} delay_ms must be a non-negative integer."
                    )
                normalized.append(MacroStep(step_type, ms=delay))
            elif step_type == "text":
                text = step_data.get("text")
                if not isinstance(text, str) or not text.isascii():
                    raise MacroValidationError(
                        f"Step {index} text must contain ASCII characters only."
                    )
                if len(text) > self.max_text_length:
                    raise MacroValidationError(
                        f"Step {index} text exceeds {self.max_text_length} characters."
                    )
                self._validate_text(text, index)
                normalized.append(MacroStep(step_type, text=text))
            else:
                raise MacroValidationError(
                    f"Step {index} has unsupported type '{step_type}'. "
                    "Nested macro execution is not allowed."
                )
        return tuple(normalized)

    @staticmethod
    def _validate_text(text: str, index: int) -> None:
        for character in text:
            if character in _PLAIN_CHARACTERS or character in _SHIFTED_CHARACTERS:
                continue
            if character.isalpha() and character.isascii():
                continue
            if character.isdigit() and character.isascii():
                continue
            raise MacroValidationError(
                f"Step {index} contains unsupported ASCII character "
                f"{character!r}."
            )

    def _run(self, handle: MacroHandle, steps: tuple[MacroStep, ...]) -> None:
        held: dict[int, None] = {}
        error: Exception | None = None
        deadline = self._clock() + self.max_duration
        try:
            self._execute(handle, steps, held, deadline)
        except Exception as caught:
            error = caught
        finally:
            for code in reversed(tuple(held)):
                try:
                    self.output.release(code)
                except Exception as caught:
                    if error is None:
                        error = caught
            handle._error = error
            self._remove_active(handle)

    def _execute(
        self,
        handle: MacroHandle,
        steps: tuple[MacroStep, ...],
        held: dict[int, None],
        deadline: float,
    ) -> None:
        for step in steps:
            if handle._cancel_event.is_set():
                return
            if self._clock() > deadline:
                raise MacroValidationError("Macro exceeded its runtime limit.")

            if step.type == "press":
                self._press(step.key, held)
            elif step.type == "release":
                self.output.release(step.key)
                held.pop(step.key, None)
            elif step.type == "tap":
                self._tap(step.key, held)
            elif step.type == "delay_ms":
                delay = step.ms / 1000
                remaining = deadline - self._clock()
                if delay > remaining:
                    raise MacroValidationError(
                        "Macro delay would exceed its runtime limit."
                    )
                if self._waiter(handle._cancel_event, delay):
                    return
            elif step.type == "text":
                for character in step.text:
                    if handle._cancel_event.is_set():
                        return
                    self._type_character(character, held)

    def _press(self, code: int, held: dict[int, None]) -> None:
        if code not in held:
            self.output.press(code)
            held[code] = None

    def _tap(self, code: int, held: dict[int, None]) -> None:
        if code in held:
            self.output.emit(code, 2)
        else:
            self.output.tap(code)

    def _type_character(self, character: str, held: dict[int, None]) -> None:
        shift_code = resolve_key("LEFTSHIFT")
        if character in ("\n", "\r", "\t") or character in _PLAIN_CHARACTERS:
            code = resolve_key(_PLAIN_CHARACTERS[character])
            self._tap(code, held)
            return

        shifted = character in _SHIFTED_CHARACTERS or character.isupper()
        key_name = (
            _SHIFTED_CHARACTERS[character]
            if character in _SHIFTED_CHARACTERS
            else character.lower()
        )
        code = resolve_key(key_name)
        release_shift = shifted and shift_code not in held
        if release_shift:
            self._press(shift_code, held)
        self._tap(code, held)
        if release_shift:
            self.output.release(shift_code)
            held.pop(shift_code, None)

    def _remove_active(self, handle: MacroHandle) -> None:
        with self._lock:
            active = [
                current
                for current in self._active.get(handle.name, [])
                if current is not handle and not current.done
            ]
            if active:
                self._active[handle.name] = active
            else:
                self._active.pop(handle.name, None)
