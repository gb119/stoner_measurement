"""Tests for the motor-control engine and public scripting access."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.motor_controller import MotorMoveDirection
from stoner_measurement.instruments.simulated import SimulatedMotorController
from stoner_measurement.motor_control import MotorControllerEngine
from stoner_measurement.motor_control.types import MotorEngineStatus


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

        driver._position = 270.0  # pylint: disable=protected-access
        driver._target_position = 123.0  # pylint: disable=protected-access
        engine.move_to_angle(90.0, direction=MotorMoveDirection.CLOCKWISE)

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

    def test_engine_resolves_move_through_zero_with_safe_limit_rules(self, qapp):
        _repo_qapp(qapp)

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)

        driver._position = 170.0  # pylint: disable=protected-access
        engine.move_to_angle(190.0, direction=MotorMoveDirection.TOWARDS_ZERO)

        assert driver.get_target_position() == pytest.approx(-170.0)
        assert engine.get_engine_state().displayed_angle == pytest.approx(190.0)

        engine.shutdown()

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)
        driver._position = 90.0  # pylint: disable=protected-access
        engine.move_to_angle(135.0, direction=MotorMoveDirection.TOWARDS_ZERO)
        assert driver.get_target_position() == pytest.approx(135.0)

        engine.shutdown()

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)
        driver._position = 180.0  # pylint: disable=protected-access
        engine.move_to_angle(-180.0, direction=MotorMoveDirection.COUNTERCLOCKWISE)
        assert driver.get_target_position() == pytest.approx(180.0)
        state = engine.get_engine_state()
        assert state.target_angle == pytest.approx(180.0)
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
        assert driver.get_target_position() == pytest.approx(180.0)
        driver._position = -180.0  # pylint: disable=protected-access
        engine.move_to_angle(270.0, direction=MotorMoveDirection.TOWARDS_ZERO)
        assert driver.get_target_position() == pytest.approx(-90.0)

        engine.shutdown()

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)
        driver._position = 175.0  # pylint: disable=protected-access
        engine._safe_clockwise_limit = 220.0  # pylint: disable=protected-access
        engine._safe_counterclockwise_limit = 140.0  # pylint: disable=protected-access
        engine.move_to_angle(205.0, direction=MotorMoveDirection.TOWARDS_ZERO)
        assert driver.get_target_position() == pytest.approx(205.0)

        engine.shutdown()

        engine = MotorControllerEngine()
        driver = SimulatedMotorController()
        engine.connect_instrument(driver)
        driver._position = 175.0  # pylint: disable=protected-access
        engine.move_to_angle(205.0, direction=MotorMoveDirection.TOWARDS_ZERO)
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


def test_top_level_public_motor_exports():
    from stoner_measurement import (
        MotorControllerEngine as TopLevelMotorControllerEngine,
    )
    from stoner_measurement import MotorEngineState, MotorReading, SimulatedMotorController
    from stoner_measurement.instruments import (
        SimulatedMotorController as InstrumentsSimulatedMotorController,
    )

    assert TopLevelMotorControllerEngine is MotorControllerEngine
    assert MotorEngineState.__name__ == "MotorEngineState"
    assert MotorReading.__name__ == "MotorReading"
    assert SimulatedMotorController is InstrumentsSimulatedMotorController


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))