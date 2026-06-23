"""State-scan sub-package — plugins that command hardware to move to set-points.

Exports :class:`StateScanPlugin` (abstract base) and :class:`CounterPlugin`
(built-in example implementation).
"""

from stoner_measurement.plugins.state_scan.base import StateScanPlugin
from stoner_measurement.plugins.state_scan.counter import CounterPlugin
from stoner_measurement.plugins.state_scan.keithley_2400 import (
    Keithley2400PointScanPlugin,
)
from stoner_measurement.plugins.state_scan.magnet_controller import (
    MagnetControllerScanPlugin,
)
from stoner_measurement.plugins.state_scan.temperature_controller import (
    TemperatureControllerScanPlugin,
)

__all__ = [
    "CounterPlugin",
    "Keithley2400PointScanPlugin",
    "MagnetControllerScanPlugin",
    "StateScanPlugin",
    "TemperatureControllerScanPlugin",
]
