"""Motor-controller-backed state-sweep plugin."""

from __future__ import annotations

from stoner_measurement.plugins.state._motor_controller_plugin import (
    MotorControllerPluginMixin,
)
from stoner_measurement.plugins.state_sweep.base import StateSweepPlugin


class MotorControllerSweepPlugin(MotorControllerPluginMixin, StateSweepPlugin):
    """Sweep the motor angle continuously while collecting data in motion.

    Use this plugin when you want a rotation stage or motor axis to move
    continuously and your measurement sub-sequence to run repeatedly while the
    angle is changing. This is useful for angular sweeps where stopping at
    every point would be unnecessarily slow.

    The **Sweep** tab selects a multi-segment ramp or monitor-and-filter
    generator. A multi-segment ramp defines an optional starting angle and a
    sequence of absolute targets, angular rates, and measurement flags. Once
    motion begins, the plugin samples the live angle and runs nested steps at
    the generator's polling interval without stopping the motor. Segment rates
    are interpreted in degrees per second. **Start from current value** skips
    the initial positioning move.

    The **Sweep** tab also controls the timeout factor and optional temporary
    motor-engine polling rate. The timeout is the generator's estimated
    duration multiplied by the configured factor, which defaults to ``2.0``;
    the previous engine polling rate is restored when the sweep exits. The
    **Settings** tab controls acceleration, move direction, and which measured
    angle, target-angle, and angular-rate outputs are published. Motion rates
    come from the sweep segments, so there is no separate fixed-velocity
    control. The **Data** tab selects values recorded during motion.

    The plugin connects the application's preferred controller through the
    shared motor engine when necessary. Completing or aborting the sweep
    restores temporary polling configuration and leaves the shared engine
    connected. It does not automatically return the motor home.

    Attributes:
        sweep_timeout_factor (float):
            Multiplier applied to the estimated sweep duration when computing
            the allowed wall-clock runtime.
        default_sweep_timeout_factor (float):
            Default timeout multiplier for motor sweeps. This plugin uses
            ``2.0``.
        sweep_rate_time_scale_seconds (float):
            Time-scale factor used to interpret sweep rates. This plugin uses
            ``1.0`` so that configured ramp rates are treated as ``deg/s``.
        sweep_generator (BaseSweepGenerator):
            Active sweep generator instance controlling the angular
            trajectory.
        acceleration (float | str):
            Acceleration or sequence expression in degrees per second squared.
        direction (MotorMoveDirection):
            Direction policy used for initial and segment target moves.
        report_outputs (list[str] | None):
            Optional motor readbacks exposed to the sequence value catalogue.
        value (float):
            Most recently sampled control value, in degrees.
        ix (int):
            Index of the most recently yielded sweep point.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Create the plugin and inspect its defaults from the console:

        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> plugin = MotorControllerSweepPlugin()
        >>> plugin.name
        'Motor Controller'
        >>> plugin.state_name
        'Control Value'
        >>> plugin.units
        'deg'
    """

    _default_sweep_timeout_factor = 2.0
    _sweep_rate_time_scale_seconds = 1.0

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
