"""Temperature-controller-backed state-sweep plugin."""

from __future__ import annotations

from stoner_measurement.plugins.state._temperature_controller_plugin import (
    TemperatureControllerPluginMixin,
)
from stoner_measurement.plugins.state_sweep.base import StateSweepPlugin


class TemperatureControllerSweepPlugin(TemperatureControllerPluginMixin, StateSweepPlugin):
    """Sweep temperature continuously while collecting data in motion.

    Use this plugin when you want temperature to change continuously, with
    data collected while the temperature is moving rather than only after
    settling at a set of discrete points. This is useful for ramp-based
    measurements, thermal drift studies, and overview scans where waiting for
    full equilibration at every point would take too long.

    In the configuration tabs, the **Settings** tab contains the inherited
    temperature-controller options such as loop selection, tolerance,
    stability handling, and timeout factor. The sweep-generator area lets you
    define how the setpoint evolves over time, for example with a
    multi-segment ramp using different targets, rates, and measurement flags.
    The **Data Collection** section controls which values are recorded during
    the sweep. The **Help/About** tab uses this docstring as end-user
    guidance.

    Rates for multi-segment ramp sweeps are interpreted in ``K/min`` and the
    default timeout factor for this plugin is ``4.0``. That more generous
    default reflects that real cryostats often take substantially longer than
    a simple ramp-rate estimate would suggest.

    Attributes:
        loop (int):
            Control loop used by the inherited controller logic.
        wait_for_stable (bool):
            Inherited controller setting controlling whether stability criteria
            are enforced in addition to target tracking.
        sweep_timeout_factor (float):
            Multiplier applied to the estimated sweep duration when computing
            the allowed wall-clock runtime.
        default_sweep_timeout_factor (float):
            Default timeout multiplier for temperature sweeps. This plugin
            uses ``4.0``.
        sweep_rate_time_scale_seconds (float):
            Time-scale factor used to interpret sweep rates. This plugin uses
            ``60.0`` so that configured ramp rates are treated as ``K/min``.
        sweep_generator (BaseSweepGenerator):
            Active sweep generator instance controlling the temperature
            trajectory.
        value (float):
            Most recently sampled control value, in kelvin.
        ix (int):
            Index of the most recently yielded sweep point.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Create the plugin and inspect its defaults from the console:

        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> plugin = TemperatureControllerSweepPlugin()
        >>> plugin.name
        'Temperature Controller'
        >>> plugin.state_name
        'Control Value'
        >>> plugin.units
        'K'
        >>> plugin.sweep_rate_time_scale_seconds
        60.0
        >>> plugin.default_sweep_timeout_factor
        4.0
    """

    _default_sweep_timeout_factor = 4.0
    _sweep_rate_time_scale_seconds = 60.0

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