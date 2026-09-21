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

    **Settings** selects the control loop and reported sensors; a blank sensor
    list includes all known sensors. **Sweep** selects the generator, segment
    targets, rates, measurement flags and timeout factor. **Data** selects
    collected values and column roles. Stability criteria belong to the shared
    controller. This sweep collects while moving instead of waiting for
    stability at each point.

    Rates for multi-segment ramp sweeps are interpreted in ``K/min`` and the
    default timeout factor for this plugin is ``4.0``. That more generous
    default reflects that real cryostats often take substantially longer than
    a simple ramp-rate estimate would suggest.

    The loop selector labels Primary and Secondary explicitly. Secondary is
    optional and disabled by default in the controller panel. A saved unavailable
    loop remains selected and cannot silently fall back to the other instrument.
    Unqualified sensor names refer to primary; use ``secondary:A`` in sensor
    lists to select channel A on secondary. Available-sensor pickers avoid typing
    channel names. Blank sensor lists include both connected controllers.

    Attributes:
        controller_id (str):
            Persistent controller slot, ``"primary"`` (default) or ``"secondary"``.
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
        control_loop (int):
            One-based control loop; defaults to 1.
        sensor_channels (list[str] | None):
            Reported sensors; None selects all known sensors.
        instance_name (str):
            Inherited Python identifier for this instance in the Script tab and
            QtConsole.
        comment (str):
            Inherited optional note displayed beside this step.
        sequence_engine (SequenceEngine | None):
            Inherited owning engine and its live namespace; None while
            detached.
        meas_flag (bool):
            Inherited flag indicating a measurement point.
        collect_data (bool):
            Inherited switch enabling collection of selected sequence outputs.
        data (TraceData):
            Inherited accumulated table; inspect data.df after collection.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        With a sequence instance named ``temperature_controller_sweep``, use
        the QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            temperature_controller_sweep.control_loop = 2
            temperature_controller_sweep.collect_data = True
            temperature_controller_sweep.data.df.head()
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
