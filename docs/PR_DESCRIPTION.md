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

The user authorized squash merge after the latest PR CI succeeds. Respect
all GitHub branch rules and required reviews; verify main and its CI after
merge. No release version or package publication is included.
