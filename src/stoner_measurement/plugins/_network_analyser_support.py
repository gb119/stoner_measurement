"""Shared definitions for direct network-analyser plugins."""

from __future__ import annotations

import enum
from collections.abc import Callable

import numpy as np

from stoner_measurement.instruments import (
    AgilentE5062A,
    AgilentN5222A,
    NetworkAnalyser,
    TraceFormat,
)


class NetworkAnalyserModel(enum.Enum):
    """Concrete analyser drivers available to application plugins."""

    E5062A = "e5062a"
    N5222A = "n5222a"


class NetworkAnalyserSweepVariable(enum.Enum):
    """Independent variable sourced by an analyser plugin."""

    FREQUENCY = "frequency"
    POWER = "power"


NETWORK_ANALYSER_DRIVERS: dict[NetworkAnalyserModel, Callable[..., NetworkAnalyser]] = {
    NetworkAnalyserModel.E5062A: AgilentE5062A,
    NetworkAnalyserModel.N5222A: AgilentN5222A,
}
NETWORK_ANALYSER_DRIVER_LABELS = {
    NetworkAnalyserModel.E5062A: "Agilent E5062A ENA",
    NetworkAnalyserModel.N5222A: "Agilent N5222A PNA",
}
S_PARAMETERS = ("S11", "S12", "S21", "S22")
OUTPUT_FORMATS = {
    TraceFormat.LOG_MAGNITUDE: "Log magnitude (dB)",
    TraceFormat.LINEAR_MAGNITUDE: "Linear magnitude",
    TraceFormat.PHASE: "Phase (degrees)",
    TraceFormat.REAL: "Real part",
    TraceFormat.IMAGINARY: "Imaginary part",
}


def format_s_parameter_values(values: np.ndarray, output_format: TraceFormat) -> np.ndarray:
    """Convert complex S-parameters to a scalar application representation."""
    complex_values = np.asarray(values, dtype=np.complex128)
    if output_format is TraceFormat.LOG_MAGNITUDE:
        with np.errstate(divide="ignore"):
            return 20.0 * np.log10(np.abs(complex_values))
    if output_format is TraceFormat.LINEAR_MAGNITUDE:
        return np.abs(complex_values)
    if output_format is TraceFormat.PHASE:
        return np.angle(complex_values, deg=True)
    if output_format is TraceFormat.REAL:
        return complex_values.real
    if output_format is TraceFormat.IMAGINARY:
        return complex_values.imag
    raise ValueError(f"Unsupported S-parameter output format: {output_format!r}")


def s_parameter_units(output_format: TraceFormat) -> str:
    """Return units for a scalar S-parameter representation."""
    if output_format is TraceFormat.LOG_MAGNITUDE:
        return "dB"
    if output_format is TraceFormat.PHASE:
        return "°"
    return ""
