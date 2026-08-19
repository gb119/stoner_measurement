"""Tests for EditFunctionScanCommand."""

from __future__ import annotations

import numpy as np
import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QLineEdit

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import EditFunctionScanCommand
from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.plugins.trace import DummyPlugin
from stoner_measurement.scan import FunctionScanGenerator, SteppedScanGenerator, WaveformType


def _attach_sequence(engine, command):
    function_scan = CounterPlugin()
    function_scan.instance_name = "field_scan"
    function_scan.sequence_engine = engine
    function_scan.scan_generator = FunctionScanGenerator(
        amplitude=1.0,
        offset="initial_offset",
        periods=1.0,
        num_points=8,
        exponent=2.0,
        phase=10.0,
        parent=function_scan,
    )

    stepped_scan = CounterPlugin()
    stepped_scan.instance_name = "stepped_scan"
    stepped_scan.sequence_engine = engine
    stepped_scan.scan_generator = SteppedScanGenerator(parent=stepped_scan)

    command.sequence_engine = engine
    engine.update_step_plugin_catalog([function_scan, stepped_scan, command])
    return function_scan, stepped_scan


def test_execute_replaces_supplied_values_and_retains_blank_settings(qapp, engine):
    command = EditFunctionScanCommand()
    function_scan, _ = _attach_sequence(engine, command)
    command.target_scan = "field_scan"
    command.amplitude_expr = "initial_amplitude * 2"
    command.periods_expr = "period_count"
    command.points_expr = "point_count"
    command.waveform_expr = "waveform_name"
    command.phase_expr = "start_phase + 5"
    engine._namespace.update(  # noqa: SLF001
        {
            "initial_amplitude": 1.5,
            "initial_offset": 0.25,
            "period_count": 2.0,
            "point_count": 12,
            "waveform_name": "Triangle",
            "start_phase": 20.0,
        }
    )

    command.execute()

    generator = function_scan.scan_generator
    assert isinstance(generator, FunctionScanGenerator)
    assert generator.amplitude == 3.0
    assert generator.offset == "initial_offset"
    assert generator.periods == 2.0
    assert generator.num_points == 12
    assert generator.exponent == 2.0
    assert generator.phase == 25.0
    assert generator.waveform is WaveformType.TRIANGLE
    assert generator.values.shape == (12,)
    assert np.isfinite(generator.values).all()


def test_known_waveform_label_does_not_need_quoting(qapp, engine):
    command = EditFunctionScanCommand()
    function_scan, _ = _attach_sequence(engine, command)
    command.target_scan = "field_scan"
    command.waveform_expr = "Sawtooth"
    engine._namespace["initial_offset"] = 0.0  # noqa: SLF001

    command.execute()

    assert function_scan.scan_generator.waveform is WaveformType.SAWTOOTH


def test_replacements_are_atomic_when_an_expression_fails(qapp, engine):
    command = EditFunctionScanCommand()
    function_scan, _ = _attach_sequence(engine, command)
    command.target_scan = "field_scan"
    command.amplitude_expr = "2.0"
    command.offset_expr = "missing_name + 1"

    with pytest.raises(Exception):
        command.execute()

    assert function_scan.scan_generator.amplitude == 1.0
    assert function_scan.scan_generator.offset == "initial_offset"


def test_all_blank_fields_leave_existing_scan_untouched(qapp, engine):
    command = EditFunctionScanCommand()
    function_scan, _ = _attach_sequence(engine, command)
    command.target_scan = "field_scan"
    generator = function_scan.scan_generator
    before = generator.to_json()
    changes = []
    generator.values_changed.connect(lambda: changes.append(True))

    command.execute()

    assert generator.to_json() == before
    assert changes == []


def test_eligible_scans_excludes_base_plugins_and_other_generator_types(qapp, engine):
    base_scan = CounterPlugin()
    base_scan.instance_name = "base_scan"
    engine.add_plugin("base_scan", base_scan)
    command = EditFunctionScanCommand()
    function_scan, _ = _attach_sequence(engine, command)

    assert command.eligible_scans() == [function_scan]
    assert engine.step_plugins()[-1] is command


def test_execute_edits_function_generator_owned_by_trace_plugin(qapp, engine):
    command = EditFunctionScanCommand()
    trace_scan = DummyPlugin()
    trace_scan.instance_name = "iv_trace"
    trace_scan.sequence_engine = engine
    command.sequence_engine = engine
    engine.update_step_plugin_catalog([trace_scan, command])
    command.target_scan = trace_scan.instance_name
    command.amplitude_expr = "trace_amplitude"
    command.offset_expr = "0.5"
    command.points_expr = "trace_points"
    engine._namespace.update(  # noqa: SLF001
        {"trace_amplitude": 4.0, "trace_points": 15}
    )

    command.execute()

    generator = trace_scan.scan_generator
    assert isinstance(generator, FunctionScanGenerator)
    assert generator.amplitude == 4.0
    assert generator.offset == 0.5
    assert generator.num_points == 15
    assert generator.values.shape == (15,)


def test_config_widget_lists_eligible_scan_and_uses_blank_retain_fields(
    qapp, engine, managed_qt_widget
):
    command = EditFunctionScanCommand()
    function_scan, _ = _attach_sequence(engine, command)

    widget = managed_qt_widget(command.config_widget())

    target = widget.findChild(QComboBox, "target_scan_plugin")
    assert target.count() == 1
    assert target.itemData(0) == function_scan.instance_name
    assert command.target_scan == function_scan.instance_name
    for name in ("amplitude", "offset", "periods", "points", "exponent", "phase"):
        edit = widget.findChild(QLineEdit, f"{name}_expression")
        assert edit.text() == ""
        assert "Retain current" in edit.placeholderText()
    waveform = widget.findChild(QComboBox, "waveform_expression")
    assert waveform.isEditable()
    assert waveform.currentText() == ""

    amplitude = widget.findChild(QLineEdit, "amplitude_expression")
    amplitude.setText("base_amplitude * scale")
    amplitude.editingFinished.emit()
    waveform.setCurrentText("Square")
    assert command.amplitude_expr == "base_amplitude * scale"
    assert command.waveform_expr == "Square"

    reconfigure = widget.findChild(QCheckBox, "reconfigure_after_edit")
    assert not reconfigure.isChecked()
    reconfigure.setChecked(True)
    assert command.reconfigure_after_edit is True


def test_config_widget_refreshes_when_generator_type_changes(qapp, engine, managed_qt_widget):
    command = EditFunctionScanCommand()
    function_scan, stepped_scan = _attach_sequence(engine, command)
    widget = managed_qt_widget(command.config_widget())
    target = widget.findChild(QComboBox, "target_scan_plugin")
    assert target.count() == 1

    stepped_scan.scan_generator = FunctionScanGenerator(parent=stepped_scan)
    engine.update_step_plugin_catalog([function_scan, stepped_scan, command])
    qapp.processEvents()

    assert target.count() == 2
    assert {target.itemData(index) for index in range(target.count())} == {
        "field_scan",
        "stepped_scan",
    }


def test_config_widget_lists_state_and_trace_function_scans(qapp, engine, managed_qt_widget):
    command = EditFunctionScanCommand()
    function_scan, _ = _attach_sequence(engine, command)
    trace_scan = DummyPlugin()
    trace_scan.instance_name = "iv_trace"
    trace_scan.sequence_engine = engine
    engine.update_step_plugin_catalog([function_scan, trace_scan, command])

    widget = managed_qt_widget(command.config_widget())
    target = widget.findChild(QComboBox, "target_scan_plugin")

    assert {target.itemData(index) for index in range(target.count())} == {
        "field_scan",
        "iv_trace",
    }
    assert "Counter" in target.itemText(target.findData("field_scan"))
    assert "Dummy" in target.itemText(target.findData("iv_trace"))


def test_json_round_trip_preserves_optional_expressions(qapp):
    command = EditFunctionScanCommand()
    command.target_scan = "temperature_scan"
    command.amplitude_expr = "starting_amplitude * scale"
    command.points_expr = "points_for_stage"
    command.waveform_expr = "'Square'"
    command.reconfigure_after_edit = True

    restored = BasePlugin.from_json(command.to_json())

    assert isinstance(restored, EditFunctionScanCommand)
    assert restored.target_scan == "temperature_scan"
    assert restored.amplitude_expr == "starting_amplitude * scale"
    assert restored.offset_expr == ""
    assert restored.points_expr == "points_for_stage"
    assert restored.waveform_expr == "'Square'"
    assert restored.reconfigure_after_edit is True


def test_generated_code_optionally_reconfigures_target_after_edit(qapp):
    command = EditFunctionScanCommand()
    command.instance_name = "edit_scan"
    command.target_scan = "field_scan"

    assert command.generate_action_code(1, [], lambda *_args: []) == [
        "    edit_scan()",
        "",
    ]

    command.reconfigure_after_edit = True

    assert command.generate_action_code(1, [], lambda *_args: []) == [
        "    edit_scan()",
        "    field_scan.configure()",
        "",
    ]


def test_execute_rejects_missing_or_ineligible_target(qapp, engine):
    command = EditFunctionScanCommand()
    _, stepped_scan = _attach_sequence(engine, command)
    command.target_scan = stepped_scan.instance_name

    with pytest.raises(RuntimeError, match="no longer uses"):
        command.execute()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
