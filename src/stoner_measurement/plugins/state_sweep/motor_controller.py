"""Motor-controller-backed state-sweep plugin."""

from __future__ import annotations

from stoner_measurement.plugins.state._motor_controller_plugin import (
    MotorControllerPluginMixin,
)
from stoner_measurement.plugins.state_sweep.base import StateSweepPlugin


class MotorControllerSweepPlugin(MotorControllerPluginMixin, StateSweepPlugin):
    """Sweep the motor angle continuously according to a sweep generator."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_motor_controller_plugin()

    @property
    def name(self) -> str:
        return "Motor Controller"

    @property
    def state_name(self) -> str:
        return "Control Value"

    @property
    def units(self) -> str:
        return "deg"

    def __next__(self) -> bool:
        return super().__next__()

    def to_json(self) -> dict[str, object]:
        data = super().to_json()
        data.update(self._motor_settings_to_json())
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        super()._restore_from_json(data)
        self._restore_motor_settings(data)