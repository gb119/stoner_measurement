# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Branch: `main`
Analyzed commit: `81367a75586d6c6084fa522e080bd42d0364a417`
Downloaded: 2026-08-09

## Refresh Status

- Codacy authentication succeeded.
- `HEAD` and `origin/main` matched the analyzed commit when refreshed.
- The issue list was downloaded with `--branch main --limit 1000`.
- `codacy-reports/issues.json` is the authoritative 31-issue raw snapshot.
- `codacy-reports/issues.csv` was regenerated from the same snapshot.

## Snapshot Totals

- Total: **31** (previously 35; net reduction of 4)
- `Error`: **0**
- `High`: **0**
- `Warning`: **30** (previously 32)
- `Info`: **1** (previously 3)

## Category and Pattern Split

- `Complexity` / `Prospector_mccabe`: 25
- `BestPractice`:
  - `Semgrep_codacy.python.i18n.no-hardcoded-strftime`: 4
  - `Agentlinter_structure_modular-files`: 1
- `CodeStyle` / `PyLintPython3_W0404`: 1

## Exact Delta From The 35-Issue Snapshot

Codacy retired eight previous result IDs and created four new result IDs.

Cleared:

- 2 plot-points complexity findings:
  - `PlotPointsCommand.sequence_engine`: previous complexity 17
  - `PlotPointsCommand._build_y_series_section`: previous complexity 35
- 2 redundant imports:
  - `tests/test_magnet_control.py`: `MagnetLimits`
  - `tests/unit/plugins/trace/test_trace_plugin.py`: `pandas`
- 4 previous timestamp result IDs at their old line numbers.

New IDs:

- 4 `no-hardcoded-strftime` results at the same four configuration backup
  statements, shifted down one line by their explanatory comments.

These four are regenerated copies of the previous false-positive rule/file
pairs, not four new code defects. The rule-specific `nosemgrep` identifiers
were not recognised by Codacy. A plain line-scoped `# nosemgrep`, with the
rationale retained on the preceding line, is the next suppression attempt.

The remaining `W0404` is another local `numpy` import in
`tests/unit/plugins/trace/test_trace_plugin.py`. Its Codacy result ID persisted
while the reported line moved from the removed duplicate at line 186 to the
still-present duplicate now at line 234. Remove that import mechanically.

## Pending Working Tranche

The following changes have been completed locally but are not part of the
downloaded 31-issue snapshot yet:

- replaced all four rule-specific timestamp directives with plain,
  line-scoped `# nosemgrep` markers;
- removed the remaining redundant local `numpy` import;
- reduced `PlotTraceCommand.sequence_engine` below the McCabe threshold;
- reduced the four small production helpers below the McCabe threshold:
  - `TraceChannelSelectionMixin._wire_data_source_widgets`;
  - `PressureControllerEngine._build_state`;
  - `StatePlugin.collect`;
  - `_IPythonConsoleWidget._shutdown_kernel`.

If Codacy accepts the four plain suppressions and introduces no replacement
findings, the next snapshot should contain 21 issues: 20 complexity findings
and the single Agentlinter advisory.

## Priorities After Reanalysis

### P1: shared or visual UI construction

- `plugins/base_plugin.py::_general_config_widget` (22)
- `ui/plot_widget.py::axis_changes` (22)
- `ui/plot_widget.py::_open_axes_dialog` (23)
- `ui/widgets/round_dial.py::_preferred_label_values` (17)

These have wider UI impact and need concrete widget/interaction regression
checks, so they follow the narrower production helpers.

### P2: hardware trace-plugin complexity

The Keithley trace configuration methods range from 17 to 36. Refactor them
only one method at a time, preserving configuration, restoration, trigger,
and hardware-protocol boundaries. Unit tests cannot replace live instrument
validation for timing behaviour.

### P3: test-only complexity

The eight test/helper McCabe findings are lowest priority unless they impede
maintenance or conceal duplicated setup. They do not affect runtime behaviour.

## Import Policy

- Prefer ordinary eager module-level imports.
- Keep `TYPE_CHECKING` imports for annotation-only dependencies.
- Keep runtime discovery/imports for plugins, drivers, resources, and genuine
  optional dependencies.
- Retain function-local imports only for demonstrated cycles, optional
  dependencies, or deliberate test import-state behaviour.
- Profile import cost before adopting Python 3.15 explicit lazy imports.
