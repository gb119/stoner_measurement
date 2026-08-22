"""Axis-coordinate mappings used by :mod:`stoner_measurement.ui.plot_widget`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pyqtgraph as pg

AxisScale = Literal["linear", "log", "symlog", "logit", "asinh"]
AXIS_SCALES: tuple[AxisScale, ...] = ("linear", "log", "symlog", "logit", "asinh")
_LEGACY_UNIT_LABEL = re.compile(r"^(?P<label>.*?)\s*\((?P<unit>[^()]*)\)\s*$")


@dataclass(frozen=True)
class AxisLabel:
    """A plot-axis quantity label and its physical unit.

    Keeping the two fields separate lets PyQtGraph apply an SI prefix to the
    unit (for example ``mA``) without altering the underlying trace values.
    """

    label: str
    unit: str = ""

    @classmethod
    def coerce(cls, value: AxisLabel | str, unit: str = "") -> AxisLabel:
        """Return structured metadata, accepting legacy ``"Name (unit)"`` text."""
        if isinstance(value, cls):
            return value
        text = str(value).strip()
        if unit:
            return cls(text, str(unit).strip())
        match = _LEGACY_UNIT_LABEL.fullmatch(text)
        if match is None:
            return cls(text)
        return cls(match.group("label").strip(), match.group("unit").strip())

    def __str__(self) -> str:
        """Return the conventional unscaled user-facing representation."""
        return f"{self.label} ({self.unit})" if self.unit else self.label


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

    @property
    def axis_label(self) -> AxisLabel:
        """Return the axis quantity and base unit as structured metadata."""
        return AxisLabel(self.labelText, self.labelUnits)

    def set_axis_label(self, label: AxisLabel | str, unit: str = "") -> None:
        """Set structured axis metadata and enable automatic SI unit prefixes."""
        metadata = AxisLabel.coerce(label, unit)
        self.setLabel(
            metadata.label,
            units=metadata.unit,
            siPrefixEnableRanges=((0.0, float("inf")),),
        )
        self.enableAutoSIPrefix(True)

    def labelString(self) -> str:  # noqa: N802
        """Put SI prefixes on units, never show PyQtGraph's ``x...`` factor."""
        if (
            self.labelUnits
            or self.autoSIPrefixScale == 1.0
            or getattr(self, "_scale", "linear") != "linear"
        ):
            return super().labelString()
        scale = self.autoSIPrefixScale
        try:
            self.autoSIPrefixScale = 1.0
            return super().labelString()
        finally:
            self.autoSIPrefixScale = scale

    def set_scale_mapping(self, scale: AxisScale, parameter: float = 1.0) -> None:
        """Select the coordinate mapping used to format this axis."""
        self._scale, self._scale_parameter = validate_scale(scale, parameter)
        self.setLogMode(self._scale == "log")
        self.picture = None
        self.update()

    def tickStrings(self, values, scale, spacing):  # noqa: N802
        """Format transformed tick positions as raw values."""
        if self._scale in {"linear", "log"}:
            strings = super().tickStrings(values, scale, spacing)
            if (
                self._scale == "linear"
                and not self.labelUnits
                and self.labelUnitPrefix
                and self.autoSIPrefixScale != 1.0
            ):
                return [
                    text if float(value) == 0.0 else f"{text}{self.labelUnitPrefix}"
                    for text, value in zip(strings, values, strict=True)
                ]
            return strings
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
