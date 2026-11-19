"""Tests for pure-Python key-name resolution and remapping."""

from types import SimpleNamespace

import pytest

from keyshift.mapping_engine import (
    MappingEngine,
    UnknownKeyError,
    resolve_key,
)


def event(code: int, value: int, name: str = "KEY_A") -> SimpleNamespace:
    """Create an event-like object without importing evdev."""
    return SimpleNamespace(code=code, name=name, value=value, timestamp=1.5)


def test_key_resolver_accepts_aliases_and_linux_names() -> None:
    assert resolve_key("CapsLock") == resolve_key("capslock")
    assert resolve_key("KEY_CAPSLOCK") == resolve_key("CapsLock")
    assert resolve_key("Ctrl") == resolve_key("KEY_LEFTCTRL")
    assert resolve_key("A") == resolve_key("KEY_A")


def test_unknown_key_error_suggests_known_names() -> None:
    with pytest.raises(UnknownKeyError, match="Did you mean KEY_CAPSLOCK"):
        resolve_key("CapsLok")


def test_mapping_engine_maps_a_press_and_release() -> None:
    engine = MappingEngine({"CapsLock": "Ctrl"})

    press = engine.process(event(resolve_key("CapsLock"), 1, "KEY_CAPSLOCK"))[0]
    release = engine.process(event(resolve_key("CapsLock"), 0, "KEY_CAPSLOCK"))[0]

    assert (press.name, press.value) == ("KEY_LEFTCTRL", 1)
    assert (release.name, release.value) == ("KEY_LEFTCTRL", 0)


def test_swap_mappings_are_applied_once_directly() -> None:
    engine = MappingEngine({"A": "B", "B": "A"})

    a_output = engine.process(event(resolve_key("A"), 1))[0]
    b_output = engine.process(event(resolve_key("B"), 1, "KEY_B"))[0]

    assert a_output.code == resolve_key("B")
    assert b_output.code == resolve_key("A")


def test_release_and_repeat_keep_press_target_after_mapping_change() -> None:
    engine = MappingEngine({"A": "B"})
    source_code = resolve_key("A")

    press = engine.process(event(source_code, 1))[0]
    engine.set_mapping("A", "C")
    repeat = engine.process(event(source_code, 2))[0]
    release = engine.process(event(source_code, 0))[0]

    assert [press.code, repeat.code, release.code] == [
        resolve_key("B"),
        resolve_key("B"),
        resolve_key("B"),
    ]


def test_unmapped_key_passes_through_unchanged() -> None:
    engine = MappingEngine({"A": "B"})

    result = engine.process(event(resolve_key("Z"), 1, "KEY_Z"))[0]

    assert result.code == resolve_key("Z")
    assert result.name == "KEY_Z"
    assert result.value == 1


def test_mapping_table_replacement_and_removal() -> None:
    engine = MappingEngine({"A": "B"})
    engine.set_mappings({"C": "D"})

    assert engine.mappings == {
        resolve_key("C"): resolve_key("D"),
    }
    assert engine.remove_mapping("C")
    assert not engine.remove_mapping("C")


def test_unknown_mapping_is_rejected_without_evdev() -> None:
    with pytest.raises(UnknownKeyError):
        MappingEngine({"NOT_A_KEY": "A"})
