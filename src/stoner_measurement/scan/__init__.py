"""Scan generator sub-package.

Provides :class:`BaseScanGenerator` and the concrete
:class:`FunctionScanGenerator` implementation together with its Qt
configuration widget :class:`FunctionScanWidget`.
"""

from stoner_measurement.scan.base import BaseScanGenerator
from stoner_measurement.scan.function_generator import (
    FunctionScanGenerator,
    FunctionScanWidget,
    WaveformType,
)

__all__ = [
    "BaseScanGenerator",
    "FunctionScanGenerator",
    "FunctionScanWidget",
    "WaveformType",
]
