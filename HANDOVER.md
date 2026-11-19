# Keyshift handover

Updated: 2026-11-20 (Asia/Bangkok).
Repository: https://github.com/HafizGD/Keyshift
Branch: `fix/audit-runtime-errors`; target: `main`; original base: `8f85b03`.

## Delivered work

Five audit defects are fixed: repeated active macro crashes, premature shared-key
release, stale remap aliases, non-string YAML key crashes, and non-JSON empty
device output. Missing-device startup now offers actionable guidance.

Read these records before making further changes:

- [Initial audit](docs/INITIAL_AUDIT.md): the pre-fix state and reproduction evidence.
- [Fix report](docs/FIX_REPORT.md): before/after behavior and regression tests.
- [Test report](docs/TEST_REPORT.md): 111 passing tests, build checks and hardware limits.
- [Progress](docs/PROGRESS.md): publication and CI status.
- [Changelog](CHANGELOG.md): user-visible changes.

Do not repeat the completed fixes unless a new reproducible defect is found.

## Verified locally

Python 3.14.4: 111 tests passed; pip check, build, twine check and diff whitespace
checks passed. CLI and simulated service behavior were verified. The previous
independent code review found no critical or important issues.

From WSL, in the repository root:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
.venv/bin/keyshift doctor
.venv/bin/keyshift list-devices --json
```

Only run the bounded remapping service after a real keyboard node and uinput
access are available, using the finite timeout and emergency-exit instructions
in [README.md](README.md).

## Remaining validation

This WSL environment lacks `/dev/input`; `/dev/uinput` is inaccessible to the
current user. Actual keyboard grabbing, desktop remapping, and physical
reconnect behavior still require verification on a suitable Linux setup.
No kernel modules, group membership, or device permissions were changed.

## Pull request and CI

At initial report preparation, commit/push/PR and Actions verification are still
pending. Replace this status with observed links and results after publication.
The CI matrix is Python 3.10-3.13 and runs tests, build, and twine checks.

## Approval boundary

The user authorized commit, push, and PR creation only. **Do not merge to main
or enable auto-merge without separate explicit user approval.** Keep the local
checkout and remote branch available for review.
