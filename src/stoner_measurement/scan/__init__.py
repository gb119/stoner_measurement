"""Scan generator sub-package.

Provides :class:`BaseScanGenerator` and concrete implementations:
:class:`ArbitraryFunctionScanGenerator` with its Qt configuration widget
:class:`ArbitraryFunctionScanWidget`,
:class:`FunctionScanGenerator` with its Qt configuration widget
:class:`FunctionScanWidget`, :class:`SteppedScanGenerator` with its Qt
configuration widget :class:`SteppedScanWidget`, and
:class:`RampScanGenerator` with its Qt configuration widget
:class:`RampScanWidget`, and
:class:`ListScanGenerator` with its Qt configuration widget
:class:`ListScanWidget`.
"""

from stoner_measurement.scan.arbitrary_function_generator import (
    ArbitraryFunctionScanGenerator,
    ArbitraryFunctionScanWidget,
)
from stoner_measurement.scan.base import BaseScanGenerator
from stoner_measurement.scan.function_generator import (
    FunctionScanGenerator,
    FunctionScanWidget,
    WaveformType,
)
from stoner_measurement.scan.list_generator import ListScanGenerator, ListScanWidget
from stoner_measurement.scan.ramp_generator import (
    RampMode,
    RampScanGenerator,
    RampScanWidget,
)
from stoner_measurement.scan.stepped_generator import (
    SteppedScanGenerator,
    SteppedScanWidget,
)

__all__ = [
    "ArbitraryFunctionScanGenerator",
    "ArbitraryFunctionScanWidget",
    "BaseScanGenerator",
    "FunctionScanGenerator",
    "FunctionScanWidget",
    "ListScanGenerator",
    "ListScanWidget",
    "RampMode",
    "RampScanGenerator",
    "RampScanWidget",
    "SteppedScanGenerator",
    "SteppedScanWidget",
    "WaveformType",
]
