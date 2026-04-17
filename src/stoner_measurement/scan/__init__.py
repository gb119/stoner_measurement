"""Scan generator sub-package.

Provides :class:`BaseScanGenerator` and the following concrete implementations
together with their Qt configuration widgets:

* :class:`ArbitraryFunctionScanGenerator` / :class:`ArbitraryFunctionScanWidget`
* :class:`FunctionScanGenerator` / :class:`FunctionScanWidget`
* :class:`ListScanGenerator` / :class:`ListScanWidget`
* :class:`RampScanGenerator` / :class:`RampScanWidget`
* :class:`SteppedScanGenerator` / :class:`SteppedScanWidget`
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
