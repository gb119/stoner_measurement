"""Command plugin for setting a temperature-controller loop target."""

from __future__ import annotations

import math
from typing import Any

from qtpy.QtWidgets import QFormLayout, QSpinBox, QWidget

from stoner_measurement.plugins.command.set_engine_state import SetEngineStateCommand
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine


class SetTemperatureCommand(SetEngineStateCommand):
    """Set one temperature-control loop and optionally wait until it reaches setpoint."""

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
        return bool(state.at_setpoint.get(self.control_loop, False))

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
