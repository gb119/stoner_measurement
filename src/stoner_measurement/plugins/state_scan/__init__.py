"""State-scan sub-package — plugins that command hardware to move to set-points.

Exports :class:`StateScanPlugin` (abstract base) and :class:`CounterPlugin`
(built-in example implementation).
"""

from stoner_measurement.plugins.state_scan.base import StateScanPlugin
from stoner_measurement.plugins.state_scan.counter import CounterPlugin

__all__ = [
    "CounterPlugin",
    "StateScanPlugin",
]
