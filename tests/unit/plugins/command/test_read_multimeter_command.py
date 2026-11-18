"""Single-reading DMM command settings, scalar outputs and lifecycle."""

import json
import math
from unittest.mock import MagicMock

import pytest
from qtpy.QtWidgets import QComboBox, QWidget

from stoner_measurement.core.validation import ValidationError
from stoner_measurement.instruments.dmm import DmmFunction
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command.read_multimeter import (
    DMM_CHANNELS,
    DMM_DRIVERS,
    ReadMultimeterCommand,
)


def _connected():
    command = ReadMultimeterCommand()
    command._meter = MagicMock()
    command._connected_driver = command.driver
    return command


@pytest.mark.parametrize("driver", DMM_DRIVERS)
def test_model_connect_reconnect_cleanup(driver, monkeypatch):
    command = ReadMultimeterCommand()
    command.driver = driver
    factory = MagicMock()
    monkeypatch.setitem(DMM_DRIVERS, driver, factory)
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.read_multimeter.GpibTransport.from_resource_string", MagicMock(),
    )
    command.connect()
    command.connect()
    assert factory.call_count == 2
    assert factory.return_value.confirm_identity.call_count == 2
    factory.return_value.disconnect.assert_called_once()
    command.disconnect()
    command.disconnect()
    assert factory.return_value.disconnect.call_count == 2


def test_failed_identity_releases_partial_transport(monkeypatch):
    command = ReadMultimeterCommand()
    factory, transport = MagicMock(), MagicMock()
    factory.return_value.confirm_identity.side_effect = OSError("identity failed")
    monkeypatch.setitem(DMM_DRIVERS, command.driver, factory)
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.read_multimeter.GpibTransport.from_resource_string",
        MagicMock(return_value=transport),
    )
    with pytest.raises(OSError, match="identity failed"):
        command.connect()
    transport.close.assert_called_once()
    assert command._meter is None


def test_expressions_are_resolved_at_configuration(engine):
    command = _connected()
    engine.add_plugin("read_multimeter", command)
    command.autorange = False
    command.input_range = "limit"
    command.nplc = "cycles"
    command.trigger_delay = "delay"
    command.engine_namespace.update(limit=20.0, cycles=2.0, delay=0.05)
    command.validate()
    command.configure()
    command._meter.configure_single_reading.assert_called_once_with(
        DmmFunction.VOLT_DC, autorange=False, input_range=20.0, nplc=2.0, gate_time=0.1,
        trigger_delay=0.05, filter_enabled=False, filter_count=10, filter_type="REP", ac_bandwidth=300.0,
    )


@pytest.mark.parametrize("function", list(DMM_CHANNELS))
def test_function_units_and_fresh_reading(function, engine):
    command = _connected()
    command.function = function.value
    engine.add_plugin("read_multimeter", command)
    command.configure()
    command._meter.read_single_snapshot.return_value = (1.25, {"trigger_delay": 0.0, "timeout": 30.0})
    command()
    assert command.value == 1.25
    label, unit = DMM_CHANNELS[function]
    key = f"{command.instance_name}:{label}"
    assert command.reported_value_units()[key] == unit
    assert engine.evaluate_expression(command.reported_values()[key]) == 1.25
    command._meter.read_single_snapshot.return_value = (2.5, {"trigger_delay": 0.1, "timeout": 40.0})
    command()
    assert command.value == 2.5
    assert command.settings_readback["timeout"] == 40.0
    command.disconnect()
    assert command.value == 2.5


def test_settings_outputs_are_actual_readbacks_not_requested_values(engine):
    command = _connected()
    engine.add_plugin("read_multimeter", command)
    command.input_range = 10.0
    command.configure()
    command._meter.read_single_snapshot.return_value = (0.01, {
        "range": 0.1, "autorange": 1.0, "nplc": 1.0, "filter_enabled": 0.0,
        "filter_count": 10.0, "filter_type": 0.0, "trigger_delay": 0.0, "timeout": 30.0,
    })
    command()
    outputs = command.reported_values()
    assert engine.evaluate_expression(outputs["read_multimeter:Range"]) == 0.1
    assert command.reported_value_units()["read_multimeter:Range"] == "V"
    assert set(outputs) == set(command.reported_value_units())


def test_failure_clears_reading_and_setting_outputs():
    command = _connected()
    command.configure()
    command.value = 5.0
    command.settings_readback = {"range": 10.0}
    command._meter.read_single_snapshot.side_effect = TimeoutError("no reading")
    with pytest.raises(TimeoutError, match="no reading"):
        command()
    assert math.isnan(command.value) and not command.settings_readback


def test_disabled_function_settings_are_not_evaluated():
    command = _connected()
    command.function = "FREQ"
    command.input_range = "not valid syntax !"
    command.nplc = "also invalid !"
    assert command.validate()
    command.configure()
    outputs = command.reported_values()
    assert "read_multimeter:Gate Time" in outputs
    assert "read_multimeter:NPLC" not in outputs
    assert "read_multimeter:Range" not in outputs


def test_ui_updates_controls_and_output_catalogue(engine, managed_plugin_config_tabs):
    command = ReadMultimeterCommand()
    engine.add_plugin("read_multimeter", command)
    engine.update_step_plugin_catalog([command])
    page = managed_plugin_config_tabs(command)[0][1]
    function = page.findChild(QComboBox, "multimeter_function")
    bandwidth = page.findChild(QComboBox, "multimeter_ac_bandwidth")
    function.setCurrentIndex(function.findData("VOLT:AC"))
    bandwidth.setCurrentIndex(bandwidth.findData(30.0))
    assert not page.findChild(QWidget, "multimeter_nplc").isEnabled()
    assert "read_multimeter:AC Bandwidth" in engine.values_catalog
    assert "read_multimeter:NPLC" not in engine.values_catalog
    function.setCurrentIndex(function.findData("FREQ"))
    assert page.findChild(QWidget, "multimeter_gate_time").isEnabled()
    assert not page.findChild(QWidget, "multimeter_autorange").isEnabled()
    assert "read_multimeter:Frequency" in engine.values_catalog


def test_json_preserves_settings_without_live_readings():
    command = _connected()
    command.driver = "keithley_2700"
    command.function = "FRES"
    command.nplc = "integration"
    command.value = 123.0
    command.settings_readback = {"range": 1000.0}
    restored = BasePlugin.from_json(json.loads(json.dumps(command.to_json())))
    assert restored.to_json() == command.to_json()
    assert restored._meter is None and math.isnan(restored.value)
    assert not restored.settings_readback


def test_generated_sequence_reads_twice_then_closes(engine, null_plot_display_host, monkeypatch):
    command = ReadMultimeterCommand()
    command.sequence_engine = engine
    factory = MagicMock()
    factory.return_value.read_single_snapshot.side_effect = [(1.0, {}), (2.0, {})]
    monkeypatch.setitem(DMM_DRIVERS, command.driver, factory)
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.read_multimeter.GpibTransport.from_resource_string", MagicMock(),
    )
    namespace = dict(engine.namespace)
    namespace[command.instance_name] = command
    code = engine.generate_sequence_code([command, command], {})
    exec(code, namespace)  # noqa: S102  # nosec B102  # pylint: disable=exec-used
    factory.assert_called_once()
    assert factory.return_value.read_single_snapshot.call_count == 2
    factory.return_value.disconnect.assert_called_once()
    assert command.value == 2.0


@pytest.mark.parametrize("name,value", [("nplc", -1), ("function", "UNKNOWN"), ("trigger_delay", "1 +")])
def test_invalid_settings_fail_preflight(name, value):
    command = ReadMultimeterCommand()
    setattr(command, name, value)
    with pytest.raises(ValidationError):
        command.validate()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
