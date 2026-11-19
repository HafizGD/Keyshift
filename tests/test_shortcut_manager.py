"""Tests for keyboard shortcut detection without hardware."""

from types import SimpleNamespace

import pytest

from keyshift.mapping_engine import resolve_key
from keyshift.shortcut_manager import (
    ShortcutAction,
    ShortcutError,
    ShortcutManager,
)


def event(key: str, value: int) -> SimpleNamespace:
    return SimpleNamespace(
        code=resolve_key(key),
        name=f"KEY_{key.upper()}",
        value=value,
        timestamp=2.0,
    )


def test_shortcut_emits_output_chord_in_press_release_order() -> None:
    manager = ShortcutManager({"Ctrl+Alt+T": "Ctrl+Shift+T"})

    assert manager.process(event("LEFTCTRL", 1)).buffered
    assert manager.process(event("LEFTALT", 1)).buffered
    result = manager.process(event("T", 1))

    assert result.matched
    assert [item.name for item in result.events] == [
        "KEY_LEFTCTRL",
        "KEY_LEFTSHIFT",
        "KEY_T",
        "KEY_T",
        "KEY_LEFTSHIFT",
        "KEY_LEFTCTRL",
    ]
    assert [item.value for item in result.events] == [1, 1, 1, 0, 0, 0]


def test_nonmatching_prefix_is_flushed_as_original_events() -> None:
    manager = ShortcutManager({"Ctrl+Alt+T": "Ctrl+Shift+T"})

    assert manager.process(event("LEFTCTRL", 1)).events == ()
    result = manager.process(event("X", 1))

    assert [(item.name, item.value) for item in result.events] == [
        ("KEY_LEFTCTRL", 1),
        ("KEY_X", 1),
    ]
    assert not result.matched


def test_unmatched_modifier_press_and_release_are_not_lost() -> None:
    manager = ShortcutManager({"Ctrl+Alt+T": "Ctrl+Shift+T"})

    assert manager.process(event("LEFTCTRL", 1)).buffered
    result = manager.process(event("LEFTCTRL", 0))

    assert [(item.code, item.value) for item in result.events] == [
        (resolve_key("LEFTCTRL"), 1),
        (resolve_key("LEFTCTRL"), 0),
    ]
    assert not manager.pressed_modifiers


def test_matched_physical_modifiers_are_consumed_until_released() -> None:
    manager = ShortcutManager({"CapsLock+H": "Ctrl+Shift+T"})
    manager.process(event("CapsLock", 1))
    result = manager.process(event("H", 1))
    releases = [
        manager.process(event(key, 0))
        for key in ("H", "CapsLock")
    ]

    assert result.matched
    assert all(item.matched and not item.events for item in releases)
    assert not manager.pressed_modifiers


def test_shortcut_can_return_an_action_for_the_service() -> None:
    manager = ShortcutManager(
        {"CapsLock+H": ShortcutAction("profile:gaming")}
    )
    manager.process(event("CapsLock", 1))

    result = manager.process(event("H", 1))

    assert result.matched
    assert result.action == "profile:gaming"
    assert result.events == ()


def test_register_and_remove_shortcut() -> None:
    manager = ShortcutManager()
    manager.register_shortcut("Ctrl+Alt+T", "Ctrl+Shift+T")

    assert manager.remove_shortcut("KEY_LEFTCTRL+KEY_LEFTALT+KEY_T")
    assert not manager.remove_shortcut("Ctrl+Alt+T")


def test_invalid_or_duplicate_shortcut_is_rejected() -> None:
    with pytest.raises(ShortcutError, match="at least two"):
        ShortcutManager({"Ctrl": "Alt"})

    with pytest.raises(ShortcutError, match="Duplicate"):
        ShortcutManager(
            {
                "Ctrl+Alt+T": "Ctrl+Shift+T",
                "KEY_LEFTCTRL+KEY_LEFTALT+KEY_T": "Ctrl+Alt+T",
            }
        )
