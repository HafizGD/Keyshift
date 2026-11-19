"""Pure-Python key-name resolution and stateful key remapping."""

from collections.abc import Mapping
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Protocol


_KEY_CODES = {
    "ESC": 1,
    "1": 2,
    "2": 3,
    "3": 4,
    "4": 5,
    "5": 6,
    "6": 7,
    "7": 8,
    "8": 9,
    "9": 10,
    "0": 11,
    "MINUS": 12,
    "EQUAL": 13,
    "BACKSPACE": 14,
    "TAB": 15,
    "Q": 16,
    "W": 17,
    "E": 18,
    "R": 19,
    "T": 20,
    "Y": 21,
    "U": 22,
    "I": 23,
    "O": 24,
    "P": 25,
    "LEFTBRACE": 26,
    "RIGHTBRACE": 27,
    "ENTER": 28,
    "LEFTCTRL": 29,
    "A": 30,
    "S": 31,
    "D": 32,
    "F": 33,
    "G": 34,
    "H": 35,
    "J": 36,
    "K": 37,
    "L": 38,
    "SEMICOLON": 39,
    "APOSTROPHE": 40,
    "GRAVE": 41,
    "LEFTSHIFT": 42,
    "BACKSLASH": 43,
    "Z": 44,
    "X": 45,
    "C": 46,
    "V": 47,
    "B": 48,
    "N": 49,
    "M": 50,
    "COMMA": 51,
    "DOT": 52,
    "SLASH": 53,
    "RIGHTSHIFT": 54,
    "KPASTERISK": 55,
    "LEFTALT": 56,
    "SPACE": 57,
    "CAPSLOCK": 58,
    "F1": 59,
    "F2": 60,
    "F3": 61,
    "F4": 62,
    "F5": 63,
    "F6": 64,
    "F7": 65,
    "F8": 66,
    "F9": 67,
    "F10": 68,
    "NUMLOCK": 69,
    "SCROLLLOCK": 70,
    "KP7": 71,
    "KP8": 72,
    "KP9": 73,
    "KPMINUS": 74,
    "KP4": 75,
    "KP5": 76,
    "KP6": 77,
    "KPPLUS": 78,
    "KP1": 79,
    "KP2": 80,
    "KP3": 81,
    "KP0": 82,
    "KPDOT": 83,
    "F11": 87,
    "F12": 88,
    "KPENTER": 96,
    "RIGHTCTRL": 97,
    "KPSLASH": 98,
    "SYSRQ": 99,
    "RIGHTALT": 100,
    "HOME": 102,
    "UP": 103,
    "PAGEUP": 104,
    "LEFT": 105,
    "RIGHT": 106,
    "END": 107,
    "DOWN": 108,
    "PAGEDOWN": 109,
    "INSERT": 110,
    "DELETE": 111,
    "PAUSE": 119,
    "LEFTMETA": 125,
    "RIGHTMETA": 126,
    "MENU": 127,
    "MUTE": 113,
    "VOLUMEDOWN": 114,
    "VOLUMEUP": 115,
}

_ALIASES = {
    "ALT": "LEFTALT",
    "CAPS": "CAPSLOCK",
    "CONTROL": "LEFTCTRL",
    "CTRL": "LEFTCTRL",
    "ESCAPE": "ESC",
    "META": "LEFTMETA",
    "RETURN": "ENTER",
    "SHIFT": "LEFTSHIFT",
    "SUPER": "LEFTMETA",
}

_CODE_NAMES = {code: f"KEY_{name}" for name, code in _KEY_CODES.items()}


class KeyEventLike(Protocol):
    """Fields consumed from a listener event without importing hardware code."""

    code: int
    name: str
    value: int
    timestamp: float


class UnknownKeyError(ValueError):
    """Raised when a key name cannot be resolved."""


@dataclass(frozen=True)
class OutputEvent:
    """A normalized event to send to a virtual keyboard."""

    code: int
    name: str
    value: int
    timestamp: float


def resolve_key(key: str | int) -> int:
    """Resolve common Linux key names and aliases to their numeric code."""
    if isinstance(key, int):
        if key <= 0:
            raise UnknownKeyError(f"Invalid Linux key code: {key}.")
        return key

    normalized = key.strip().upper()
    if normalized.startswith("KEY_"):
        normalized = normalized[4:]
    normalized = _ALIASES.get(normalized, normalized)
    if normalized in _KEY_CODES:
        return _KEY_CODES[normalized]

    suggestions = get_close_matches(
        normalized,
        [*_KEY_CODES, *_ALIASES],
        n=3,
        cutoff=0.45,
    )
    hint = ""
    if suggestions:
        formatted = ", ".join(
            f"KEY_{_ALIASES.get(item, item)}" for item in suggestions
        )
        hint = f" Did you mean {formatted}?"
    raise UnknownKeyError(f"Unknown key '{key}'.{hint}")


def key_name(code: int) -> str:
    """Return a canonical key name or a numeric fallback."""
    return _CODE_NAMES.get(code, f"KEY_{code}")


def remap_key(key: str, target: str) -> str:
    """Validate a source/target pair and return the target's canonical name."""
    resolve_key(key)
    return key_name(resolve_key(target))


class MappingEngine:
    """Map each physical key event directly to at most one output key."""

    def __init__(
        self,
        mappings: Mapping[str | int, str | int] | None = None,
    ) -> None:
        self._mappings: dict[int, int] = {}
        self._held_targets: dict[int, int] = {}
        if mappings:
            self.set_mappings(mappings)

    @property
    def mappings(self) -> dict[int, int]:
        """Return a copy of the active source-to-target mapping table."""
        return self._mappings.copy()

    def set_mappings(
        self,
        mappings: Mapping[str | int, str | int],
    ) -> None:
        """Replace the complete mapping table after validating every key."""
        self._mappings = {
            resolve_key(source): resolve_key(target)
            for source, target in mappings.items()
        }

    def set_mapping(self, source: str | int, target: str | int) -> None:
        """Add or replace one direct mapping."""
        self._mappings[resolve_key(source)] = resolve_key(target)

    def remove_mapping(self, source: str | int) -> bool:
        """Remove one mapping and report whether it existed."""
        return self._mappings.pop(resolve_key(source), None) is not None

    def process(self, event: KeyEventLike) -> list[OutputEvent]:
        """Map one press, release, or repeat while preserving key pairing."""
        if event.value not in (0, 1, 2):
            raise ValueError(f"Unsupported key event value: {event.value}")

        source_code = event.code
        if event.value == 1:
            target_code = self._held_targets.get(
                source_code,
                self._mappings.get(source_code, source_code),
            )
            self._held_targets[source_code] = target_code
        elif event.value == 0:
            target_code = self._held_targets.pop(
                source_code,
                self._mappings.get(source_code, source_code),
            )
        else:
            target_code = self._held_targets.get(
                source_code,
                self._mappings.get(source_code, source_code),
            )

        output_name = (
            key_name(target_code)
            if target_code != source_code
            else event.name
        )
        return [
            OutputEvent(
                code=target_code,
                name=output_name,
                value=event.value,
                timestamp=event.timestamp,
            )
        ]
