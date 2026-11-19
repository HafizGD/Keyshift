# Fix five audited runtime and CLI defects with regression coverage

Target: `HafizGD/Keyshift`, base `main`, head `fix/audit-runtime-errors`.

Repeated macro shortcuts could stop the service, shared remap targets could be
released too early, and source aliases could ignore the latest remap. Invalid
YAML field names crashed diagnosis/recovery, while empty JSON device listings
emitted prose.

This PR fixes all five cases and adds 26 regression/compatibility cases (111 tests):

- Ignore duplicate requests for an active macro while continuing keyboard input.
- Keep shared targets down until the final source releases them, including across configuration changes.
- Replace permanent remap aliases by resolved source in global and active-profile configuration.
- Reject non-string YAML field names through ConfigError, retaining read-only doctor checks and backup/recovery.
- Emit `[]` for successful empty JSON device output and send discovery warnings to stderr.

Missing-device startup now explains required Linux keyboard nodes instead of
suggesting the range 1 to 0. The initial audit, fix/test reports, changelog,
progress record and handover are included.

Validation on Python 3.14.4: 111 tests passed; pip check, source/wheel build,
twine check, and git diff --check passed. The regression run before implementation
had 25 failures and 86 passes. Independent implementation review found no
critical or important findings.

Physical keyboard validation remains outstanding: this WSL environment has no
`/dev/input` and no read/write access to `/dev/uinput` for the current user.
Bounded startup exits with actionable guidance. Simulated hardware tests do not
establish actual desktop remapping. No kernel or device permissions were changed.

Verify the existing Python 3.10-3.13 GitHub Actions matrix after PR creation.
Do not merge or enable auto-merge without the user's explicit approval.
