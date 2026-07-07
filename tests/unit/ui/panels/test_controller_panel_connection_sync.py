"""Tests for controller-panel resync from existing engine connections."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.simulated import (
    SimulatedMagnetController,
    SimulatedMotorController,
    SimulatedTemperatureController,
)
from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.motor_control.engine import MotorControllerEngine
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.ui.widgets import VisaResourceStatus


@pytest.fixture(autouse=True)
def cleanup_controller_engine_singletons():
    """Ensure controller-engine singletons do not leak between tests."""
    for engine_cls in (
        TemperatureControllerEngine,
        MagnetControllerEngine,
        MotorControllerEngine,
    ):
        engine = engine_cls._singleton  # pylint: disable=protected-access
        if engine is not None:
            engine.shutdown()
    yield
    for engine_cls in (
        TemperatureControllerEngine,
        MagnetControllerEngine,
        MotorControllerEngine,
    ):
        engine = engine_cls._singleton  # pylint: disable=protected-access
        if engine is not None:
            engine.shutdown()


@pytest.fixture
def temperature_engine(qapp):
    """Return a connected temperature engine and shut it down after the test."""
    _ = qapp
    engine = TemperatureControllerEngine.instance()
    engine.preferred_transport_name = "GPIB"
    engine.preferred_address = "GPIB0::9::INSTR"
    engine.connect_instrument(SimulatedTemperatureController())
    engine._connected_transport_name = "Serial"  # pylint: disable=protected-access
    engine._connected_address = "port=COM7;baud=9600"  # pylint: disable=protected-access
    yield engine
    engine.shutdown()


@pytest.fixture
def magnet_engine(qapp):
    """Return a connected magnet engine and shut it down after the test."""
    _ = qapp
    engine = MagnetControllerEngine.instance()
    engine.preferred_transport_name = "GPIB"
    engine.preferred_address = "GPIB0::9::INSTR"
    engine.connect_instrument(SimulatedMagnetController())
    engine._connected_transport_name = "Serial"  # pylint: disable=protected-access
    engine._connected_address = "port=COM8;baud=9600"  # pylint: disable=protected-access
    yield engine
    engine.shutdown()


@pytest.fixture
def motor_engine(qapp):
    """Return a connected motor engine and shut it down after the test."""
    _ = qapp
    engine = MotorControllerEngine.instance()
    engine.preferred_transport_name = "GPIB"
    engine.preferred_address = "GPIB0::9::INSTR"
    engine.connect_instrument(SimulatedMotorController())
    engine._connected_transport_name = "Serial"  # pylint: disable=protected-access
    engine._connected_address = "port=COM9;baud=9600"  # pylint: disable=protected-access
    yield engine
    engine.shutdown()


def test_temperature_panel_syncs_existing_connection_on_show(qapp, temperature_engine):
    """Showing the temperature panel should reflect an already-open connection."""
    from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

    panel = TemperatureControlPanel()
    before_updated = panel._updated_label.text()  # pylint: disable=protected-access

    assert panel._transport_combo.currentText() == "GPIB"  # pylint: disable=protected-access
    assert not panel._loop_groups  # pylint: disable=protected-access

    panel.show()
    qapp.processEvents()

    assert panel._transport_combo.currentText() == "Serial"  # pylint: disable=protected-access
    assert panel._serial_port_combo.current_resource() == "COM7"  # pylint: disable=protected-access
    assert panel._serial_port_combo.status is VisaResourceStatus.CONNECTED  # pylint: disable=protected-access
    assert not panel._btn_connect.isEnabled()  # pylint: disable=protected-access
    assert panel._btn_disconnect.isEnabled()  # pylint: disable=protected-access
    assert panel._capabilities is not None  # pylint: disable=protected-access
    assert panel._loop_groups  # pylint: disable=protected-access
    assert panel._updated_label.text() != before_updated  # pylint: disable=protected-access


def test_magnet_panel_syncs_existing_connection_on_show(qapp, magnet_engine):
    """Showing the magnet panel should reflect an already-open connection."""
    from stoner_measurement.ui.magnet_panel import MagnetControlPanel

    panel = MagnetControlPanel()
    before_updated = panel._updated_label.text()  # pylint: disable=protected-access

    assert panel._transport_combo.currentText() == "GPIB"  # pylint: disable=protected-access

    panel.show()
    qapp.processEvents()

    assert panel._transport_combo.currentText() == "Serial"  # pylint: disable=protected-access
    assert panel._serial_port_combo.current_resource() == "COM8"  # pylint: disable=protected-access
    assert panel._serial_port_combo.status is VisaResourceStatus.CONNECTED  # pylint: disable=protected-access
    assert not panel._btn_connect.isEnabled()  # pylint: disable=protected-access
    assert panel._btn_disconnect.isEnabled()  # pylint: disable=protected-access
    assert panel._updated_label.text() != before_updated  # pylint: disable=protected-access


def test_motor_panel_syncs_existing_connection_on_show(qapp, motor_engine):
    """Showing the motor panel should reflect an already-open connection."""
    from stoner_measurement.ui.motor_panel import MotorControlPanel

    panel = MotorControlPanel()
    before_angle = panel._angle_label.text()  # pylint: disable=protected-access

    assert panel._transport_combo.currentText() == "GPIB"  # pylint: disable=protected-access

    panel.show()
    qapp.processEvents()

    assert panel._transport_combo.currentText() == "Serial"  # pylint: disable=protected-access
    assert panel._serial_port_combo.current_resource() == "COM9"  # pylint: disable=protected-access
    assert panel._serial_port_combo.status is VisaResourceStatus.CONNECTED  # pylint: disable=protected-access
    assert not panel._btn_connect.isEnabled()  # pylint: disable=protected-access
    assert panel._btn_disconnect.isEnabled()  # pylint: disable=protected-access
    assert panel._angle_label.text() != before_angle  # pylint: disable=protected-access


def test_temperature_panel_reacts_to_external_connect_and_disconnect(qapp):
    """An open temperature panel should resync on external connect changes."""
    from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

    engine = TemperatureControllerEngine.instance()
    engine.preferred_driver_name = "SimulatedTemperatureController"
    engine.preferred_transport_name = "Null (test)"
    engine.preferred_address = ""
    panel = TemperatureControlPanel()
    panel.show()
    qapp.processEvents()

    assert panel._btn_connect.isEnabled()  # pylint: disable=protected-access
    assert not panel._loop_groups  # pylint: disable=protected-access

    engine.connect_preferred_driver()
    qapp.processEvents()

    assert not panel._btn_connect.isEnabled()  # pylint: disable=protected-access
    assert panel._btn_disconnect.isEnabled()  # pylint: disable=protected-access
    assert panel._transport_combo.currentText() == "Null (test)"  # pylint: disable=protected-access
    assert panel._loop_groups  # pylint: disable=protected-access

    engine.disconnect_instrument()
    qapp.processEvents()

    assert panel._btn_connect.isEnabled()  # pylint: disable=protected-access
    assert not panel._btn_disconnect.isEnabled()  # pylint: disable=protected-access
    assert not panel._loop_groups  # pylint: disable=protected-access
    engine.shutdown()


def test_magnet_panel_reacts_to_external_connect_and_disconnect(qapp):
    """An open magnet panel should resync on external connect changes."""
    from stoner_measurement.ui.magnet_panel import MagnetControlPanel

    engine = MagnetControllerEngine.instance()
    engine.preferred_driver_name = "SimulatedMagnetController"
    engine.preferred_transport_name = "Null (test)"
    engine.preferred_address = ""
    panel = MagnetControlPanel()
    panel.show()
    qapp.processEvents()

    assert panel._btn_connect.isEnabled()  # pylint: disable=protected-access

    engine.connect_preferred_driver()
    qapp.processEvents()

    assert not panel._btn_connect.isEnabled()  # pylint: disable=protected-access
    assert panel._btn_disconnect.isEnabled()  # pylint: disable=protected-access
    assert panel._transport_combo.currentText() == "Null (test)"  # pylint: disable=protected-access

    engine.disconnect_instrument()
    qapp.processEvents()

    assert panel._btn_connect.isEnabled()  # pylint: disable=protected-access
    assert not panel._btn_disconnect.isEnabled()  # pylint: disable=protected-access
    engine.shutdown()


def test_motor_panel_reacts_to_external_connect_and_disconnect(qapp):
    """An open motor panel should resync on external connect changes."""
    from stoner_measurement.ui.motor_panel import MotorControlPanel

    engine = MotorControllerEngine.instance()
    engine.preferred_driver_name = "SimulatedMotorController"
    engine.preferred_transport_name = "Null (test)"
    engine.preferred_address = ""
    panel = MotorControlPanel()
    panel.show()
    qapp.processEvents()

    assert panel._btn_connect.isEnabled()  # pylint: disable=protected-access

    engine.connect_preferred_driver()
    qapp.processEvents()

    assert not panel._btn_connect.isEnabled()  # pylint: disable=protected-access
    assert panel._btn_disconnect.isEnabled()  # pylint: disable=protected-access
    assert panel._transport_combo.currentText() == "Null (test)"  # pylint: disable=protected-access

    engine.disconnect_instrument()
    qapp.processEvents()

    assert panel._btn_connect.isEnabled()  # pylint: disable=protected-access
    assert not panel._btn_disconnect.isEnabled()  # pylint: disable=protected-access
    engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
