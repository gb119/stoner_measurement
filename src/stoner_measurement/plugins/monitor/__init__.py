"""Monitor sub-package — plugins that passively record experimental state.

Exports :class:`MonitorPlugin` (abstract base) from
:mod:`stoner_measurement.plugins.monitor.base`.
"""

from stoner_measurement.plugins.monitor.base import MonitorPlugin

__all__ = [
    "MonitorPlugin",
]
