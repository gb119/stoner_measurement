"""State-control sub-package — backward-compatibility shim.

``state_control`` is kept as a compatibility alias for ``state_scan``.
New code should import from :mod:`stoner_measurement.plugins.state_scan`
directly.

Exports :class:`StateScanPlugin` under the legacy name
:class:`StateControlPlugin`, and :class:`CounterPlugin`.
"""

from stoner_measurement.plugins.state_scan.base import StateScanPlugin as StateControlPlugin
from stoner_measurement.plugins.state_scan.counter import CounterPlugin

__all__ = [
    "CounterPlugin",
    "StateControlPlugin",
]
