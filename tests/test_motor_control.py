"""Tests for the motor-control engine and public scripting access."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stoner_measurement.instruments.motor_controller import MotorMoveDirection
from stoner_measurement.instruments.simulated import SimulatedMotorController
from stoner_measurement.motor_control import MotorControllerEngine
from stoner_measurement.motor_control.types import (
    MotorEngineState,
    MotorEngineStatus,
    MotorReading,
)


def _repo_qapp(qapp):
    """Reference the shared qapp fixture to keep pylint quiet."""
    return qapp


class TestSimulatedMotorControllerIntegration:
    def test_engine_reads_simulated_motor_controller(self, qapp):
        _repo_qapp(qapp)

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()

        engine.connect_instrument(driver)

        state = engine.read_controller_state()

        assert state is not None
        assert state.reading is not None
        assert state.reading.angle == pytest.approx(0.0)
        assert state.reading.target_angle == pytest.approx(0.0)

        engine.shutdown()

    def test_engine_observes_simulated_motor_motion(self, qapp):
        _repo_qapp(qapp)

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()

        engine.connect_instrument(driver)

        engine.set_velocity(20.0)
        engine.set_acceleration(60.0)
        engine.move_to_angle(45.0, direction=MotorMoveDirection.CLOCKWISE)
        driver._last_update -= 1.0  # pylint: disable=protected-access

        state = engine.read_controller_state()

        assert state is not None
        assert state.reading is not None
        assert state.reading.angle > 0.0
        assert state.reading.target_angle == pytest.approx(45.0)
        assert state.reading.displayed_angle is not None
        assert state.reading.move_direction == "clockwise"

        engine.shutdown()

    def test_engine_rejects_explicit_direction_target_outside_absolute_limits(self, qapp):
        _repo_qapp(qapp)

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)

        driver._position = 170.0  # pylint: disable=protected-access
        driver._target_position = 123.0  # pylint: disable=protected-access
        with pytest.raises(ValueError, match="soft-limit"):
            engine.move_to_angle(-160.0, direction=MotorMoveDirection.CLOCKWISE)

        assert driver.get_target_position() == pytest.approx(123.0)

        state = engine.get_engine_state()
        assert state.target_angle is None
        assert state.displayed_angle is None

        engine.shutdown()

    def test_engine_resolves_explicit_direction_target_within_absolute_limits(self, qapp):
        _repo_qapp(qapp)

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)

        driver._position = 10.0  # pylint: disable=protected-access
        engine.move_to_angle(100.0, direction=MotorMoveDirection.CLOCKWISE)

        assert driver.get_target_position() == pytest.approx(100.0)
        state = engine.get_engine_state()
        assert state.target_angle == pytest.approx(100.0)
        assert state.displayed_angle == pytest.approx(100.0)
        assert state.move_direction == "clockwise"

        engine.shutdown()

    def test_move_to_angle_invalidates_cached_target_state(self, qapp):
        _repo_qapp(qapp)

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)
        engine._is_at_target = True
        engine._stable = True
        engine._latest_state = MotorEngineState(
            reading=MotorReading(
                timestamp=datetime.now(tz=UTC),
                angle=0.0,
                target_angle=0.0,
                moving=False,
                at_target=True,
            ),
            target_angle=0.0,
            at_target=True,
            stable=True,
            engine_status=MotorEngineStatus.POLLING,
        )

        engine.move_to_angle(45.0, direction=MotorMoveDirection.CLOCKWISE)
        state = engine.get_engine_state()

        assert state.target_angle == pytest.approx(45.0)
        assert state.at_target is False
        assert state.stable is False
        assert state.reading is not None
        assert state.reading.at_target is False
        engine.shutdown()

    def test_engine_force_allows_soft_limit_override(self, qapp):
        _repo_qapp(qapp)

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)

        driver._position = 170.0  # pylint: disable=protected-access
        engine.move_to_angle(-160.0, direction=MotorMoveDirection.CLOCKWISE, force=True)

        assert driver.get_target_position() == pytest.approx(200.0)
        state = engine.get_engine_state()
        assert state.target_angle == pytest.approx(200.0)
        assert state.displayed_angle == pytest.approx(200.0)
        assert state.move_direction == "clockwise"

        engine.shutdown()

    def test_engine_uses_relative_move_for_signed_soft_limit_wraparound(self, qapp):
        _repo_qapp(qapp)

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)

        engine._soft_limit = 200.0  # pylint: disable=protected-access
        driver._position = -190.0  # pylint: disable=protected-access
        engine.move_to_angle(190.0, direction=MotorMoveDirection.SHORTEST)

        assert driver.get_target_position() == pytest.approx(190.0)
        state = engine.get_engine_state()
        assert state.target_angle == pytest.approx(190.0)
        assert state.displayed_angle == pytest.approx(190.0)
        assert state.move_direction == "clockwise"

        engine.shutdown()

    def test_engine_resolves_shortest_moves_with_soft_limit_rules(self, qapp):
        _repo_qapp(qapp)

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)

        driver._position = 170.0  # pylint: disable=protected-access
        engine.move_to_angle(190.0, direction=MotorMoveDirection.SHORTEST)

        assert driver.get_target_position() == pytest.approx(190.0)
        assert engine.get_engine_state().displayed_angle == pytest.approx(190.0)

        engine.shutdown()

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)
        driver._position = 90.0  # pylint: disable=protected-access
        engine.move_to_angle(135.0, direction=MotorMoveDirection.SHORTEST)
        assert driver.get_target_position() == pytest.approx(135.0)

        engine.shutdown()

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)
        driver._position = 180.0  # pylint: disable=protected-access
        engine.move_to_angle(-180.0, direction=MotorMoveDirection.COUNTERCLOCKWISE)
        assert driver.get_target_position() == pytest.approx(-180.0)
        state = engine.get_engine_state()
        assert state.target_angle == pytest.approx(-180.0)
        assert state.displayed_angle == pytest.approx(180.0)

        engine.shutdown()

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)
        driver._position = 0.0  # pylint: disable=protected-access
        engine.move_to_angle(180.0, direction=MotorMoveDirection.CLOCKWISE)
        assert driver.get_target_position() == pytest.approx(180.0)
        driver._position = 180.0  # pylint: disable=protected-access
        engine.move_to_angle(-180.0, direction=MotorMoveDirection.COUNTERCLOCKWISE)
        assert driver.get_target_position() == pytest.approx(-180.0)
        driver._position = -180.0  # pylint: disable=protected-access
        engine.move_to_angle(270.0, direction=MotorMoveDirection.SHORTEST)
        assert driver.get_target_position() == pytest.approx(-90.0)

        engine.shutdown()

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)
        driver._position = 175.0  # pylint: disable=protected-access
        engine._soft_limit = 220.0  # pylint: disable=protected-access
        engine.move_to_angle(205.0, direction=MotorMoveDirection.SHORTEST)
        assert driver.get_target_position() == pytest.approx(205.0)

        engine.shutdown()

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)
        driver._position = 175.0  # pylint: disable=protected-access
        engine.move_to_angle(205.0, direction=MotorMoveDirection.SHORTEST)
        assert driver.get_target_position() == pytest.approx(-155.0)

        engine.shutdown()

    def test_engine_connect_driver_by_name_uses_simulated_motor(self, qapp):
        _repo_qapp(qapp)

        engine = MotorControllerEngine()

        engine.connect_driver(
            "SimulatedMotorController",
            "Null (test)",
            "",
        )

        assert engine.connected_driver is not None
        assert isinstance(engine.connected_driver, SimulatedMotorController)
        assert engine.connected_driver_name == "SimulatedMotorController"
        assert engine.connected_transport_name == "Null (test)"
        assert engine.connected_address == ""
        assert engine.status in {MotorEngineStatus.CONNECTED, MotorEngineStatus.POLLING}

        engine.shutdown()


class TestMotorControlPanel:
    def test_creates_widget(self, qapp):
        _repo_qapp(qapp)
        from stoner_measurement.ui.motor_panel import MotorControlPanel

        panel = MotorControlPanel()
        assert panel is not None
        assert panel.windowTitle() == "Motor Control"

    def test_close_hides_not_destroys(self, qapp):
        _repo_qapp(qapp)
        from stoner_measurement.ui.motor_panel import MotorControlPanel

        panel = MotorControlPanel()
        panel.show()
        assert panel.isVisible()
        panel.close()
        assert not panel.isVisible()

    def test_hide_button_hides_panel(self, qapp):
        _repo_qapp(qapp)
        from stoner_measurement.ui.motor_panel import MotorControlPanel

        panel = MotorControlPanel()
        panel.show()
        assert panel._btn_hide.text() == "Hide"
        assert panel.isVisible()
        panel._btn_hide.click()
        qapp.processEvents()
        assert not panel.isVisible()

    def test_save_button_is_on_connection_tab(self, qapp):
        _repo_qapp(qapp)
        from qtpy.QtWidgets import QPushButton

        from stoner_measurement.ui.motor_panel import MotorControlPanel

        panel = MotorControlPanel()
        connection_tab = panel._tabs.widget(0)  # pylint: disable=protected-access
        control_tab = panel._tabs.widget(1)  # pylint: disable=protected-access

        connection_labels = [btn.text() for btn in connection_tab.findChildren(QPushButton)]
        control_labels = [btn.text() for btn in control_tab.findChildren(QPushButton)]

        assert "Save Settings to YAML" in connection_labels
        assert "Save Settings to YAML" not in control_labels

    def test_target_angle_accepts_negative_values_within_soft_limit(self, qapp):
        _repo_qapp(qapp)
        from stoner_measurement.ui.motor_panel import MotorControlPanel

        panel = MotorControlPanel()
        panel._engine._soft_limit = 190.0  # pylint: disable=protected-access
        panel._refresh_target_angle_bounds()  # pylint: disable=protected-access

        panel._target_angle_spin.setValue(-180.0)  # pylint: disable=protected-access

        assert panel._target_angle_spin.value() == pytest.approx(-180.0)  # pylint: disable=protected-access
        assert panel._target_angle_spin.opts["bounds"] == pytest.approx((-190.0, 190.0))  # pylint: disable=protected-access

    def test_target_angle_clamps_to_soft_limit(self, qapp):
        _repo_qapp(qapp)
        from stoner_measurement.ui.motor_panel import MotorControlPanel

        panel = MotorControlPanel()
        panel._engine._soft_limit = 190.0  # pylint: disable=protected-access
        panel._refresh_target_angle_bounds()  # pylint: disable=protected-access

        panel._target_angle_spin.setValue(205.0)  # pylint: disable=protected-access

        assert panel._target_angle_spin.value() == pytest.approx(190.0)  # pylint: disable=protected-access

    def test_dial_uses_signed_bidirectional_mode(self, qapp):
        _repo_qapp(qapp)
        from stoner_measurement.ui.motor_panel import MotorControlPanel

        panel = MotorControlPanel()

        assert panel._dial.minimumValue() == pytest.approx(-180.0)  # pylint: disable=protected-access
        assert panel._dial.maximumValue() == pytest.approx(180.0)  # pylint: disable=protected-access
        assert panel._dial.minimumAngle() == pytest.approx(-180.0)  # pylint: disable=protected-access
        assert panel._dial.maximumAngle() == pytest.approx(180.0)  # pylint: disable=protected-access
        assert panel._dial.wrap() is False  # pylint: disable=protected-access

    def test_soft_limit_prompt_retries_confirmed_forced_move(self, qapp, monkeypatch):
        _repo_qapp(qapp)
        from qtpy.QtWidgets import QMessageBox

        from stoner_measurement.ui import motor_panel as motor_panel_module
        from stoner_measurement.ui.motor_panel import MotorControlPanel

        class _PromptingEngine:
            def __init__(self):
                self.calls = []
                self.preferred_driver_name = ""
                self.preferred_transport_name = ""
                self.preferred_address = ""

            def set_velocity(self, value):
                self.velocity = value

            def set_acceleration(self, value):
                self.acceleration = value

            def move_to_angle(self, angle, *, direction, force=False):
                self.calls.append((angle, direction, force))
                if not force:
                    raise ValueError("soft-limit violation")

        engine = _PromptingEngine()
        panel = MotorControlPanel()
        panel._engine = engine  # pylint: disable=protected-access
        panel._target_angle_spin.setValue(-160.0)  # pylint: disable=protected-access
        panel._direction_combo.setCurrentIndex(0)  # pylint: disable=protected-access

        monkeypatch.setattr(
            motor_panel_module.QMessageBox,
            "warning",
            lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
        )

        panel._on_apply_and_move()  # pylint: disable=protected-access

        assert engine.calls == [
            (-160.0, MotorMoveDirection.CLOCKWISE, False),
            (-160.0, MotorMoveDirection.CLOCKWISE, True),
        ]


def test_top_level_public_motor_exports():
    import stoner_measurement as top_level
    from stoner_measurement import (
        MotorControllerEngine as TopLevelMotorControllerEngine,
    )
    from stoner_measurement.instruments import (
        SimulatedMotorController as InstrumentsSimulatedMotorController,
    )

    assert TopLevelMotorControllerEngine is MotorControllerEngine
    assert top_level.MotorEngineState.__name__ == "MotorEngineState"
    assert top_level.MotorReading.__name__ == "MotorReading"
    assert top_level.SimulatedMotorController is InstrumentsSimulatedMotorController


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
