# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Branch: `main`
Analyzed commit: `124beb3fdae5aeb50ae88b1c36073887568b1eb2`
Codacy analysis completed: 2026-09-22T09:56:05.656Z
Downloaded: 2026-09-23 22:13 UTC

## Current remote snapshot

The complete `--branch main --limit 1000` pull contains **19 issues**:
12 Warning and 7 Info. The prior snapshot from
20 September contained 45 issues. `issues.json` is the raw remote inventory;
`issues.csv` records each issue and its local disposition. Issue locations
refer to the analyzed commit, before the local edits below.

## Local disposition

| Disposition | Issues |
| --- | ---: |
| Production complexity refactored | 2 |
| Exact-integer contract with narrow Pylint suppression | 1 |
| Generated-expression tests with narrow Bandit suppressions | 2 |
| Markdown formatting corrected | 6 |
| Keithley LIST term defined | 1 |
| Intentional maintainer and hardware guidance retained | 7 |

The expected remote remainder is **7 Agentlinter advisories**, subject to
Codacy reanalysis. The six escape-hatch suggestions conflict with explicit
Conda, resource-ownership and held-DC contracts. The modular-file suggestion
conflicts with the deliberate single maintainer entry point. No issues were
marked ignored in Codacy.

## Fixes and verification

- Extracted supported ramp application and monitor loop restoration into
  cohesive helpers. Both flagged methods are below the local McCabe threshold
  of 15. The existing controller and sequence tests passed: **34 passed**
  offscreen under PyQt5, with one pytest cache warning.
- Preserved exact `int` validation for loop references, which deliberately
  rejects `bool` and subclasses; the scoped Pylint C0123 suppression passes.
- Kept expression execution in integration tests because those generated
  expressions are the runtime contract; scoped Bandit B307 suppressions pass.
- Fixed the six reported Markdown errors and three additional errors found by
  local Markdownlint in the touched notes. Markdownlint reports zero issues
  across the three touched Markdown files.
- Defined the Keithley 6221 `LIST` mode at first use while preserving
  the held-DC instruction.
- Ruff lint passed on changed Python files and `git diff --check` passed.
  Full-file Ruff formatting remains pre-existing work in the engine and monitor
  modules; formatting those whole files would add unrelated changes.

The checkout's HEAD matches the analyzed Codacy commit. The new local fixes
have not been committed or pushed, so their remote clearance is unverified.
Live hardware and other Qt bindings were not validated.
