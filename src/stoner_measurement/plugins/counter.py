"""Backward-compatibility shim for ``stoner_measurement.plugins.counter``.

:class:`CounterPlugin` has been moved to
:mod:`stoner_measurement.plugins.state_control.counter`.  This module
re-exports it so that existing code that imports from
``stoner_measurement.plugins.counter`` continues to work.

New code should import directly from
:mod:`stoner_measurement.plugins.state_control`::

    from stoner_measurement.plugins.state_control import CounterPlugin
"""

from stoner_measurement.plugins.state_control.counter import CounterPlugin

__all__ = [
    "CounterPlugin",
]
