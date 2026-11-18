"""Buffered electrometer channels alongside the 2400 and nanovoltmeter."""

import json
from unittest.mock import MagicMock

import numpy as np
import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QTableWidget

from stoner_measurement.instruments.electrometer import ElectrometerDataFormat, ElectrometerFunction
from stoner_measurement.instruments.keithley.k2400 import BufferReading
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace._electrometer import ELECTROMETER_DRIVERS
from stoner_measurement.plugins.trace._nanovoltmeter_support import NANOVOLTMETER_DRIVERS
from stoner_measurement.plugins.trace.keithley_2400 import Keithley2400SweepPlugin


def _plugin(nanovoltmeter=False):
    plugin = Keithley2400SweepPlugin()
    plugin._resource = "GPIB0::24::INSTR"
    plugin._smu = MagicMock()
    plugin._electrometer.settings.enabled = True
    plugin._electrometer.meter = MagicMock()
    plugin._secondary_enabled = nanovoltmeter
    if nanovoltmeter:
        plugin._secondary_nanovoltmeter = MagicMock()
        plugin._secondary_nanovoltmeter.get_capabilities.return_value = NANOVOLTMETER_DRIVERS[
            plugin._secondary_driver
        ].CAPABILITIES
    plugin.scan_generator.generate = MagicMock(return_value=[0.001, 0.002])
    return plugin


@pytest.mark.parametrize("nanovoltmeter", [False, True])
def test_configure_meter_and_trigger_chain(nanovoltmeter, engine):
    plugin = _plugin(nanovoltmeter)
    engine.add_plugin("smu", plugin)
    settings = plugin._electrometer.settings
    settings.driver = "keithley_6517"
    settings.function = "VOLT"
    settings.autorange = False
    settings.input_range = "2 * 10"
    settings.nplc = "2 / 2"
    settings.filter_enabled = True
    settings.filter_count = 4
    settings.data_format = "DRE"
    settings.trigger_delay = "0.01 * 2"
    plugin.configure()
    meter = plugin._electrometer.meter
    meter.configure_input.assert_called_once_with(
        ElectrometerFunction.VOLT, autorange=False, input_range=20.0,
        nplc=1.0, filter_enabled=True, filter_count=4, zero_check=False,
    )
    meter.set_data_format.assert_called_once_with(ElectrometerDataFormat.DREAL)
    meter.prepare_buffer.assert_called_once_with(2)
    config = meter.configure_trigger_model.call_args.args[0]
    assert (config.trigger_source.value, config.arm_source.value) == ("TLIN", "IMM")
    assert config.trigger_count == 2 and config.arm_count == 1 and config.trigger_delay == 0.02
    meter.configure_trigger_link.assert_called_once_with(
        input_line=1 if nanovoltmeter else 2, output_line=3,
    )
    plugin._smu.configure_trigger_link_source_handshake.assert_called_once_with(
        input_line=3, output_line=2,
    )


@pytest.mark.parametrize("driver", ELECTROMETER_DRIVERS)
def test_connect_all_three_instruments(driver, monkeypatch):
    plugin = _plugin(True)
    plugin._electrometer.meter = None
    plugin._electrometer.settings.driver = driver
    transports = [MagicMock(), MagicMock(), MagicMock()]
    monkeypatch.setattr(
        "stoner_measurement.plugins.trace.keithley_2400.GpibTransport.from_resource_string",
        MagicMock(side_effect=transports),
    )
    monkeypatch.setattr("stoner_measurement.plugins.trace.keithley_2400.Keithley2400", MagicMock())
    monkeypatch.setitem(NANOVOLTMETER_DRIVERS, plugin._secondary_driver, MagicMock())
    meter = MagicMock()
    factory = MagicMock(return_value=meter)
    monkeypatch.setitem(ELECTROMETER_DRIVERS, driver, factory)
    plugin.connect()
    factory.assert_called_once_with(transports[-1])
    meter.confirm_identity.assert_called_once()
    plugin.disconnect()
    meter.abort.assert_called_once()
    meter.disconnect.assert_called_once()


@pytest.mark.parametrize("nanovoltmeter", [False, True])
def test_acquisition_arms_meters_before_source_and_reads_buffer(nanovoltmeter, monkeypatch):
    plugin = _plugin(nanovoltmeter)
    plugin.configure()
    smu, meter = plugin._smu, plugin._electrometer.meter
    calls = []
    meter.start_buffer.side_effect = lambda: calls.append("electrometer")
    if nanovoltmeter:
        plugin._secondary_nanovoltmeter.initiate.side_effect = lambda: calls.append("nanovoltmeter")
        plugin._secondary_nanovoltmeter.read_buffer.return_value = (0.1, 0.2)
    smu.initiate.side_effect = lambda: calls.append("source")
    smu.wait_for_buffer_full_srq.return_value = True
    smu.read_buffer_records.return_value = (
        BufferReading(voltage=0.1, current=0.001, resistance=100, time=0, status=0),
        BufferReading(voltage=0.2, current=0.002, resistance=100, time=1, status=0),
    )
    meter.read_buffer.return_value = (1e-10, 2e-10)
    monkeypatch.setattr("stoner_measurement.plugins.trace.keithley_2400.time.sleep", lambda _: None)
    trace = plugin.measure({})["IV"]
    assert calls == (["electrometer", "nanovoltmeter", "source"] if nanovoltmeter else ["electrometer", "source"])
    meter.wait_for_buffer_complete.assert_called_once()
    meter.read_buffer.assert_called_once_with()
    np.testing.assert_allclose(trace.df["electrometer Current"], [1e-10, 2e-10])
    assert trace.units["electrometer Current"] == "A"
    assert "secondary V" in trace.df if nanovoltmeter else "secondary V" not in trace.df


@pytest.mark.parametrize("field,value,error", [
    ("buffer_size", 3, "buffer size"),
    ("trigger_count", 4, "trigger count"),
    ("nplc", -1, "NPLC"),
    ("completion_line", 2, "distinct"),
    ("function", "VOLT", "function"),
    ("data_format", "DRE", "transfer format"),
    ("resource", "GPIB0::24::INSTR", "distinct GPIB"),
])
def test_invalid_settings_rejected_before_configuring_source(field, value, error):
    plugin = _plugin()
    setattr(plugin._electrometer.settings, field, value)
    with pytest.raises(ValueError, match=error):
        plugin.configure()
    plugin._smu.reset.assert_not_called()


def test_roundtrip_including_disabled_settings_and_legacy_default():
    plugin = _plugin()
    settings = plugin._electrometer.settings
    settings.enabled = False
    settings.driver = "keithley_6514"
    settings.function = "CHAR"
    settings.nplc = "integration"
    settings.prefix = "gate"
    data = json.loads(json.dumps(plugin.to_json()))
    restored = BasePlugin.from_json(data)
    assert restored._electrometer.settings == settings
    data.pop("secondary_electrometer")
    assert not BasePlugin.from_json(data)._electrometer.settings.enabled


def test_page_model_capabilities_and_independent_enable(managed_plugin_config_tabs):
    plugin = Keithley2400SweepPlugin()
    pages = managed_plugin_config_tabs(plugin)
    settings_page = pages[1][1]
    table = settings_page.findChild(QTableWidget, "electrometer_settings")
    enabled = settings_page.findChild(QCheckBox, "electrometer_enabled")
    function = settings_page.findChild(QComboBox, "electrometer_function")
    driver = settings_page.findChild(QComboBox, "electrometer_driver")
    data_format = settings_page.findChild(QComboBox, "electrometer_data_format")
    assert not table.isEnabled()
    assert function.count() == 1
    enabled.setChecked(True)
    assert table.isEnabled()
    assert not plugin._secondary_enabled
    assert not settings_page.findChild(QComboBox, "trigger_routing").isEnabled()
    driver.setCurrentIndex(driver.findData("keithley_6517"))
    assert function.count() == 4 and data_format.count() == 3
    function.setCurrentIndex(function.findData("CHAR"))
    assert plugin._electrometer.settings.function == "CHAR"
    driver.setCurrentIndex(driver.findData("keithley_6485"))
    assert function.currentData() == "CURR" and data_format.count() == 2


def test_short_buffer_fails_and_aborts_all_owned_instruments(monkeypatch):
    plugin = _plugin(True)
    plugin.configure()
    plugin._smu.wait_for_buffer_full_srq.return_value = True
    plugin._secondary_nanovoltmeter.read_buffer.return_value = (1.0, 2.0)
    plugin._electrometer.meter.read_buffer.return_value = (1e-10,)
    monkeypatch.setattr("stoner_measurement.plugins.trace.keithley_2400.time.sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="electrometer returned 1 readings"):
        plugin._acquire_buffer_records({})
    plugin._electrometer.meter.abort.assert_called_once()
    plugin._secondary_nanovoltmeter.abort.assert_called_once()
    plugin._smu.safe_output_off.assert_called_once()


def test_cleanup_failure_still_closes_other_instruments():
    plugin = _plugin(True)
    plugin._electrometer.meter.abort.side_effect = OSError("abort failed")
    meter, smu, nano = plugin._electrometer.meter, plugin._smu, plugin._secondary_nanovoltmeter
    with pytest.raises(OSError, match="abort failed"):
        plugin.disconnect()
    meter.disconnect.assert_called_once()
    smu.disconnect.assert_called_once()
    nano.disconnect.assert_called_once()
    assert plugin._electrometer.meter is None


def test_reconnect_releases_all_three_previous_connections(monkeypatch):
    plugin = _plugin(True)
    plugin._electrometer.meter = None
    monkeypatch.setattr(
        "stoner_measurement.plugins.trace.keithley_2400.GpibTransport.from_resource_string",
        MagicMock(side_effect=lambda *a, **k: MagicMock()),
    )
    smu_factory, nano_factory, electro_factory = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr("stoner_measurement.plugins.trace.keithley_2400.Keithley2400", smu_factory)
    monkeypatch.setitem(NANOVOLTMETER_DRIVERS, plugin._secondary_driver, nano_factory)
    monkeypatch.setitem(ELECTROMETER_DRIVERS, plugin._electrometer.settings.driver, electro_factory)
    plugin.connect()
    plugin.connect()
    for factory in (smu_factory, nano_factory, electro_factory):
        assert factory.call_count == 2
        factory.return_value.disconnect.assert_called_once()


def test_failed_electrometer_identification_closes_partial_transports(monkeypatch):
    plugin = _plugin(True)
    plugin._electrometer.meter = None
    transports = [MagicMock(), MagicMock(), MagicMock()]
    monkeypatch.setattr(
        "stoner_measurement.plugins.trace.keithley_2400.GpibTransport.from_resource_string",
        MagicMock(side_effect=transports),
    )
    monkeypatch.setattr("stoner_measurement.plugins.trace.keithley_2400.Keithley2400", MagicMock())
    monkeypatch.setitem(NANOVOLTMETER_DRIVERS, plugin._secondary_driver, MagicMock())
    factory = MagicMock()
    factory.return_value.confirm_identity.side_effect = OSError("wrong meter")
    monkeypatch.setitem(ELECTROMETER_DRIVERS, plugin._electrometer.settings.driver, factory)
    with pytest.raises(OSError, match="wrong meter"):
        plugin.connect()
    for transport in transports:
        transport.close.assert_called_once()
    assert plugin._smu is plugin._secondary_nanovoltmeter is plugin._electrometer.meter is None


def test_charge_column_and_statistics_use_si_units():
    plugin = _plugin()
    plugin._electrometer.settings.driver = "keithley_6514"
    plugin._electrometer.settings.function = "CHAR"
    plugin._electrometer.settings.prefix = "gate"
    plugin._electrometer.readings = (1e-9, 3e-9)
    plugin._sweep_values = (0.001, 0.002)
    plugin._report_channel_statistics = True
    plugin._acquire_buffer_records = MagicMock(return_value=(
        BufferReading(voltage=0.1, current=0.001, resistance=100, time=0, status=0),
        BufferReading(voltage=0.2, current=0.002, resistance=100, time=1, status=0),
    ))
    trace = plugin.measure({})["IV"]
    assert trace.units["gate Charge"] == "C"
    assert plugin.get_channel_statistic("IV gate Charge", "mean") == pytest.approx(2e-9)
    key = f"{plugin.instance_name}:IV gate Charge mean"
    assert key in plugin.reported_values()
    assert plugin.reported_value_units()[key] == "C"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
