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
- [Test report](docs/TEST_REPORT.md): 113 passing tests, build checks and hardware limits.
- [Progress](docs/PROGRESS.md): publication and CI status.
- [Changelog](CHANGELOG.md): user-visible changes.

Final review also fixed stale held-key ownership when the same service object
is run again; two regression cases cover normal exit and disconnection.
Do not repeat completed fixes unless a new reproducible defect is found.

## Verified locally

Python 3.14.4: 113 tests passed; pip check, build, twine check and diff whitespace
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

## Final review checkpoint

The final-review baseline is `68ed6b04b5f6f38c4e2cd9d7ea8fd9e74d20d035`.
[PR #1](https://github.com/HafizGD/Keyshift/pull/1) is open and mergeable against
`main` at `8f85b03e8916552aaad32a8bf840d034298ae7ac`; the branch is not behind
main (zero commits behind, four ahead at the start of final review).

[CI run 44662243060](https://github.com/HafizGD/Keyshift/actions/runs/44662243060)
passed all Python 3.10-3.13 jobs at that baseline. Fresh local verification on
Python 3.14.4 passed **111 tests, zero failures, in 0.25s**, pip check, an
isolated source/wheel build, twine validation of both artifacts, and full-PR
whitespace checks. Physical keyboard operation remains unverified.

Final independent review found a service-reuse regression and verified its
fix in `2820eba6f73703b35f3a86f4c58a13b043a4eb0e`. The two new tests failed
before the fix; all **113 tests passed in 0.25s** afterward. Source/wheel build,
twine, pip check, and whitespace validation passed again. The reviewer reran
the two cases plus held-key reload (3 passed) and found no remaining Important
or Critical issues. The new code awaits CI on the final documentation commit;
run 44662243060 above only verifies the earlier `68ed6b0` baseline.

Recheck CI for the final PR head before merging. After squash merge, verify the
main tree and its push-triggered CI, then record the merge evidence here and
in [PROGRESS.md](docs/PROGRESS.md). This checkpoint does not claim a merge.

## Historical publication checkpoint (superseded)

[PR #1](https://github.com/HafizGD/Keyshift/pull/1) is open from
`fix/audit-runtime-errors` to `main`; it has not been merged. On resumption,
local HEAD, the remote branch, and the PR head all matched
`e1ed7c93bf47bb56399f14b0438567cd460a024e` (three published commits).

[CI run 44593892075](https://github.com/HafizGD/Keyshift/actions/runs/44593892075)
completed successfully for that revision. All four Python 3.10-3.13 jobs passed
tests, distribution builds, and twine validation. Local revalidation on Python
3.14.4 also passed: 111 tests in 0.57s, pip check, and patch whitespace checks.

The old PR-creation blocker is historical: the PR already existed when this
session resumed. Do not recreate it or retry credential workarounds. See
[progress](docs/PROGRESS.md) for publication evidence. These results identify
the verified revision; verify the new PR head after any further push.

## Approval boundary

On 2026-11-20 the user explicitly authorized documentation updates, commit,
push, and **squash merge of PR #1 into main** once the final review and all
available/required checks pass. This supersedes the earlier no-merge boundary.
Respect GitHub branch rules and required reviews; never bypass checks. Preserve
the feature branch until the merge result has been verified. Record post-merge
results in this handover and the progress report.
