# Changelog

## Unreleased

### Fixed

- Keep the remapping service running when an active macro's shortcut is triggered again; ignore the duplicate request.
- Keep a shared remap output pressed until its last physical source is released, without duplicate press events.
- Replace permanent remaps consistently across case and `KEY_` source aliases, including active profiles.
- Reject non-string YAML field names with configuration errors so diagnostics and backup/recovery do not crash.
- Return `[]` for successful empty `list-devices --json` output and write discovery warnings to stderr.
- Explain missing Linux keyboard devices instead of suggesting a device range of 1 to 0.

### Tests and documentation

- Add 26 regression/compatibility cases; the suite now contains 111 passing tests.
- Document the initial audit, before/after fixes, verification evidence, progress, and handover.
- Clarify that real remapping requires keyboard event devices and uinput access; physical keyboard operation remains unverified in the current WSL environment.

No release version has been changed or published by this work.
