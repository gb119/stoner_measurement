"""Backward-compatibility shim for ``stoner_measurement.plugins.dummy``.

:class:`DummyPlugin` has been moved to
:mod:`stoner_measurement.plugins.trace.dummy`.  This module re-exports it so
that existing code that imports from ``stoner_measurement.plugins.dummy``
continues to work.

New code should import directly from :mod:`stoner_measurement.plugins.trace`::

    from stoner_measurement.plugins.trace import DummyPlugin
"""

from stoner_measurement.plugins.trace.dummy import DummyPlugin

__all__ = [
    "DummyPlugin",
]
