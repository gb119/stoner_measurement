"""Trace sub-package — plugins that collect (x, y) data traces from instruments.

Exports :class:`TracePlugin` (abstract base), :class:`TraceStatus`,
:class:`DummyPlugin` from :mod:`stoner_measurement.plugins.trace.dummy`, and
:class:`Keithley6221_2182APlugin` together with :class:`ConnectionMode`,
:class:`ComplianceMode`, and :class:`SourceRangeMode` from
:mod:`stoner_measurement.plugins.trace.k6221_2182a`.

The private helper classes :class:`_ScanTabContainer` and :class:`_ScanPage`
are also re-exported for internal use and testing.
"""

from stoner_measurement.plugins.trace.base import (
    TracePlugin,
    TraceStatus,
    _ScanPage,
    _ScanTabContainer,
)
from stoner_measurement.plugins.trace.dummy import DummyPlugin
from stoner_measurement.plugins.trace.k6221_2182a import (
    ComplianceMode,
    ConnectionMode,
    DigitalFilterType,
    Keithley6221_2182APlugin,
    SecondaryTriggerMode,
    SourceRangeMode,
)
from stoner_measurement.plugins.trace.k6221_multi_sr830 import (
    Keithley6221_MultiSR830Plugin,
    LockInOutput,
    WaveformScanMode,
)
from stoner_measurement.plugins.trace.keithley_2400 import (
    ConnectionMode as K2400ConnectionMode,
)
from stoner_measurement.plugins.trace.keithley_2400 import (
    Keithley2400SweepPlugin,
    SweepSourceMode,
    TriggerRouting,
)
from stoner_measurement.plugins.trace.keithley_2400 import (
    RangeMode as K2400RangeMode,
)
from stoner_measurement.plugins.trace.keithley_2400 import (
    TerminalMode as K2400TerminalMode,
)

__all__ = [
    "ComplianceMode",
    "ConnectionMode",
    "DigitalFilterType",
    "DummyPlugin",
    "K2400ConnectionMode",
    "K2400RangeMode",
    "K2400TerminalMode",
    "Keithley2400SweepPlugin",
    "Keithley6221_2182APlugin",
    "Keithley6221_MultiSR830Plugin",
    "SweepSourceMode",
    "TriggerRouting",
    "LockInOutput",
    "SecondaryTriggerMode",
    "SourceRangeMode",
    "TracePlugin",
    "TraceStatus",
    "WaveformScanMode",
    "_ScanPage",
    "_ScanTabContainer",
]
