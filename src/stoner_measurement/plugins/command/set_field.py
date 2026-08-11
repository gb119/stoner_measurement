"""Command plugin for setting the magnet-controller field target."""

from __future__ import annotations

import math

from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.plugins.command.set_engine_state import SetEngineStateCommand


class SetFieldCommand(SetEngineStateCommand):
    """Set the magnetic-field target during a sequence.

    Use this command to ramp the active magnet controller to a new field. If
    necessary, the command connects the preferred configured controller before
    starting the ramp. It can either continue after the first state read or
    hold sequence execution until the magnet engine reports that the target
    has been reached.

    The configuration tab provides **Setpoint expression** and **Wait
    expression** controls. The setpoint is in tesla and may be a number or an
    expression evaluated in the sequence namespace when the step runs. The
    wait expression defaults to ``True``; use ``False`` or another Boolean
    expression when the ramp should proceed concurrently with later steps.

    When execution finishes, the command publishes **Field**, **Target Field**,
    **Current**, **Voltage**, **At Target**, and **Stable** scalar outputs from
    the final controller state. Boolean outputs are represented as ``1.0`` or
    ``0.0``. A reported quench stops the command with an error both before the
    ramp and while waiting.

    Attributes:
        setpoint_expr (str):
            Numeric expression for the target field in tesla. Defaults to
            ``"0.0"``.
        wait_expr (str):
            Boolean expression controlling whether execution waits for the
            field target. Defaults to ``"True"``.
        instance_name (str):
            Inherited sequence-instance name used to identify the command and
            its published scalar outputs.
        sequence_engine (SequenceEngine | None):
            Inherited reference to the sequence engine and its live namespace.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Configure a field step from the QtConsole::

            set_field.setpoint_expr = "maximum_field / 2"
            set_field.wait_expr = "wait_for_magnet"

        After execution, inspect the final readback::

            set_field.output_value("Field")
            set_field.output_value("At Target")
    """

    setpoint_suffix = "T"

    @property
    def name(self) -> str:
        return "Set Field"

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"magnetic_field"})

    @property
    def output_names(self) -> tuple[str, ...]:
        return ("Field", "Target Field", "Current", "Voltage", "At Target", "Stable")

    def _ensure_engine(self):
        engine = MagnetControllerEngine.instance()
        if engine.connected_driver is None:
            engine.connect_preferred_driver()
        if engine.connected_driver is None:
            raise RuntimeError("No magnet controller is connected.")
        return engine

    def _set_target(self, engine, setpoint: float) -> None:
        self._raise_if_quenched(engine.get_engine_state())
        engine.ramp_to_field(setpoint)

    def _read_state(self, engine):
        return engine.read_controller_state() or engine.get_engine_state()

    def _target_reached(self, state, setpoint: float) -> bool:
        self._raise_if_quenched(state)
        return bool(state.at_target)

    @staticmethod
    def _raise_if_quenched(state) -> None:
        if state.reading is not None and state.reading.quench_detected:
            raise RuntimeError("Magnet controller reported a quench condition.")

    def _state_values(self, state) -> dict[str, float]:
        self._raise_if_quenched(state)
        reading = state.reading
        return {
            "Field": math.nan if reading is None or reading.field is None else float(reading.field),
            "Target Field": math.nan if state.target_field is None else float(state.target_field),
            "Current": math.nan if reading is None else float(reading.current),
            "Voltage": math.nan if reading is None or reading.voltage is None else float(reading.voltage),
            "At Target": float(bool(state.at_target)),
            "Stable": float(bool(state.stable)),
        }
