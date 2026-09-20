# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Branch: `main`
Analyzed commit: `2ccb56bd42d4857f99065d9fbe33dde3534085ce`
Downloaded: 2026-09-20
Codacy analysis completed: 2026-09-20T20:08:45.243Z

## Refreshed baseline

The complete `--branch main --limit 1000` pull contains **45 issues**:
2 Error, 5 High, 22 Warning, and 16 Info. Codacy's repository overview also
reports 45 issues. The previous August snapshot contained 43 issues.

`issues.json` remains the authoritative remote snapshot. `issues.csv` contains
all 45 rows and a separate local disposition; its locations refer to the
analyzed commit, before the local edits.

## Local disposition

| Disposition                                    | Issues |
| ---------------------------------------------- | ------ |
| Code fixes or reviewed narrow suppressions     | 26     |
| Test-only complexity excluded by configuration | 8      |
| Guidance terminology and reference clarified   | 5      |
| Intentional guidance advisories retained       | 6      |

The expected remote remainder is **6 guidance advisories**, subject to Codacy
accepting the configuration, formatting and scoped suppressions on reanalysis.
No remote findings have been marked ignored, and these edits have not been
committed or pushed.

## Changes

- Shared DAQmx input/output trigger validation between trace and point-scan
  plugins; separated physical-channel checks from task-source selection.
  Validation order and error messages are preserved.
- Corrected the existing Prospector test exclusion from `tests/` to `tests/**`
  and added the same exclusion to the separate Codacy `metric` engine.
  Prospector's exclusion covers all its test checks, including McCabe; it is
  not a per-rule exclusion. Other analyzer settings were preserved.
- Kept test scenarios and fake-driver structures intact; no test complexity
  refactoring is retained.
- Replaced redundant lambdas, clarified the required concrete Keithley point
  class, renamed ambiguous fit-function current arguments, fixed nested-function
  spacing, and kept overload bodies compatible with pycodestyle E704.
- Replaced the SR7265 empty-string comparison with equivalent string truthiness
  to avoid a false hardcoded-password report.
- Added narrow documented suppressions for trusted generated-code test execution
  and expression evaluation, deliberate fake-transport initialization, Qt's
  extension constructor, the SR830 concrete return value, and the documentation
  audit's shell-free Git invocation.
- Expanded guidance terminology and converted the existing, tracked Keithley
  design-note reference into a Markdown link.

## Retained advisories

Five Agentlinter escape-hatch suggestions conflict with intentional lifecycle,
held-DC and supported-Conda requirements. Those requirements remain unchanged.
The modular-file advisory is retained because `AGENTS.md` is deliberately the
single maintainer entry point. Do not relax these contracts to satisfy a heuristic.

## Verification

- Final retained-change regression run: **485 passed**, one warning, using
  Python 3.14.7 and PyQt5 5.15.11 offscreen with Windows fonts.
- Ruff lint and formatting checks on changed Python files.
- Targeted Pylint and Bandit checks for the reported rules.
- pycodestyle E704, E741 and E306 checks on the affected production files.
- McCabe: all functions in the three changed DAQmx modules are at or below 15.
- Codacy YAML parsed and recursive Prospector/metric exclusions checked.
- `git diff --check`.

An earlier broader run passed 587 tests with one dependency-path skip, plus a
228-test plugin run. The initial broad attempt hit an existing Windows pytest
temporary-directory permission error; a fresh `--basetemp` resolved it.
Remote Codacy reanalysis, other Qt bindings, and physical hardware validation
remain unverified. Full-suite testing was not performed.

## Configuration reference

Codacy documents recursive `test/**` globs and the separate `metric` engine in
[its configuration reference](https://docs.codacy.com/repositories-configure/codacy-configuration-file/).
