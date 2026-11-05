# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`

Branch: `main`

Analysed commit: `0a7f2d5f36d3aa459047752a26b1a006c451614f`

Analysis completed: 2026-11-05T18:04:48.536Z

## Remote inventory and local fixes

The latest issue pull and repository metadata both report **three active
issues**. All three have local fixes; remote reanalysis is pending.

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
- `issues.csv` records the three findings and their local dispositions.
- `resolved-issues.csv` preserves the five previously resolved findings and
  their verified source-fix commit from 3 November.
- Ruff check/format, targeted Pylint `W0122,W0012` and Bandit B102 pass for
  the edited Python files.
- The 12 preflight tests pass on Python 3.12.14 and 3.14.7 with offscreen
  PyQt5, including eight additional expression scope cases for the CI repair.
- The full Python 3.12 suite passed: 4,238 passed, two skipped in 240.29 seconds.

The current source repair also fixes a Python 3.12 comprehension-local
misclassification in preflight validation. Hosted CI and Codacy must analyse
the pushed repair before remote clearance can be claimed.
