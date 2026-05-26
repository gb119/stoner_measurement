"""Temperature-controller-backed state-scan plugin."""

from __future__ import annotations

from stoner_measurement.plugins.state._temperature_controller_plugin import (
    TemperatureControllerPluginMixin,
)
from stoner_measurement.plugins.state_scan.base import StateScanPlugin


class TemperatureControllerScanPlugin(TemperatureControllerPluginMixin, StateScanPlugin):
    """State-scan plugin that drives the temperature controller engine."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_temperature_controller_plugin()

    @property
    def name(self) -> str:
        return "Temperature Controller"

    @property
    def state_name(self) -> str:
        return "Setpoint"

    @property
    def units(self) -> str:
        return "K"

    def to_json(self) -> dict[str, object]:
        data = super().to_json()
        data.update(self._temperature_settings_to_json())
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        super()._restore_from_json(data)
        self._restore_temperature_settings(data)
