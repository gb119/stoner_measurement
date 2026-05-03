"""Trace sub-package — plugins that collect (x, y) data traces from instruments.

Exports :class:`TracePlugin` (abstract base), :class:`TraceData`, and
:class:`TraceStatus` from :mod:`stoner_measurement.plugins.trace.base`,
:class:`DummyPlugin` from :mod:`stoner_measurement.plugins.trace.dummy`, and
:class:`Keithley6221_2182APlugin` together with :class:`ConnectionMode` from
:mod:`stoner_measurement.plugins.trace.k6221_2182a`.

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
from stoner_measurement.plugins.trace.k6221_2182a import (
    ConnectionMode,
    Keithley6221_2182APlugin,
)

__all__ = [
    "ConnectionMode",
    "DummyPlugin",
    "Keithley6221_2182APlugin",
    "TraceData",
    "TracePlugin",
    "TraceStatus",
    "_ScanPage",
    "_ScanTabContainer",
]
