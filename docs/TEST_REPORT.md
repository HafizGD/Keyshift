# Test report

Verification date: 2026-11-20 (Asia/Bangkok).
Branch: `fix/audit-runtime-errors`; baseline: `8f85b03`.

## Environment

- WSL Ubuntu; existing project virtual environment, Python 3.14.4.
- Tests run from the repository root using `.venv/bin/python`.
- Builds used isolated build environments and temporary output directories.
- CLI mutation checks used temporary XDG configuration/state directories.

## Results

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

## GitHub Actions

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
