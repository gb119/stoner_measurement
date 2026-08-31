"""Behaviour tests for reusable DAQmx trigger configuration widgets."""

from __future__ import annotations

import pytest

from stoner_measurement.ui.widgets.daqmx_trigger_widget import (
    DaqmxInputTrigger,
    DaqmxInputTriggerMode,
    DaqmxInputTriggerWidget,
    DaqmxOutputTrigger,
    DaqmxOutputTriggerWidget,
    DaqmxTriggerEdge,
    DaqmxTriggerIdleState,
)
from stoner_measurement.ui.widgets.si_spinbox import SISpinBox


def test_input_trigger_modes_enable_only_relevant_controls(managed_qt_widget):
    widget = managed_qt_widget(DaqmxInputTriggerWidget())

    assert not widget.edge_combo.isEnabled()
    assert not widget.terminal_combo.isEnabled()
    assert not widget.level_spin.isEnabled()

    widget.set_trigger(
        DaqmxInputTrigger(
            mode=DaqmxInputTriggerMode.ANALOG,
            edge=DaqmxTriggerEdge.FALLING,
            terminal="/Dev1/APFI0",
            analog_level=0.125,
        )
    )

    assert widget.edge_combo.isEnabled()
    assert widget.terminal_combo.isEnabled()
    assert widget.level_spin.isEnabled()
    assert widget.trigger() == DaqmxInputTrigger(
        mode=DaqmxInputTriggerMode.ANALOG,
        edge=DaqmxTriggerEdge.FALLING,
        terminal="/Dev1/APFI0",
        analog_level=0.125,
    )

    digital_index = widget.mode_combo.findData(DaqmxInputTriggerMode.DIGITAL.value)
    widget.mode_combo.setCurrentIndex(digital_index)

    assert widget.edge_combo.isEnabled()
    assert widget.terminal_combo.isEnabled()
    assert not widget.level_spin.isEnabled()


def test_discovered_routes_retain_manually_configured_values(managed_qt_widget):
    input_widget = managed_qt_widget(
        DaqmxInputTriggerWidget(trigger=DaqmxInputTrigger(terminal="/Dev2/PFI7"))
    )
    output_widget = managed_qt_widget(
        DaqmxOutputTriggerWidget(trigger=DaqmxOutputTrigger(line="Dev2/port1/line3"))
    )

    input_widget.set_available_terminals(("/Dev1/PFI1", "/Dev1/PFI0"))
    output_widget.set_available_lines(("Dev1/port0/line1", "Dev1/port0/line0"))

    assert input_widget.terminal_combo.currentText() == "/Dev2/PFI7"
    assert output_widget.line_combo.currentText() == "Dev2/port1/line3"


def test_output_trigger_phase_and_shape_round_trip(managed_qt_widget):
    trigger = DaqmxOutputTrigger(
        enabled=True,
        line="Dev1/port0/line0",
        idle_state=DaqmxTriggerIdleState.HIGH,
        phase_angle=135.0,
        delay=2e-6,
        high_time=3e-6,
        low_time=5e-6,
    )
    widget = managed_qt_widget(DaqmxOutputTriggerWidget(trigger=trigger))

    assert widget.trigger() == trigger
    assert widget.phase_angle_spin.isEnabled()
    assert widget.preview._trigger == trigger
    assert widget.minimumSize() == widget.maximumSize()
    assert widget.layout().getItemPosition(widget.layout().indexOf(widget.preview)) == (
        2,
        0,
        1,
        2,
    )

    changes = []
    widget.trigger_changed.connect(changes.append)
    widget.phase_angle_spin.setValue(225.0)

    assert changes[-1].phase_angle == 225.0
    assert widget.preview._trigger.phase_angle == 225.0


def test_trigger_models_have_json_compatible_round_trips():
    input_trigger = DaqmxInputTrigger(
        mode=DaqmxInputTriggerMode.DIGITAL,
        edge=DaqmxTriggerEdge.FALLING,
        terminal="/Dev1/PFI2",
    )
    output_trigger = DaqmxOutputTrigger(
        enabled=True,
        line="Dev1/port0/line1",
        phase_angle=90.0,
        high_time=1e-3,
    )

    assert DaqmxInputTrigger.from_dict(input_trigger.to_dict()) == input_trigger
    assert DaqmxOutputTrigger.from_dict(output_trigger.to_dict()) == output_trigger
    assert "line" in output_trigger.to_dict()
    assert "counter" not in output_trigger.to_dict()


def test_all_physical_property_editors_are_si_spin_boxes(managed_qt_widget):
    input_widget = managed_qt_widget(DaqmxInputTriggerWidget())
    output_widget = managed_qt_widget(DaqmxOutputTriggerWidget())

    assert isinstance(input_widget.level_spin, SISpinBox)
    assert all(
        isinstance(editor, SISpinBox)
        for editor in (
            output_widget.phase_angle_spin,
            output_widget.delay_spin,
            output_widget.high_time_spin,
            output_widget.low_time_spin,
        )
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
