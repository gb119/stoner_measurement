# Codacy Issues Summary

Repository: `gh/gb119/stoner_measurement`
Branch: `main`
Total issues downloaded: **70**

## Local quick-win pass

Updated on 2026-06-27 after applying the safe, low-risk fixes locally.

- Cleared the listed duplicate re-import findings (`PyLintPython3_W0404`) in tests.
- Replaced direct append lambdas with bound methods where the signal signature is a simple pass-through (`PyLintPython3_W0108`).
- Made the listed unused locals explicit (`PyLintPython3_W0612`).
- Fixed the selected pycodestyle issues for a missing nested-function blank line, bare `except`, and long lines.
- Left complexity, intentional Qt mixedCase API names, hardcoded date-format findings, and `exec` findings for separate review.

Verification:

- `python -m ruff check <touched files>`
- `python -m pylint --disable=all --enable=W0404,W0108,W0612,C0200,W0702 <touched files>`
- `python -m pytest <affected test files> --tb=short` (`521 passed`)

## By severity

- Info: 39
- Warning: 31

## By category

- CodeStyle: 34
- Complexity: 20
- BestPractice: 9
- Comprehensibility: 2
- Security: 2
- UnusedCode: 2
- Documentation: 1

## Top patterns

- Prospector_mccabe: 20
- Prospector_pycodestyle: 12
- PyLintPython3_W0404: 9
- Semgrep_codacy.python.i18n.no-hardcoded-strftime: 8
- PyLintPython3_W0108: 6
- markdownlint_MD032: 5
- PyLintPython3_C0200: 2
- Bandit_B102: 2
- PyLintPython3_W0612: 2
- Agentlinter_clarity_undefined-term: 1
- Agentlinter_completeness_has-identity: 1
- Agentlinter_completeness_has-tools: 1
- Agentlinter_completeness_has-boundaries: 1

## Top files

- tests/test_sequence_engine.py: 8
- .github/copilot-instructions.md: 5
- AGENTS.md: 4
- src/stoner_measurement/plugins/trace/k6221_multi_sr830.py: 3
- src/stoner_measurement/ui/widgets/round_dial.py: 3
- src/stoner_measurement/ui/plot_widget.py: 3
- tests/test_temperature_control.py: 3
- src/stoner_measurement/ui/magnet_panel.py: 2
- src/stoner_measurement/qt_compat.py: 2
- src/stoner_measurement/ui/temperature_panel.py: 2
- src/stoner_measurement/plugins/trace/keithley_2400.py: 2
- src/stoner_measurement/plugins/command/plot_points.py: 2
- src/stoner_measurement/plugins/trace/k6221_2182a.py: 2
- tests/test_dummy_plugin.py: 1
- tests/test_serializer.py: 1
- tests/unit/ui/dialogs/test_settings_dialog.py: 1
- src/stoner_measurement/plugins/transform/_trace_selection.py: 1
- tests/test_motor_control.py: 1
- src/stoner_measurement/ui/log_viewer.py: 1
- tests/unit/instruments/transport/test_udp_transport.py: 1

## Likely quick wins

### PyLintPython3_W0404 (9)

Remove local re-imports; usually one-line import cleanup in tests.

- `tests/test_dummy_plugin.py:228` - Reimport 'numpy' (imported line 7)
- `tests/test_serializer.py:307` - Reimport 'DummyPlugin' (imported line 300)
- `tests/test_motor_control.py:193` - Reimport 'SimulatedMotorController' (imported line 8)
- `tests/unit/instruments/transport/test_udp_transport.py:39` - Reimport 'UdpTransport' (imported line 7)
- `tests/test_new_ui_widgets.py:709` - Reimport 'SISpinBox' (imported line 18)
- `tests/test_k6221_multi_sr830_plugin.py:292` - Reimport 'LockInLineFilter' (imported line 12)
- `tests/test_sequence_engine.py:118` - Reimport 'DummyPlugin' (imported line 8)
- `tests/test_sequence_engine.py:170` - Reimport 'DummyPlugin' (imported line 8)
- `tests/test_logging_support.py:101` - Reimport '_QtLogHandler' (imported line 9)

### PyLintPython3_W0108 (6)

Replace unnecessary lambdas with the function or method directly.

- `tests/unit/ui/dialogs/test_settings_dialog.py:163` - Lambda may not be necessary
- `tests/test_sequence_engine.py:893` - Lambda may not be necessary
- `tests/test_sequence_engine.py:136` - Lambda may not be necessary
- `tests/test_sequence_engine.py:206` - Lambda may not be necessary
- `tests/test_sequence_engine.py:150` - Lambda may not be necessary
- `tests/unit/ui/panels/test_dock_panel.py:177` - Lambda may not be necessary

### PyLintPython3_W0612 (2)

Delete unused local variables or assert the value if it matters.

- `tests/test_sequence_engine.py:323` - Unused variable 'code'
- `tests/test_state_sweep_plugin.py:393` - Unused variable 'ix'

### PyLintPython3_C0200 (2)

Use `enumerate()` instead of `range(len(...))`.

- `src/stoner_measurement/ui/temperature_panel.py:1285` - Consider using enumerate instead of iterating with range and len
- `src/stoner_measurement/ui/widgets/round_dial.py:1053` - Consider using enumerate instead of iterating with range and len

### Prospector_pycodestyle (12)

Mostly local formatting/import/exception cleanups; inspect individually.

- `tests/test_sequence_engine.py:835` - expected 1 blank line before a nested definition, found 0 (E306)
- `src/stoner_measurement/plugins/trace/k6221_multi_sr830.py:1226` - do not use bare 'except' (E722)
- `src/stoner_measurement/ui/magnet_panel.py:1344` - line too long (188 > 159 characters) (E501)
- `src/stoner_measurement/ui/widgets/round_dial.py:77` - variable 'valueChanged' in class scope should not be mixedCase (N815)
- `src/stoner_measurement/qt_compat.py:6` - variable 'pyqtSlot' in global scope should not be mixedCase (N816)
- `src/stoner_measurement/plugins/trace/keithley_2400.py:1022` - continuation line unaligned for hanging indent (E131)
- `src/stoner_measurement/ui/widgets/si_combo_box.py:75` - variable 'valueChanged' in class scope should not be mixedCase (N815)
- `src/stoner_measurement/qt_compat.py:5` - variable 'pyqtSignal' in global scope should not be mixedCase (N816)
- `src/stoner_measurement/ui/widgets/percent_slider.py:47` - variable 'valueChanged' in class scope should not be mixedCase (N815)
- `tests/unit/ui/widgets/test_plot_widget.py:153` - line too long (171 > 159 characters) (E501)
- `src/stoner_measurement/ui/widgets/visa_resource_widget.py:235` - variable 'currentTextChanged' in class scope should not be mixedCase (N815)
- `src/stoner_measurement/ui/plot_widget.py:1098` - line too long (201 > 159 characters) (E501)

### markdownlint_MD032 (5)

Blank-line fixes around Markdown lists.

- `.github/copilot-instructions.md:116` - Lists should be surrounded by blank lines
- `.github/copilot-instructions.md:63` - Lists should be surrounded by blank lines
- `.github/copilot-instructions.md:92` - Lists should be surrounded by blank lines
- `.github/copilot-instructions.md:87` - Lists should be surrounded by blank lines
- `.github/copilot-instructions.md:71` - Lists should be surrounded by blank lines

## Larger or riskier work

### Prospector_mccabe (20)

- `src/stoner_measurement/plugins/trace/k6221_multi_sr830.py:696` - Keithley6221_MultiSR830Plugin._plugin_config_tabs is too complex (24) (MC0001)
- `src/stoner_measurement/ui/widgets/round_dial.py:899` - RoundDialWidget._preferred_label_values is too complex (17) (MC0001)
- `src/stoner_measurement/plugins/transform/_trace_selection.py:144` - TraceChannelSelectionMixin._wire_data_source_widgets is too complex (17) (MC0001)
- `src/stoner_measurement/plugins/command/plot_points.py:243` - PlotPointsCommand.sequence_engine is too complex (17) (MC0001)
- `tests/test_magnet_control.py:39` - _make_fake_driver is too complex (25) (MC0001)
- `src/stoner_measurement/instruments/motor_controller.py:116` - resolve_wrapped_target_angle is too complex (19) (MC0001)
- `src/stoner_measurement/plugins/trace/dataframe_trace.py:232` - DataFrameTracePlugin._build_data_tab is too complex (28) (MC0001)
- `src/stoner_measurement/ui/plot_widget.py:1108` - PlotWidget._open_axes_dialog is too complex (21) (MC0001)
- `src/stoner_measurement/plugins/trace/k6221_2182a.py:949` - Keithley6221_2182APlugin._plugin_config_tabs is too complex (34) (MC0001)
- `src/stoner_measurement/plugins/command/plot_trace.py:299` - PlotTraceCommand.sequence_engine is too complex (21) (MC0001)
- `tests/test_temperature_control.py:335` - TestEngineLifecycle.test_connect_then_disconnect is too complex (18) (MC0001)
- `src/stoner_measurement/plugins/state_sweep/base.py:151` - _StateSweepPage._build_data_collection_section is too complex (16) (MC0001)
- ... 8 more

### Semgrep_codacy.python.i18n.no-hardcoded-strftime (8)

- `src/stoner_measurement/ui/log_viewer.py:674` - Avoid hardcoded date format strings in strftime.
- `src/stoner_measurement/motor_control/config.py:37` - Avoid hardcoded date format strings in strftime.
- `src/stoner_measurement/ui/magnet_panel.py:664` - Avoid hardcoded date format strings in strftime.
- `src/stoner_measurement/temperature_control/config.py:37` - Avoid hardcoded date format strings in strftime.
- `src/stoner_measurement/ui/motor_panel.py:362` - Avoid hardcoded date format strings in strftime.
- `src/stoner_measurement/ui/temperature_panel.py:708` - Avoid hardcoded date format strings in strftime.
- `src/stoner_measurement/ui/console_widget.py:99` - Avoid hardcoded date format strings in strftime.
- `src/stoner_measurement/magnet_control/config.py:56` - Avoid hardcoded date format strings in strftime.

### Bandit_B102 (2)

- `src/stoner_measurement/plugins/transform/curve_fit.py:1328` - Use of exec detected.
- `src/stoner_measurement/scan/arbitrary_function_generator.py:175` - Use of exec detected.

