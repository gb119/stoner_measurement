"""Tests for the optional secondary nanovoltmeter in the 6221 trace plugin."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit

from stoner_measurement.instruments.keithley.k182 import Keithley182
from stoner_measurement.instruments.keithley.k2182 import Keithley2182A
from stoner_measurement.instruments.nanovoltmeter import NanovoltmeterTriggerSource
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace import (
    ConnectionMode,
    Keithley6221_2182APlugin,
    SecondaryTriggerMode,
)
from stoner_measurement.plugins.trace.k6221_2182a import _NANOVOLTMETER_DRIVERS


def _enabled_plugin() -> Keithley6221_2182APlugin:
    plugin = Keithley6221_2182APlugin()
    plugin._secondary_enabled = True
    plugin._secondary_nanovoltmeter = MagicMock()
    plugin._secondary_nanovoltmeter.get_capabilities.return_value = Keithley2182A.CAPABILITIES
    return plugin


def test_disabled_secondary_json_only_exports_master_switch(qapp):
    plugin = Keithley6221_2182APlugin()
    plugin._secondary_resource = "GPIB0::99::INSTR"
    plugin._secondary_prefix = "hidden"

    assert plugin.to_json()["secondary_nanovoltmeter"] == {"enabled": False}


def test_enabled_secondary_settings_round_trip(qapp):
    plugin = Keithley6221_2182APlugin()
    plugin._secondary_enabled = True
    plugin._secondary_resource = "GPIB0::18::INSTR"
    plugin._secondary_prefix = "hall"
    plugin._secondary_trigger_mode = SecondaryTriggerMode.DAISY_CHAIN
    plugin._secondary_nplc = 10.0
    plugin._secondary_voltage_range = 0.1
    plugin._secondary_filter_type = "WINDOW"
    plugin._secondary_filter_count = 23
    plugin._secondary_trigger_delay = 0.125
    plugin._secondary_line_sync = True
    plugin._secondary_autozero = False
    plugin._secondary_analog_filter = True
    plugin._secondary_relative_enabled = True
    plugin._secondary_relative_value = 2e-6
    plugin._secondary_digits = 7

    restored = BasePlugin.from_json(plugin.to_json())

    assert restored._secondary_enabled is True
    assert restored._secondary_driver == "keithley_2182a"
    assert restored._secondary_resource == "GPIB0::18::INSTR"
    assert restored._secondary_prefix == "hall"
    assert restored._secondary_trigger_mode is SecondaryTriggerMode.DAISY_CHAIN
    assert restored._secondary_nplc == pytest.approx(10.0)
    assert restored._secondary_voltage_range == pytest.approx(0.1)
    assert restored._secondary_filter_type == "WINDOW"
    assert restored._secondary_filter_count == 23
    assert restored._secondary_trigger_delay == pytest.approx(0.125)
    assert restored._secondary_line_sync is True
    assert restored._secondary_autozero is False
    assert restored._secondary_analog_filter is True
    assert restored._secondary_relative_enabled is True
    assert restored._secondary_relative_value == pytest.approx(2e-6)
    assert restored._secondary_digits == 7


def test_secondary_page_master_switch_enables_controls(qapp):
    plugin = Keithley6221_2182APlugin()
    widget = plugin._plugin_config_tabs()
    enabled = widget.findChild(QCheckBox, "secondary_enabled")
    controls = widget.findChild(QGroupBox, "secondary_controls")

    assert controls.isEnabled() is False
    assert widget.findChild(QComboBox, "secondary_driver").count() == 2

    enabled.setChecked(True)
    widget.findChild(QLineEdit, "secondary_prefix").setText("transverse")

    assert controls.isEnabled() is True
    assert plugin._secondary_enabled is True
    assert plugin._secondary_prefix == "transverse"

    wiring = widget.findChild(QComboBox, "secondary_trigger_mode")
    wiring.setCurrentIndex(wiring.findData(SecondaryTriggerMode.DAISY_CHAIN))
    assert plugin._secondary_trigger_mode is SecondaryTriggerMode.DAISY_CHAIN


def test_secondary_driver_and_resource_use_separate_form_rows(qapp):
    plugin = Keithley6221_2182APlugin()
    settings = plugin._plugin_config_tabs()
    controls = settings.findChild(QGroupBox, "secondary_controls")
    form = controls.layout()
    assert isinstance(form, QFormLayout)

    rows_by_label = {}
    for row in range(form.rowCount()):
        label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
        field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
        if label_item is not None and field_item is not None:
            rows_by_label[label_item.widget().text()] = field_item.widget()

    assert rows_by_label["Driver:"] is settings.findChild(QComboBox, "secondary_driver")
    assert rows_by_label["GPIB resource:"].objectName() == "secondary_resource"


def test_keithley_182_selection_exposes_only_supported_settings(qapp):
    plugin = Keithley6221_2182APlugin()
    widget = plugin._plugin_config_tabs()
    driver = widget.findChild(QComboBox, "secondary_driver")

    driver.setCurrentIndex(driver.findData("keithley_182"))

    nplc = widget.findChild(QComboBox, "secondary_nplc")
    digits = widget.findChild(QComboBox, "secondary_digits")
    filter_type = widget.findChild(QComboBox, "secondary_filter_type")
    assert [nplc.itemData(index) for index in range(nplc.count())] == [0.15, 1.0, 5.0]
    assert [digits.itemData(index) for index in range(digits.count())] == [3, 4, 5, 6]
    assert [filter_type.itemData(index) for index in range(filter_type.count())] == [
        "OFF",
        "FAST",
        "MEDIUM",
        "SLOW",
    ]
    assert widget.findChild(QCheckBox, "secondary_autozero").isEnabled() is False
    assert widget.findChild(QCheckBox, "secondary_line_sync").isEnabled() is False
    assert widget.findChild(QComboBox, "secondary_driver").currentText() == "Keithley 182"
    assert _NANOVOLTMETER_DRIVERS["keithley_182"] is Keithley182


def test_keithley_182_settings_round_trip(qapp):
    plugin = Keithley6221_2182APlugin()
    plugin._secondary_enabled = True
    plugin._secondary_driver = "keithley_182"
    plugin._secondary_nplc = 0.15
    plugin._secondary_digits = 5
    plugin._secondary_filter_type = "SLOW"

    restored = BasePlugin.from_json(plugin.to_json())

    assert restored._secondary_driver == "keithley_182"
    assert restored._secondary_nplc == pytest.approx(0.15)
    assert restored._secondary_digits == 5
    assert restored._secondary_filter_type == "SLOW"


def test_parallel_page_warns_when_secondary_may_overrun(qapp):
    plugin = Keithley6221_2182APlugin()
    widget = plugin._plugin_config_tabs()
    widget.findChild(QCheckBox, "secondary_enabled").setChecked(True)
    secondary_nplc = widget.findChild(QComboBox, "secondary_nplc")
    secondary_nplc.setCurrentIndex(secondary_nplc.findData(10.0))

    warning = widget.findChild(QLabel, "secondary_timing_warning")

    assert "overrun" in warning.text().lower()
    assert "0.2 s" in warning.text()


def test_configure_applies_secondary_meter_settings(qapp):
    plugin = _enabled_plugin()
    plugin._k6221 = MagicMock()
    plugin._k2182a = MagicMock()
    plugin.scan_generator = MagicMock()
    plugin.scan_generator.generate.return_value = np.array([1e-3, 2e-3])
    plugin._secondary_nplc = 10.0
    plugin._secondary_voltage_range = 0.1
    plugin._secondary_filter_type = "REPEAT"
    plugin._secondary_filter_count = 4
    plugin._secondary_trigger_delay = 0.2

    plugin.configure()

    meter = plugin._secondary_nanovoltmeter
    meter.reset.assert_called_once_with()
    meter.set_nplc.assert_called_once_with(10.0)
    meter.set_autorange.assert_called_once_with(False)
    meter.set_range.assert_called_once_with(0.1)
    meter.set_filter_enabled.assert_called_once_with(True)
    meter.set_filter_count.assert_called_once_with(4)
    meter.set_filter_type.assert_called_once_with("REPEAT")
    meter.set_buffer_size.assert_called_once_with(2)
    meter.set_trigger_delay.assert_called_once_with(0.2)
    meter.set_trigger_count.assert_called_once_with(2)


def test_configure_adapts_to_keithley_182_capabilities(qapp):
    plugin = _enabled_plugin()
    plugin._secondary_driver = "keithley_182"
    plugin._secondary_digits = 6
    plugin._secondary_nplc = 1.0
    plugin._secondary_filter_type = "MEDIUM"
    plugin._secondary_nanovoltmeter.get_capabilities.return_value = Keithley182.CAPABILITIES
    plugin._k6221 = MagicMock()
    plugin._k2182a = MagicMock()
    plugin.scan_generator = MagicMock()
    plugin.scan_generator.generate.return_value = np.array([1e-3, 2e-3])

    plugin.configure()

    meter = plugin._secondary_nanovoltmeter
    meter.reset.assert_not_called()
    meter.set_line_sync_enabled.assert_not_called()
    meter.set_autozero_enabled.assert_not_called()
    meter.set_filter_count.assert_not_called()
    meter.set_filter_type.assert_called_once_with("MEDIUM")
    meter.set_buffer_size.assert_called_once_with(2)
    meter.set_trigger_source.assert_called_once_with(NanovoltmeterTriggerSource.EXT)


def test_configure_logs_parallel_overrun_warning(qapp, caplog):
    plugin = _enabled_plugin()
    plugin._k6221 = MagicMock()
    plugin._k2182a = MagicMock()
    plugin.scan_generator = MagicMock()
    plugin.scan_generator.generate.return_value = np.array([1e-3, 2e-3])
    plugin._secondary_nplc = 10.0

    with caplog.at_level(logging.WARNING):
        plugin.configure()

    assert "measurement overrun" in caplog.text


def test_measure_adds_prefixed_secondary_derived_columns(qapp):
    plugin = _enabled_plugin()
    plugin._secondary_prefix = "hall"

    def acquire(_parameters):
        plugin._secondary_voltages = (0.3, 0.8, 1.2)
        return [(0.0, 0.1), (2.0, 0.4), (-3.0, -0.6)]

    plugin._acquire_pairs = acquire
    trace = plugin.measure({})["IV"]

    assert list(trace.df.columns) == ["V", "R", "P", "hall V", "hall R", "hall P"]
    assert np.isnan(trace.df.loc[0.0, "hall R"])
    assert trace.df.loc[2.0, "hall R"] == pytest.approx(0.4)
    assert trace.df.loc[-3.0, "hall P"] == pytest.approx(-3.6)


def test_acquisition_arms_and_reads_secondary_meter(qapp):
    plugin = _enabled_plugin()
    plugin._k6221 = MagicMock()
    plugin._k6221.wait_for_sweep_complete_srq.return_value = True
    plugin._k2182a = MagicMock()
    plugin._k2182a.read_buffer.return_value = (0.1, 0.2)
    plugin._secondary_nanovoltmeter.read_buffer.return_value = (0.3, 0.4)
    plugin._sweep_values = np.array([1.0, 2.0])

    with patch("stoner_measurement.plugins.trace.k6221_2182a.time.sleep"):
        pairs = plugin._acquire_pairs({})

    assert pairs == [(1.0, 0.1), (2.0, 0.2)]
    plugin._secondary_nanovoltmeter.initiate.assert_called_once_with()
    plugin._secondary_nanovoltmeter.read_buffer.assert_called_once_with(count=2)
    assert plugin._secondary_voltages == (0.3, 0.4)


@pytest.mark.parametrize(
    ("mode", "expected_timeout"),
    [
        (SecondaryTriggerMode.PARALLEL, 11.0),
        (SecondaryTriggerMode.DAISY_CHAIN, 22.0),
    ],
)
def test_trigger_wiring_changes_sweep_timing_estimate(qapp, mode, expected_timeout):
    plugin = _enabled_plugin()
    plugin._secondary_trigger_mode = mode
    plugin._k6221 = MagicMock()
    plugin._k6221.wait_for_sweep_complete_srq.return_value = True
    plugin._k2182a = MagicMock()
    plugin._source_delay = 0.0
    plugin._k2182a.read_buffer.return_value = tuple(range(500))
    plugin._secondary_nanovoltmeter.read_buffer.return_value = tuple(range(500))
    plugin._sweep_values = np.arange(500)

    with patch("stoner_measurement.plugins.trace.k6221_2182a.time.sleep"):
        plugin._acquire_pairs({})

    plugin._k6221.wait_for_sweep_complete_srq.assert_called_once_with(
        pytest.approx(expected_timeout)
    )


def test_connect_and_disconnect_include_secondary_meter(qapp):
    plugin = Keithley6221_2182APlugin()
    plugin._secondary_enabled = True
    plugin._connection_mode = ConnectionMode.DIRECT_GPIB
    transports = [MagicMock(), MagicMock(), MagicMock()]
    source = MagicMock()
    primary = MagicMock()
    secondary = MagicMock()

    with (
        patch(
            "stoner_measurement.plugins.trace.k6221_2182a.GpibTransport.from_resource_string",
            side_effect=transports,
        ),
        patch(
            "stoner_measurement.plugins.trace.k6221_2182a.Keithley6221",
            return_value=source,
        ),
        patch(
            "stoner_measurement.plugins.trace.k6221_2182a.Keithley2182A",
            side_effect=[primary, secondary],
        ),
        patch.dict(
            "stoner_measurement.plugins.trace.k6221_2182a._NANOVOLTMETER_DRIVERS",
            {"keithley_2182a": MagicMock(side_effect=[secondary])},
        ),
    ):
        plugin.connect()

    assert plugin._secondary_nanovoltmeter is secondary
    secondary.confirm_identity.assert_called_once_with()

    plugin.disconnect()

    secondary.disconnect.assert_called_once_with()
    assert plugin._secondary_nanovoltmeter is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
