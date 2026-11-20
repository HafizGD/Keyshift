# Initial audit

Date: 2026-11-20 (Asia/Bangkok). Baseline: `8f85b03e8916552aaad32a8bf840d034298ae7ac` on `main`.

This is a retrospective record of the observed state **before** the fixes on
`fix/audit-runtime-errors`. It preserves the original audit evidence; it is
not a claim that the fixed branch still has these failures.

## Baseline checks

- Python 3.14.4 in the existing WSL Ubuntu `.venv`.
- Original automated suite: **85 passed in 0.19s**.
- CLI version/help/status opened successfully; package version was 0.1.0.
- Source distribution and wheel built; `twine check` passed for both.
- The passing suite did not cover the five reproduced cases below.

## Confirmed defects

| ID | Trigger before the fix | Observed result | Impact |
| --- | --- | --- | --- |
| KSH-001 | Trigger `F1+F2 -> action:macro:slow` twice while a macro with a delay is still running. | `MacroAlreadyRunningError: Macro 'slow' is already running.` escaped the service; the service stopped and closed its output. | An ordinary repeated shortcut ended remapping. |
| KSH-002 | Configure `A -> B`; press A, press B, release A while B remains held. | Output was `B down, B down, B up`. | B was released before its remaining physical source was released. |
| KSH-003 | Run `remap a B`, `remap A C`, then `remap a D`. | All commands reported success, but configuration retained `{'a': 'D', 'A': 'C'}` and the engine resolved A to C. | The most recent user request was ignored because aliases occupied separate entries. |
| KSH-004 | Put `1: invalid` in `config.yaml`, then run `doctor` or `status`. | Both exited with `TypeError: sequence item 0: expected str instance, int found`. | Diagnostics and normal backup/recovery were bypassed by the exception. |
| KSH-005 | Run `list-devices --json` with no keyboards discovered. | Exit 0 with `No keyboard devices found.` on stdout. | Consumers expecting JSON could not parse successful output. |

Macro and key event failures were reproduced through the real service pipeline
with simulated input/output. The CLI/configuration failures used temporary XDG
paths so the user's actual configuration was not changed.

## Environment limitation, separate from the five defects

The audited WSL environment had no `/dev/input` directory. `/dev/uinput`
existed but was inaccessible for read/write by the current user; the uinput
module was not detected under `/sys/module/uinput`.

`keyshift run --device 1 --timeout 2` exited 1 before opening a keyboard, with
the misleading message `choose a number from 1 to 0`. `doctor` reported device
warnings. Therefore physical keyboard grabbing, real output, device reconnect,
and actual desktop behavior were not validated. A missing module-directory
entry alone does not prove that the kernel lacks uinput support.

See [FIX_REPORT.md](FIX_REPORT.md) for changes and [TEST_REPORT.md](TEST_REPORT.md)
for regression and current verification evidence.
