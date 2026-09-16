"""Independent point-voltmeter controls, persistence and driver capabilities."""

import json
from unittest.mock import MagicMock

import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QGroupBox, QSpinBox

from stoner_measurement.instruments.keithley.k182 import Keithley182
from stoner_measurement.instruments.keithley.k2182 import Keithley2182A
from stoner_measurement.plugins._point_voltmeter import METER_DEFAULTS, configure_meter
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command.keithley_set import Keithley6221SetCommand
from stoner_measurement.plugins.state_scan.k6221_2182a import Keithley6221PointScanPlugin
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.widgets import SISpinBox


@pytest.mark.parametrize("is_command", [False, True])
def test_separate_tabs_and_independent_controls_roundtrip(is_command, managed_qt_widget):
    owner = Keithley6221SetCommand() if is_command else Keithley6221PointScanPlugin()
    point = owner._point_plugin if is_command else owner
    root = managed_qt_widget(owner.config_widget() if is_command else point._plugin_config_tabs())
    tabs = root.findChild(FontAwareTabWidget) if is_command else root
    assert [tabs.tabText(index) for index in range(tabs.count())] == ["General", "Primary", "Secondary"]
    for role, index in (("primary", 1), ("secondary", 2)):
        page = tabs.widget(index)
        page.findChild(QGroupBox, role).setChecked(True)
        for key, value in (("nplc", 5.0), ("voltage_range", 0.1), ("digits", 6), ("filter_type", "REPEAT")):
            combo = page.findChild(QComboBox, f"{role}_{key}")
            combo.setCurrentIndex(combo.findData(value))
        page.findChild(QSpinBox, f"{role}_filter_count").setValue(12 + index)
        page.findChild(QCheckBox, f"{role}_autozero").setChecked(False)
        page.findChild(QCheckBox, f"{role}_line_sync").setChecked(True)
        page.findChild(QCheckBox, f"{role}_analog_filter").setChecked(True)
        page.findChild(QCheckBox, f"{role}_relative_enabled").setChecked(True)
        page.findChild(SISpinBox, f"{role}_relative_value").setValue("offset_voltage")
        page.findChild(SISpinBox, f"{role}_trigger_delay").setValue(0.02 * index)
    restored = BasePlugin.from_json(json.loads(json.dumps(owner.to_json())))
    restored_point = restored._point_plugin if is_command else restored
    for role in ("primary", "secondary"):
        for key in METER_DEFAULTS:
            assert getattr(restored_point, f"_{role}_{key}") == getattr(point, f"_{role}_{key}")
    assert point._primary_filter_count == 13
    assert point._secondary_filter_count == 14


def test_driver_switch_refreshes_choices_and_disables_unsupported_controls(managed_qt_widget):
    point = Keithley6221PointScanPlugin()
    point._secondary_enabled = True
    root = managed_qt_widget(point._plugin_config_tabs())
    driver = root.findChild(QComboBox, "secondary_driver")
    driver.setCurrentIndex(driver.findData("keithley_182"))
    nplc = root.findChild(QComboBox, "secondary_nplc")
    assert [nplc.itemData(i) for i in range(nplc.count())] == list(Keithley182.CAPABILITIES.nplc_values)
    assert point._secondary_digits == Keithley182.CAPABILITIES.default_digits
    for key in ("autozero", "line_sync", "filter_count"):
        assert not root.findChild(QCheckBox if key != "filter_count" else QSpinBox, "secondary_" + key).isEnabled()
    relative = root.findChild(SISpinBox, "secondary_relative_value")
    assert not relative.isEnabled()
    root.findChild(QCheckBox, "secondary_relative_enabled").setChecked(True)
    assert relative.isEnabled()
    driver.setCurrentIndex(driver.findData("keithley_2182a"))
    assert root.findChild(QCheckBox, "secondary_autozero").isEnabled()


@pytest.mark.parametrize("role", ["primary", "secondary"])
def test_measurement_configuration_applies_settings_and_runtime_expressions(engine, role):
    point = Keithley6221PointScanPlugin()
    point.sequence_engine = engine
    point.engine_namespace["offset"] = 0.002
    settings = dict(voltage_range=0.1, digits=6, nplc=5.0, trigger_delay="offset * 10",
                    autozero=False, line_sync=True, filter_type="REPEAT", filter_count=17,
                    analog_filter=True, relative_enabled=True, relative_value="offset")
    for key, value in settings.items():
        setattr(point, f"_{role}_{key}", value)
    meter = MagicMock()
    meter.get_capabilities.return_value = Keithley2182A.CAPABILITIES
    configure_meter(point, role, meter)
    for method, value in (
        ("set_range", 0.1), ("set_autorange", False), ("set_nplc", 5.0), ("set_digits", 6),
        ("set_trigger_delay", 0.02), ("set_autozero_enabled", False), ("set_line_sync_enabled", True),
        ("set_filter_enabled", True), ("set_filter_type", "REPEAT"), ("set_filter_count", 17),
        ("set_analog_filter_enabled", True), ("set_relative_enabled", True), ("set_relative_value", 0.002),
    ):
        getattr(meter, method).assert_called_once_with(value)
    meter.set_buffer_size.assert_not_called()


def test_legacy_182_settings_use_driver_defaults_and_avoid_unsupported_commands():
    point = BasePlugin.from_json({
        "class": "stoner_measurement.plugins.state_scan.k6221_2182a:Keithley6221PointScanPlugin",
        "secondary_enabled": True, "secondary_driver": "keithley_182", "secondary_nplc": 1.0,
    })
    assert point._secondary_digits == Keithley182.CAPABILITIES.default_digits
    meter = MagicMock()
    meter.get_capabilities.return_value = Keithley182.CAPABILITIES
    configure_meter(point, "secondary", meter)
    for method in ("reset", "set_autozero_enabled", "set_line_sync_enabled", "set_filter_count", "set_range"):
        getattr(meter, method).assert_not_called()
    meter.set_autorange.assert_called_once_with(True)
    meter.set_filter_enabled.assert_called_once_with(False)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
