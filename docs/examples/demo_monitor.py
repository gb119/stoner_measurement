"""A minimal monitor returning one scalar reading."""

from stoner_measurement.plugins.monitor import MonitorPlugin


class DemoMonitorPlugin(MonitorPlugin):
    """Read one simulated temperature and publish it in kelvin."""

    @property
    def name(self):
        return "Demo Monitor"

    @property
    def has_lifecycle(self):
        return False

    @property
    def quantity_names(self):
        return ["Temperature"]

    @property
    def units(self):
        return {"Temperature": "K"}

    def read(self):
        """Return a simulated reading using the declared quantity name."""
        return {"Temperature": 293.15}
