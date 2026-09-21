"""Combined temperature panel and catalogue-backed selector contracts."""

import pytest
from qtpy.QtWidgets import QHBoxLayout

from stoner_measurement.instruments.simulated import SimulatedTemperatureController
from stoner_measurement.plugins.command.set_temperature import SetTemperatureCommand
from stoner_measurement.temperature_control import engine as engine_module
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.temperature_control.references import LoopRef
from stoner_measurement.ui.temperature_selectors import TemperatureLoopSelector


@pytest.fixture
def rig(monkeypatch, qapp):
    monkeypatch.setattr(engine_module, "load_temperature_controller_config", lambda: {})
    service = TemperatureControllerEngine()
    service.set_polling_rate(0)
    monkeypatch.setattr(TemperatureControllerEngine, "_singleton", service)
    yield service
    service.shutdown()


def test_combined_controls_restrict_inputs_and_keep_primary_layout(
    rig, managed_temperature_panel, monkeypatch
):
    rig.connect_instrument(SimulatedTemperatureController())
    panel = managed_temperature_panel()
    panel._sync_existing_connection_state()
    assert isinstance(panel._loop_layout, QHBoxLayout)
    assert panel._loop_layout.count() == 2
    assert not panel._control_tabs.isTabVisible(1)
    assert panel._loop_layout.itemAt(0).widget() is panel._loop_groups[1]
    secondary = SimulatedTemperatureController()
    monkeypatch.setattr(secondary, "get_loop_input_channels", lambda loop: ("B",))
    rig.connect_instrument(secondary, controller_id="secondary")
    assert panel._loop_layout.count() == 2
    assert panel._secondary_loop_layout.count() == 2
    assert panel._control_tabs.isTabVisible(1)
    group = panel._loop_groups[LoopRef("secondary", 1)]
    assert group._channel_combo.count() == 1
    assert group._channel_combo.itemData(0) == "B"
    rig.disconnect_instrument()
    assert set(panel._loop_groups) == {LoopRef("secondary", 1), LoopRef("secondary", 2)}
    assert panel._control_tabs.currentIndex() == 1
    rig.set_controller_enabled("secondary", False)
    assert not panel._control_tabs.isTabVisible(1)


def test_shared_stability_selectors_preserve_missing_selection(rig, managed_temperature_panel):
    rig.connect_instrument(SimulatedTemperatureController())
    rig.connect_instrument(SimulatedTemperatureController(), controller_id="secondary")
    panel = managed_temperature_panel()
    combo = panel._stab_table.cellWidget(0, 1)
    assert combo.findData("A") >= 0
    index = combo.findData("secondary:B")
    assert combo.itemText(index) == "B.2"
    combo.setCurrentIndex(index)
    panel._on_apply_stability()
    assert rig.stability_config.bands[0].tolerance_channel == "secondary:B"
    assert rig.controller("secondary").stability_config is rig.stability_config
    rig.disconnect_instrument()
    rig.controller("secondary").disconnect_instrument()
    combo = panel._stab_table.cellWidget(0, 1)
    assert combo.currentData() == "secondary:B"
    assert "unavailable" in combo.currentText()


def test_input_settings_share_page_with_separate_owner_tables(rig, managed_temperature_panel):
    panel = managed_temperature_panel()
    tab = panel._tabs.widget(panel._input_settings_tab_index)
    assert tab.layout().indexOf(panel._input_settings_widget) >= 0
    assert tab.layout().indexOf(panel._secondary_input_settings) >= 0
    assert panel._secondary_input_settings._engine is rig.controller("secondary")


def test_chart_has_distinct_temperature_setpoint_and_heater_traces(rig, managed_temperature_panel):
    panel = managed_temperature_panel()
    for slot in ("primary", "secondary"):
        rig.connect_instrument(SimulatedTemperatureController(), controller_id=slot)
    rig.set_setpoint(LoopRef("secondary", 1), 200)
    rig.read_controller_state()
    assert panel._chart_values["SP_1"][-1] == 300
    assert panel._chart_values["secondary:SP_1"][-1] == 200
    assert "T_A" in panel._chart_values
    assert "secondary:T_A" in panel._chart_values
    assert "secondary:H_1" in panel._chart_values
    assert panel._legend_items["secondary:T_A"].text(0) == "T_A.2"
    assert panel._legend_items["secondary:SP_1"].text(0) == "SP_1.2"
    assert {name for name in panel._legend_items if "dT/dt" in name} == {"dT/dt"}


def test_selector_retains_missing_owner_and_refreshes_on_connection(rig, managed_qt_widget):
    plugin = SetTemperatureCommand()
    plugin.controller_id = "secondary"
    selector = managed_qt_widget(TemperatureLoopSelector(plugin))
    assert "unavailable" in selector.currentText()
    rig.connect_instrument(SimulatedTemperatureController(), controller_id="secondary")
    assert "unavailable" not in selector.currentText()
    assert selector.currentData() == LoopRef("secondary", 1)
    rig.controller("secondary").disconnect_instrument()
    assert selector.currentData() == LoopRef("secondary", 1)
    assert "unavailable" in selector.currentText()


def test_secondary_zone_curves_and_gas_controls_use_own_capabilities(
    rig, managed_temperature_panel
):
    from dataclasses import replace

    from stoner_measurement.instruments.temperature_controller import (
        InputChannelSettings,
        ZoneEntry,
    )

    class AuxiliaryController(SimulatedTemperatureController):
        def get_capabilities(self):
            return replace(
                super().get_capabilities(),
                has_zone=True,
                has_input_settings=True,
                has_cryogen_control=True,
                has_gas_auto_mode=True,
            )

        def get_calibration_curve_names(self):
            return {1: "Secondary curve"}

        def get_input_channel_settings(self, channel):
            return InputChannelSettings(curve_number=1)

        def get_num_zones(self, loop):
            return 1

        def get_zone(self, loop, index):
            return ZoneEntry(300, 1, 2, 3, 4, 1, 0)

        def get_gas_flow(self):
            return 12.0

        def get_needle_valve(self):
            return 12.0

        def get_gas_auto(self):
            return True

    rig.connect_instrument(SimulatedTemperatureController())
    rig.connect_instrument(AuxiliaryController(), controller_id="secondary")
    panel = managed_temperature_panel()
    panel._sync_existing_connection_state()
    assert panel._zone_loop_combo.currentData() == LoopRef("secondary", 1)
    assert panel._secondary_input_settings._curve_names == {1: "Secondary curve"}
    assert not panel._input_settings_widget._channels
    assert panel._needle_group.isHidden()
    assert panel._secondary_cryogen is not None
    assert panel._secondary_cryogen._auto.isChecked()
    assert not panel._secondary_cryogen._apply.isEnabled()
    assert panel._chart_values["secondary:NV"][-1] == 12.0


def test_chart_splitter_resizes_and_single_rate_follows_selected_sensor(
    rig, managed_temperature_panel, qtbot
):
    from dataclasses import replace

    from qtpy.QtCore import QEvent, QPoint, QPointF, Qt
    from qtpy.QtGui import QMouseEvent
    from qtpy.QtWidgets import QApplication

    from stoner_measurement.temperature_control.types import StabilityBand, StabilityConfig

    rig.connect_instrument(SimulatedTemperatureController())
    rig.connect_instrument(SimulatedTemperatureController(), controller_id="secondary")
    panel = managed_temperature_panel()
    panel.resize(1150, 950)
    panel._tabs.setCurrentWidget(panel._chart_splitter.parentWidget())
    panel.show()
    qtbot.waitExposed(panel)
    splitter = panel._chart_splitter
    before = splitter.sizes()
    handle = splitter.handle(1)
    qtbot.mousePress(handle, Qt.MouseButton.LeftButton, pos=handle.rect().center())
    destination = handle.rect().center() + QPoint(-100, 0)
    QApplication.sendEvent(
        handle,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(destination),
            QPointF(handle.mapToGlobal(destination)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qtbot.mouseRelease(handle, Qt.MouseButton.LeftButton)
    assert splitter.sizes()[0] < before[0]
    rig.set_stability_config(StabilityConfig(bands=[StabilityBand(rate_channel="secondary:B")]))
    state = rig.read_controller_state()
    state.secondary.readings["B"] = replace(state.secondary.readings["B"], rate_of_change=1.25)
    now = state.secondary.readings["B"].timestamp.timestamp()
    panel._update_rate_chart(state, now)
    assert panel._rate_source_channel == "secondary:B"
    assert panel._chart_values["dT/dt"][-1] == 1.25
    assert "B.2" in panel._legend_items["dT/dt"].toolTip(0)
    rig.set_stability_config(StabilityConfig(bands=[StabilityBand(rate_channel="A")]))
    rig.read_controller_state()
    assert len(panel._chart_values["dT/dt"]) == 1
    rig.set_stability_config(
        StabilityConfig(bands=[StabilityBand(rate_channel="secondary:missing")])
    )
    rig.read_controller_state()
    assert panel._legend_items["dT/dt"].text(1) == "Unavailable"
    assert panel._chart_widget.y_data("dT/dt") == []


def test_stability_rows_can_be_reordered(rig, managed_temperature_panel):
    from stoner_measurement.temperature_control.types import StabilityBand, StabilityConfig

    rig.set_stability_config(
        StabilityConfig(
            bands=[
                StabilityBand(max_temperature_k=100, rate_channel="A"),
                StabilityBand(max_temperature_k=500, rate_channel="secondary:B"),
            ]
        )
    )
    panel = managed_temperature_panel()
    panel._stab_table.setCurrentCell(1, 0)
    panel._move_stability_band(-1)
    panel._on_apply_stability()
    assert rig.stability_config.bands[0].rate_channel == "secondary:B"
    assert rig.stability_config.bands[1].max_temperature_k == 100


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
