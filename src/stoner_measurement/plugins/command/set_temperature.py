"""Command plugin for setting a temperature-controller loop target."""

from __future__ import annotations

import math
from typing import Any

from qtpy.QtWidgets import QFormLayout, QSpinBox, QWidget

from stoner_measurement.plugins.command.set_engine_state import SetEngineStateCommand
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine


class SetTemperatureCommand(SetEngineStateCommand):
    """Set a temperature-control loop target during a sequence.

    Use this command to change the setpoint of one loop on the active
    temperature controller. If necessary, the command connects the preferred
    configured controller before setting the target. It can either continue
    immediately or hold sequence execution until the engine reports that the
    selected loop is stable.

    The configuration tab provides **Control loop**, **Setpoint expression**,
    and **Wait expression** controls. The setpoint is in kelvin and may be a
    number or an expression evaluated in the sequence namespace when the step
    runs. The wait expression defaults to ``True``; set it to ``False`` or to
    another Boolean expression to continue after the first state read.

    When execution finishes, the command publishes **Temperature**,
    **Setpoint**, **Heater Output**, **At Setpoint**, and **Stable** scalar
    outputs from the final controller state. Boolean outputs are represented
    as ``1.0`` or ``0.0``. They can be selected by later sequence steps or read
    with :meth:`output_value` in the console.

    Attributes:
        control_loop (int):
            One-based controller loop to update. Defaults to ``1``.
        setpoint_expr (str):
            Numeric expression for the target temperature in kelvin. Defaults
            to ``"300.0"``.
        wait_expr (str):
            Boolean expression controlling whether execution waits for the
            selected loop to become stable. Defaults to ``"True"``.
        instance_name (str):
            Inherited sequence-instance name used to identify the command and
            its published scalar outputs.
        sequence_engine (SequenceEngine | None):
            Inherited reference to the sequence engine and its live namespace.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Configure an instance from the QtConsole before running its sequence
        step::

            set_temperature.control_loop = 2
            set_temperature.setpoint_expr = "base_temperature + 5"
            set_temperature.wait_expr = "settle_before_measurement"

        After execution, inspect the captured state::

            set_temperature.output_value("Temperature")
            set_temperature.output_value("Stable")
    """

    setpoint_suffix = "K"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setpoint_expr = "300.0"
        self.control_loop = 1

    @property
    def name(self) -> str:
        return "Set Temperature"

    @property
    def controller_features(self) -> frozenset[str]:
        return frozenset({"temperature"})

    @property
    def output_names(self) -> tuple[str, ...]:
        return ("Temperature", "Setpoint", "Heater Output", "At Setpoint", "Stable")

    def _ensure_engine(self):
        engine = TemperatureControllerEngine.instance()
        if engine.connected_driver is None:
            engine.connect_preferred_driver()
        if engine.connected_driver is None:
            raise RuntimeError("No temperature controller is connected.")
        return engine

    def _set_target(self, engine, setpoint: float) -> None:
        engine.set_setpoint(self.control_loop, setpoint)

    def _read_state(self, engine):
        return engine.read_controller_state() or engine.get_engine_state()

    def _target_reached(self, state, setpoint: float) -> bool:
        return bool(state.stable.get(self.control_loop, False))

    def _state_values(self, state) -> dict[str, float]:
        channel = state.input_channels.get(self.control_loop)
        reading = state.readings.get(channel) if channel else None
        return {
            "Temperature": math.nan if reading is None else float(reading.value),
            "Setpoint": float(state.setpoints.get(self.control_loop, math.nan)),
            "Heater Output": float(state.heater_outputs.get(self.control_loop, math.nan)),
            "At Setpoint": float(bool(state.at_setpoint.get(self.control_loop, False))),
            "Stable": float(bool(state.stable.get(self.control_loop, False))),
        }

    def _add_specific_config(self, layout: QFormLayout, widget: QWidget) -> None:
        loop = QSpinBox(widget)
        loop.setObjectName("control_loop")
        loop.setRange(1, 99)
        loop.setValue(self.control_loop)
        loop.valueChanged.connect(lambda value: setattr(self, "control_loop", int(value)))
        layout.addRow("Control loop:", loop)

    def _specific_to_json(self) -> dict[str, Any]:
        return {"control_loop": self.control_loop}

    def _restore_specific_json(self, data: dict[str, Any]) -> None:
        self.control_loop = max(1, int(data.get("control_loop", 1)))
