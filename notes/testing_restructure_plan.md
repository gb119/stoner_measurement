# Testing Restructure Plan

This is the historical migration log for the test-suite restructure. Durable
test layout and philosophy guidance lives in `notes/testing_guidelines.md`.

This document records the test-suite restructure so future Codex sessions can
continue without rediscovering the same coverage map.

## Current Baseline

Baseline command, run from the repository root:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement pytest --cov=stoner_measurement --cov-report=json:coverage.json --cov-report=term-missing
```

Latest observed result:

- 2386 tests passed.
- Combined branch-aware coverage: 74%.
- Statement coverage: 78%.
- Branch coverage: 57%.

The lower branch coverage means new tests should prefer branch/edge cases over
more happy-path assertions for already-covered code.

## Target Layout

```text
tests/
  unit/
    scan/
    sweep/
    instruments/
      transport/
      drivers/
      contracts/
    plugins/
      command/
      trace/
      transform/
      state/
      monitor/
    ui/
      widgets/
      panels/
      dialogs/
    control/
      magnet/
      motor/
      temperature/
    core/
  integration/
    app/
    sequence/
    plugin_workflows/
  fixtures/
    fake_instruments.py
    fake_transports.py
    qt_helpers.py
    plugin_factories.py
```

## Hot Test Files

These files carry too much unrelated behavior and should be split by module or
contract as they are touched:

| File | Tests | Lines | Suggested split |
| --- | ---: | ---: | --- |
| `tests/test_instruments.py` | 452 | 4692 | `unit/instruments/drivers/` plus shared driver contracts |
| `tests/test_command_plugin.py` | 256 | 3244 | `unit/plugins/command/test_<command>.py` |
| `tests/test_ui.py` | 139 | 1876 | `unit/ui/widgets/`, `unit/ui/panels/`, `integration/app/` |
| `tests/test_plugin_subtypes.py` | 121 | 1092 | plugin contracts plus subtype-specific unit files |
| `tests/test_curve_fit_plugin.py` | 109 | 1241 | keep focused, but split UI/config from fit execution |
| `tests/test_sequence_engine.py` | 100 | 906 | `unit/core/` and `integration/sequence/` |

## Cold Coverage Spots

Ranked by missed lines plus missed branches:

| Module | Coverage | Debt | Recommended approach |
| --- | ---: | ---: | --- |
| `ui/temperature_panel.py` | 54% | 623 | Extract/test state helpers; add thin Qt signal tests |
| `ui/widgets/round_dial.py` | 44% | 539 | Parametrize modes, label placement, color/theme branches |
| `ui/value_watch.py` | 43% | 419 | Unit-test model/state transitions before full widget flows |
| `ui/dock_panel.py` | 63% | 413 | Split tree-model behavior from drag/drop integration |
| `ui/magnet_panel.py` | 60% | 362 | Test state rendering and command enablement with fake engine |
| `ui/settings_dialog.py` | 9% | 267 | Quick win: construct/apply/cancel/reset/validation tests |
| `temperature_control/engine.py` | 63% | 246 | Contract tests for driver connection and state transitions |
| `plugins/trace/k6221_multi_sr830.py` | 80% | 212 | Fill branch cases around config validation and UI callbacks |
| `plugins/trace/keithley_2400.py` | 68% | 193 | Split config UI, sweep construction, execution branches |
| `magnet_control/engine.py` | 71% | 179 | Add fake-driver state transition tests |
| `instruments/transport/gpib_transport.py` | 46% | 173 | Mock PyVISA resources under a transport contract |
| `sweep/monitor_and_filter_generator.py` | 36% | 166 | Pure unit tests for filtering, abort, and monitor branches |

## Migration Rules

- Move tests by behavior, not by old filename.
- Prefer one test module per production module unless a contract file covers a
  family of implementations.
- Keep slow app-level workflows under `tests/integration/`.
- Keep widget construction, signal, and property synchronization tests under
  `tests/unit/ui/`.
- Use contract helper functions for repeated interfaces:
  - transport open/read/write/error behavior
  - instrument identity, validation, query/write mapping
  - plugin JSON/config/generated-code/lifecycle behavior
  - monitor/state plugin connect/read/reported-values behavior
- When adding coverage to cold UI modules, first look for extractable pure
  helpers. Avoid testing large panels only through full application workflows.
- Keep `QT_QPA_PLATFORM=offscreen` for Qt test runs.
- Use `conda run -n stoner_measurement ...` for every project command.

## Suggested CI Buckets

```text
fast unit: non-Qt logic, contracts, serializers
qt unit: widgets/panels/dialogs with offscreen Qt
integration: app/plugin workflow tests
coverage: combined report
```

Possible commands:

```powershell
conda run -n stoner_measurement pytest tests/unit
conda run -n stoner_measurement pytest tests/unit/ui
conda run -n stoner_measurement pytest tests/integration
conda run -n stoner_measurement pytest --cov=stoner_measurement --cov-report=term-missing
```

## Completed In First Migration Pass

- Created the target directory skeleton.
- Moved the first low-risk widget tests to `tests/unit/ui/widgets/`.
- Verified nested pytest discovery for the migrated tests.

- Moved:
  - `tests/test_percent_slider.py` -> `tests/unit/ui/widgets/test_percent_slider.py`
  - `tests/test_si_combo_box.py` -> `tests/unit/ui/widgets/test_si_combo_box.py`
  - `tests/test_visa_resource_widget.py` -> `tests/unit/ui/widgets/test_visa_resource_widget.py`

## Completed In Second Migration Pass

- Moved `tests/test_round_dial.py` to `tests/unit/ui/widgets/test_round_dial.py`.
- Split `tests/test_ui.py` into:
  - `TestDockPanel` -> `tests/unit/ui/panels/test_dock_panel.py`
  - `TestPlotWidget` -> `tests/unit/ui/widgets/test_plot_widget.py`
  - `TestConfigPanel` -> `tests/unit/ui/panels/test_config_panel.py`
  - `TestMainWindow` -> `tests/integration/app/test_main_window.py`
- Removed the old monolithic `tests/test_ui.py`.
- Normalized one plot-widget assertion to expect the real ellipsis glyph in
  `"Configure Axes…"`'s UI label.
- Verified the migrated tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement pytest tests/unit/ui/widgets/test_round_dial.py tests/unit/ui/widgets/test_plot_widget.py tests/unit/ui/panels/test_dock_panel.py tests/unit/ui/panels/test_config_panel.py tests/integration/app/test_main_window.py --tb=short
conda run -n stoner_measurement pytest --collect-only -q
conda run -n stoner_measurement ruff check tests/unit/ui tests/integration/app --select "F401,F811,F821,F841"
```

Result:

- Migrated tranche: 156 passed.
- Full collection: 2386 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Third Migration Pass

- Moved the scan generator tests into `tests/unit/scan/`:
  - `tests/test_scan_generators.py` -> `tests/unit/scan/test_scan_generators.py`
  - `tests/test_stepped_scan_generator.py` -> `tests/unit/scan/test_stepped_scan_generator.py`
  - `tests/test_list_scan_generator.py` -> `tests/unit/scan/test_list_scan_generator.py`
  - `tests/test_ramp_scan_generator.py` -> `tests/unit/scan/test_ramp_scan_generator.py`
  - `tests/test_arbitrary_function_scan_generator.py` -> `tests/unit/scan/test_arbitrary_function_scan_generator.py`
- Verified the migrated tranche:

```powershell
conda run -n stoner_measurement pytest tests/unit/scan --tb=short
conda run -n stoner_measurement pytest --collect-only -q
conda run -n stoner_measurement ruff check tests/unit/scan --select "F401,F811,F821,F841"
```

Result:

- Scan tranche: 274 passed.
- Full collection: 2386 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Fourth Migration Pass

- Started transport contract tests in `tests/unit/instruments/contracts/` with
  reusable checks for open/close, context-manager lifecycle, and query
  write-then-read behavior.
- Moved the concrete `NullTransport` tests from `tests/test_instruments.py` to
  `tests/unit/instruments/transport/test_null_transport.py`.
- Left the existing URI parsing and GPIB/PyVISA tests in `tests/test_instruments.py`
  for the next transport-focused pass so they can move with their mock resource
  scaffolding.
- Verified the migrated tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts tests\unit\instruments\transport\test_null_transport.py --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\contracts tests\unit\instruments\transport\test_null_transport.py --select F401,F811,F821,F841
```

Result:

- Transport tranche: 13 passed.
- Full collection: 2389 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Fifth Migration Pass

- Continued transport migration by moving URI/resource parsing tests from
  `tests/test_instruments.py` to
  `tests/unit/instruments/transport/test_transport_uri.py`.
- Moved GPIB protocol termination and `PassThroughGpibTransport` tests from
  `tests/test_instruments.py` to
  `tests/unit/instruments/transport/test_gpib_transport.py`.
- Kept serial flow-control tests in `tests/test_instruments.py` for a later
  serial-specific transport pass.
- Verified the migrated tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts tests\unit\instruments\transport --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\transport tests\unit\instruments\contracts --select F401,F811,F821,F841
```

Result:

- Transport tranche: 48 passed.
- Full collection: 2389 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Sixth Migration Pass

- Finished the transport reshuffle from `tests/test_instruments.py` by moving:
  - UDP socket tests to `tests/unit/instruments/transport/test_udp_transport.py`
  - Ethernet framing tests to `tests/unit/instruments/transport/test_ethernet_transport.py`
  - Serial flow-control tests to `tests/unit/instruments/transport/test_serial_transport.py`
- Left instrument locking and driver behavior in `tests/test_instruments.py` for
  the later driver-focused split.
- Verified the migrated tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\instruments\contracts tests\unit\instruments\transport --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\transport tests\unit\instruments\contracts --select F401,F811,F821,F841
```

Result:

- Transport tranche: 66 passed.
- Full collection: 2391 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Seventh Migration Pass

- Added first cold-spot tests for `ui/settings_dialog.py` under
  `tests/unit/ui/dialogs/test_settings_dialog.py`.
- Covered construction from saved settings, unknown-theme fallback,
  accept/reject persistence behavior, toolbar row loading/collection/removal,
  validation warnings, and save/cancel handling without touching real user
  settings or toolbar config files.
- Verified the tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\ui\dialogs --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests\unit\ui\dialogs --select F401,F811,F821,F841
```

Result:

- Settings-dialog tranche: 10 passed.
- Full collection: 2401 tests collected.
- Focused Ruff import/name checks passed.

## Completed In Eighth Migration Pass

- Began splitting `tests/test_command_plugin.py` into
  `tests/unit/plugins/command/test_<command>.py`.
- Moved the low-dependency command coverage into focused unit files:
  - `tests/unit/plugins/command/test_base_command.py`
  - `tests/unit/plugins/command/test_wait_command.py`
  - `tests/unit/plugins/command/test_status_command.py`
  - `tests/unit/plugins/command/test_alert_command.py`
  - `tests/unit/plugins/command/test_plot_clear_command.py`
- Trimmed `tests/test_command_plugin.py` so it now retains only the larger
  `SaveCommand`, `PlotTraceCommand`, `DetailsCommand`, and `PlotPointsCommand`
  groups for follow-up passes.
- Updated the migrated base command config-tabs assertion to match the current
  base plugin contract: command config tab first, optional About tab last.
- Verified the tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command\test_base_command.py tests\unit\plugins\command\test_wait_command.py tests\unit\plugins\command\test_status_command.py tests\unit\plugins\command\test_alert_command.py tests\unit\plugins\command\test_plot_clear_command.py tests\test_command_plugin.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\plugins\command tests\test_command_plugin.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Command-plugin tranche: 256 passed.
- Full collection: 2401 tests collected.
- Ruff checks passed for the migrated command files and remaining command
  plugin file.

## Completed In Ninth Migration Pass

- Continued splitting `tests/test_command_plugin.py` by moving
  `DetailsCommand` coverage into
  `tests/unit/plugins/command/test_details_command.py`.
- Replaced repeated inline imports in the migrated tests with module-level
  imports for the command, Qt widgets, settings helpers, and `BasePlugin`.
- Trimmed `tests/test_command_plugin.py` so it now retains only the larger
  `SaveCommand`, `PlotTraceCommand`, and `PlotPointsCommand` groups.
- Verified the tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command\test_details_command.py tests\test_command_plugin.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\plugins\command tests\test_command_plugin.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Details-command tranche plus remaining command monolith: 174 passed.
- Full collection: 2401 tests collected.
- Ruff checks passed for the command test area.

## Completed In Tenth Migration Pass

- Continued splitting `tests/test_command_plugin.py` by moving
  `PlotPointsCommand` coverage into
  `tests/unit/plugins/command/test_plot_points_command.py`.
- Kept the small plot-timeout test double local to the new file so
  `PlotPointsCommand` tests are independent of the remaining PlotTrace block.
- Trimmed `tests/test_command_plugin.py` so it now retains only
  `SaveCommand` and `PlotTraceCommand` coverage.
- Verified the tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command\test_plot_points_command.py tests\test_command_plugin.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\plugins\command tests\test_command_plugin.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Plot-points tranche plus remaining command monolith: 153 passed.
- Full collection: 2401 tests collected.
- Ruff checks passed for the command test area.

## Completed In Eleventh Migration Pass

- Continued splitting `tests/test_command_plugin.py` by moving
  `SaveCommand` coverage into
  `tests/unit/plugins/command/test_save_command.py`.
- Preserved the existing Save command test bodies during the move and added a
  focused module header/imports.
- Trimmed `tests/test_command_plugin.py` so it now contains only
  `PlotTraceCommand` coverage, making the final monolith removal a straight
  PlotTrace move/rename.
- Verified the tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command\test_save_command.py tests\test_command_plugin.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\plugins\command tests\test_command_plugin.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Save-command tranche plus remaining PlotTrace monolith: 118 passed.
- Full collection: 2401 tests collected.
- Ruff checks passed for the command test area.

## Completed In Twelfth Migration Pass

- Finished splitting the command plugin monolith by moving the remaining
  `PlotTraceCommand` coverage from `tests/test_command_plugin.py` to
  `tests/unit/plugins/command/test_plot_trace_command.py`.
- Removed the top-level `tests/test_command_plugin.py` monolith.
- Preserved IDE/direct-file execution for the split command test files by
  adding a small `if __name__ == "__main__": pytest.main([__file__, "--pdb"])`
  block to each new command test module.
- Verified the final command-plugin tranche:

```powershell
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command\test_plot_trace_command.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\plugins\command
conda run -n stoner_measurement python -m pytest tests\unit\plugins\command --tb=short
conda run -n stoner_measurement python tests\unit\plugins\command\test_wait_command.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- PlotTrace command tranche: 64 passed.
- Command test area: 256 passed.
- Direct-file smoke test: `test_wait_command.py` passed when run as a script.
- Full collection: 2401 tests collected.
- Ruff checks passed for the command test area.
- `tests/test_command_plugin.py` no longer exists.

## Completed In Thirteenth Migration Pass

- Split `tests/test_plugin_subtypes.py` into focused plugin-family files:
  - `tests/unit/plugins/trace/test_trace_plugin.py`
  - `tests/unit/plugins/state/test_state_control_plugin.py`
  - `tests/unit/plugins/state/test_state_control_data_collection.py`
  - `tests/unit/plugins/monitor/test_monitor_plugin.py`
  - `tests/unit/plugins/transform/test_transform_plugin.py`
  - `tests/unit/plugins/test_reported_outputs.py`
- Preserved the small local test doubles inside the split files so the new
  modules remain independently runnable from an IDE.
- Removed the top-level `tests/test_plugin_subtypes.py` monolith after the
  overlap run confirmed the moved coverage still passed.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\test_plugin_subtypes.py --tb=short
conda run -n stoner_measurement python -m pytest tests\unit\plugins\trace\test_trace_plugin.py tests\unit\plugins\state\test_state_control_plugin.py tests\unit\plugins\state\test_state_control_data_collection.py tests\unit\plugins\monitor\test_monitor_plugin.py tests\unit\plugins\transform\test_transform_plugin.py tests\unit\plugins\test_reported_outputs.py tests\test_plugin_subtypes.py --tb=short
conda run -n stoner_measurement python -m pytest --collect-only -q
conda run -n stoner_measurement python -m ruff check tests\unit\plugins
```

Result:

- Overlap run before deletion: 246 passed.
- Split plugin test area after deletion: 123 passed.
- Direct-file smoke test: `test_state_control_plugin.py` passed when run as a script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the split plugin test area.

## Completed In Fourteenth Migration Pass

- Split the first SCPI driver tranche out of `tests/test_instruments.py` into:
  - `tests/unit/instruments/drivers/test_keithley_2400.py`
  - `tests/unit/instruments/drivers/test_keithley_2000.py`
  - `tests/unit/instruments/drivers/test_keithley_2182a.py`
- Moved the following legacy groups:
  - `TestKeithley2400`
  - `TestKeithley24xxVariants`
  - `TestKeithley2000`
  - `TestKeithley2000Variants`
  - `TestKeithley2182A`
  - `TestKeithley2182Variants`
- Kept the small `_null(...)` helper local to each split file so the modules
  remain directly runnable from an IDE without depending on package-style test
  imports.
- Trimmed the moved imports and classes out of `tests/test_instruments.py`.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_keithley_2400.py tests\unit\instruments\drivers\test_keithley_2000.py tests\unit\instruments\drivers\test_keithley_2182a.py tests\test_instruments.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\drivers tests\test_instruments.py
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_keithley_2400.py tests\unit\instruments\drivers\test_keithley_2000.py tests\unit\instruments\drivers\test_keithley_2182a.py --tb=short
conda run -n stoner_measurement python tests\unit\instruments\drivers\test_keithley_2000.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Overlap run before trimming: 473 passed.
- Split driver area after trimming: 63 passed.
- Direct-file smoke test: `test_keithley_2000.py` passed when run as a script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the split driver area and remaining monolith.

## Completed In Fifteenth Migration Pass

- Split the next focused instrument tranche out of `tests/test_instruments.py`
  into:
  - `tests/unit/instruments/drivers/test_srs830.py`
  - `tests/unit/instruments/drivers/test_lakeshore_m81_lockin.py`
  - `tests/unit/instruments/drivers/test_keithley_6221.py`
- Moved the following legacy groups:
  - `TestSRS830`
  - `TestLakeshoreM81LockIn`
  - `TestKeithley6221`
- Kept the small `_null(...)` helper local to each split file so the modules
  remain directly runnable from an IDE without depending on package-style test
  imports.
- Treated `TestSRS830` as its own focused lock-in slice because the SR830 is
  not SCPI-based in the same sense as the other two moved classes, while
  `LakeshoreM81LockIn` and `Keithley6221` remain straightforward SCPI driver
  migrations.
- Trimmed the moved imports and classes out of `tests/test_instruments.py`.
- Verified the tranche:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_srs830.py tests\unit\instruments\drivers\test_lakeshore_m81_lockin.py tests\unit\instruments\drivers\test_keithley_6221.py tests\test_instruments.py --tb=short
conda run -n stoner_measurement python -m ruff check tests\unit\instruments\drivers tests\test_instruments.py
conda run -n stoner_measurement python -m pytest tests\unit\instruments\drivers\test_srs830.py tests\unit\instruments\drivers\test_lakeshore_m81_lockin.py tests\unit\instruments\drivers\test_keithley_6221.py --tb=short
conda run -n stoner_measurement python tests\unit\instruments\drivers\test_srs830.py
conda run -n stoner_measurement python -m pytest --collect-only -q
```

Result:

- Overlap run before trimming: 406 passed.
- Split driver area after trimming: 59 passed.
- Direct-file smoke test: `test_srs830.py` passed when run as a script.
- Full collection: 2490 tests collected.
- Ruff checks passed for the split driver area and remaining monolith.

## Next Recommended Migration Batch

1. Continue `tests/test_instruments.py` with the next adjacent self-contained
   driver tranche:
   - `TestKeithleyElectrometers`
   - `TestLakeshoreM81CurrentSource`
   - `TestLakeshore625`
2. This keeps momentum in the remaining driver-heavy section of the monolith
   before moving on to the larger temperature, magnet, and higher-behaviour
   integration-style blocks.
