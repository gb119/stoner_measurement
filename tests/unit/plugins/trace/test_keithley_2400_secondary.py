"""Optional secondary-nanovoltmeter behaviour for the Keithley 2400 trace."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QSpinBox

from stoner_measurement.instruments.keithley.k182 import Keithley182
from stoner_measurement.instruments.keithley.k2182 import Keithley2182A
from stoner_measurement.instruments.keithley.k2400 import BufferReading
from stoner_measurement.instruments.nanovoltmeter import NanovoltmeterTriggerSource
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace._nanovoltmeter_support import NANOVOLTMETER_DRIVERS
from stoner_measurement.plugins.trace.keithley_2400 import Keithley2400SweepPlugin


def _configured_plugin() -> Keithley2400SweepPlugin:
    plugin = Keithley2400SweepPlugin()
    plugin._secondary_enabled = True
    plugin._smu = MagicMock()
    plugin._secondary_nanovoltmeter = MagicMock()
    plugin._secondary_nanovoltmeter.get_capabilities.return_value = Keithley2182A.CAPABILITIES
    plugin.scan_generator.generate = MagicMock(return_value=[0.001, 0.002])
    return plugin


def test_disabled_secondary_json_only_exports_master_switch():
    plugin = Keithley2400SweepPlugin()
    plugin._secondary_resource = "GPIB0::99::INSTR"

    assert plugin.to_json()["secondary_nanovoltmeter"] == {"enabled": False}


def test_enabled_secondary_settings_round_trip():
    plugin = Keithley2400SweepPlugin()
    plugin._secondary_enabled = True
    plugin._secondary_driver = "keithley_182"
    plugin._secondary_resource = "GPIB0::18::INSTR"
    plugin._secondary_prefix = "transverse"
    plugin._secondary_nplc = 0.15
    plugin._secondary_digits = 5
    plugin._secondary_filter_type = "SLOW"

    restored = BasePlugin.from_json(plugin.to_json())

    assert restored._secondary_enabled is True
    assert restored._secondary_driver == "keithley_182"
    assert restored._secondary_resource == "GPIB0::18::INSTR"
    assert restored._secondary_prefix == "transverse"
    assert restored._secondary_nplc == pytest.approx(0.15)
    assert restored._secondary_digits == 5
    assert restored._secondary_filter_type == "SLOW"


def test_secondary_page_uses_driver_capabilities(managed_qt_widget):
    plugin = Keithley2400SweepPlugin()
    widget = managed_qt_widget(plugin._plugin_config_tabs())
    enabled = widget.findChild(QCheckBox, "secondary_enabled")
    controls = widget.findChild(QGroupBox, "secondary_controls")
    driver = widget.findChild(QComboBox, "secondary_driver")

    assert controls.isEnabled() is False
    enabled.setChecked(True)
    driver.setCurrentIndex(driver.findData("keithley_182"))

    nplc = widget.findChild(QComboBox, "secondary_nplc")
    digits = widget.findChild(QComboBox, "secondary_digits")
    filter_type = widget.findChild(QComboBox, "secondary_filter_type")
    assert controls.isEnabled() is True
    assert widget.findChild(QComboBox, "trigger_routing").isEnabled() is False
    assert widget.findChild(QSpinBox, "trigger_in_line").isEnabled() is True
    assert widget.findChild(QSpinBox, "trigger_out_line").isEnabled() is True
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


def test_secondary_driver_and_resource_use_separate_form_rows(managed_qt_widget):
    plugin = Keithley2400SweepPlugin()
    settings = managed_qt_widget(plugin._plugin_config_tabs())
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


def test_connect_opens_and_identifies_secondary_meter():
    plugin = Keithley2400SweepPlugin()
    plugin._resource = "GPIB0::24::INSTR"
    plugin._secondary_enabled = True
    plugin._secondary_resource = "GPIB0::8::INSTR"
    fake_smu = MagicMock()
    fake_meter = MagicMock()
    meter_factory = MagicMock(return_value=fake_meter)
    transports = (MagicMock(), MagicMock())

    with (
        patch(
            "stoner_measurement.plugins.trace.keithley_2400.GpibTransport.from_resource_string",
            side_effect=transports,
        ) as make_transport,
        patch("stoner_measurement.plugins.trace.keithley_2400.Keithley2400", return_value=fake_smu),
        patch.dict(NANOVOLTMETER_DRIVERS, {"keithley_2182a": meter_factory}),
    ):
        plugin.connect()

    assert make_transport.call_count == 2
    meter_factory.assert_called_once_with(transports[1])
    fake_meter.connect.assert_called_once_with()
    fake_meter.confirm_identity.assert_called_once_with()


def test_configure_forces_trigger_link_source_handshake():
    plugin = _configured_plugin()

    plugin.configure()

    trigger_config = plugin._smu.configure_trigger_model.call_args.args[0]
    assert trigger_config.trigger_source.value == "TLIN"
    assert trigger_config.trigger_count == 2
    assert trigger_config.arm_count == 1
    plugin._smu.configure_trigger_link_source_handshake.assert_called_once_with(
        input_line=1,
        output_line=2,
    )


def test_configure_applies_secondary_external_trigger_settings():
    plugin = _configured_plugin()
    plugin._secondary_voltage_range = 0.1
    plugin._secondary_filter_type = "REPEAT"
    plugin._secondary_filter_count = 4

    plugin.configure()

    meter = plugin._secondary_nanovoltmeter
    meter.reset.assert_called_once_with()
    meter.set_range.assert_called_once_with(0.1)
    meter.set_filter_count.assert_called_once_with(4)
    meter.set_trigger_source.assert_called_once_with(NanovoltmeterTriggerSource.EXT)
    meter.set_buffer_size.assert_called_once_with(2)
    meter.set_trigger_count.assert_called_once_with(2)


def test_configure_respects_legacy_meter_capabilities():
    plugin = _configured_plugin()
    plugin._secondary_driver = "keithley_182"
    plugin._secondary_filter_type = "MEDIUM"
    plugin._secondary_nanovoltmeter.get_capabilities.return_value = Keithley182.CAPABILITIES

    plugin.configure()

    meter = plugin._secondary_nanovoltmeter
    meter.reset.assert_not_called()
    meter.set_line_sync_enabled.assert_not_called()
    meter.set_autozero_enabled.assert_not_called()
    meter.set_filter_count.assert_not_called()
    meter.set_filter_type.assert_called_once_with("MEDIUM")


def test_acquisition_arms_secondary_and_reads_its_buffer():
    plugin = _configured_plugin()
    plugin._sweep_values = (0.001, 0.002)
    plugin._smu.wait_for_buffer_full_srq.return_value = True
    plugin._smu.read_buffer_records.return_value = (
        BufferReading(voltage=0.1, current=0.001, resistance=100.0, time=1.0, status=0),
        BufferReading(voltage=0.4, current=0.002, resistance=200.0, time=2.0, status=0),
    )
    plugin._secondary_nanovoltmeter.read_buffer.return_value = (0.2, 0.6)

    with patch("stoner_measurement.plugins.trace.keithley_2400.time.sleep"):
        plugin._acquire_buffer_records({})

    plugin._secondary_nanovoltmeter.set_buffer_feed_continuous_next.assert_called_once_with()
    plugin._secondary_nanovoltmeter.initiate.assert_called_once_with()
    plugin._secondary_nanovoltmeter.read_buffer.assert_called_once_with(count=2)
    assert plugin._secondary_voltages == pytest.approx((0.2, 0.6))


def test_measure_adds_prefixed_secondary_voltage_resistance_and_power_columns():
    plugin = Keithley2400SweepPlugin()
    plugin._secondary_enabled = True
    plugin._secondary_prefix = "hall"
    plugin._sweep_values = (0.001, 0.002)
    plugin._secondary_voltages = (0.2, 0.6)
    records = (
        BufferReading(voltage=0.1, current=0.001, resistance=100.0, time=1.0, status=0),
        BufferReading(voltage=0.4, current=0.002, resistance=200.0, time=2.0, status=0),
    )
    plugin._acquire_buffer_records = MagicMock(return_value=records)

    trace = plugin.measure({})["IV"]

    np.testing.assert_allclose(trace.df["hall V"], [0.2, 0.6])
    np.testing.assert_allclose(trace.df["hall R"], [200.0, 300.0])
    np.testing.assert_allclose(trace.df["hall P"], [0.0002, 0.0012])


def test_disconnect_closes_secondary_meter():
    plugin = _configured_plugin()
    meter = plugin._secondary_nanovoltmeter

    plugin.disconnect()

    meter.abort.assert_called_once_with()
    meter.disconnect.assert_called_once_with()
    assert plugin._secondary_nanovoltmeter is None
