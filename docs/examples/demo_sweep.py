"""A minimal state sweep over a simulated voltage ramp."""

from math import isfinite
from time import monotonic

from stoner_measurement.plugins.state_sweep import StateSweepPlugin
from stoner_measurement.sweep import MultiSegmentRampSweepGenerator


class DemoSweepPlugin(StateSweepPlugin):
    """Run children as a simulated voltage ramps towards its target."""

    _sweep_generator_class = MultiSegmentRampSweepGenerator
    _sweep_generator_classes = [MultiSegmentRampSweepGenerator]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sweep_generator.segments = [(1.0, 5.0, True)]
        self._rate = 5.0
        self.set_state(0.0)

    @property
    def name(self):
        return "Demo Sweep"

    @property
    def state_name(self):
        return "Voltage"

    @property
    def units(self):
        return "V"

    def set_state(self, value):
        """Set the initial voltage immediately."""
        self._start = self._target = float(value)
        self._started = monotonic()
        self._duration = 0.0

    def set_rate(self, value):
        """Set the speed of the next ramp in volts per second."""
        if not isfinite(value) or value <= 0:
            raise ValueError("The ramp rate must be finite and positive.")
        self._rate = value

    def set_target(self, value):
        """Start a ramp from the current voltage to the target."""
        self._start = self.get_state()
        self._target = float(value)
        self._duration = abs(self._target - self._start) / self._rate
        self._started = monotonic()

    def get_state(self):
        """Sample the current voltage from the simulated ramp."""
        elapsed = monotonic() - self._started
        if elapsed >= self._duration:
            return self._target
        fraction = elapsed / self._duration
        return self._start + (self._target - self._start) * fraction

    def is_at_target(self):
        """Report whether the simulated ramp has finished."""
        return monotonic() - self._started >= self._duration
