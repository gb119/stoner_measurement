"""Time-based state-sweep plugin."""

from __future__ import annotations

import time

from stoner_measurement.plugins.state_sweep.base import StateSweepPlugin
from stoner_measurement.sweep import (
    MonitorAndFilterSweepGenerator,
    MultiSegmentRampSweepGenerator,
)


class SweepTimePlugin(StateSweepPlugin):
    """Use elapsed time itself as the swept variable.

    Use this plugin when you want a measurement to run as a function of time
    rather than as a function of a hardware control parameter. It is useful
    for time traces, relaxation measurements, drift monitoring, or any
    experiment where repeated data collection should follow a time-based sweep
    generator.

    In the configuration tabs, choose a sweep generator that defines the time
    points or time profile. The plugin simply reports elapsed time in seconds;
    it does not control any external hardware.

    The sweep-generator tab is therefore the main configuration surface for
    this plugin. It defines the time points, sample intervals, or multi-segment
    timing profile to follow. The Help/About tab uses this docstring to explain
    that the plugin measures elapsed time rather than commanding an instrument.

    For script-oriented use, the internal state is the elapsed time measured
    from a monotonic clock, with :meth:`set_state` adjusting the effective
    start time accordingly.

    Attributes:
        _start_time (float):
            Monotonic-clock reference time used to convert between elapsed time
            and the plugin's reported state.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> plugin = SweepTimePlugin()
        >>> plugin.units
        's'
    """

    _sweep_generator_class = MonitorAndFilterSweepGenerator
    _sweep_generator_classes = [
        MonitorAndFilterSweepGenerator,
        MultiSegmentRampSweepGenerator,
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._start_time = time.monotonic()

    @property
    def name(self) -> str:
        return "Sweep Time"

    @property
    def state_name(self) -> str:
        return "Time"

    @property
    def units(self) -> str:
        return "s"

    def set_state(self, value: float) -> None:
        self._start_time = time.monotonic() - float(value)

    def get_state(self) -> float:
        return float(time.monotonic() - self._start_time)
