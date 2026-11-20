# Test report

Verification date: 2026-11-20 (Asia/Bangkok).
Branch: `fix/audit-runtime-errors`; baseline: `8f85b03`.

## Environment

- WSL Ubuntu; existing project virtual environment, Python 3.14.4.
- Tests run from the repository root using `.venv/bin/python`.
- Builds used isolated build environments and temporary output directories.
- CLI mutation checks used temporary XDG configuration/state directories.

## Final review verification after the additional regression fix

Implementation commit: `2820eba6f73703b35f3a86f4c58a13b043a4eb0e`.
Two service-reuse cases failed before the fix (normal exit and disconnection),
both because the second run emitted only B up instead of B down then B up.
Resetting held-key ownership at the start of run fixes the stale state while
preserving it during in-session configuration reloads.

After the fix: **113 passed, zero failed, in 0.25s**, on Python 3.14.4.
Dependency consistency, isolated source/wheel builds, twine validation of both
artifacts, and whitespace checks were rerun and passed. Independent review
verified both new cases and the existing held-key reload case (3 passed),
with no remaining Important or Critical findings.

Final PR head `664f50617b8570915bfee7f661584bd0c6fb2589` subsequently passed
[CI run 44663810657](https://github.com/HafizGD/Keyshift/actions/runs/44663810657).
Jobs 136048143852 (3.10), 136048143950 (3.11), 136048144072 (3.12), and
136048144096 (3.13) all completed successfully, including tests and
build/twine steps. The merge request was denied by the connector (HTTP 403),
so no post-merge main verification is claimed. Later documentation pushes
need their own CI verification before merging.

## Initial final-review checkpoint (before the additional fix)

Verified code baseline: `68ed6b04b5f6f38c4e2cd9d7ea8fd9e74d20d035`.
All commands below were rerun for the final review on 2026-11-20.

| Check | Result |
| --- | --- |
| Complete pytest suite, Python 3.14.4 | **111 passed, 0 failed, in 0.25s** |
| pip check | No broken requirements |
| Isolated source and wheel build | Both built successfully |
| twine check | Both distributions PASSED |
| git diff --check origin/main...HEAD | Passed |
| Branch comparison | 0 commits behind main, 4 ahead before final documentation |
| Physical keyboard access | `/dev/input` absent; `/dev/uinput` exists but is not readable/writable by this user |

[CI run 44662243060](https://github.com/HafizGD/Keyshift/actions/runs/44662243060)
completed successfully for that exact baseline. All four jobs and their tests,
distribution builds, and twine checks passed:

| Python | Job ID | Result |
| --- | --- | --- |
| 3.10 | 136042993286 | Passed |
| 3.11 | 136042993269 | Passed |
| 3.12 | 136042992861 | Passed |
| 3.13 | 136042993191 | Passed |

CI must also pass for the new documentation commit before merge and for main
after merge. Those later results will be recorded in the final merge record.

## Historical local results (previous session)

| Check | Command or scenario | Observed result |
| --- | --- | --- |
| Complete suite | `.venv/bin/python -m pytest -q` | **111 passed in 0.57s**, exit 0, during resumed-session verification. |
| Dependencies | `.venv/bin/python -m pip check` | `No broken requirements found.`, exit 0. |
| Distribution build | `.venv/bin/python -m build --outdir <temporary-dist>` | Source archive and wheel built, exit 0. |
| Distribution validation | `.venv/bin/python -m twine check <temporary-dist>/*` | Both artifacts PASSED, exit 0. |
| Patch whitespace | `git diff --check` | No errors. |
| Version | `keyshift --version` | `keyshift 0.1.0`, exit 0. |
| Empty JSON | `keyshift list-devices --json` | `[]`, exit 0. |
| Diagnosis | `keyshift doctor` | Dependencies/configuration OK; input/uinput warnings, exit 0. Warnings are not hardware readiness. |
| Bounded service startup | `keyshift run --device 1 --timeout 2` | Exit 1 with actionable missing-keyboard guidance; physical service startup blocked by the environment. |

## Regression history

Before fixes, the original suite had 85 passing tests. Adding 26 regression and
compatibility cases produced **25 failed, 86 passed** before implementation.
After implementation, all **111** passed (earlier verifications: 0.34s and
0.25s; resumed-session verification: 0.57s). The one added case that already
passed checks reset compatibility; the new failure run demonstrated the five
defects and related missing-device error.

Coverage includes repeated macros without stopping input processing, shared key
target ownership, remap reload/reset, global/profile source aliases, invalid
YAML keys and backup/recovery, read-only diagnosis, empty JSON with warnings,
and empty device selection. See [FIX_REPORT.md](FIX_REPORT.md) for exact tests.

The earlier manual CLI regression run also verified profile create/activate/delete,
latest-alias-wins mapping, unmap, malformed-YAML diagnosis without mutation, and
status recovery with the original invalid contents in `.bak`. Those cases are
also covered by the freshly rerun suite.

## Physical-keyboard limitation

`/dev/input` is absent in this WSL environment. `/dev/uinput` exists but is not
read/write accessible to the current user. `/sys/module/uinput` was not present;
that observation alone is not proof that the kernel lacks support.

No physical keyboard events were captured, no real keyboard was grabbed, and
no actual desktop remapping was validated. Input/output behavior was tested
through simulated hardware and real processing logic. Tests/build success does
not establish real-device operation. Verification on an environment exposing a
readable keyboard event node and writable uinput remains outstanding.

## Historical GitHub Actions evidence (superseded)

The repository CI workflow runs tests, builds distributions, and runs twine on
Python **3.10, 3.11, 3.12, and 3.13** for pull requests targeting `main`.
Local Python 3.14 testing is additional evidence, not a substitute for this matrix.
The feature-branch push alone does not trigger the current push filter, which is
restricted to `main`; opening the PR triggers the matrix.

On resumption, [PR #1](https://github.com/HafizGD/Keyshift/pull/1) was already
open with head `e1ed7c93bf47bb56399f14b0438567cd460a024e`, matching local HEAD
and the remote branch. The earlier PR-creation failures are historical.

[CI run 44593892075](https://github.com/HafizGD/Keyshift/actions/runs/44593892075)
was fetched for that commit and reported `completed` / `success`. Job-level
verification confirmed:

| Python | Job ID | Tests | Build and twine |
| --- | --- | --- | --- |
| 3.10 | 135806895354 | Passed | Passed |
| 3.11 | 135806896234 | Passed | Passed |
| 3.12 | 135806895998 | Passed | Passed |
| 3.13 | 135806896026 | Passed | Passed |

The legacy commit-status list remained empty; success is supported by the
completed workflow and all four jobs. Fresh local verification on Python
3.14.4 also passed all 111 tests in 0.57s, pip check, and patch whitespace
checks. CI evidence above applies to the recorded revision; check the latest
PR head again after any subsequent push. See [PROGRESS.md](PROGRESS.md).
