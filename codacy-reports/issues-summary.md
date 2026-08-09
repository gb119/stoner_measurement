# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Branch: `main`
Analyzed commit: `7dbb0426b502ff28e1dcfaa4918ee26c987dfaf5`
Downloaded: 2026-08-09

## Refresh Status

- Codacy authentication succeeded.
- `HEAD` and `origin/main` matched the analyzed commit when refreshed.
- The issue list was downloaded with `--branch main --limit 1000`.
- `codacy-reports/issues.json` is the authoritative raw snapshot.
- `codacy-reports/issues.csv` was regenerated from the same 35 issues.

## Snapshot Totals

- Total: **35** (previously 57; down 22)
- `Error`: **0** (previously 1)
- `High`: **0** (previously 2)
- `Warning`: **32** (previously 34)
- `Info`: **3** (previously 20)

## Category Split

- `Complexity`: 27
- `BestPractice`: 5
- `CodeStyle`: 3

All Security, ErrorProne, and UnusedCode findings cleared. The Pylint/Bandit
false-positive markers were recognized, as were the genuine style and
unused-code fixes.

## Current Pattern Split

- `Prospector_mccabe`: 27
- `Semgrep_codacy.python.i18n.no-hardcoded-strftime`: 4
- `PyLintPython3_W0404`: 3
- `Agentlinter_structure_modular-files`: 1

## Changes Since This Snapshot

The three remaining `W0404` findings were confirmed as redundant imports and
removed locally after the download:

- `tests/test_magnet_control.py`: duplicate `MagnetLimits`
- `tests/unit/plugins/trace/test_trace_plugin.py`: duplicate `numpy`
- `tests/unit/plugins/trace/test_trace_plugin.py`: duplicate `pandas`

The four timestamp lines already had Semgrep markers, but the rule ID was
followed by prose on the same directive. They now use an exact
`# nosemgrep: semgrep_codacy.python.i18n.no-hardcoded-strftime` directive with
the rationale on the preceding line. This should give Codacy an unambiguous
rule-specific suppression on the next analysis.

`AGENTS.md` is 107 lines and contains one cohesive repository instruction set.
The Agentlinter modular-file finding is a low-priority advisory rather than a
runtime or maintenance defect; no source suppression has been added without a
documented Agentlinter suppression mechanism.

## Import Policy

- Prefer ordinary eager module-level imports.
- Keep `TYPE_CHECKING` imports for annotation-only dependencies.
- Keep runtime discovery/imports for plugins, drivers, resources, and genuine
  optional dependencies.
- Retain function-local imports only for demonstrated cycles, optional
  dependencies, or deliberate test import-state behaviour.
- Profile import cost before adopting Python 3.15 explicit lazy imports.

## Plot-Points Complexity Tranche

Completed locally after this snapshot:

- `PlotPointsCommand._build_y_series_section`: McCabe **35 -> 2**.
- `PlotPointsCommand.sequence_engine`: McCabe **17 -> 3**.
- Signal wiring now uses one declarative binding table and a shared
  connect/disconnect helper.
- The Y-series editor now separates widget creation, layout, signal binding,
  and configuration updates into focused helpers; no extracted function has
  McCabe complexity above 6.
- Added behaviour-level interaction coverage for editing every Y-series field
  and rebuilding the grid after add/remove operations.

Verification:

- Ruff check and format check passed.
- Targeted Pylint complexity/error checks: 10.00/10.
- Focused plot-points tests: 38 passed.
- Full command-plugin tests: 286 passed, 1 optional-path test skipped.

Together with the local reimport and Semgrep changes, a successful Codacy
reanalysis should remove nine findings from the 35-issue raw snapshot without
introducing a replacement complexity hotspot. Refresh Codacy before selecting
the next complexity target.
