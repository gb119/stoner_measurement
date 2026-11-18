"""Single-reading outputs, settings and owned electrometer lifecycle."""

import json
import math
from unittest.mock import MagicMock

import pytest
from qtpy.QtWidgets import QComboBox

from stoner_measurement.core.validation import ValidationError
from stoner_measurement.instruments.electrometer import ElectrometerFunction
from stoner_measurement.plugins._electrometer import ELECTROMETER_DRIVERS
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command.read_electrometer import ReadElectrometerCommand


def _connected_command():
    command = ReadElectrometerCommand()
    command._meter = MagicMock()
    command._connected_driver = command.driver
    return command


@pytest.mark.parametrize("driver", ELECTROMETER_DRIVERS)
def test_selected_driver_connects_identifies_and_reconnects(driver, monkeypatch):
    command = ReadElectrometerCommand()
    command.driver = driver
    transport = MagicMock()
    transport_factory = MagicMock(return_value=transport)
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.read_electrometer.GpibTransport.from_resource_string",
        transport_factory,
    )
    meter = MagicMock()
    factory = MagicMock(return_value=meter, MEASURE_FUNCTIONS=ELECTROMETER_DRIVERS[driver].MEASURE_FUNCTIONS)
    monkeypatch.setitem(ELECTROMETER_DRIVERS, driver, factory)
    command.connect()
    command.connect()
    assert factory.call_count == 2
    factory.assert_called_with(transport)
    assert meter.confirm_identity.call_count == 2
    meter.abort.assert_called_once()
    meter.disconnect.assert_called_once()
    command.disconnect()


def test_partial_connection_is_closed_and_retry_is_allowed(monkeypatch):
    command = ReadElectrometerCommand()
    transports = [MagicMock(), MagicMock()]
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.read_electrometer.GpibTransport.from_resource_string",
        MagicMock(side_effect=transports),
    )
    bad, good = MagicMock(), MagicMock()
    bad.confirm_identity.side_effect = OSError("identity failed")
    factory = MagicMock(side_effect=[bad, good], MEASURE_FUNCTIONS=(ElectrometerFunction.CURR,))
    monkeypatch.setitem(ELECTROMETER_DRIVERS, command.driver, factory)
    with pytest.raises(OSError, match="identity failed"):
        command.connect()
    transports[0].close.assert_called_once()
    assert command._meter is None
    command.connect()
    assert command._meter is good
    command.disconnect()


def test_configuration_evaluates_expressions_at_setup(engine):
    command = _connected_command()
    engine.add_plugin("read_meter", command)
    command.autorange = False
    command.input_range = "input_limit"
    command.nplc = "cycles"
    command.trigger_delay = "settle"
    command.timeout = "read_timeout"
    command.filter_enabled = True
    command.filter_count = 4
    command.engine_namespace.update(input_limit=2e-8, cycles=2.0, settle=0.05, read_timeout=60.0)
    command.configure()
    command._meter.configure_input.assert_called_once_with(
        ElectrometerFunction.CURR, autorange=False, input_range=2e-8,
        nplc=2.0, filter_enabled=True, filter_count=4, zero_check=False,
    )
    command._meter.prepare_single_reading.assert_called_once_with(trigger_delay=0.05)
    assert command._meter.transport.timeout == 60.0


@pytest.mark.parametrize("function,quantity,unit", [
    ("CURR", "Current", "A"), ("VOLT", "Voltage", "V"),
    ("RES", "Resistance", "Ω"), ("CHAR", "Charge", "C"),
])
def test_each_execution_publishes_a_fresh_scalar(function, quantity, unit):
    command = _connected_command()
    command.driver = command._connected_driver = "keithley_6514"
    command.function = function
    command.instance_name = "gate"
    command.configure()
    command._meter.read_measurement.side_effect = [1.25, 2.5]
    command()
    assert command.value == 1.25
    command()
    assert command.value == 2.5
    assert command._meter.read_measurement.call_count == 2
    assert command.reported_values() == {f"gate:{quantity}": "gate.value"}
    assert command.reported_value_units() == {f"gate:{quantity}": unit}
    command.disconnect()
    assert command.value == 2.5


def test_failed_read_discards_previous_output():
    command = _connected_command()
    command.configure()
    command.value = 2.0
    command._meter.read_measurement.side_effect = TimeoutError("read failed")
    with pytest.raises(TimeoutError, match="read failed"):
        command()
    assert math.isnan(command.value)


def test_cleanup_failure_still_disconnects_and_is_idempotent():
    command = _connected_command()
    meter = command._meter
    meter.abort.side_effect = OSError("abort failed")
    with pytest.raises(OSError, match="abort failed"):
        command.disconnect()
    meter.disconnect.assert_called_once()
    assert command._meter is None
    command.disconnect()


def test_json_roundtrip_restores_settings_but_not_readings_or_connections():
    command = _connected_command()
    command.driver = "keithley_6517"
    command.function = "CHAR"
    command.resource = "GPIB0::19::INSTR"
    command.nplc = "integration"
    command.value = 123.0
    restored = BasePlugin.from_json(json.loads(json.dumps(command.to_json())))
    assert restored.to_json() == command.to_json()
    assert restored._meter is None and math.isnan(restored.value)
    assert restored.function == "CHAR" and restored.nplc == "integration"


def test_ui_models_limit_functions_and_refresh_output_catalogue(managed_plugin_config_tabs, engine):
    command = ReadElectrometerCommand()
    command.instance_name = "gate"
    engine.add_plugin("gate", command)
    engine.update_step_plugin_catalog([command])
    command.value = 5.0
    pages = managed_plugin_config_tabs(command)
    page = pages[0][1]
    driver = page.findChild(QComboBox, "electrometer_driver")
    function = page.findChild(QComboBox, "electrometer_function")
    assert driver.count() == 3 and function.count() == 1
    assert command.value == 5.0
    driver.setCurrentIndex(driver.findData("keithley_6514"))
    assert math.isnan(command.value)
    assert function.count() == 4
    function.setCurrentIndex(function.findData("VOLT"))
    assert command.function == "VOLT"
    assert command.reported_value_units() == {"gate:Voltage": "V"}
    assert "gate:Voltage" in engine.values_catalog
    driver.setCurrentIndex(driver.findData("keithley_6485"))
    assert command.function == "CURR" and function.count() == 1


def test_validation_does_not_evaluate_runtime_expressions_or_open_hardware(engine, monkeypatch):
    command = ReadElectrometerCommand()
    engine.add_plugin("read_meter", command)
    command.nplc = "cycles"
    command.eval_float = MagicMock(side_effect=AssertionError("no evaluation in preflight"))
    connect = MagicMock(side_effect=AssertionError("no connection in preflight"))
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.read_electrometer.GpibTransport.from_resource_string", connect,
    )
    assert command.validate()
    command.eval_float.assert_not_called()
    connect.assert_not_called()


@pytest.mark.parametrize("setting,value", [
    ("function", "VOLT"), ("nplc", -1.0), ("nplc", "1 +"),
    ("timeout", float("nan")), ("resource", ""), ("filter_count", 0),
])
def test_invalid_settings_fail_preflight(setting, value):
    command = ReadElectrometerCommand()
    setattr(command, setting, value)
    with pytest.raises(ValidationError):
        command.validate()


def test_generated_sequence_connects_once_reads_each_time_and_cleans_up(engine, null_plot_display_host, monkeypatch):
    command = ReadElectrometerCommand()
    command.sequence_engine = engine
    meter = MagicMock()
    meter.read_measurement.side_effect = [1e-9, 2e-9]
    factory = MagicMock(return_value=meter, MEASURE_FUNCTIONS=(ElectrometerFunction.CURR,))
    monkeypatch.setitem(ELECTROMETER_DRIVERS, command.driver, factory)
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.read_electrometer.GpibTransport.from_resource_string", MagicMock(),
    )
    code = engine.generate_sequence_code([command, command], {})
    namespace = dict(engine.namespace)
    namespace[command.instance_name] = command
    # Execute the project's generated action code with only fake instruments.
    exec(code, namespace)  # noqa: S102  # nosec B102  # pylint: disable=exec-used
    factory.assert_called_once()
    assert meter.read_measurement.call_count == 2
    meter.disconnect.assert_called_once()
    assert command.value == 2e-9


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
