"""Tests for motor-panel motion controls and stable sizing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from stoner_measurement.instruments.motor_controller import MotorMoveDirection
from stoner_measurement.ui.motor_panel import MotorControlPanel


class _RecordingEngine:
    preferred_driver_name = ""
    preferred_transport_name = ""
    preferred_address = ""

    def __init__(self) -> None:
        self.moves: list[MotorMoveDirection] = []

    def set_velocity(self, value: float) -> None:
        self.velocity = value

    def set_acceleration(self, value: float) -> None:
        self.acceleration = value

    def move_home(self, *, direction: MotorMoveDirection) -> None:
        self.moves.append(direction)


def test_move_home_applies_motion_settings_and_displayed_direction(qapp):
    panel = MotorControlPanel()
    engine = _RecordingEngine()
    panel._engine = engine  # noqa: SLF001
    panel._velocity_spin.setValue(12.0)  # noqa: SLF001
    panel._acceleration_spin.setValue(34.0)  # noqa: SLF001
    shortest_index = panel._direction_combo.findData(MotorMoveDirection.SHORTEST)  # noqa: SLF001
    panel._direction_combo.setCurrentIndex(shortest_index)  # noqa: SLF001

    panel._on_move_home()  # noqa: SLF001

    assert engine.velocity == pytest.approx(12.0)
    assert engine.acceleration == pytest.approx(34.0)
    assert engine.moves == [MotorMoveDirection.SHORTEST]


def test_status_bar_reserves_width_for_stable_control_columns(qapp):
    panel = MotorControlPanel()
    status_bar = panel._status_label.parentWidget()  # noqa: SLF001

    assert status_bar.minimumWidth() >= 720


def test_read_state_updates_direction_combo_from_requested_mode(qapp, monkeypatch):
    panel = MotorControlPanel()
    clockwise_index = panel._direction_combo.findData(MotorMoveDirection.CLOCKWISE)  # noqa: SLF001
    panel._direction_combo.setCurrentIndex(clockwise_index)  # noqa: SLF001
    state = SimpleNamespace(
        target_angle=None,
        direction_mode="shortest",
        move_direction="clockwise",
        velocity=None,
        acceleration=None,
    )
    monkeypatch.setattr(panel, "_read_controller_state_or_warn", lambda _title: state)

    panel._on_read_state()  # noqa: SLF001

    assert panel._direction_combo.currentData() is MotorMoveDirection.SHORTEST  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
