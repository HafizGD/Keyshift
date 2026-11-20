# Changelog

## Unreleased

### Fixed

- Keep the remapping service running when an active macro's shortcut is triggered again; ignore the duplicate request.
- Keep a shared remap output pressed until its last physical source is released, without duplicate press events.
- Replace permanent remaps consistently across case and `KEY_` source aliases, including active profiles.
- Reject non-string YAML field names with configuration errors so diagnostics and backup/recovery do not crash.
- Return `[]` for successful empty `list-devices --json` output and write discovery warnings to stderr.
- Explain missing Linux keyboard devices instead of suggesting a device range of 1 to 0.
- Clear stale held-key ownership when reusing a service object after normal exit or disconnection, so the next run receives its first key press.

### Tests and documentation

- Add 26 original regression/compatibility cases (111 passing tests), then two final-review service-reuse cases; the suite now contains 113 passing tests.
- Verify implementation commit `2820eba` with all 113 tests, isolated distribution builds, twine, pip check, and independent review.
- Document the initial audit, before/after fixes, verification evidence, progress, and handover.
- Clarify that real remapping requires keyboard event devices and uinput access; physical keyboard operation remains unverified in the current WSL environment.

- Reverify the final-review baseline `68ed6b0`: 111 local tests passed, source/wheel builds and package validation passed, and [CI run 44662243060](https://github.com/HafizGD/Keyshift/actions/runs/44662243060) passed on Python 3.10-3.13.
- Preserve historical audit/test evidence separately from current final-review and merge tracking in the handover and reports.

- Verify the complete final-review revision `664f506` with [CI run 44663810657](https://github.com/HafizGD/Keyshift/actions/runs/44663810657), passing on Python 3.10-3.13; merge status is recorded separately in the handover.

No release version has been changed or published by this work.
