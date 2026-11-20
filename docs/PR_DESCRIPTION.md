# Fix audited runtime and CLI defects with regression coverage

Repeated macro shortcuts could stop remapping, shared targets could release
too early, and source aliases could ignore the latest mapping. Invalid YAML
field names crashed validation/recovery, and successful empty JSON device
listings emitted prose. Final review also reproduced a service-reuse
regression: a stale held key suppressed the first press on the next run.

This PR fixes the five audited defects, clears held-key ownership at the
start of a new service run, and gives actionable missing-device guidance.
In-session configuration reloads continue to preserve held-key pairing.
The original 85 tests plus 28 regression/compatibility cases now total 113.

Validation: 113 local tests passed on Python 3.14.4; pip check, isolated
source/wheel builds, twine validation, and whitespace checks passed. The two
service-reuse cases failed before their fix. Independent final review
verified that fix and found no remaining Important or Critical issues.
See docs/TEST_REPORT.md and docs/PROGRESS.md for revision-specific CI evidence.

Physical keyboard grabbing, actual uinput output, desktop remapping, and
physical reconnect remain unverified: WSL has no /dev/input and no usable
uinput access. No device permissions or kernel settings were changed.

CI run 44664181017 passed all four Python 3.10-3.13 jobs on commit 976b783,
including tests and distribution build/twine checks. Fresh local verification
passed 113 tests. See the current PR checks for any later documentation update.

This handover stops at the open PR and verified CI. Do not infer permission to
merge from the approval to use Git-helper authentication for PR/CI requests.
No merge, auto-merge, release version change, or package publication is included.
