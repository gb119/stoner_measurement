"""A minimal state scan over an in-memory setpoint."""

from stoner_measurement.plugins.state_scan import StateScanPlugin


class DemoScanPlugin(StateScanPlugin):
    """Set a simulated voltage before running the children at each point."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._voltage = 0.0

    @property
    def name(self):
        return "Demo Scan"

    @property
    def state_name(self):
        return "Voltage"

    @property
    def units(self):
        return "V"

    def set_state(self, value):
        """Apply the requested setpoint immediately."""
        self._voltage = float(value)

    def get_state(self):
        """Return the current simulated voltage."""
        return self._voltage

    def is_at_target(self):
        """Report that the immediate state change has settled."""
        return True
