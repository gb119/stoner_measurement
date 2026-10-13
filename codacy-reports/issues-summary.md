# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Branch: `main`
Analyzed commit: `12d943b269e830bf8292178e0ea0e6969ec72c17`
Codacy analysis completed: 2026-10-10T12:42:24.117Z
Downloaded: 2026-10-10 (UTC)

## Current remote snapshot

The complete `--branch main --limit 1000` pull contains **20 issues**:
1 Error, 1 High, 17 Warning and 1 Info. Repository metadata independently
reports the same count and analyzed commit, which matches local HEAD.
The prior snapshot contained 19 issues. `issues.json` is the raw remote inventory;
`issues.csv` records every issue and its local disposition. Locations refer to
the analyzed commit, before the local edits.

## Local disposition

| Disposition | Issues |
| --- | ---: |
| Production complexity refactored | 10 |
| Callable guard clarified for Pylint | 1 |
| Exception reference narrowed in test double | 1 |
| Intentional maintainer guidance retained | 7 |
| Already defined Keithley LIST term retained | 1 |

All **12 Python findings** are addressed locally. The expected remainder is
**8 Agentlinter advisories**, subject to Codacy reanalysis. Six escape-hatch
suggestions conflict with explicit Conda, resource-ownership, reconnect and
held-DC contracts. The modular-file suggestion conflicts with the deliberate
single maintainer entry point, which already links detailed guidance. `LIST`
is defined at first use as the Keithley programmed-current list mode; this
advisory is a false positive. No issues were marked ignored in Codacy, no
downloaded findings were suppressed, and no analysis exclusions were added.

## Fixes and verification

Extracted cohesive helpers for surface row/replay validation, display contract
validation and state replay, legacy request bookkeeping, Cartesian axes, and
plugin execution and control wiring. Validation order, failure cleanup, plot
acknowledgements, signals and saved settings retain their existing contracts.

| Flagged method | Before | After |
| --- | ---: | ---: |
| `CartesianPlotBridge.validate` | 17 | 12 |
| `CartesianPlotBridge.apply` | 17 | 15 |
| `PlotTraceCommand.execute` | 17 | 12 |
| `PlotTraceCommand._wire_config_signals` | 17 | 14 |
| `PlotPointsCommand.execute` | 16 | 7 |
| `SurfaceGrid.validate` | 20 | 12 |
| `SurfaceCanvasDisplay.validate` | 27 | 13 |
| `PlotDisplayHost._create` | 17 | 9 |
| `PlotDisplayHost.switch_display` | 16 | 12 |
| `PlotService._apply` | 17 | 13 |

Local McCabe inspection found no graph above 15 across the seven changed
production modules, including new helpers. The two Pylint findings were
analyzer-narrowing problems: split the replay importer's callable guard from
the exporter check, and use a local reference for the exception-valued test
factory. Runtime rejection and discovery behaviour remain covered by tests.

- **381 tests passed**, covering core surface/service transactions, registry,
  host and replacement failures, surface canvases, Cartesian plot/axis widgets,
  Plot Points/Trace/Markers, sequence plotting and display switching.
- Ruff lint and formatting checks passed on all eight changed Python files.
- Targeted Pylint `E0710,E1102,E1120` passed on all eight changed Python files.
- `git diff --check` passed.
- Tests used Python 3.14.7, PyQt5 5.15.11 and Qt 5.15.15, offscreen with Windows
  fonts, a fresh `--basetemp`, and `-p no:cacheprovider`.

The environment lacks a Codacy launcher. The cached official
`@codacy/codacy-cloud-cli` 1.12.1 entry point was run via
`CONDA_EXE run -n stoner_measurement node` to fetch issues and repository
metadata. JSON was parsed before replacing the raw inventory.

The changes are local and uncommitted. Remote Codacy clearance requires push
and reanalysis. Other Qt bindings, native OpenGL rendering and live hardware
were not validated in this maintenance batch; the full suite was not run.

See [the maintenance note](../notes/2026-10-10-codacy-cleanup.md) for reproduction.
