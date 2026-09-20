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

    The **Data** tab enables collection, selects sequence outputs and their
    column roles, and controls when accumulated data is cleared or appended.

    Attributes:
        _start_time (float):
            Monotonic-clock reference time used to convert between elapsed time
            and the plugin's reported state.
        instance_name (str):
            Inherited Python identifier for this instance in the Script tab and
            QtConsole.
        comment (str):
            Inherited optional note displayed beside this step.
        sequence_engine (SequenceEngine | None):
            Inherited owning engine and its live namespace; None while
            detached.
        sweep_generator (BaseSweepGenerator):
            Inherited generator defining successive sequence points.
        value (float):
            Inherited current sequence control value.
        ix (int):
            Inherited zero-based iteration index.
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
        With an instance named ``sweep_time`` in the sequence, use the
        QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            sweep_time.collect_data = True
            sweep_time.value
            sweep_time.data.df.head()
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
