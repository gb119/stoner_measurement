"""Temperature-controller-backed state-sweep plugin."""

from __future__ import annotations

from stoner_measurement.plugins.state._temperature_controller_plugin import (
    TemperatureControllerPluginMixin,
)
from stoner_measurement.plugins.state_sweep.base import StateSweepPlugin


class TemperatureControllerSweepPlugin(TemperatureControllerPluginMixin, StateSweepPlugin):
    """Sweep temperature continuously according to a sweep generator.

    Use this plugin when you want temperature to change continuously, with
    data collected while the temperature is moving rather than only after
    settling at a set of discrete points. This is useful for ramp-based
    measurements, thermal drift studies, and time-efficient overview scans.

    In the configuration tabs, you choose the temperature-controller settings
    and the sweep generator that defines how the temperature should evolve
    with time. The plugin then follows that generator while reporting the
    current control value back to the sequence framework.

    The temperature-specific tab provides the detailed control-loop and
    stability settings from
    :class:`~stoner_measurement.plugins.state._temperature_controller_plugin.TemperatureControllerPluginMixin`,
    while the sweep tab defines the time evolution of the requested
    temperature. The Help/About tab uses this docstring to explain how
    continuous temperature ramps are configured.

    Attributes:
        loop (int):
            Control loop used by the inherited controller logic.
        wait_for_stable (bool):
            Inherited controller setting controlling whether stability criteria
            are enforced in addition to target tracking.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> plugin = TemperatureControllerSweepPlugin()
        >>> plugin.name
        'Temperature Controller'
        >>> plugin.state_name
        'Control Value'
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_temperature_controller_plugin()

    @property
    def name(self) -> str:
        return "Temperature Controller"

    @property
    def state_name(self) -> str:
        return "Control Value"

    @property
    def units(self) -> str:
        return "K"

    def __next__(self) -> bool:
        """Advance the sweep using the configured sweep generator semantics."""
        return super().__next__()

    def to_json(self) -> dict[str, object]:
        data = super().to_json()
        data.update(self._temperature_settings_to_json())
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        super()._restore_from_json(data)
        self._restore_temperature_settings(data)
