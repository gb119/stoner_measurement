# Codacy Issues Summary

Repository: gh/gb119/stoner_measurement, branch main

Remote analysed commit: 0c87f03eddd12dc643a3673689e6231ca6164981

Analysis completed: 2026-11-13T21:52:01.1Z

## Current result

Zero active remote findings, confirmed after pushing the source fixes.
The complete issue search returned total 0 with no next cursor; the repository
summary independently reports 0 issues for the source-fix commit.

| Findings | Local fix |
| --- | --- |
| Pylint W0611: unused VisaResourceStatus import (1) | Removed unused temperature-test import |
| Pylint W0404: transport reimports (2) | Reused module-level imports throughout the transport test module |
| Bandit B307: eval in lock-in test (1) | Used the existing asteval dependency with errors propagated; retained the numerical expression assertion |

No remote ignore states or analyser exclusions changed. The Bandit finding is
in a regression test evaluating a plugin-generated expression, with no external
input. Historical confirmed resolutions remain in resolved-issues.csv.

## Validation

- Latest main CI passed all four Python 3.12/3.14 and PyQt5/PyQt6 jobs plus
  coverage: GitHub Actions run 43471883445.
- All 278 tests in the five affected test modules passed locally on Python
  3.14.7/PyQt5 using offscreen Qt and a repository-local temporary directory.
- Ruff passed across src/tests/docs; six import/spacing findings fixed.
- Targeted Pylint W0611/W0404 and Bandit B307 passed.
- git diff --check passed.
- The usual Codacy client was unavailable in the Conda environment. Snapshots
  were retrieved from authenticated Codacy v3 issue-search and repository APIs;
  credentials were not included in reports.
- Remote reanalysis confirmed all four findings resolved in 0c87f03.
