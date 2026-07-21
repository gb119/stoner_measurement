# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Downloaded: 2026-07-21

## Refresh Status

- Codacy auth probe succeeded on 2026-07-21.
- Fresh issue download completed with `--branch main --limit 1000`.
- Local raw snapshot: `codacy-reports/issues.json`

## Snapshot Totals

- Total issues downloaded: **70**
- Severity split:
  - `High`: 1
  - `Warning`: 40
  - `Info`: 29

## Category Split

- `Complexity`: 25
- `CodeStyle`: 24
- `BestPractice`: 10
- `Security`: 5
- `UnusedCode`: 4
- `ErrorProne`: 1
- `Comprehensibility`: 1

## Highest-Severity Findings

### Error

- None in the current snapshot.

### High

- `tests/unit/instruments/contracts/test_mass_flow_controller_contracts.py:15`
  - `PyLintPython3_E0110`
  - `Abstract class 'MassFlowController' with abstract methods instantiated`

## Largest Warning Buckets

- `Prospector_mccabe`: 25 complexity findings
- `Semgrep_codacy.python.i18n.no-hardcoded-strftime`: 10 findings
- `Prospector_pycodestyle`: 10 style findings
- `Bandit`: 5 security findings
- `PyLintPython3_W0612`: 3 unused-variable findings
- `PyLintPython3_W0108`: 3 unnecessary-lambda findings

## PEP8 Style Findings

The 10 current `Prospector_pycodestyle` findings split into two groups:

- Likely ignorable PyQt naming conventions:
  - `src/stoner_measurement/qt_compat.py:5` — `pyqtSignal`
  - `src/stoner_measurement/qt_compat.py:6` — `pyqtSlot`
  - `src/stoner_measurement/ui/widgets/round_dial.py:77` — `valueChanged`
  - `src/stoner_measurement/ui/widgets/visa_resource_widget.py:236` — `currentTextChanged`
  - `src/stoner_measurement/ui/widgets/si_combo_box.py:76` — `valueChanged`
  - `src/stoner_measurement/ui/widgets/percent_slider.py:48` — `valueChanged`
- Real style issues still worth fixing:
  - `src/stoner_measurement/plugins/trace/keithley_2400.py:1040` — `E131` hanging indent
  - `tests/unit/instruments/contracts/test_base_instrument_core.py:117` — `E305` missing blank lines
  - `tests/unit/instruments/contracts/test_lockin_amplifier_exports.py:36` — `E305` missing blank lines
  - `src/stoner_measurement/plugins/trace/base.py:594` — `E306` missing blank line before nested definition

For the mixed-case signal names, the current assessment is that they reflect
normal Qt/PyQt API style and are better handled as explicit ignores than by
renaming public signal attributes.

## Top Files By Issue Count

- `tests/test_magnet_control.py`: 4
- `src/stoner_measurement/ui/widgets/round_dial.py`: 3
- `tests/test_temperature_control.py`: 3
- `src/stoner_measurement/qt_compat.py`: 2
- `tests/unit/instruments/contracts/test_temperature_controller_contracts.py`: 2
- `src/stoner_measurement/plugins/trace/k6221_2182a.py`: 2
- `src/stoner_measurement/plugins/trace/keithley_2400.py`: 2
- `src/stoner_measurement/ui/plot_widget.py`: 2

## Coverage Overlap

The current Codacy snapshot overlaps with several of the July 21 coverage
cold-spots:

- `src/stoner_measurement/ui/widgets/round_dial.py`
- `src/stoner_measurement/ui/plot_widget.py`
- `src/stoner_measurement/ui/magnet_panel.py`

These are good candidates for paired refactor-plus-test passes because they
combine static-analysis debt with coverage debt.

## Immediate Plan

1. Clear the single `High` finding in `test_mass_flow_controller_contracts.py`.
2. Review the 5 Bandit findings and classify real defects vs intentional dynamic behavior.
3. Tackle the 10 `strftime` warnings with a shared formatting helper if the code paths align cleanly.
4. Mark the 6 PyQt mixed-case `Prospector_pycodestyle` findings as ignorable if Codacy suppression is desired.
5. Fix the remaining 4 real pycodestyle formatting issues in a small mechanical batch.
6. Chip away at the 25 complexity findings one module or test helper at a time.
7. Sweep the remaining `Info` findings in small mechanical cleanup batches.

## Best First Pass

The highest-leverage next tranche is:

- `tests/unit/instruments/contracts/test_mass_flow_controller_contracts.py`
- `src/stoner_measurement/pressure_control/engine.py`
- `src/stoner_measurement/core/sequence_engine.py`
- `src/stoner_measurement/plugins/transform/curve_fit.py`
- `src/stoner_measurement/scan/arbitrary_function_generator.py`

That pass would clear the only `High` finding and cover the current Bandit-backed warning set.
