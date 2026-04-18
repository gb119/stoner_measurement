"""Ramp scan generator and its configuration widget.

:class:`RampScanGenerator` generates a monotonic ramp from a start value to an
end value over a fixed number of points using linear, exponential,
logarithmic, or power-law shaping. :class:`RampScanWidget` provides a live
preview of the resulting sequence.
"""

from __future__ import annotations

import enum
import math

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtGui
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.scan.base import BaseScanGenerator

_SPINBOX_MAX_ABS = 1e9
_MAX_NUM_POINTS = 10_000
_BASE_EPS = 1e-12


class RampMode(enum.Enum):
    """Supported shaping modes for :class:`RampScanGenerator`."""

    LINEAR = "Linear"
    EXPONENTIAL = "Exponential"
    LOGARITHMIC = "Logarithmic"
    POWER = "Power"


class RampScanGenerator(BaseScanGenerator):
    """Scan generator that ramps from :attr:`start` to :attr:`end`.

    Attributes:
        start (float):
            Start value of the ramp.
        end (float):
            End value of the ramp.
        num_points (int):
            Number of points in the sequence.
        mode (RampMode):
            Ramp shaping mode.
        base (float):
            Base parameter used by non-linear modes.
    """

    def __init__(
        self,
        *,
        start: float = 0.0,
        end: float = 1.0,
        num_points: int = 100,
        mode: RampMode = RampMode.LINEAR,
        base: float = math.e,
        parent: QObject | None = None,
    ) -> None:
        """Initialise the ramp scan generator."""
        super().__init__(parent)
        self._start = float(start)
        self._end = float(end)
        self._num_points = max(2, int(num_points))
        self._mode = RampMode(mode)
        self._base = float(base)

    @property
    def start(self) -> float:
        """Start value of the ramp."""
        return self._start

    @start.setter
    def start(self, value: float) -> None:
        self._start = float(value)
        self._invalidate_cache()

    @property
    def end(self) -> float:
        """End value of the ramp."""
        return self._end

    @end.setter
    def end(self, value: float) -> None:
        self._end = float(value)
        self._invalidate_cache()

    @property
    def num_points(self) -> int:
        """Number of points in the sequence."""
        return self._num_points

    @num_points.setter
    def num_points(self, value: int) -> None:
        self._num_points = max(2, int(value))
        self._invalidate_cache()

    @property
    def mode(self) -> RampMode:
        """Ramp shaping mode."""
        return self._mode

    @mode.setter
    def mode(self, value: RampMode) -> None:
        self._mode = RampMode(value)
        self._invalidate_cache()

    @property
    def base(self) -> float:
        """Base parameter used in non-linear ramp modes."""
        return self._base

    @base.setter
    def base(self, value: float) -> None:
        self._base = float(value)
        self._invalidate_cache()

    def _linear_values(self) -> np.ndarray:
        """Return a linear ramp from start to end."""
        return np.linspace(self._start, self._end, self._num_points, dtype=float)

    def _nonlinear_offset(self) -> float:
        """Return an offset that keeps transformed endpoints in-domain."""
        return min(self._start, self._end) - 1.0

    def generate(self) -> np.ndarray:
        """Compute the ramp sequence."""
        if self._num_points < 2 or abs(self._end - self._start) < _BASE_EPS:
            return self._linear_values()

        mode = self._mode
        base = self._base
        if mode is RampMode.LINEAR:
            return self._linear_values()

        if base <= 0.0 or (mode in (RampMode.EXPONENTIAL, RampMode.LOGARITHMIC) and abs(base - 1.0) < _BASE_EPS):
            return self._linear_values()
        if mode is RampMode.POWER and abs(base) < _BASE_EPS:
            return self._linear_values()

        offset = self._nonlinear_offset()
        start_s = self._start - offset
        end_s = self._end - offset
        if start_s <= 0.0 or end_s <= 0.0:
            return self._linear_values()

        if mode is RampMode.EXPONENTIAL:
            x_start = math.log(start_s, base)
            x_end = math.log(end_s, base)
            x_vals = np.linspace(x_start, x_end, self._num_points, dtype=float)
            return np.power(base, x_vals) + offset

        if mode is RampMode.LOGARITHMIC:
            x_start = math.pow(base, start_s)
            x_end = math.pow(base, end_s)
            x_vals = np.linspace(x_start, x_end, self._num_points, dtype=float)
            return offset + np.log(x_vals) / np.log(base)

        x_start = math.pow(start_s, 1.0 / base)
        x_end = math.pow(end_s, 1.0 / base)
        x_vals = np.linspace(x_start, x_end, self._num_points, dtype=float)
        return offset + np.power(x_vals, base)

    def measure_flags(self) -> np.ndarray:
        """Return per-point measure flags (all ``True``)."""
        return np.ones(self._num_points, dtype=bool)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a :class:`RampScanWidget` configured for this generator."""
        return RampScanWidget(generator=self, parent=parent)

    def to_json(self) -> dict:
        """Serialise this generator's configuration."""
        return {
            "type": "RampScanGenerator",
            "start": self._start,
            "end": self._end,
            "num_points": self._num_points,
            "mode": self._mode.value,
            "base": self._base,
            "units": self._units,
        }

    @classmethod
    def _from_json_data(cls, data: dict, parent=None) -> RampScanGenerator:
        """Reconstruct a :class:`RampScanGenerator` from serialised *data*."""
        mode = RampMode(data.get("mode", RampMode.LINEAR.value))
        instance = cls(
            start=float(data.get("start", 0.0)),
            end=float(data.get("end", 1.0)),
            num_points=int(data.get("num_points", 100)),
            mode=mode,
            base=float(data.get("base", math.e)),
            parent=parent,
        )
        instance.units = str(data.get("units", ""))
        return instance


class RampScanWidget(QWidget):
    """Configuration and live-preview widget for :class:`RampScanGenerator`."""

    def __init__(
        self,
        generator: RampScanGenerator,
        parent: QWidget | None = None,
    ) -> None:
        """Initialise the widget and bind it to *generator*."""
        super().__init__(parent)
        self._generator = generator
        self._build_ui()
        self._connect_signals()
        self._refresh_plot()

    def _build_ui(self) -> None:
        """Build controls and preview plot."""
        root_layout = QVBoxLayout(self)

        controls_box = QGroupBox("Parameters")
        form = QFormLayout(controls_box)

        self._start_spin = pg.SpinBox()
        self._start_spin.setOpts(bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), decimals=6, siPrefix=True)
        self._start_spin.setValue(self._generator.start)
        form.addRow("Start:", self._start_spin)

        self._end_spin = pg.SpinBox()
        self._end_spin.setOpts(bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), decimals=6, siPrefix=True)
        self._end_spin.setValue(self._generator.end)
        form.addRow("End:", self._end_spin)

        self._points_spin = pg.SpinBox(int=True)
        self._points_spin.setOpts(bounds=(2, _MAX_NUM_POINTS))
        self._points_spin.setValue(self._generator.num_points)
        form.addRow("Points:", self._points_spin)

        self._mode_combo = QComboBox()
        for mode in RampMode:
            self._mode_combo.addItem(mode.value, mode)
        self._mode_combo.setCurrentIndex(list(RampMode).index(self._generator.mode))
        form.addRow("Mode:", self._mode_combo)

        self._base_spin = pg.SpinBox()
        self._base_spin.setOpts(bounds=(-_SPINBOX_MAX_ABS, _SPINBOX_MAX_ABS), decimals=6, siPrefix=True)
        self._base_spin.setValue(self._generator.base)
        form.addRow("Base:", self._base_spin)

        root_layout.addWidget(controls_box)

        # --- Preview plot ---
        self._plot_widget = pg.PlotWidget()

        font = QtGui.QFont()
        font.setPointSize(10)
        font.setBold(True)
        font.setFamily("Arial")

        axis_pen = pg.mkPen(color="white", width=2)
        for axis, label in zip(["left", "bottom"], ["Value", "Index"]):
            axis = self._plot_widget.getAxis(axis)
            axis.setTextPen(pg.mkPen("white"))
            axis.setTickFont(font)
            axis.setLabel(
                label, **{"font-size": "11pt", "font-family": "Arial", "font-weight": "bold", "color": "white"}
            )
            axis.setPen(axis_pen)
        self._curve = self._plot_widget.plot(pen=pg.mkPen(color="yellow", width=2.5))
        root_layout.addWidget(self._plot_widget)
        self.setLayout(root_layout)

    def _connect_signals(self) -> None:
        """Wire control signals to generator updates and plot refresh."""
        self._start_spin.valueChanged.connect(self._on_start_changed)
        self._end_spin.valueChanged.connect(self._on_end_changed)
        self._points_spin.valueChanged.connect(self._on_points_changed)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._base_spin.valueChanged.connect(self._on_base_changed)
        self._generator.values_changed.connect(self._refresh_plot)
        self._generator.units_changed.connect(self._update_units)
        self._update_units(self._generator.units)

    def _update_units(self, units: str) -> None:
        """Update the suffix of value spinboxes to match *units*."""
        for spin in (self._start_spin, self._end_spin):
            spin.setOpts(suffix=units)

    def _on_start_changed(self, value: float) -> None:
        """Update generator start."""
        self._generator.start = value

    def _on_end_changed(self, value: float) -> None:
        """Update generator end."""
        self._generator.end = value

    def _on_points_changed(self, value: int) -> None:
        """Update generator number of points."""
        self._generator.num_points = value

    def _on_mode_changed(self, index: int) -> None:
        """Update generator mode."""
        self._generator.mode = self._mode_combo.itemData(index)

    def _on_base_changed(self, value: float) -> None:
        """Update generator base."""
        self._generator.base = value

    def _refresh_plot(self) -> None:
        """Re-render the preview curve."""
        values = self._generator.values
        x_vals = np.arange(len(values), dtype=float)
        self._curve.setData(x_vals, values)

    def get_generator(self) -> RampScanGenerator:
        """Return the :class:`RampScanGenerator` bound to this widget."""
        return self._generator
