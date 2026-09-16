"""6221 optional-meter, trigger and resource-ownership contracts."""

import json
import math
from unittest.mock import MagicMock, call

import pytest
from qtpy.QtWidgets import QGroupBox

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.state_scan import k6221_2182a as module


@pytest.fixture
def connected(monkeypatch):
    transports = []

    def transport(*args, **kwargs):
        result = MagicMock()
        transports.append(result)
        return result

    source = MagicMock()
    primary = MagicMock()
    secondary = MagicMock()
    primary.get_capabilities.return_value = module.Keithley2182A.CAPABILITIES
    secondary.get_capabilities.return_value = module.Keithley2182A.CAPABILITIES
    primary.measure_voltage.return_value = 0.02
    secondary.measure_voltage.return_value = 0.03
    monkeypatch.setattr(module.GpibTransport, "from_resource_string", transport)
    monkeypatch.setattr(module.PassThroughGpibTransport, "from_resource_string", transport)
    monkeypatch.setattr(module, "Keithley6221", lambda transport: source)
    monkeypatch.setattr(module, "Keithley2182A", lambda transport: primary)
    monkeypatch.setitem(module.NANOVOLTMETER_DRIVERS, "keithley_2182a", lambda transport: secondary)
    plugin = module.Keithley6221PointScanPlugin()
    plugin._source_delay = 0
    return plugin, source, primary, secondary, transports


@pytest.mark.parametrize("primary,secondary", [(False, False), (True, False), (False, True), (True, True)])
def test_independent_meters_and_output_schema(connected, primary, secondary):
    plugin, source, first, second, transports = connected
    plugin._primary_enabled = primary
    plugin._secondary_enabled = secondary
    plugin.connect()
    plugin.configure()
    source.reset_mock()
    plugin.set_state(0.001)
    assert len(transports) == 1 + primary + secondary
    assert first.measure_voltage.call_count == int(primary)
    assert second.measure_voltage.call_count == int(secondary)
    expected = {"source_value": 0.001}
    if primary:
        expected.update(voltage=0.02, resistance=20)
    if secondary:
        expected.update(secondary_voltage=0.03, secondary_resistance=30)
    values = {
        key.split(".")[-1]: eval(expression, {plugin.instance_name: plugin})
        for key, expression in plugin.reported_values().items()
    }
    assert values == expected
    assert plugin.reported_values().keys() == plugin.reported_value_units().keys()
    assert source.mock_calls[:2] == [call.set_source_level(0.001), call.enable_output(True)]
    plugin.disconnect()
    source.enable_output.assert_called_with(False)
    assert all(item.close.call_count == 1 for item in transports)


def test_zero_current_and_failed_read_do_not_publish_stale_results(connected):
    plugin, source, meter, _, _ = connected
    plugin._primary_enabled = True
    plugin.connect()
    plugin.configure()
    plugin.set_state(0)
    assert math.isnan(plugin._readings["resistance"])
    meter.measure_voltage.side_effect = RuntimeError("read failed")
    with pytest.raises(RuntimeError, match="read failed"):
        plugin.set_state(0.001)
    assert plugin._readings == {}
    source.enable_output.assert_called_with(False)


def test_repeated_points_hold_dc_without_running_hardware_sweeps(connected):
    plugin, source, _, _, _ = connected
    plugin.connect()
    plugin.configure()
    source.reset_mock()
    for value in (0.001, 0.002):
        plugin.set_state(value)
    assert source.mock_calls == [
        call.set_source_level(0.001), call.enable_output(True),
        call.set_source_level(0.002), call.enable_output(True),
    ]
    assert len(plugin.reported_values()) == 1


def test_reconnect_and_partial_failure_release_owned_resources(connected):
    plugin, _, primary, _, transports = connected
    plugin.connect()
    plugin.connect()
    transports[0].close.assert_called_once()
    plugin._primary_enabled = True
    primary.confirm_identity.side_effect = RuntimeError("identity")
    with pytest.raises(RuntimeError, match="identity"):
        plugin.connect()
    assert all(item.close.call_count == 1 for item in transports)
    assert plugin._source is None
    assert plugin._meters == {}


def test_cleanup_failure_blocks_reconnect_and_attempts_all_closes(connected):
    plugin, _, _, _, transports = connected
    plugin._secondary_enabled = True
    plugin.connect()
    transports[0].close.side_effect = RuntimeError("close failed")
    with pytest.raises(RuntimeError, match="close failed"):
        plugin.connect()
    assert len(transports) == 2
    assert all(item.close.call_count == 1 for item in transports)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0.106, -0.106])
def test_invalid_current_never_enables_output(connected, value):
    plugin, source, _, _, _ = connected
    plugin.connect()
    with pytest.raises(ValueError):
        plugin.set_state(value)
    source.enable_output.assert_not_called()


def test_json_and_independent_meter_controls(qapp, managed_qt_widget):
    plugin = module.Keithley6221PointScanPlugin()
    plugin._secondary_enabled = True
    plugin._source_delay = "settling_time"
    restored = BasePlugin.from_json(json.loads(json.dumps(plugin.to_json())))
    assert restored.to_json() == plugin.to_json()
    widget = managed_qt_widget(restored._plugin_config_tabs())
    widget.findChild(QGroupBox, "primary").setChecked(True)
    widget.findChild(QGroupBox, "secondary").setChecked(False)
    assert restored._primary_enabled
    assert not restored._secondary_enabled
    assert len(restored.reported_values()) == 3


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
