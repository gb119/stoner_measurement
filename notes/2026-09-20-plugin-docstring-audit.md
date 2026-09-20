# Plugin class docstring audit and corrections

Date: 20 September 2026.
Baseline: `main` at `f3d9295c70a7b116a2ba0ea4253e088db7a6c10f`.

## Scope and criteria

Reviewed all **62 registered sequence plugins** in the
[project entry points](../pyproject.toml): commands, scans, sweeps, traces,
monitors, transforms and sequence containers. Abstract bases, helper widgets,
drivers and the internal top-level container are outside this command audit.
Compatibility aliases are not counted twice.

The source of truth is **Docstring formatting** in
[the repository instructions](../.github/copilot-instructions.md):

- Explain the measurement purpose for an end user.
- Describe configuration tabs and options.
- Describe script-accessible attributes, including inherited ones.
- Provide console interaction examples.
- Use Google-style sections, typed descriptions, British English, opening
  summaries ending in a full stop and examples within 79 source columns.
- Describe constructor keyword parameters where applicable.

This is documentation verification against the implementation, not instrument
protocol validation or a complete audit of every method docstring.

## Findings and corrections

Initially, **14 classes lacked an Attributes section** and **24 lacked console
code**, including GUI-only prose under Examples headings. Many other examples
only printed class metadata. Inherited identity, engine context and result
attributes were often undocumented.

Corrected all 62 registered class docstrings:

- Expanded guidance for If, Reconfigure, Run Again, Make Safe, pressure
  controls/monitoring, Keithley set/point commands and transforms.
- Replaced obsolete temperature `loop` with `control_loop`; removed obsolete
  magnet `wait_for_stable`/`tolerance` and temperature-monitor connection fields.
  Documented current shared-engine controls.
- Corrected the multi-lock-in result to one `Signals` table, the 6221 x column,
  the Dummy result name and Save's TDI/NeXus description. Added differential
  and secondary-meter options on buffered Keithley traces.
- Added inherited identity, comment, engine context and relevant family state.
- Supplied console examples using explicitly named existing instances.
  Fixed the curve-fit source example and checked embedded Python source.
- Corrected spelling, copied descriptions, attribute formatting and section
  separation affecting the shared About renderer.

## Complete inventory

Every row was corrected and rechecked. Initial gaps:
**A** = absent Attributes section; **C** = absent console code;
**I** = no typed instance-name entry, an indicator of inherited-documentation
gaps rather than a claim that all inherited attributes were absent.
**Review** = other content or example improvements.

| Plugin                       | Class source                                                                                                    | Initial gaps |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------ |
| counter                      | [CounterPlugin](../src/stoner_measurement/plugins/state_scan/counter.py#L18)                                    | I            |
| daqmx_point_scan             | [DaqmxPointScanPlugin](../src/stoner_measurement/plugins/state_scan/daqmx.py#L39)                               | C, I         |
| daqmx_set                    | [DaqmxSetCommand](../src/stoner_measurement/plugins/command/daqmx_set.py#L46)                                   | C, I         |
| magnet_controller_scan       | [MagnetControllerScanPlugin](../src/stoner_measurement/plugins/state_scan/magnet_controller.py#L11)             | I            |
| k2400_point_scan             | [Keithley2400PointScanPlugin](../src/stoner_measurement/plugins/state_scan/keithley_2400.py#L100)               | C, I         |
| k6221_point_scan             | [Keithley6221PointScanPlugin](../src/stoner_measurement/plugins/state_scan/k6221_2182a.py#L34)                  | A, C, I      |
| k2400_set                    | [Keithley2400SetCommand](../src/stoner_measurement/plugins/command/keithley_set.py#L95)                         | A, C, I      |
| k6221_set                    | [Keithley6221SetCommand](../src/stoner_measurement/plugins/command/keithley_set.py#L153)                        | A, C, I      |
| network_analyser_point_scan  | [NetworkAnalyserPointScanPlugin](../src/stoner_measurement/plugins/state_scan/network_analyser.py#L35)          | C, I         |
| temperature_controller_scan  | [TemperatureControllerScanPlugin](../src/stoner_measurement/plugins/state_scan/temperature_controller.py#L11)   | I            |
| motor_controller_scan        | [MotorControllerScanPlugin](../src/stoner_measurement/plugins/state_scan/motor_controller.py#L11)               | C, I         |
| xray_diffractometer_scan     | [XrayDiffractometerScanPlugin](../src/stoner_measurement/plugins/state_scan/xray_diffractometer.py#L17)         | A, I         |
| sweep_time                   | [SweepTimePlugin](../src/stoner_measurement/plugins/state_sweep/sweep_time.py#L14)                              | I            |
| magnet_controller_sweep      | [MagnetControllerSweepPlugin](../src/stoner_measurement/plugins/state_sweep/magnet_controller.py#L13)           | I            |
| temperature_controller_sweep | [TemperatureControllerSweepPlugin](../src/stoner_measurement/plugins/state_sweep/temperature_controller.py#L11) | I            |
| motor_controller_sweep       | [MotorControllerSweepPlugin](../src/stoner_measurement/plugins/state_sweep/motor_controller.py#L11)             | I            |
| curve_fit                    | [CurveFitPlugin](../src/stoner_measurement/plugins/transform/curve_fit.py#L675)                                 | Review       |
| extremum_locator             | [ExtremumLocatorPlugin](../src/stoner_measurement/plugins/transform/extremum_locator.py#L31)                    | C, I         |
| branch_split                 | [BranchSplitPlugin](../src/stoner_measurement/plugins/transform/branch_split.py#L42)                            | I            |
| fourier_transform            | [FourierTransformPlugin](../src/stoner_measurement/plugins/transform/fourier_transform.py#L29)                  | I            |
| savgol_filter                | [SavitzkyGolayPlugin](../src/stoner_measurement/plugins/transform/savgol_filter.py#L18)                         | I            |
| symmetry_decomposition       | [SymmetryDecompositionPlugin](../src/stoner_measurement/plugins/transform/symmetry_decomposition.py#L78)        | A, C, I      |
| window_filter                | [WindowFilterPlugin](../src/stoner_measurement/plugins/transform/window_filter.py#L46)                          | I            |
| x_offset_removal             | [XOffsetRemovalPlugin](../src/stoner_measurement/plugins/transform/voltage_offset.py#L31)                       | A, C, I      |
| dummy                        | [DummyPlugin](../src/stoner_measurement/plugins/trace/dummy.py#L23)                                             | I            |
| function_trace               | [FunctionTracePlugin](../src/stoner_measurement/plugins/trace/function_trace.py#L23)                            | C, I         |
| daqmx_trace                  | [DaqmxTracePlugin](../src/stoner_measurement/plugins/trace/daqmx.py#L246)                                       | C, I         |
| k6221_dc_iv                  | [Keithley6221_2182APlugin](../src/stoner_measurement/plugins/trace/k6221_2182a.py#L208)                         | I            |
| k6221_multi_sr830            | [Keithley6221_MultiSR830Plugin](../src/stoner_measurement/plugins/trace/k6221_multi_sr830.py#L355)              | I            |
| k2400_dc_iv                  | [Keithley2400SweepPlugin](../src/stoner_measurement/plugins/trace/keithley_2400.py#L129)                        | I            |
| network_analyser             | [NetworkAnalyserTracePlugin](../src/stoner_measurement/plugins/trace/network_analyser.py#L48)                   | C, I         |
| network_analyser_set         | [NetworkAnalyserSetCommand](../src/stoner_measurement/plugins/command/network_analyser_set.py#L24)              | C, I         |
| plot_clear                   | [PlotClearCommand](../src/stoner_measurement/plugins/command/plot_clear.py#L37)                                 | I            |
| add_plot_marker              | [AddPlotMarkerCommand](../src/stoner_measurement/plugins/command/plot_markers.py#L24)                           | C, I         |
| remove_plot_markers          | [RemovePlotMarkersCommand](../src/stoner_measurement/plugins/command/plot_markers.py#L156)                      | C, I         |
| plot_points                  | [PlotPointsCommand](../src/stoner_measurement/plugins/command/plot_points.py#L165)                              | I            |
| plot_trace                   | [PlotTraceCommand](../src/stoner_measurement/plugins/command/plot_trace.py#L100)                                | I            |
| save                         | [SaveCommand](../src/stoner_measurement/plugins/command/save.py#L370)                                           | I            |
| wait                         | [WaitCommand](../src/stoner_measurement/plugins/command/wait.py#L19)                                            | I            |
| status                       | [StatusCommand](../src/stoner_measurement/plugins/command/status.py#L37)                                        | I            |
| alert                        | [AlertCommand](../src/stoner_measurement/plugins/command/alert.py#L20)                                          | I            |
| if_command                   | [IfCommand](../src/stoner_measurement/plugins/command/if_command.py#L14)                                        | A, C, I      |
| break_if                     | [BreakIfCommand](../src/stoner_measurement/plugins/command/loop_control.py#L92)                                 | Review       |
| continue_if                  | [ContinueIfCommand](../src/stoner_measurement/plugins/command/loop_control.py#L151)                             | Review       |
| run_parallel                 | [RunParallelPlugin](../src/stoner_measurement/plugins/sequence/containers.py#L162)                              | Review       |
| run_sequentially             | [RunSequentiallyPlugin](../src/stoner_measurement/plugins/sequence/containers.py#L74)                           | Review       |
| details                      | [DetailsCommand](../src/stoner_measurement/plugins/command/details.py#L78)                                      | I            |
| edit_function_scan           | [EditFunctionScanCommand](../src/stoner_measurement/plugins/command/edit_function_scan.py#L29)                  | Review       |
| reconfigure                  | [ReconfigureCommand](../src/stoner_measurement/plugins/command/reconfigure.py#L15)                              | A, C, I      |
| run_again                    | [RunAgainCommand](../src/stoner_measurement/plugins/command/run_again.py#L14)                                   | A, C, I      |
| make_safe                    | [MakeSafeCommand](../src/stoner_measurement/plugins/command/make_safe.py#L18)                                   | A, C, I      |
| magnetic_field_monitor       | [MagneticFieldMonitorPlugin](../src/stoner_measurement/plugins/monitor/magnet_controller.py#L29)                | I            |
| temperature_monitor          | [TemperatureMonitorPlugin](../src/stoner_measurement/plugins/monitor/temperature_controller.py#L59)             | I            |
| motor_angle_monitor          | [MotorAngleMonitorPlugin](../src/stoner_measurement/plugins/monitor/motor_controller.py#L19)                    | C, I         |
| pressure_monitor             | [PressureMonitorPlugin](../src/stoner_measurement/plugins/monitor/pressure_controller.py#L37)                   | A, C, I      |
| pressure_set_flow            | [PressureSetFlowCommand](../src/stoner_measurement/plugins/command/pressure_set_flow.py#L15)                    | Review       |
| pressure_gauge_channel       | [PressureGaugeChannelCommand](../src/stoner_measurement/plugins/command/pressure_gauge_channel.py#L13)          | A, C, I      |
| set_temperature              | [SetTemperatureCommand](../src/stoner_measurement/plugins/command/set_temperature.py#L15)                       | Review       |
| set_field                    | [SetFieldCommand](../src/stoner_measurement/plugins/command/set_field.py#L11)                                   | Review       |
| set_position                 | [SetPositionCommand](../src/stoner_measurement/plugins/command/set_position.py#L16)                             | Review       |
| set_diffractometer           | [SetDiffractometerCommand](../src/stoner_measurement/plugins/command/set_diffractometer.py#L18)                 | A, I         |
| read_diffractometer          | [ReadDiffractometerCommand](../src/stoner_measurement/plugins/command/read_diffractometer.py#L11)               | A, I         |

## Verification

- Loaded all 62 registered classes with Qt offscreen in the project environment.
- Confirmed documented attributes exist, allowing Curve Fit's dynamically
  compiled `fit` and optional `p0` accessors.
- Executed all 62 console examples on detached instances without connecting to
  instruments; checked assignment targets for silently created misspellings.
- Compiled embedded fit/function source and resolved Curve Fit's callables.
- Rendered all 62 class docstrings with the shared converter, checking Attributes
  visibility and omission of constructor-only sections.
- Compared ASTs without docstrings against the baseline: executable code is
  unchanged across all 58 modified Python files.
- Focused tests: **668 passed, 1 skipped**.
- Markdownlint on this report and `git diff --check`: **passed**.
- Ruff on changed Python files: **passed**. A broader plugin-tree check found
  six existing issues in untouched `RSJ_JJ.py`, `bloch_grueneisen.py` and
  `hall_resistance.py` fitting-library modules, outside this change.

The focused test command used `QT_QPA_PLATFORM=offscreen` and
`QT_QPA_FONTDIR=C:\Windows\Fonts`:

```powershell
& $env:CONDA_EXE run --no-capture-output -n stoner_measurement pytest `
    tests/test_base_plugin.py tests/test_dummy_plugin.py `
    tests/test_k6221_2182a_plugin.py tests/unit/plugins/command `
    tests/unit/plugins/transform/test_branch_split.py `
    tests/unit/plugins/transform/test_extremum_locator.py -q --tb=short
```

## About-tab boundary

The shared renderer deliberately omits Examples, Args, Keyword Parameters,
Returns and Raises. Console examples remain available in class docstrings,
including through Python help; their absence from About is existing behaviour.

Three plugins provide bespoke About HTML: `dummy`, `k6221_dc_iv` and
`k2400_dc_iv`. Their class docstrings meet the checked criteria, but their custom
About pages do not automatically incorporate these edits. Existing HTML is
retained, including instrument wiring guidance. The renderer and custom pages
were not changed.

Hardware execution and bench behaviour were not tested. Original untracked
Keithley notes/documentation and `test.json` were left untouched.
