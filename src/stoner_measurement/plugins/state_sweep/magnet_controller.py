"""Magnet-controller-backed state-sweep plugin."""

from __future__ import annotations

from stoner_measurement.plugins.state._magnet_controller_plugin import (
    MagnetControllerPluginMixin,
)
from stoner_measurement.plugins.state_sweep.base import StateSweepPlugin


class MagnetControllerSweepPlugin(MagnetControllerPluginMixin, StateSweepPlugin):
    """Sweep the magnetic field continuously while collecting data in motion.

    Use this plugin when you want the magnet field to ramp continuously and
    your measurement sub-sequence to run repeatedly while the field is
    changing. This is useful for field sweeps where the exact timing within
    the ramp matters, or where stopping to stabilise at many discrete points
    would be too slow.

    In the configuration tabs, the **Settings** tab contains the inherited
    magnet-controller options such as tolerance, stability handling, and
    timeout factor. The sweep-generator area lets you choose how the field
    evolves, for example using a multi-segment ramp with different targets,
    rates, and measurement flags. The **Data Collection** section controls
    which values are recorded from the plugin during the sweep. The
    **Help/About** tab uses this docstring as end-user guidance.

    Rates for multi-segment ramp sweeps are interpreted in ``T/min`` and the
    default timeout factor for this plugin is ``2.0``. Together, those define
    the default wall-clock timeout used for estimated sweep durations.

    Attributes:
        wait_for_stable (bool):
            Inherited controller setting controlling whether stability criteria
            are enforced in addition to target tracking.
        tolerance (float):
            Allowed field error, in tesla, used by the inherited controller
            logic.
        sweep_timeout_factor (float):
            Multiplier applied to the estimated sweep duration when computing
            the allowed wall-clock runtime.
        default_sweep_timeout_factor (float):
            Default timeout multiplier for magnet sweeps. This plugin uses
            ``2.0``.
        sweep_rate_time_scale_seconds (float):
            Time-scale factor used to interpret sweep rates. This plugin uses
            ``60.0`` so that configured ramp rates are treated as ``T/min``.
        sweep_generator (BaseSweepGenerator):
            Active sweep generator instance controlling the field trajectory.
        value (float):
            Most recently sampled control value, in tesla.
        ix (int):
            Index of the most recently yielded sweep point.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Create the plugin and inspect its user-facing metadata:

        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> plugin = MagnetControllerSweepPlugin()
        >>> plugin.name
        'Magnet Controller'
        >>> plugin.state_name
        'Control Value'
        >>> plugin.units
        'T'
        >>> plugin.sweep_rate_time_scale_seconds
        60.0
        >>> plugin.default_sweep_timeout_factor
        2.0
    """

    _default_sweep_timeout_factor = 2.0
    _sweep_rate_time_scale_seconds = 60.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_magnet_controller_plugin()

    @property
    def name(self) -> str:
        return "Magnet Controller"

    @property
    def state_name(self) -> str:
        return "Control Value"

    @property
    def units(self) -> str:
        return "T"

    def __next__(self) -> bool:
        """Advance the sweep using the configured sweep generator semantics."""
        return super().__next__()

    def to_json(self) -> dict[str, object]:
        data = super().to_json()
        data.update(self._magnet_settings_to_json())
        return data

    def _restore_from_json(self, data: dict[str, object]) -> None:
        super()._restore_from_json(data)
        self._restore_magnet_settings(data)