# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Downloaded: 2026-07-01
Total issues downloaded: **108**

## Issue Split

- Markdown files: 54
- Python files: 54

## Markdown Findings

- `markdownlint_MD013`: 26 line-length findings.
- `markdownlint_MD032`: 9 list blank-line findings.
- `markdownlint_MD022`: 5 heading blank-line findings.
- `markdownlint_MD046`: 2 fenced-code style findings.
- `markdownlint_MD040`: 2 fenced-code language findings.
- `markdownlint_MD036`: 2 emphasis-used-as-heading findings.
- `markdownlint_MD012`, `MD023`, `MD041`, and `MD009`: 1 finding each.
- Agentlinter completeness/clarity checks: 4 findings.

Markdown files with findings:

- `codacy-reports/issues-summary.md`: 13
- `notes/incremental_save.md`: 12
- `notes/Lakeshore 625.md`: 9
- `TODO.md`: 8
- `.github/copilot-instructions.md`: 5
- `AGENTS.md`: 4
- `notes/motor-control.md`: 3

## Python Findings

- `Prospector_mccabe`: 21 complexity findings.
- `Semgrep_codacy.python.i18n.no-hardcoded-strftime`: 8 hardcoded date-format findings.
- `Prospector_pycodestyle`: 7 style findings.
- `PyLintPython3_W0404`: 6 re-import findings.
- `Prospector_pyflakes`: 2 findings.
- `PyLintPython3_C0200`: 2 `range(len(...))` findings.
- `Bandit_B102`: 2 `exec` findings.
- `PyLintPython3_W0108`: 2 unnecessary-lambda findings.
- `PyLintPython3_E0110`, `E1120`, `W0611`, and `W0612`: 1 finding each.

Top Python files with findings:

- `tests/test_magnet_control.py`: 3
- `tests/test_temperature_control.py`: 3
- `src/stoner_measurement/ui/widgets/round_dial.py`: 3
- `tests/test_new_ui_widgets.py`: 2
- `src/stoner_measurement/ui/plot_widget.py`: 2
- `src/stoner_measurement/ui/temperature_panel.py`: 2
- `tests/test_controller_state_plugins.py`: 2
- `src/stoner_measurement/plugins/trace/k6221_2182a.py`: 2
- `src/stoner_measurement/plugins/trace/k6221_multi_sr830.py`: 2
- `src/stoner_measurement/plugins/command/plot_points.py`: 2

## Fix Pass

The Markdown fixes in this pass targeted the files above. The Python issues were summarized only and left for
separate review because many are complexity, security, or behaviour-sensitive findings.
