"""Tests for pure-Python key-name resolution and remapping."""

from types import SimpleNamespace

import pytest

from keyshift.mapping_engine import (
    MappingEngine,
    TemporaryMappingManager,
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


def test_temporary_duration_mapping_expires_and_overrides_permanent_mapping() -> None:
    now = [5.0]
    temporary = TemporaryMappingManager(
        [
            {
                "mode": "duration",
                "source": "A",
                "target": "B",
                "duration": 10,
            }
        ],
        clock=lambda: now[0],
    )
    engine = MappingEngine({"A": "C"})

    engine.set_temporary_mappings(temporary.active_mappings())
    active = engine.process(event(resolve_key("A"), 1))[0]
    now[0] = 15.0
    engine.set_temporary_mappings(temporary.active_mappings())
    paired_release = engine.process(event(resolve_key("A"), 0))[0]
    expired = engine.process(event(resolve_key("A"), 1))[0]

    assert active.code == resolve_key("B")
    assert paired_release.code == resolve_key("B")
    assert expired.code == resolve_key("C")


def test_temporary_toggle_consumes_trigger_and_toggles_mapping() -> None:
    temporary = TemporaryMappingManager(
        [
            {
                "mode": "toggle",
                "source": "A",
                "target": "B",
                "trigger": "F1",
            }
        ]
    )
    trigger = event(resolve_key("F1"), 1, "KEY_F1")

    assert temporary.process(trigger)
    assert temporary.active_mappings() == {resolve_key("A"): resolve_key("B")}
    assert temporary.process(event(resolve_key("F1"), 0, "KEY_F1"))
    assert temporary.active_mappings() == {resolve_key("A"): resolve_key("B")}
    assert temporary.process(trigger)
    assert temporary.active_mappings() == {}


def test_temporary_layer_is_active_only_while_trigger_is_held() -> None:
    temporary = TemporaryMappingManager(
        [
            {
                "mode": "layer",
                "source": "A",
                "target": "B",
                "trigger": "CapsLock",
            }
        ]
    )

    assert temporary.process(event(resolve_key("CapsLock"), 1, "KEY_CAPSLOCK"))
    assert temporary.active_mappings() == {
        resolve_key("A"): resolve_key("B")
    }
    assert temporary.process(event(resolve_key("CapsLock"), 0, "KEY_CAPSLOCK"))
    assert temporary.active_mappings() == {}


@pytest.mark.parametrize(
    "mappings, second",
    [({"A": "B"}, "B"), ({"A": "B", "C": "B"}, "C")],
)
@pytest.mark.parametrize("release_first", [True, False])
def test_shared_target_stays_pressed_until_last_source_released(mappings, second, release_first) -> None:
    engine = MappingEngine(mappings)
    first_code, second_code = resolve_key("A"), resolve_key(second)
    presses = engine.process(event(first_code, 1)) + engine.process(event(second_code, 1))
    assert [(item.code, item.value) for item in presses] == [(48, 1)]
    first_up, last_up = (first_code, second_code) if release_first else (second_code, first_code)
    assert engine.process(event(first_up, 0)) == []
    repeat = engine.process(event(last_up, 2))
    release = engine.process(event(last_up, 0))
    assert [(item.code, item.value) for item in repeat + release] == [(48, 2), (48, 0)]


def test_shared_target_release_survives_configuration_change() -> None:
    engine = MappingEngine({"A": "B", "C": "B"})
    engine.process(event(30, 1))
    engine.process(event(46, 1))
    engine.set_mappings({"A": "D", "C": "E"})
    assert engine.process(event(30, 0)) == []
    assert [(item.code, item.value) for item in engine.process(event(46, 0))] == [(48, 0)]
    assert engine.process(event(30, 1))[0].code == 32


def test_unmatched_release_does_not_release_another_sources_target() -> None:
    engine = MappingEngine({"A": "B"})
    engine.process(event(30, 1))
    assert engine.process(event(48, 0)) == []
    assert [(item.code, item.value) for item in engine.process(event(30, 0))] == [(48, 0)]


def test_repeated_press_does_not_duplicate_or_leak_target_ownership() -> None:
    engine = MappingEngine({"A": "B"})
    engine.process(event(30, 1))
    assert engine.process(event(30, 1)) == []
    assert [(item.code, item.value) for item in engine.process(event(30, 0))] == [(48, 0)]


def test_reset_forgets_all_owners_of_shared_target() -> None:
    engine = MappingEngine({"A": "B"})
    engine.process(event(30, 1))
    engine.process(event(48, 1))
    engine.reset_held_keys()
    output = engine.process(event(30, 1)) + engine.process(event(30, 0))
    assert [(item.code, item.value) for item in output] == [(48, 1), (48, 0)]
