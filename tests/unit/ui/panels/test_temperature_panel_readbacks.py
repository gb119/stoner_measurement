"""Connection notifications must not repeatedly read expensive hardware tables."""

from collections import Counter
from dataclasses import replace

import pytest

from stoner_measurement.instruments.simulated import SimulatedTemperatureController
from stoner_measurement.instruments.temperature_controller import InputChannelSettings, ZoneEntry
from stoner_measurement.temperature_control import engine as engine_module
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.temperature_control.references import LoopRef


class CountingController(SimulatedTemperatureController):
    """Expose table capabilities and count meaningful hardware readbacks."""

    def __init__(self):
        super().__init__()
        self.reads = Counter()

    def get_capabilities(self):
        return replace(super().get_capabilities(), num_inputs=2, input_channels=("A", "B"),
                       has_zone=True, has_input_settings=True,
                       has_cryogen_control=False, has_gas_auto_mode=False)

    def get_setpoint(self, loop):
        self.reads["setpoint"] += 1
        return super().get_setpoint(loop)

    def get_num_zones(self, loop):
        return 2

    def get_zone(self, loop, index):
        self.reads["zone"] += 1
        return ZoneEntry(300, 1, 2, 3, 0, 0, 0)

    def get_calibration_curve_names(self):
        self.reads["curves"] += 1
        return {5: "Standard Diode"}

    def get_input_channel_settings(self, channel):
        self.reads["input"] += 1
        return InputChannelSettings(curve_number=5)


@pytest.fixture
def rig(monkeypatch, qapp):
    monkeypatch.setattr(engine_module, "load_temperature_controller_config", lambda: {})
    service = TemperatureControllerEngine()
    service.set_polling_rate(0)
    monkeypatch.setattr(TemperatureControllerEngine, "_singleton", service)
    yield service
    service.shutdown()


def test_secondary_connect_preserves_primary_controls_and_reads(rig, managed_temperature_panel):
    panel = managed_temperature_panel()
    primary = CountingController()
    rig.connect_instrument(primary)
    controls = panel._loop_groups[1]
    controls._sp_spin.setValue(123)
    before = primary.reads.copy()
    assert before["zone"] == before["curves"] == before["input"] == 0
    rig.connect_instrument(CountingController(), controller_id="secondary")
    panel._sync_existing_connection_state()
    panel._sync_existing_connection_state()
    assert primary.reads == before
    assert panel._loop_groups[1] is controls
    assert controls._sp_spin.value() == 123
    assert LoopRef("secondary", 1) in panel._loop_groups


def test_tables_load_on_first_use_and_preserve_edits(rig, managed_temperature_panel):
    panel = managed_temperature_panel()
    primary = CountingController()
    rig.connect_instrument(primary)
    panel._tabs.setCurrentIndex(panel._zone_tab_index)
    assert primary.reads["zone"] == 2
    panel._zone_table_widget._table.cellWidget(0, 0).setValue(250)
    panel._tabs.setCurrentIndex(0)
    panel._tabs.setCurrentIndex(panel._zone_tab_index)
    assert primary.reads["zone"] == 2
    secondary = CountingController()
    rig.connect_instrument(secondary, controller_id="secondary")
    assert primary.reads["zone"] == 2
    assert secondary.reads["zone"] == 0
    assert panel._zone_table_widget._table.cellWidget(0, 0).value() == 250
    panel._tabs.setCurrentIndex(panel._input_settings_tab_index)
    assert secondary.reads["curves"] == secondary.reads["input"] == 0
    panel._input_tabs.setCurrentIndex(1)
    assert primary.reads["curves"] == secondary.reads["curves"] == 1
    assert primary.reads["input"] == secondary.reads["input"] == 2
    combo = panel._input_settings_widget._editors["A"]["curve_number"]
    assert combo.itemText(combo.findData(5)) == "Standard Diode (5)"
    combo.setCurrentIndex(combo.findData(2))
    panel._tabs.setCurrentIndex(0)
    panel._tabs.setCurrentIndex(panel._input_settings_tab_index)
    panel._input_tabs.setCurrentIndex(0)
    assert primary.reads["curves"] == 1
    assert primary.reads["input"] == 2
    assert combo.currentData() == 2


def test_reconnect_invalidates_only_replaced_sessions_tables(rig, managed_temperature_panel):
    panel = managed_temperature_panel()
    primary, secondary = CountingController(), CountingController()
    rig.connect_instrument(primary)
    rig.connect_instrument(secondary, controller_id="secondary")
    panel._tabs.setCurrentIndex(panel._input_settings_tab_index)
    panel._input_tabs.setCurrentIndex(1)
    before = primary.reads.copy()
    primary_editor = panel._input_settings_widget._editors["A"]
    replacement = CountingController()
    rig.connect_instrument(replacement, controller_id="secondary")
    assert primary.reads == before
    assert panel._input_settings_widget._editors["A"] is primary_editor
    assert replacement.reads["curves"] == 1
    assert replacement.reads["input"] == 2


def test_failed_zone_load_can_be_retried(rig, managed_temperature_panel, monkeypatch):
    panel = managed_temperature_panel()
    rig.connect_instrument(CountingController())
    original = rig.get_zone_table
    monkeypatch.setattr(rig, "get_zone_table", lambda loop: None)
    panel._tabs.setCurrentIndex(panel._zone_tab_index)
    assert panel._zone_loaded is None
    monkeypatch.setattr(rig, "get_zone_table", original)
    panel._tabs.setCurrentIndex(0)
    panel._tabs.setCurrentIndex(panel._zone_tab_index)
    assert panel._zone_loaded == panel._zone_target
    assert panel._zone_table_widget._table.rowCount() == 2


def test_unread_loading_and_failed_settings_are_disabled(rig, managed_temperature_panel, monkeypatch):
    panel = managed_temperature_panel()
    driver = CountingController()
    rig.connect_instrument(driver)
    loop = panel._loop_groups[1]
    assert loop._settings_body.isEnabled()
    assert loop._apply_button.isEnabled()
    assert not panel._zone_table_widget._table.isEnabled()
    assert not panel._input_settings_widget._table.isEnabled()

    def read_zone(loop, index):
        assert not panel._zone_table_widget._table.isEnabled()
        assert not panel._zone_table_widget._apply_button.isEnabled()
        return ZoneEntry(300, 1, 2, 3, 0, 0, 0)

    monkeypatch.setattr(driver, "get_zone", read_zone)
    panel._tabs.setCurrentIndex(panel._zone_tab_index)
    assert panel._zone_table_widget._table.isEnabled()

    original = rig.get_loop_settings

    def unavailable(loop_number):
        assert not loop._settings_body.isEnabled()
        assert not loop._apply_button.isEnabled()
        return None

    monkeypatch.setattr(rig, "get_loop_settings", unavailable)
    assert not loop.read_from_hardware()
    assert not loop._settings_body.isEnabled()
    monkeypatch.setattr(rig, "get_loop_settings", original)
    assert loop.read_from_hardware()
    assert loop._settings_body.isEnabled()

    def read_input(channel):
        assert not panel._input_settings_widget._table.isEnabled()
        assert not panel._input_settings_widget._write_button.isEnabled()
        return InputChannelSettings(curve_number=5)

    monkeypatch.setattr(driver, "get_input_channel_settings", read_input)
    panel._tabs.setCurrentIndex(panel._input_settings_tab_index)
    assert panel._input_settings_widget._table.isEnabled()
    monkeypatch.setattr(rig, "get_input_channel_settings", lambda channel: None)
    assert not panel._input_settings_widget.read_all(show_warning=False)
    assert not panel._input_settings_widget._table.isEnabled()
    assert not panel._input_settings_widget._write_button.isEnabled()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
