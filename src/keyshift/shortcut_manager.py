"""Pure-Python chord detection and shortcut output generation."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from keyshift.mapping_engine import (
    KeyEventLike,
    OutputEvent,
    key_name,
    resolve_key,
)


_MODIFIERS = frozenset(
    resolve_key(name)
    for name in (
        "KEY_LEFTCTRL",
        "KEY_RIGHTCTRL",
        "KEY_LEFTALT",
        "KEY_RIGHTALT",
        "KEY_LEFTSHIFT",
        "KEY_RIGHTSHIFT",
        "KEY_LEFTMETA",
        "KEY_RIGHTMETA",
    )
)


class ShortcutError(ValueError):
    """Raised when a shortcut binding is invalid."""


@dataclass(frozen=True)
class ShortcutAction:
    """An action for the service layer to execute after a shortcut match."""

    name: str


@dataclass(frozen=True)
class ShortcutResult:
    """Events/action returned by processing one physical key event."""

    events: tuple[OutputEvent, ...]
    matched: bool = False
    action: str | None = None
    buffered: bool = False


@dataclass(frozen=True)
class _Binding:
    trigger: tuple[int, ...]
    output: tuple[int, ...] | None
    action: str | None


class _EventLike(Protocol):
    code: int
    name: str
    value: int
    timestamp: float


class ShortcutManager:
    """Detect configured chords while buffering incomplete trigger prefixes."""

    def __init__(
        self,
        bindings: Mapping[str, str | ShortcutAction] | None = None,
    ) -> None:
        self._bindings: list[_Binding] = []
        self._pressed: set[int] = set()
        self._consumed: set[int] = set()
        self._pending: list[_EventLike] = []
        if bindings:
            self.set_bindings(bindings)

    @property
    def pressed_modifiers(self) -> frozenset[int]:
        """Return the currently held left/right Ctrl, Alt, Shift, and Meta keys."""
        return frozenset(self._pressed & _MODIFIERS)

    def set_bindings(
        self,
        bindings: Mapping[str, str | ShortcutAction],
    ) -> None:
        """Replace all shortcuts, validating trigger and output chord names."""
        parsed: list[_Binding] = []
        seen: set[frozenset[int]] = set()
        for trigger, output in bindings.items():
            trigger_keys = self._parse_chord(trigger, require_combo=True)
            trigger_set = frozenset(trigger_keys)
            if trigger_set in seen:
                raise ShortcutError(f"Duplicate shortcut trigger '{trigger}'.")
            seen.add(trigger_set)

            if isinstance(output, ShortcutAction):
                if not output.name:
                    raise ShortcutError("Shortcut action name cannot be empty.")
                parsed.append(_Binding(trigger_keys, None, output.name))
            elif output.startswith("action:"):
                action = output.removeprefix("action:").strip()
                if not action:
                    raise ShortcutError("Shortcut action name cannot be empty.")
                parsed.append(_Binding(trigger_keys, None, action))
            else:
                parsed.append(
                    _Binding(
                        trigger_keys,
                        self._parse_chord(output, require_combo=False),
                        None,
                    )
                )
        self._bindings = parsed

    def register_shortcut(
        self,
        trigger: str,
        output: str | ShortcutAction,
    ) -> None:
        """Add one shortcut while preserving existing bindings."""
        existing = {
            self._format_chord(binding.trigger): (
                ShortcutAction(binding.action)
                if binding.action is not None
                else self._format_chord(binding.output or ())
            )
            for binding in self._bindings
        }
        existing[trigger] = output
        self.set_bindings(existing)

    def remove_shortcut(self, trigger: str) -> bool:
        """Remove a trigger by its resolved key set."""
        trigger_keys = frozenset(self._parse_chord(trigger, require_combo=True))
        previous_count = len(self._bindings)
        self._bindings = [
            binding
            for binding in self._bindings
            if frozenset(binding.trigger) != trigger_keys
        ]
        return len(self._bindings) != previous_count

    def process(self, event: KeyEventLike) -> ShortcutResult:
        """Buffer prefixes, consume matching physical chords, and emit outputs."""
        if event.value not in (0, 1, 2):
            raise ValueError(f"Unsupported key event value: {event.value}")

        if event.value == 0:
            self._pressed.discard(event.code)
        elif event.value == 1:
            self._pressed.add(event.code)

        if event.code in self._consumed:
            if event.value == 0:
                self._consumed.discard(event.code)
            return ShortcutResult(events=(), matched=True, buffered=True)

        if self._pending:
            self._pending.append(event)
            binding = self._matched_binding(event)
            if binding is not None:
                self._pending.clear()
                self._consumed.update(binding.trigger)
                return self._result_for_binding(binding, event.timestamp)
            if event.value == 0 or not self._is_prefix():
                return self._flush_pending()
            return ShortcutResult(events=(), buffered=True)

        if event.value == 1 and self._is_prefix():
            self._pending.append(event)
            return ShortcutResult(events=(), buffered=True)

        return ShortcutResult(events=(self._passthrough(event),))

    def _parse_chord(self, chord: str, *, require_combo: bool) -> tuple[int, ...]:
        parts = [part.strip() for part in chord.split("+")]
        if not parts or any(not part for part in parts):
            raise ShortcutError(f"Invalid shortcut chord '{chord}'.")
        if require_combo and len(parts) < 2:
            raise ShortcutError(f"Shortcut trigger '{chord}' needs at least two keys.")
        codes = tuple(resolve_key(part) for part in parts)
        if len(set(codes)) != len(codes):
            raise ShortcutError(f"Shortcut chord '{chord}' repeats a key.")
        return codes

    def _is_prefix(self) -> bool:
        if not self._pressed:
            return False
        for binding in self._bindings:
            trigger = set(binding.trigger)
            prefix_keys = set(binding.trigger[:-1])
            if self._pressed < trigger and self._pressed <= trigger:
                if self._pressed & prefix_keys:
                    return True
        return False

    def _matched_binding(self, event: KeyEventLike) -> _Binding | None:
        if event.value != 1:
            return None
        for binding in self._bindings:
            if event.code == binding.trigger[-1] and self._pressed == set(binding.trigger):
                return binding
        return None

    def _result_for_binding(
        self,
        binding: _Binding,
        timestamp: float,
    ) -> ShortcutResult:
        events: tuple[OutputEvent, ...] = ()
        if binding.output is not None:
            events = self._output_chord(binding.output, timestamp)
        return ShortcutResult(
            events=events,
            matched=True,
            action=binding.action,
        )

    def _output_chord(
        self,
        codes: tuple[int, ...],
        timestamp: float,
    ) -> tuple[OutputEvent, ...]:
        if not codes:
            return ()
        modifiers, primary = codes[:-1], codes[-1]
        sequence = [
            *((code, 1) for code in modifiers),
            (primary, 1),
            (primary, 0),
            *((code, 0) for code in reversed(modifiers)),
        ]
        return tuple(
            OutputEvent(
                code=code,
                name=key_name(code),
                value=value,
                timestamp=timestamp,
            )
            for code, value in sequence
        )

    def _flush_pending(self) -> ShortcutResult:
        events = tuple(self._passthrough(event) for event in self._pending)
        self._pending.clear()
        return ShortcutResult(events=events)

    @staticmethod
    def _passthrough(event: _EventLike) -> OutputEvent:
        return OutputEvent(
            code=event.code,
            name=event.name,
            value=event.value,
            timestamp=event.timestamp,
        )

    @staticmethod
    def _format_chord(codes: tuple[int, ...]) -> str:
        return "+".join(key_name(code).removeprefix("KEY_") for code in codes)
