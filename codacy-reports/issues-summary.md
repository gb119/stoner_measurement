# Codacy Issues Summary

Repository `gh/gb119/stoner_measurement`, branch `main`

Remote analysed commit `a43190d39da09248a4c3a5a044b1631b92af0ef7`

Analysis completed at `2026-11-23T20:47:37.818Z`.

## Current result

The commit passed the Codacy quality gate with zero new issues and six fixed
issues. The commit's issue delta marks all six as `Fixed`. The `main` branch
has grade A, and its complete issue search returned zero active issues and no
next cursor. [Codacy commits](https://app.codacy.com/gh/gb119/stoner_measurement/commits)

## Resolved findings

Bandit `B102` and Pylint `W0122` each flagged the same three test-only `exec()`
calls at the following lines in the parent commit.

- `tests/unit/plugins/monitor/test_monitor_plugin.py`, line 128. The success
  test runs the generated monitor action on the sequence engine and checks
  the returned reading, cache and single signal emission.
- `tests/unit/plugins/monitor/test_monitor_plugin.py`, line 179. The failure
  test runs the generated action on the engine and checks the reported error,
  the last successful reading and the absence of another reading signal.
- `tests/unit/plugins/state/test_execution_parity.py`, line 80. The scan and
  sweep tests run a full generated sequence through the engine and verify
  data collection, child failures and disconnection against direct execution.

The [resolution history](resolved-issues.csv) records all six findings with
their original Codacy result IDs, fix commit and analysis timestamp.

## Verified CI and coverage

- GitHub Actions run `45262950792` passed on `a43190d`. All four combinations
  of Python 3.12 and 3.14 with PyQt5 and PyQt6 passed. The coverage job passed
  and uploaded the merged report to Codacy.
  [GitHub Actions run](https://github.com/gb119/stoner_measurement/actions/runs/45262950792)
- Codacy reports **87.41% coverage** for `a43190d`, above the repository's
  85% goal. Its latest coverage record is up to date and references the same
  SHA. [Codacy coverage](https://app.codacy.com/gh/gb119/stoner_measurement/coverage)
- All 168 focused monitor and state plugin tests passed locally on Python
  3.14.7 with PyQt5. Ruff, targeted Bandit `B102` and Pylint `W0122` also passed.
