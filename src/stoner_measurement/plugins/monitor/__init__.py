"""Monitor sub-package — plugins that passively record experimental state.

Exports :class:`MonitorPlugin` (abstract base) from
:mod:`stoner_measurement.plugins.monitor.base` and concrete monitor plugins.
"""

from stoner_measurement.plugins.monitor.base import MonitorPlugin
from stoner_measurement.plugins.monitor.magnet_controller import (
    MagneticFieldMonitorPlugin,
)
from stoner_measurement.plugins.monitor.motor_controller import (
    MotorAngleMonitorPlugin,
)
from stoner_measurement.plugins.monitor.pressure_controller import (
    PressureMonitorPlugin,
)
from stoner_measurement.plugins.monitor.temperature_controller import (
    TemperatureMonitorPlugin,
)

__all__ = [
    "MonitorPlugin",
    "MagneticFieldMonitorPlugin",
    "MotorAngleMonitorPlugin",
    "PressureMonitorPlugin",
    "TemperatureMonitorPlugin",
]
