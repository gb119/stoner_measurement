"""Command plugin for setting the magnet-controller field target."""

from __future__ import annotations

import math

from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.plugins.command.set_engine_state import SetEngineStateCommand


class SetFieldCommand(SetEngineStateCommand):
    """Set magnetic field and optionally wait until the engine reports it at target."""

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
