# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Downloaded: 2026-07-17

## Refresh Status

- Codacy auth probe succeeded on 2026-07-17.
- Fresh issue download completed with `--limit 1000`.
- Local raw snapshot: `codacy-reports/issues.json`

## Snapshot Totals

- Total issues downloaded: **85**
- Severity split:
  - `Error`: 1
  - `High`: 9
  - `Warning`: 41
  - `Info`: 34

## Category Split

- `Complexity`: 25
- `CodeStyle`: 25
- `BestPractice`: 16
- `ErrorProne`: 10
- `UnusedCode`: 4
- `Security`: 4
- `Documentation`: 1

## Highest-Severity Findings

### Error

- `tests/test_new_ui_widgets.py:299`
  - `PyLintPython3_E1120`
  - `No value for argument 'cls' in classmethod call`

### High

- `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py:39`
  - `PyLintPython3_E0110`
  - `Abstract class 'TemperatureController' with abstract methods instantiated`
- `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py:43`
  - `PyLintPython3_E0110`
  - `Abstract class 'MagnetController' with abstract methods instantiated`
- `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py:47`
  - `PyLintPython3_E0110`
  - `Abstract class 'SourceMeter' with abstract methods instantiated`
- `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py:51`
  - `PyLintPython3_E0110`
  - `Abstract class 'CurrentSource' with abstract methods instantiated`
- `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py:55`
  - `PyLintPython3_E0110`
  - `Abstract class 'DigitalMultimeter' with abstract methods instantiated`
- `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py:59`
  - `PyLintPython3_E0110`
  - `Abstract class 'Nanovoltmeter' with abstract methods instantiated`
- `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py:63`
  - `PyLintPython3_E0110`
  - `Abstract class 'Electrometer' with abstract methods instantiated`
- `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py:67`
  - `PyLintPython3_E0110`
  - `Abstract class 'LockInAmplifier' with abstract methods instantiated`
- `tests/test_motor_controller.py:24`
  - `PyLintPython3_E0110`
  - `Abstract class 'IncompleteMotorController' with abstract methods instantiated`

## Largest Warning Buckets

- `Prospector_mccabe`: 25 complexity findings
- `Semgrep_codacy.python.i18n.no-hardcoded-strftime`: 10 findings
- `Bandit`: 3 findings
- `Agentlinter_structure_modular-files`: 1 finding
- `markdownlint_MD024`: 1 finding

## Top Files By Issue Count

- `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py`: 9
- `notes/Leybold Centre-three.md`: 4
- `tests/test_magnet_control.py`: 4
- `src/stoner_measurement/ui/widgets/round_dial.py`: 3
- `tests/test_temperature_control.py`: 3
- `notes/eurotherm.md`: 3

## Immediate Plan

1. Fix the 10 `Error` and `High` findings first.
2. Clear the 34 `Info` findings in small mechanical batches.
3. Review the 10 `strftime` findings for shared-helper cleanup.
4. Classify the 3 Bandit findings before changing behavior-sensitive code.
5. Chip away at the 25 complexity findings one module at a time.

## Best First Pass

The highest-leverage next tranche is:

- `tests/test_new_ui_widgets.py`
- `tests/unit/instruments/contracts/test_abstract_instrument_contracts.py`
- `tests/test_motor_controller.py`

That single pass can remove all `Error` and `High` issues in the current snapshot.
