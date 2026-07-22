"""Axis-coordinate mappings used by :mod:`stoner_measurement.ui.plot_widget`."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pyqtgraph as pg

AxisScale = Literal["linear", "log", "symlog", "logit", "asinh"]
AXIS_SCALES: tuple[AxisScale, ...] = ("linear", "log", "symlog", "logit", "asinh")


def validate_scale(scale: str, parameter: float = 1.0) -> tuple[AxisScale, float]:
    """Validate and normalise an axis scale configuration."""
    if scale not in AXIS_SCALES:
        raise ValueError(f"Unknown axis scale: {scale!r}")
    value = float(parameter)
    if scale in {"symlog", "asinh"} and value <= 0.0:
        raise ValueError(f"{scale} scale parameter must be positive")
    return scale, value  # type: ignore[return-value]


def transform_values(values, scale: AxisScale, parameter: float = 1.0) -> np.ndarray:
    """Map raw values into the linear coordinates used by a ViewBox."""
    data = np.asarray(values, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        if scale == "linear":
            mapped = data.copy()
        elif scale == "log":
            mapped = np.where(data > 0.0, np.log10(data), np.nan)
        elif scale == "symlog":
            magnitude = np.abs(data)
            mapped = np.where(
                magnitude <= parameter,
                data / parameter,
                np.sign(data) * (1.0 + np.log10(magnitude / parameter)),
            )
        elif scale == "logit":
            mapped = np.where(
                (data > 0.0) & (data < 1.0),
                np.log10(data / (1.0 - data)),
                np.nan,
            )
        else:
            mapped = np.arcsinh(data / parameter)
    return np.asarray(mapped, dtype=float)


def inverse_values(values, scale: AxisScale, parameter: float = 1.0) -> np.ndarray:
    """Map ViewBox coordinates back to raw values."""
    data = np.asarray(values, dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        if scale == "linear":
            raw = data.copy()
        elif scale == "log":
            raw = np.power(10.0, data)
        elif scale == "symlog":
            magnitude = np.abs(data)
            raw = np.where(
                magnitude <= 1.0,
                data * parameter,
                np.sign(data) * parameter * np.power(10.0, magnitude - 1.0),
            )
        elif scale == "logit":
            raw = 1.0 / (1.0 + np.power(10.0, -data))
        else:
            raw = parameter * np.sinh(data)
    return np.asarray(raw, dtype=float)


class MappedAxisItem(pg.AxisItem):
    """Axis item that labels linear ViewBox coordinates in raw mapped units."""

    def __init__(self, orientation: str, **kwargs) -> None:
        super().__init__(orientation, **kwargs)
        self._scale: AxisScale = "linear"
        self._scale_parameter = 1.0

    def set_scale_mapping(self, scale: AxisScale, parameter: float = 1.0) -> None:
        """Select the coordinate mapping used to format this axis."""
        self._scale, self._scale_parameter = validate_scale(scale, parameter)
        self.setLogMode(self._scale == "log")
        self.picture = None
        self.update()

    def tickStrings(self, values, scale, spacing):  # noqa: N802
        """Format transformed tick positions as raw values."""
        if self._scale in {"linear", "log"}:
            return super().tickStrings(values, scale, spacing)
        raw_values = inverse_values(values, self._scale, self._scale_parameter)
        return [_format_tick(value) for value in raw_values]


def _format_tick(value: float) -> str:
    """Return a compact, stable mapped-axis tick label."""
    if not np.isfinite(value):
        return ""
    if value == 0.0:
        return "0"
    magnitude = abs(value)
    if magnitude < 1.0e-3 or magnitude >= 1.0e4:
        return f"{value:.3e}"
    return f"{value:.6g}"
