# Fix report

Date: 2026-11-20 (Asia/Bangkok). Branch: `fix/audit-runtime-errors`.
Scope: the five defects recorded in [INITIAL_AUDIT.md](INITIAL_AUDIT.md), plus
clearer guidance when device discovery is empty. The implementation from the
previous session was verified without reimplementing it.

## KSH-001: repeated active macro stopped the service

**Before:** `KeyshiftService._run_action` propagated `MacroAlreadyRunningError`
from `MacroEngine.play`, so a second shortcut stopped the entire service.

**After:** the service catches only that specific exception and ignores the
new invocation. The existing worker remains active, no overlapping execution
is requested, and subsequent keyboard events continue through the pipeline.
Other macro errors retain their previous behavior.

Changed: [service.py](../src/keyshift/service.py).
Regression: `test_retriggering_active_macro_keeps_service_processing_input` in
[test_service.py](../tests/test_service.py), using a real macro worker with a
cancellation-controlled wait and simulated hardware.

## KSH-002: shared remap target released too early

**Before:** every physical release produced a target release, even if another
physical source still held the same target.

**After:** each physical source retains its chosen target until release.
Duplicate target presses are suppressed, and target release is emitted only
when no source still owns it. Duplicate source presses do not add ownership.
Repeats, configuration changes while held, unmatched releases, and resetting
held state are covered.

For `A -> B`, the sequence `A down, B down, A up, B repeat, B up` now emits
`B down, B repeat, B up`.

Changed: [mapping_engine.py](../src/keyshift/mapping_engine.py).
Regressions: `test_shared_target_stays_pressed_until_last_source_released`
(both release orders and remapped/unmapped second sources),
`test_shared_target_release_survives_configuration_change`,
`test_unmatched_release_does_not_release_another_sources_target`,
`test_repeated_press_does_not_duplicate_or_leak_target_ownership`, and
`test_reset_forgets_all_owners_of_shared_target` in
[test_mapping_engine.py](../tests/test_mapping_engine.py), plus
`test_service_does_not_release_shared_target_early` in the service tests.

## KSH-003: aliases left stale permanent remaps

**Before:** permanent remaps were updated by their literal spelling. `a`, `A`,
and `KEY_A` could coexist, and insertion order could override the latest request.

**After:** `remap` resolves the source key code, removes all existing spellings
of that same source, then saves the requested replacement. Updates affect the
active profile when selected, otherwise the global configuration. The sequence
`a -> B`, `A -> C`, `a -> D` now leaves one mapping and resolves A to D.

Changed: [cli.py](../src/keyshift/cli.py).
Regression: `test_remap_replaces_case_and_key_aliases` in
[test_cli_commands.py](../tests/test_cli_commands.py), parameterized for global
configuration and an active profile.

## KSH-004: malformed YAML field names crashed validation

**Before:** unknown-key formatting sorted and joined non-string YAML keys,
raising TypeError before a ConfigError could reach diagnostics or recovery.

**After:** configuration-root, metadata, macro-step and state field names are
validated as strings before sorting/joining. Invalid keys produce ConfigError.
`doctor` reports `[FAIL] Configuration` without modifying the file; ordinary
loading preserves the invalid file as `.bak`, restores defaults, and warns.

Changed: [config_manager.py](../src/keyshift/config_manager.py).
Regressions: `test_non_string_yaml_field_names_raise_config_error` (numeric,
null, boolean, mixed, and nested cases), `test_numeric_state_keys_are_backed_up_and_recovered`,
`test_doctor_rejects_numeric_yaml_keys_without_changing_file`, and
`test_status_recovers_numeric_yaml_keys_with_backup` in the configuration and
CLI test files.

## KSH-005: successful empty JSON output was prose

**Before:** the empty-device early return ran before JSON serialization.

**After:** successful `list-devices --json` always serializes an array, including
`[]`. Warnings about unreadable devices go to stderr. Human-readable mode still
explains that no keyboard was found; permission failures remain errors.

Changed: [cli.py](../src/keyshift/cli.py).
Regression: `test_cli_empty_json_is_parseable_even_with_unreadable_devices`
in [test_device_manager.py](../tests/test_device_manager.py), with and without
unreadable-device warnings.

## Related missing-device guidance

[device_manager.py](../src/keyshift/device_manager.py) now reports that readable
Linux `/dev/input/event*` keyboard devices are required and points to
`keyshift doctor`, rather than suggesting the impossible range 1 to 0.
The regression covers index, path, and name selectors.

The [README](../README.md) documents these behaviors and the physical-device
requirements. No kernel, device permissions, or host keyboard setup was changed.

## Review and verification

The previous independent read-only review approved the fixes with no critical
or important findings; its checklist-completion note was addressed. The current
verification re-read the implementation diff and ran the suite, build, package
checks and bounded CLI startup. See [TEST_REPORT.md](TEST_REPORT.md).

## Final review checkpoint

The five fixes remain unchanged at
`68ed6b04b5f6f38c4e2cd9d7ea8fd9e74d20d035`. Final local verification on
2026-11-20 passed 111 tests (zero failures), pip check, an isolated source/wheel
build, twine validation, and full-PR whitespace checks.
[CI run 44662243060](https://github.com/HafizGD/Keyshift/actions/runs/44662243060)
passed on Python 3.10-3.13 at that baseline. Final independent review found
the additional regression below, then verified its fix with no remaining
Important or Critical issues. See [PROGRESS.md](PROGRESS.md) for merge status.

Actual keyboard grabbing, desktop remapping, and physical reconnect behavior
remain unverified because WSL does not expose usable input/output devices.

## KSH-006: service reuse retained stale held-key ownership

Found during final review, after the original five fixes. Reusing a
`KeyshiftService` after it stopped while A was held caused the next A press
to be suppressed as a duplicate: with A -> B, the second run emitted only
B up. This was reproduced after both normal completion and disconnection.

Commit `2820eba6f73703b35f3a86f4c58a13b043a4eb0e` resets mapping ownership
at the start of `run()` when a fresh output device is created. Configuration
reloads within a run still preserve held-key pairing. No broader mapping
behavior or device permissions were changed.

`test_service_reuse_starts_with_fresh_held_keys` adds two cases in
[test_service.py](../tests/test_service.py). Both failed before the fix; the
complete suite passed afterward: **113 passed, zero failed, in 0.25s**.
Build, twine, pip, and whitespace checks also passed again. Independent
follow-up review ran both cases plus held-key reload (3 passed) and approved
the fix. Physical keyboard behavior remains unverified.
