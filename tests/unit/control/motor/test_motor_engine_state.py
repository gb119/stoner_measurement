"""Tests for the motor engine's published angle and direction state."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.motor_controller import MotorMoveDirection
from stoner_measurement.instruments.simulated import SimulatedMotorController
from stoner_measurement.motor_control.engine import MotorControllerEngine


def test_engine_publishes_signed_angle_from_wrapped_controller_reading(qapp):
    """A controller's 270-degree reading represents -90 degrees to scan clients."""
    engine = MotorControllerEngine()
    driver = SimulatedMotorController()
    engine.connect_instrument(driver)
    driver._position = 270.0  # noqa: SLF001

    state = engine.read_controller_state()

    assert state is not None
    assert state.reading is not None
    assert state.reading.angle == pytest.approx(-90.0)
    engine.shutdown()


def test_engine_separates_requested_direction_mode_from_resolved_direction(qapp):
    """Shortest remains the requested mode after resolving an actual clockwise move."""
    engine = MotorControllerEngine()
    driver = SimulatedMotorController()
    engine.connect_instrument(driver)

    engine.move_to_angle(90.0, direction=MotorMoveDirection.SHORTEST)
    state = engine.get_engine_state()

    assert state.direction_mode == "shortest"
    assert state.move_direction == "clockwise"
    engine.shutdown()


def test_engine_preserves_negative_180_branch_for_following_shortest_move(qapp):
    """A wrapped +180 reading must remain -180 after a command to -180."""
    engine = MotorControllerEngine()
    driver = SimulatedMotorController()
    engine.connect_instrument(driver)
    engine._target_angle = -180.0  # noqa: SLF001
    driver._position = 180.0  # noqa: SLF001
    driver._target_position = 180.0  # noqa: SLF001

    state = engine.read_controller_state()
    engine.move_to_angle(-178.0, direction=MotorMoveDirection.SHORTEST)

    assert state is not None
    assert state.reading is not None
    assert state.reading.angle == pytest.approx(-180.0)
    assert driver.get_target_position() == pytest.approx(182.0)
    assert engine.get_engine_state().move_direction == "clockwise"
    engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
