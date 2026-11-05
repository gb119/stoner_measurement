# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`

Branch: `main`

Analysed commit: `1017a05c26f36712c88a99c5744d8319fe117ad2`

Analysis completed: 2026-11-05T21:37:59.816Z

## Remote inventory and local fixes

The latest issue pull and repository metadata both report **zero active
issues** after hosted analysis of the source-fix commit above. All three
findings from the preceding inventory are verified cleared.

| Finding | Resolution |
| --- | --- |
| Markdownlint MD012 in the 3 November cleanup note | Removed the extra blank line before a heading |
| Bandit B102 in the preflight regression test | Documented line-scoped suppression for trusted generated code |
| Pylint W0122 on the same test statement | Documented line-scoped suppression for the same intentional execution |

The test executes application-generated sequence code to verify that invalid
configuration blocks connections, including inside a nested sequence. Keeping
this execution preserves the ordering regression. No external code or user
input is executed by the test, and no remote ignore states or global analysis
exclusions were changed.

## Evidence

- `issues.json` and `repository.json` contain the downloaded remote snapshot.
- `issues.csv` contains the active inventory (header only).
- `resolved-issues.csv` preserves all eight findings resolved across the
  3 November and 5 November cleanups, with their verified source-fix commits.
- Ruff check/format, targeted Pylint `W0122,W0012` and Bandit B102 pass for
  the edited Python files.
- The 12 preflight tests pass on Python 3.12.14 and 3.14.7 with offscreen
  PyQt5, including eight additional expression scope cases for the CI repair.
- The full Python 3.12 suite passed: 4,238 passed, two skipped in 240.29 seconds.

The source repair also fixes a Python 3.12 comprehension-local
misclassification in preflight validation. A separate intermittent PyQtGraph
crash in the hosted function-widget tests prompted a follow-up migration to
managed Qt teardown; this does not change the verified Codacy result above.
The follow-up passed all 4,238 tests (two skipped) with coverage on Python
3.14/PyQt5, preserving the full 4,240-test collection.
