"""Restricted ramp generator for analyser-controlled sweeps."""

from __future__ import annotations

from typing import Any

import numpy as np
from qtpy.QtCore import QObject  # type: ignore[attr-defined]
from qtpy.QtWidgets import QWidget

from stoner_measurement.scan.ramp_generator import RampMode, RampScanGenerator, RampScanWidget


class NetworkAnalyserScanGenerator(RampScanGenerator):
    """A ramp restricted to the linear and logarithmic grids VNAs source.

    ``RampMode.EXPONENTIAL`` represents a conventional logarithmically spaced
    frequency sweep here. Other general-purpose ramp shapes are not offered
    because standard analyser channels cannot source those arbitrary lists.
    """

    _SUPPORTED_MODES = (RampMode.LINEAR, RampMode.EXPONENTIAL)

    def __init__(
        self,
        *,
        start: float | str = 1.0e6,
        end: float | str = 1.0e9,
        num_points: int = 201,
        mode: RampMode = RampMode.LINEAR,
        parent: QObject | None = None,
    ) -> None:
        if RampMode(mode) not in self._SUPPORTED_MODES:
            raise ValueError("Network analyser scans support only linear or exponential spacing.")
        super().__init__(
            start=start,
            end=end,
            num_points=num_points,
            mode=mode,
            parent=parent,
        )
        self._exponential_available = True
        self._config_widgets: list[_NetworkAnalyserScanWidget] = []

    @classmethod
    def display_name(cls) -> str:
        return "Network analyser ramp"

    @property
    def mode(self) -> RampMode:
        """Return the analyser-supported ramp mode."""
        return self._mode

    @mode.setter
    def mode(self, value: RampMode) -> None:
        mode = RampMode(value)
        if mode not in self._SUPPORTED_MODES:
            raise ValueError("Network analyser scans support only linear or exponential spacing.")
        if mode is RampMode.EXPONENTIAL and not self._exponential_available:
            raise ValueError("Exponential spacing is unavailable for a power sweep.")
        self._mode = mode
        self._invalidate_cache()

    def set_exponential_available(self, available: bool) -> None:
        """Enable exponential frequency spacing or force a linear power ramp."""
        self._exponential_available = bool(available)
        if not available and self._mode is RampMode.EXPONENTIAL:
            self._mode = RampMode.LINEAR
            self._invalidate_cache()
        for widget in self._config_widgets:
            widget.set_exponential_available(available)

    def generate(self) -> np.ndarray:
        start = self.eval_float(self._start)
        end = self.eval_float(self._end)
        if not np.isfinite(start) or not np.isfinite(end):
            raise ValueError("Sweep limits must be finite.")
        if start == end:
            raise ValueError("Sweep start and stop values must differ.")
        if self._mode is RampMode.EXPONENTIAL:
            if start <= 0 or end <= 0:
                raise ValueError("Exponential sweep limits must be positive.")
            return np.geomspace(start, end, self._num_points)
        return np.linspace(start, end, self._num_points)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        widget = _NetworkAnalyserScanWidget(self, parent)
        widget.set_exponential_available(self._exponential_available)
        self._config_widgets.append(widget)
        return widget

    def to_json(self) -> dict[str, Any]:
        return {
            "type": type(self).__name__,
            "start": self._start,
            "end": self._end,
            "num_points": self._num_points,
            "mode": self._mode.value,
            "units": self._units,
        }

    @classmethod
    def _from_json_data(
        cls, data: dict[str, Any], parent: QObject | None = None
    ) -> NetworkAnalyserScanGenerator:
        instance = cls(
            start=data.get("start", 1.0e6),
            end=data.get("end", 1.0e9),
            num_points=int(data.get("num_points", 201)),
            mode=RampMode(data.get("mode", RampMode.LINEAR.value)),
            parent=parent,
        )
        instance.units = str(data.get("units", ""))
        return instance


class _NetworkAnalyserScanWidget(RampScanWidget):
    """Ramp widget with unsupported shaping and base controls removed."""

    def _build_ui(self) -> None:
        super()._build_ui()
        self._mode_combo.clear()
        self._mode_combo.setObjectName("network_analyser_scan_spacing")
        self._mode_combo.addItem("Linear", RampMode.LINEAR)
        self._mode_combo.addItem("Exponential (log-spaced)", RampMode.EXPONENTIAL)
        self._mode_combo.setCurrentIndex(self._mode_combo.findData(self._generator.mode))
        self._start_spin.setObjectName("network_analyser_scan_start")
        self._end_spin.setObjectName("network_analyser_scan_stop")
        self._points_spin.setObjectName("network_analyser_scan_points")
        base_label = self._parameter_grid.itemAtPosition(1, 2).widget()
        if base_label is not None:
            base_label.hide()
        self._base_spin.hide()

    def set_exponential_available(self, available: bool) -> None:
        """Disable spacing selection for the analyser's linear power sweep."""
        self._mode_combo.setEnabled(available)
        self._mode_combo.setCurrentIndex(self._mode_combo.findData(self._generator.mode))
