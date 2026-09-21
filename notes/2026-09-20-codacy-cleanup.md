# Codacy cleanup — 20 September 2026

## Scope and baseline

Refreshed all 45 main-branch issues at commit
`2ccb56bd42d4857f99065d9fbe33dde3534085ce`. See
[the issue summary](../codacy-reports/issues-summary.md) and the per-issue CSV
for counts, disposition, validation and intentional deferrals.

The user's follow-up requested excluding tests from complexity checks. Corrected
the existing Prospector recursive glob and added the metric exclusion in
`.codacy.yaml`. Prospector excludes its entire test analysis; no global test
exclusion was added. Production complexity checks remain active.

## Production complexity after extraction

- `validate_task_definition`: 5.
- `_validate_physical_channels`: 14.
- `validate_input_trigger`: 4.
- `validate_output_trigger`: 8.
- `DaqmxTracePlugin._validate_configuration`: 6.
- `DaqmxPointScanPlugin._validate_configuration`: 6.

## Reproduction

Run through `conda run -n stoner_measurement` (using `CONDA_EXE` when set):

- `codacy issues gh gb119 stoner_measurement --branch main --limit 1000 --output json`
- `codacy repository gh gb119 stoner_measurement --output json`
- `ruff check <changed Python files>` and `ruff format --check <changed Python files>`
- `pylint --disable=all --enable=E1102,E1111,E1120,W0108,W0122,W0233 <changed Python files>`
- `bandit -q -t B102,B105,B307,B404,B603 <changed Python files>`
- `pycodestyle --select E704,E741,E306` on the sequence engine, RSJ function and
  Keithley 6221 point-scan module.

This machine lacked the `codacy` launcher and pycodestyle. Temporary official
npm/CLI and pycodestyle installations were used through the Conda environment;
project dependencies were not changed. Sandbox process startup also failed, so
commands ran through approved escalation.

Final pytest targets (485 passed) were the changed command/state/runtime/driver/
transport tests, state sweep and new UI widget tests, both DAQmx plugins and the
DAQmx set command, Multi-SR830 and curve-fit tests. Use `QT_QPA_PLATFORM=offscreen`,
`QT_QPA_FONTDIR=C:\Windows\Fonts` and a fresh temporary `--basetemp` directory.

## Remaining work

Push/reanalyze through the normal review workflow to verify that Codacy accepts
the exclusions and suppressions; do not describe the local expected count as a
remote result. Retain the six intentional Agentlinter advisories. No instrument
protocol or physical hardware operation was changed or bench-tested.
