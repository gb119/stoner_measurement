"""A minimal trace plugin with a configured column schema."""

import numpy as np

from stoner_measurement.core.trace_data import TraceData
from stoner_measurement.plugins.trace import TracePlugin


class DemoTracePlugin(TracePlugin):
    """Return three simulated voltage samples at times 0, 1 and 2 s."""

    @property
    def name(self):
        return "Demo Trace"

    @staticmethod
    def _trace(time, voltage):
        return TraceData.from_xy(
            time,
            voltage,
            names={"x": "Time", "y": "Voltage"},
            units={"x": "s", "y": "V"},
        )

    def _measure(self, parameters):
        voltage = np.array([1.0, 2.0, 3.0])
        return {self.name: self._trace(np.arange(3), voltage)}

    def declared_outputs(self):
        """Advertise the same columns before the first acquisition."""
        return self._declare_column_trace_outputs(self.name, self._schema)

    def _schema(self):
        return self._trace(np.empty(0), np.empty(0))
