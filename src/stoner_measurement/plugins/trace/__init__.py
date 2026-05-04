"""Trace sub-package — plugins that collect (x, y) data traces from instruments.

Exports :class:`TracePlugin` (abstract base), :class:`TraceData`, and
:class:`TraceStatus` from :mod:`stoner_measurement.plugins.trace.base`,
:class:`DummyPlugin` from :mod:`stoner_measurement.plugins.trace.dummy`, and
:class:`Keithley6221_2182APlugin` together with :class:`ConnectionMode`,
:class:`ComplianceMode`, and :class:`SourceRangeMode` from
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
    ComplianceMode,
    ConnectionMode,
    Keithley6221_2182APlugin,
    SourceRangeMode,
)

__all__ = [
    "ComplianceMode",
    "ConnectionMode",
    "DummyPlugin",
    "Keithley6221_2182APlugin",
    "SourceRangeMode",
    "TraceData",
    "TracePlugin",
    "TraceStatus",
    "_ScanPage",
    "_ScanTabContainer",
]
