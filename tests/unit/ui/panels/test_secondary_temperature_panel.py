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
    assert panel._input_tabs.widget(0).layout().indexOf(panel._input_settings_widget) >= 0
    assert panel._input_tabs.widget(1).layout().indexOf(panel._secondary_input_settings) >= 0
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
    rig, managed_temperature_panel, wait_temperature_tasks
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
    assert panel._secondary_input_settings._curve_names == {}
    panel._tabs.setCurrentIndex(panel._input_settings_tab_index)
    panel._input_tabs.setCurrentIndex(1)
    wait_temperature_tasks(rig)
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


@pytest.mark.parametrize("controller_id", ["primary", "secondary"])
def test_control_edits_survive_poll_until_explicit_read(
    rig, managed_temperature_panel, controller_id, wait_temperature_tasks
):
    from dataclasses import replace

    class CryogenController(SimulatedTemperatureController):
        position = 12.0
        automatic = False

        def get_capabilities(self):
            return replace(
                super().get_capabilities(),
                has_cryogen_control=True,
                has_gas_auto_mode=True,
            )

        def get_gas_flow(self):
            return self.position

        def get_gas_auto(self):
            return self.automatic

        def set_gas_auto(self, enabled):
            self.automatic = enabled

    panel = managed_temperature_panel()
    driver = CryogenController()
    rig.connect_instrument(driver, controller_id=controller_id)
    wait_temperature_tasks(rig)
    if controller_id == "primary":
        position = panel._needle_spin
        automatic = panel._gas_auto_check
        read = panel._needle_read_btn.click
    else:
        position = panel._secondary_cryogen._position
        automatic = panel._secondary_cryogen._auto
        read = panel._secondary_cryogen._read
    assert position.value() == 12.0
    assert not automatic.isChecked()
    position.setValue(35.0)
    driver.position = 60.0
    driver.automatic = True
    rig.read_controller_state()
    assert position.value() == 35.0
    assert not automatic.isChecked()
    assert position.isEnabled()
    read()
    wait_temperature_tasks(rig)
    assert position.value() == 60.0
    assert automatic.isChecked()
    assert not position.isEnabled()
    automatic.setChecked(False)
    assert position.value() == 60.0
    assert position.isEnabled()


@pytest.mark.parametrize("mode_name", ["CLOSED_LOOP", "ZONE", "OPEN_LOOP", "OFF"])
def test_primary_itc503_apply_reaches_hardware(
    rig, managed_qt_widget, mode_name, monkeypatch, wait_temperature_tasks
):
    from qtpy.QtWidgets import QPushButton

    from stoner_measurement.instruments.oxford import OxfordITC503
    from stoner_measurement.instruments.temperature_controller import ControlMode
    from stoner_measurement.instruments.transport import NullTransport
    from stoner_measurement.ui.temperature_panel import _LoopControlGroup

    mode = ControlMode[mode_name]
    responses = [b"H\r", b"T\r"]
    expected = [b"H2\r", b"T12.0\r"]
    if mode is not ControlMode.ZONE:
        responses.extend([b"L\r", b"P\r", b"I\r", b"D\r"])
        expected.extend([b"L0\r", b"P30.0\r", b"I4.0\r", b"D0.5\r"])
    responses.extend([b"X0A3C3S00H2L0\r", b"L\r", b"A\r"])
    expected.extend([b"X\r", b"L1\r" if mode is ControlMode.ZONE else b"L0\r"])
    expected.append(b"A3\r" if mode in (ControlMode.CLOSED_LOOP, ControlMode.ZONE) else b"A2\r")
    if mode in (ControlMode.OFF, ControlMode.OPEN_LOOP):
        responses.append(b"O\r")
        expected.append(b"O0.0\r" if mode is ControlMode.OFF else b"O25.0\r")
    transport = NullTransport(responses=responses)
    transport.open()
    driver = OxfordITC503(transport=transport)
    rig._driver = driver
    group = managed_qt_widget(_LoopControlGroup(1, rig, driver.get_capabilities()))
    from stoner_measurement.temperature_control.types import LoopSettings

    monkeypatch.setattr(rig, "get_loop_settings", lambda loop: LoopSettings(
        4.2, ControlMode.CLOSED_LOOP, "A", False, 0, 1, 1, 1,
    ))
    assert group.read_from_hardware()
    group._channel_combo.setCurrentIndex(group._channel_combo.findData("B"))
    group._mode_combo.setCurrentIndex(group._mode_combo.findData(mode))
    group._sp_spin.setValue(12)
    group._pid_p_spin.setValue(30)
    group._pid_i_spin.setValue(4)
    group._pid_d_spin.setValue(0.5)
    group._manual_output_spin.setValue(25)
    assert group._heater_range_spin.isHidden()
    assert group._ramp_widget.isHidden()
    assert group._mode_combo.findData(ControlMode.MONITOR) == -1
    next(button for button in group.findChildren(QPushButton) if button.text() == "Apply").click()
    wait_temperature_tasks(rig)
    assert transport.write_log == expected


def test_primary_itc503_make_safe_uses_manual_off_sequence(rig):
    from stoner_measurement.instruments.oxford import OxfordITC503
    from stoner_measurement.instruments.transport import NullTransport
    from stoner_measurement.plugins.command.make_safe import MakeSafeCommand

    transport = NullTransport(responses=[
        b"X0A3C3S00H1L0\r", b"A\r", b"G\r",
        b"X0A1C3S00H1L0\r", b"L\r", b"A\r", b"O\r",
    ])
    transport.open()
    rig._driver = OxfordITC503(transport=transport)
    MakeSafeCommand._make_temperature_safe()
    assert transport.write_log == [
        b"X\r", b"A1\r", b"G0.0\r", b"X\r", b"L0\r", b"A0\r", b"O0.0\r",
    ]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
