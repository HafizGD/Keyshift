# Audit fixes implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Fix the five reproduced audit bugs and rerun the application.
**Architecture:** Preserve the existing CLI and pipeline. Ignore duplicate active macro requests, retain shared key targets until the last release, replace remap aliases by resolved source, validate YAML field names, and keep JSON machine-readable.
**Tech Stack:** Python >=3.10, Typer, evdev, PyYAML, pytest.
**Spec:** The five reproduced findings in the conversation and the request to fix them all and run again.

## Constraints and decisions

- The initial implementation used a local fix branch. The user subsequently authorized commit, push, and PR creation targeting main, with no merge.
- Exercise real service logic with simulated input/output; use temporary configuration directories.
- Ignore duplicate macro triggers while preserving the existing execution.
- Preserve held-key pairing across configuration reload and device reset.
- Keep doctor read-only and retain backup/recovery during ordinary configuration loading.
- Missing Linux input devices are an environment constraint; provide an actionable startup error.

## Tasks

- [x] Add regression tests and observe failures for every reproduced bug.
- [x] Handle macro retriggers in service.py; test that subsequent input still works.
- [x] Retain shared outputs in mapping_engine.py; test release order, repeat, reload, and reset.
- [x] Replace aliases in cli.py; test default and active profiles.
- [x] Validate YAML keys in config_manager.py; test root, metadata, steps, state, recovery and diagnostics.
- [x] Fix empty JSON and empty device selection; test warnings stay on stderr.
- [x] Run pytest, build, twine check, pip check, CLI regression checks and bounded startup.
- [x] Obtain independent review and address material findings with regression tests.

## Review focus

Duplicate macros must not overlap or hide unrelated failures. Shared targets must survive either release order and remap changes. Case and KEY_ aliases must replace old entries. Non-string YAML keys must not escape as TypeError. Empty JSON must remain parseable with warnings.

## Verification record

Baseline audit: 85 tests passed; CLI and build succeeded. Physical input unavailable in this WSL environment.

Regression baseline: 25 new failures reproduced; 86 tests passed (including reset compatibility). Implemented the five fixes and actionable missing-device error.

Final verification on Python 3.14.4:
- Full pytest suite: 111 passed (0.34s), including 26 additional cases.
- Build: source distribution and wheel succeeded; twine check passed for both.
- pip check: no broken requirements. git diff --check: clean.
- CLI: version/help, empty JSON, profile lifecycle, alias replacement, unmap,
  malformed-YAML doctor and status recovery all verified in temporary XDG directories.
- Bounded service startup: attempted with --device 1 --timeout 2; correctly
  reported no Linux keyboard devices. Physical remapping remains unverified:
  /dev/input is absent and /dev/uinput is inaccessible to the current user.
- Independent read-only review: approved; no critical or important findings.
  The plan checklist completion note from review is addressed here.
- At the end of the initial implementation, changes were uncommitted. Publication and subsequent verification are tracked in [PROGRESS.md](../../PROGRESS.md).
