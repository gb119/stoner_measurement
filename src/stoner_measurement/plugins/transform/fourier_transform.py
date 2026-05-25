"""FourierTransformPlugin — forward/inverse FFT transform plugin."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QComboBox, QFormLayout, QWidget

from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData
from stoner_measurement.plugins.transform._trace_selection import TraceChannelSelectionMixin
from stoner_measurement.plugins.transform.base import TransformPlugin

_OUTPUT_TRACE_KEY = "fft"


class FourierTransformPlugin(TraceChannelSelectionMixin, TransformPlugin):
    """Perform forward or inverse Fourier transforms on selected trace data."""

    def __init__(self, parent=None) -> None:
        """Initialise the Fourier transform plugin with defaults."""
        super().__init__(parent)
        self.trace_key: str = ""
        self.column_key: str = ""
        self.advanced_mode: bool = False
        self.x_expr: str = ""
        self.y_expr: str = ""

        self.inverse: bool = False
        self.output_component: str = "magnitude"

    @property
    def name(self) -> str:
        """Return the plugin display name."""
        return "Fourier Transform"

    @property
    def required_inputs(self) -> list[str]:
        """No direct runtime inputs are required."""
        return []

    @property
    def output_names(self) -> list[str]:
        """Return all plugin output names."""
        return [_OUTPUT_TRACE_KEY]

    @property
    def output_trace_names(self) -> list[str]:
        """Return the trace outputs produced by this plugin."""
        return [_OUTPUT_TRACE_KEY]

    @property
    def output_value_names(self) -> list[str]:
        """This plugin does not report scalar outputs."""
        return []

    def transform(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return Fourier-domain or time-domain data for the selected trace."""
        del data
        try:
            x_arr, y_arr, y_col_name, source_names, source_units = self._get_selected_data_arrays()
        except Exception as exc:
            self.log.error("FourierTransform: failed to retrieve data — %s", exc)
            return {}

        if len(x_arr) < 2 or len(y_arr) < 2:
            self.log.warning("FourierTransform: not enough points for transform.")
            return {}

        x_sorted, y_sorted = _sort_xy(x_arr, y_arr)
        x_uniform, y_uniform = _resample_uniform(x_sorted, y_sorted)
        if len(x_uniform) < 2:
            self.log.warning("FourierTransform: could not construct uniform grid.")
            return {}

        if self.inverse:
            x_out, y_out, x_unit = self._inverse_transform(x_uniform, y_uniform)
            default_x_name = "time"
        else:
            x_out, y_out, x_unit = self._forward_transform(x_uniform, y_uniform)
            default_x_name = "frequency"

        output_col = _output_column_name(y_col_name, self.output_component)
        y_component = _select_output_component(y_out, self.output_component)

        df = pd.DataFrame({output_col: y_component}, index=pd.Index(x_out, name="x"))

        names = dict(source_names)
        names.setdefault("x", default_x_name)
        names.setdefault(output_col, output_col)

        units = dict(source_units)
        units["x"] = x_unit
        units.setdefault(output_col, source_units.get(y_col_name, ""))

        return {
            _OUTPUT_TRACE_KEY: TraceData(
                df=df,
                column_roles={output_col: COLUMN_ROLE_Y},
                names=names,
                units=units,
            )
        }

    def _forward_transform(self, x_uniform: np.ndarray, y_uniform: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
        """Compute shifted forward FFT on a uniform grid."""
        delta = _mean_spacing(x_uniform)
        spectrum = np.fft.fft(y_uniform)
        frequencies = np.fft.fftfreq(len(y_uniform), d=delta)
        return np.fft.fftshift(frequencies), np.fft.fftshift(spectrum), _reciprocal_unit(self._x_unit())

    def _inverse_transform(self, x_uniform: np.ndarray, y_uniform: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
        """Compute inverse FFT from shifted frequency-domain input data."""
        shifted_spectrum = np.asarray(y_uniform, dtype=complex)
        unshifted_spectrum = np.fft.ifftshift(shifted_spectrum)
        signal = np.fft.ifft(unshifted_spectrum)

        delta_frequency = _mean_spacing(x_uniform)
        if delta_frequency == 0.0:
            delta_time = 1.0
        else:
            delta_time = 1.0 / (len(x_uniform) * delta_frequency)

        time_axis = (np.arange(len(signal), dtype=float) - len(signal) // 2) * delta_time
        return time_axis, np.fft.fftshift(signal), _reciprocal_unit(self._x_unit())

    def _x_unit(self) -> str:
        """Return x-axis unit from selected trace context when available."""
        traces = self.engine_namespace.get("_traces", {})
        if self.advanced_mode or not self.trace_key or self.trace_key not in traces:
            return ""
        try:
            trace_data = self.eval(traces[self.trace_key])
        except Exception:
            return ""
        units = getattr(trace_data, "units", {})
        return str(units.get("x", ""))

    def _build_data_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build the data-selection tab."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        traces: dict[str, str] = self.engine_namespace.get("_traces", {})
        ws = self._create_data_source_widgets(widget, traces)
        self._add_data_selection_rows(layout, ws)
        self._wire_data_source_widgets(ws)

        widget.setLayout(layout)
        return widget

    def _build_transform_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build the Fourier transform settings tab."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        mode_combo = QComboBox(widget)
        mode_combo.addItem("Fourier transform", False)
        mode_combo.addItem("Inverse Fourier transform", True)
        mode_combo.setCurrentIndex(1 if self.inverse else 0)

        output_combo = QComboBox(widget)
        output_combo.addItems(["magnitude", "real", "imag", "phase"])
        if self.output_component in {"magnitude", "real", "imag", "phase"}:
            output_combo.setCurrentText(self.output_component)

        layout.addRow("Mode:", mode_combo)
        layout.addRow("Output component:", output_combo)

        def _apply_mode(index: int) -> None:
            value = mode_combo.itemData(index)
            self.inverse = bool(value)

        mode_combo.currentIndexChanged.connect(_apply_mode)
        output_combo.currentTextChanged.connect(lambda text: setattr(self, "output_component", text))

        widget.setLayout(layout)
        return widget

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return plugin configuration tabs."""

        def _build_tabs() -> list[tuple[str, QWidget]]:
            tabs = super().config_tabs(parent)
            tabs.insert(1, ("Transform", self._build_transform_tab(parent)))
            return tabs

        return self._get_cached_config_tabs(_build_tabs)

    def to_json(self) -> dict[str, Any]:
        """Serialise plugin configuration to JSON-compatible data."""
        data = super().to_json()
        data["trace_key"] = self.trace_key
        data["column_key"] = self.column_key
        data["advanced_mode"] = self.advanced_mode
        data["x_expr"] = self.x_expr
        data["y_expr"] = self.y_expr
        data["inverse"] = self.inverse
        data["output_component"] = self.output_component
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore plugin configuration from serialised JSON data."""
        self.trace_key = data.get("trace_key", "")
        self.column_key = data.get("column_key", "")
        self.advanced_mode = data.get("advanced_mode", False)
        self.x_expr = data.get("x_expr", "")
        self.y_expr = data.get("y_expr", "")
        self.inverse = bool(data.get("inverse", False))
        self.output_component = data.get("output_component", "magnitude")


def _sort_xy(x_arr: np.ndarray, y_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return x/y arrays sorted in ascending x order."""
    order = np.argsort(np.asarray(x_arr, dtype=float))
    x_sorted = np.asarray(x_arr, dtype=float)[order]
    y_sorted = np.asarray(y_arr)[order]
    return x_sorted, y_sorted


def _resample_uniform(x_arr: np.ndarray, y_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Resample data onto a uniform x-grid, supporting non-uniform x spacing."""
    n_points = len(x_arr)
    if n_points < 2:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)

    x_min = float(x_arr[0])
    x_max = float(x_arr[-1])
    if x_max == x_min:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)

    x_uniform = np.linspace(x_min, x_max, n_points)

    if np.iscomplexobj(y_arr):
        y_uniform = np.interp(x_uniform, x_arr, np.real(y_arr)) + 1j * np.interp(x_uniform, x_arr, np.imag(y_arr))
    else:
        y_uniform = np.interp(x_uniform, x_arr, np.asarray(y_arr, dtype=float))
    return x_uniform, y_uniform


def _mean_spacing(x_arr: np.ndarray) -> float:
    """Return mean positive spacing for a uniform-like x grid."""
    diffs = np.diff(np.asarray(x_arr, dtype=float))
    positive_diffs = diffs[np.isfinite(diffs) & (diffs > 0.0)]
    if len(positive_diffs) == 0:
        return 1.0
    return float(np.mean(positive_diffs))


def _select_output_component(values: np.ndarray, output_component: str) -> np.ndarray:
    """Return selected scalar component from complex transform data."""
    if output_component == "real":
        return np.real(values)
    if output_component == "imag":
        return np.imag(values)
    if output_component == "phase":
        return np.angle(values)
    return np.abs(values)


def _output_column_name(base_name: str, output_component: str) -> str:
    """Return output y-column name from component and source base name."""
    suffix = output_component
    return f"{base_name}_{suffix}"


def _reciprocal_unit(unit: str) -> str:
    """Return reciprocal unit text where practical."""
    if not unit:
        return ""
    return f"1/{unit}"
