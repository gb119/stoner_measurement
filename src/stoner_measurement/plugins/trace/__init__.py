"""Trace sub-package — plugins that collect (x, y) data traces from instruments.

Exports :class:`TracePlugin` (abstract base), :class:`TraceData`,
:class:`TraceStatus`, and the ``COLUMN_ROLE_*`` role constants from
:mod:`stoner_measurement.plugins.trace.base`,
:class:`DummyPlugin` from :mod:`stoner_measurement.plugins.trace.dummy`, and
:class:`Keithley6221_2182APlugin` together with :class:`ConnectionMode`,
:class:`ComplianceMode`, and :class:`SourceRangeMode` from
:mod:`stoner_measurement.plugins.trace.k6221_2182a`.

The private helper classes :class:`_ScanTabContainer` and :class:`_ScanPage`
are also re-exported for internal use and testing.
"""

from stoner_measurement.plugins.trace.base import (
    COLUMN_ROLE_D,
    COLUMN_ROLE_E,
    COLUMN_ROLE_F,
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
    TracePlugin,
    TraceStatus,
    _ScanPage,
    _ScanTabContainer,
)
from stoner_measurement.plugins.trace.dataframe_trace import DataFrameTracePlugin
from stoner_measurement.plugins.trace.dummy import DummyPlugin
from stoner_measurement.plugins.trace.k6221_2182a import (
    ComplianceMode,
    ConnectionMode,
    Keithley6221_2182APlugin,
    SourceRangeMode,
)
from stoner_measurement.plugins.trace.k6221_multi_sr830 import (
    Keithley6221_MultiSR830Plugin,
    LockInOutput,
    ResistanceCurrentMode,
    WaveformScanMode,
)

__all__ = [
    "COLUMN_ROLE_D",
    "COLUMN_ROLE_E",
    "COLUMN_ROLE_F",
    "COLUMN_ROLE_Y",
    "COLUMN_ROLE_Z",
    "ComplianceMode",
    "ConnectionMode",
    "DataFrameTracePlugin",
    "DummyPlugin",
    "Keithley6221_2182APlugin",
    "Keithley6221_MultiSR830Plugin",
    "LockInOutput",
    "SourceRangeMode",
    "ResistanceCurrentMode",
    "TraceData",
    "TracePlugin",
    "TraceStatus",
    "WaveformScanMode",
    "_ScanPage",
    "_ScanTabContainer",
]
