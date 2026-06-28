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

    In the configuration tabs, the **Settings** tab contains the inherited
    motor-controller options such as tolerance and timeout factor. The
    sweep-generator area lets you define the motion profile, for example with
    a multi-segment ramp containing several angle targets and rates. The
    **Data Collection** section controls which values are recorded during the
    sweep. The **Help/About** tab uses this docstring as end-user guidance.

    Rates for multi-segment ramp sweeps are interpreted in ``deg/s`` and the
    default timeout factor for this plugin is ``2.0``.

    Attributes:
        tolerance (float):
            Allowed angular error, in degrees, used by the inherited
            controller logic.
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