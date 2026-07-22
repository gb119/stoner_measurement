"""Focused behaviour tests for the pressure control panel."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stoner_measurement.instruments.pressure_controller import (
    PressureReading,
    PressureStatus,
    PressureUnit,
)
from stoner_measurement.instruments.simulated import (
    SimulatedMassFlowController,
    SimulatedPressureGaugeController,
)
from stoner_measurement.pressure_control.engine import PressureControllerEngine
from stoner_measurement.pressure_control.types import PressureEngineReading, PressureEngineState
from stoner_measurement.ui.pressure_panel import PressureControlPanel
from stoner_measurement.ui.widgets import VisaResourceStatus


@pytest.fixture
def panel(qtbot):
    """Return a panel with singleton cleanup scoped to the test."""
    widget = PressureControlPanel()
    qtbot.addWidget(widget)
    yield widget
    widget._engine.shutdown()  # noqa: SLF001


def test_save_button_is_outside_both_controller_groups(panel):
    """The shared YAML save action is not owned by either connection group."""
    assert panel._btn_save_configuration.parentWidget() is not panel._address_group  # noqa: SLF001
    assert panel._btn_save_configuration.parentWidget() is not panel._mfc_address_group  # noqa: SLF001


@pytest.mark.parametrize("transport", ["Serial", "GPIB", "Ethernet", "Null (test)"])
def test_mfc_connection_indicator_tracks_all_transport_types(panel, transport):
    """Every MFC address presentation receives connected styling."""
    engine = panel._engine  # noqa: SLF001
    engine.connect_mfc_instrument(SimulatedMassFlowController())
    engine._connected_mfc_transport_name = transport  # noqa: SLF001
    engine._connected_mfc_address = ""  # noqa: SLF001

    panel._sync_existing_connection_state()  # noqa: SLF001

    index = panel._mfc_transport_combo.findText(transport)  # noqa: SLF001
    if index == 0:
        assert panel._mfc_serial_port_combo.status is VisaResourceStatus.CONNECTED  # noqa: SLF001
    elif index == 1:
        assert panel._mfc_gpib_resource_combo.status is VisaResourceStatus.CONNECTED  # noqa: SLF001
    else:
        widget = panel._mfc_ethernet_form_widget if index == 2 else panel._mfc_null_form_widget  # noqa: SLF001
        assert "#90ee90" in widget.styleSheet()


def test_chart_uses_log_pressure_axis_and_live_value_legend(panel):
    """Pressure is logarithmic and incoming traces expose current values."""
    assert panel._chart_widget._axis_log_scale["left"] is True  # noqa: SLF001
    state = PressureEngineState(
        reading=PressureEngineReading(timestamp=datetime.now(tz=UTC), readings={}),
        readings={1: PressureReading(1, 1.2e-6, PressureUnit.MBAR, PressureStatus.OK)},
        flow_actual={1: 0.25},
        flow_unit="sccm",
    )

    panel._on_state_updated(state)  # noqa: SLF001

    assert panel._legend_items["Pressure 1"].text(1) == "1.2000E-06 mbar"  # noqa: SLF001
    assert panel._legend_items["Flow actual 1"].text(1) == "0.25 sccm"  # noqa: SLF001


def test_monitor_reports_supported_interlocks(panel):
    """Named interlock states appear only when supplied by the driver state."""
    state = PressureEngineState(interlocks={"Vacuum": True, "Water": False})
    panel._on_state_updated(state)  # noqa: SLF001

    assert panel._interlock_group.isHidden() is False  # noqa: SLF001
    values = {
        panel._interlock_table.item(row, 0).text(): panel._interlock_table.item(row, 1).text()  # noqa: SLF001
        for row in range(panel._interlock_table.rowCount())  # noqa: SLF001
    }
    assert values == {"Vacuum": "OK", "Water": "Tripped"}


def test_monitor_places_gauge_controls_and_interlocks_side_by_side(panel):
    """The two narrow monitor tables share a row above the expanding MFC table."""
    layout = panel._monitor_aux_layout  # noqa: SLF001

    assert layout.count() == 2
    assert layout.itemAt(0).widget() is panel._gauge_table.parentWidget()  # noqa: SLF001
    assert layout.itemAt(1).widget() is panel._interlock_group  # noqa: SLF001


def test_engine_aggregates_mfc_read_errors_into_main_status(qapp):
    """An MFC failure marks the shared pressure-engine status as an error."""
    _ = qapp

    class BrokenMfc(SimulatedMassFlowController):
        def read_actual_value(self, channel: int = 1) -> float:
            raise RuntimeError("MFC offline")

    engine = PressureControllerEngine.instance()
    engine.connect_instrument(SimulatedPressureGaugeController())
    engine.connect_mfc_instrument(BrokenMfc())

    state = engine.read_controller_state()

    assert state is not None
    assert engine.mfc_has_error is True
    assert engine.status.value == "error"
    engine.shutdown()


def test_engine_reads_interlocks_for_capable_driver(qapp):
    """The simulated driver exercises interlock reporting end to end."""
    _ = qapp
    engine = PressureControllerEngine.instance()
    driver = SimulatedPressureGaugeController()
    driver.set_simulated_interlock("Cooling water", False)
    engine.connect_instrument(driver)

    state = engine.read_controller_state()

    assert state is not None
    assert state.interlocks == {
        "Access door": True,
        "Cooling water": False,
        "Vacuum": True,
    }
    engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
