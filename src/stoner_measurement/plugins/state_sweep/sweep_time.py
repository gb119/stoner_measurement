"""Time-based state-sweep plugin."""

from __future__ import annotations

import time

from stoner_measurement.plugins.state_sweep.base import StateSweepPlugin
from stoner_measurement.sweep import (
    MonitorAndFilterSweepGenerator,
    MultiSegmentRampSweepGenerator,
)


class SweepTimePlugin(StateSweepPlugin):
    """State-sweep plugin that sweeps elapsed time."""

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
