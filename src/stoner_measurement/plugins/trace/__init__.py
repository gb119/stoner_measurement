"""Trace sub-package — plugins that collect (x, y) data traces from instruments.

Exports :class:`TracePlugin` (abstract base), :class:`TraceData`, and
:class:`TraceStatus` from :mod:`stoner_measurement.plugins.trace.base`, and
:class:`DummyPlugin` from :mod:`stoner_measurement.plugins.trace.dummy`.

The private helper classes :class:`_ScanTabContainer` and :class:`_ScanPage`
are also re-exported for internal use and testing.
"""

from stoner_measurement.plugins.trace.base import (
    TraceData,
    TracePlugin,
    TraceStatus,
    _ScanPage,
    _ScanTabContainer,
)
from stoner_measurement.plugins.trace.dummy import DummyPlugin

__all__ = [
    "DummyPlugin",
    "TraceData",
    "TracePlugin",
    "TraceStatus",
    "_ScanPage",
    "_ScanTabContainer",
]
