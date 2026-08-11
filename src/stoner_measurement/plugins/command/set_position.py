"""Command plugin for setting the motor-controller position target."""

from __future__ import annotations

import math
from typing import Any

from qtpy.QtWidgets import QComboBox, QFormLayout, QWidget

from stoner_measurement.instruments.motor_controller import MotorMoveDirection
from stoner_measurement.motor_control.engine import MotorControllerEngine
from stoner_measurement.plugins.command.set_engine_state import SetEngineStateCommand
from stoner_measurement.plugins.state._motor_controller_plugin import _normalise_direction


class SetPositionCommand(SetEngineStateCommand):
    """Move the motor to an absolute angular position during a sequence.

    Use this command to set the target angle of the active motor controller. If
    necessary, the command connects the preferred configured controller before
    requesting the move. It can either continue after the first state read or
    hold sequence execution until the motor engine reports that the target has
    been reached.

    The configuration tab provides **Direction**, **Setpoint expression**, and
    **Wait expression** controls. Direction can be clockwise,
    counter-clockwise, or the shortest route. The setpoint is in degrees and
    may be a number or an expression evaluated in the sequence namespace when
    the step runs. The wait expression defaults to ``True``.

    When execution finishes, the command publishes **Position**, **Target
    Position**, **Angular Rate**, **At Target**, and **Stable** scalar outputs
    from the final controller state. Boolean outputs are represented as ``1.0``
    or ``0.0``.

    Attributes:
        direction (MotorMoveDirection):
            Direction used for the absolute move. Defaults to
            :attr:`MotorMoveDirection.SHORTEST`.
        setpoint_expr (str):
            Numeric expression for the target position in degrees. Defaults to
            ``"0.0"``.
        wait_expr (str):
            Boolean expression controlling whether execution waits for the
            target position. Defaults to ``"True"``.
        instance_name (str):
            Inherited sequence-instance name used to identify the command and
            its published scalar outputs.
        sequence_engine (SequenceEngine | None):
            Inherited reference to the sequence engine and its live namespace.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Configure a move from the QtConsole::

            from stoner_measurement.instruments.motor_controller import (
                MotorMoveDirection,
            )
            set_position.setpoint_expr = "sample_angle + 90"
            set_position.direction = MotorMoveDirection.CLOCKWISE
            set_position.wait_expr = "True"

        Read the captured position after execution::

            set_position.output_value("Position")
    """

    setpoint_suffix = "°"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.direction = MotorMoveDirection.SHORTEST

    @property
    def name(self) -> str:
        return "Set Position"

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"motor_position"})

    @property
    def output_names(self) -> tuple[str, ...]:
        return ("Position", "Target Position", "Angular Rate", "At Target", "Stable")

    def _ensure_engine(self):
        engine = MotorControllerEngine.instance()
        if engine.connected_driver is None:
            engine.connect_preferred_driver()
        if engine.connected_driver is None:
            raise RuntimeError("No motor controller is connected.")
        return engine

    def _set_target(self, engine, setpoint: float) -> None:
        engine.move_to_angle(setpoint, direction=self.direction)

    def _read_state(self, engine):
        return engine.read_controller_state() or engine.get_engine_state()

    def _target_reached(self, state, setpoint: float) -> bool:
        return bool(state.at_target)

    def _state_values(self, state) -> dict[str, float]:
        reading = state.reading
        return {
            "Position": math.nan if reading is None else float(reading.angle),
            "Target Position": math.nan if state.target_angle is None else float(state.target_angle),
            "Angular Rate": math.nan if reading is None else float(reading.angular_rate),
            "At Target": float(bool(state.at_target)),
            "Stable": float(bool(state.stable)),
        }

    def _add_specific_config(self, layout: QFormLayout, widget: QWidget) -> None:
        direction = QComboBox(widget)
        direction.setObjectName("move_direction")
        direction.addItem("Clockwise", MotorMoveDirection.CLOCKWISE)
        direction.addItem("Counter-clockwise", MotorMoveDirection.COUNTERCLOCKWISE)
        direction.addItem("Shortest", MotorMoveDirection.SHORTEST)
        direction.setCurrentIndex(direction.findData(self.direction))
        direction.currentIndexChanged.connect(
            lambda index: setattr(self, "direction", _normalise_direction(direction.itemData(index)))
        )
        layout.addRow("Direction:", direction)

    def _specific_to_json(self) -> dict[str, Any]:
        return {"direction": self.direction.value}

    def _restore_specific_json(self, data: dict[str, Any]) -> None:
        self.direction = _normalise_direction(data.get("direction", MotorMoveDirection.SHORTEST.value))
