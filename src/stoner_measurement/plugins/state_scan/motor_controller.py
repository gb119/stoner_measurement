"""Motor-controller-backed state-scan plugin."""

from __future__ import annotations

from stoner_measurement.plugins.state._motor_controller_plugin import (
    MotorControllerPluginMixin,
)
from stoner_measurement.plugins.state_scan.base import StateScanPlugin


class MotorControllerScanPlugin(MotorControllerPluginMixin, StateScanPlugin):
    """Move a motor through discrete absolute angles and run nested steps.

    Use this state-scan plugin when the motor must reach and settle at each
    angular set-point before the measurement sequence continues. It is suited
    to step-and-measure rotation experiments where data taken while the stage
    is moving would be invalid. Use
    :class:`~stoner_measurement.plugins.state_sweep.motor_controller.MotorControllerSweepPlugin`
    instead for measurements made continuously during motion, or
    :class:`~stoner_measurement.plugins.command.set_position.SetPositionCommand`
    for a single move without a scan loop.

    The **Scan** tab defines absolute target angles in degrees using the normal
    state-scan generators. It can start from the currently measured angle, and
    nested sequence steps run once the shared motor-controller engine reports
    that each target has been reached. The plugin polls the engine while
    settling and raises a state error if a point does not settle within the
    state-scan timeout.

    The **Settings** tab controls velocity in degrees per second, acceleration
    in degrees per second squared, and whether each absolute move follows the
    clockwise, counter-clockwise, or shortest route. Velocity and acceleration
    accept sequence expressions and are evaluated during configuration and
    again when a move is requested. **Reported outputs** selects measured
    **Angle**, **Target Angle**, and **Angular Rate** values for the sequence
    catalogue. The **Data** tab can collect these values together with outputs
    from nested measurement plugins.

    The plugin uses the application's preferred motor controller and connects
    it through the shared :class:`~stoner_measurement.motor_control.engine.MotorControllerEngine`
    when necessary. Finishing the scan leaves that shared engine connected;
    it does not home the motor or issue an additional move on disconnect.

    Attributes:
        scan_generator (BaseScanGenerator):
            Generator supplying absolute target angles in degrees.
        velocity (float | str):
            Move velocity or sequence expression in degrees per second.
        acceleration (float | str):
            Move acceleration or sequence expression in degrees per second
            squared.
        direction (MotorMoveDirection):
            Direction policy used for each absolute move.
        report_outputs (list[str] | None):
            Optional selection of motor readbacks exposed to the sequence
            value catalogue; ``None`` selects all available readbacks.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        For a polar measurement, configure a stepped angular ramp, choose the
        shortest move direction, and place the detector or lock-in measurement
        beneath this plugin in the sequence tree. The nested measurement runs
        only after the stage reaches each requested angle.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_motor_controller_plugin()

    @property
    def name(self) -> str:
        return "Motor Controller"

    @property
    def state_name(self) -> str:
        return "Angle"

    @property
    def units(self) -> str:
        return "deg"

    def to_json(self) -> dict[str, object]:
        data = super().to_json()
        data.update(self._motor_settings_to_json())
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        super()._restore_from_json(data)
        self._restore_motor_settings(data)
