"""State-control sub-package — plugins that command hardware to move to set-points.

Exports :class:`StateControlPlugin` (abstract base) from
:mod:`stoner_measurement.plugins.state_control.base` and
:class:`CounterPlugin` (built-in example implementation) from
:mod:`stoner_measurement.plugins.state_control.counter`.
"""

from stoner_measurement.plugins.state_control.base import StateControlPlugin
from stoner_measurement.plugins.state_control.counter import CounterPlugin

__all__ = [
    "CounterPlugin",
    "StateControlPlugin",
]
