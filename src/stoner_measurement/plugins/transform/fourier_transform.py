"""FourierTransformPlugin — forward and inverse Fourier-transform plugin.

This module provides :class:`FourierTransformPlugin`, a transform plugin that
converts selected trace data between time and frequency domains using FFT
routines after resampling onto a uniform x grid.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from qtpy.QtWidgets import QComboBox, QFormLayout, QWidget

from stoner_measurement.plugins.trace.base import (
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
)
from stoner_measurement.plugins.transform._trace_selection import (
    TraceChannelSelectionMixin,
)
from stoner_measurement.plugins.transform.base import TransformPlugin

_OUTPUT_TRACE_KEY = "fft"


class FourierTransformPlugin(TraceChannelSelectionMixin, TransformPlugin):
    """Transform selected trace data between time and frequency domains.

    Use this transform when you want to inspect a trace in the reciprocal
    domain or reconstruct a time-domain signal from frequency-domain data. The
    plugin takes selected x/y data, sorts it by x, resamples it onto a uniform
    grid, and then performs either a forward FFT or an inverse FFT.

    Attributes:
        trace_key (str):
            Key in the ``_traces`` catalogue used in simple mode. Defaults to
            ``""``.
        column_key (str):
            Selected y-column key from the chosen trace in simple mode.
            Defaults to ``""``.
        advanced_mode (bool):
            When ``True``, evaluate :attr:`x_expr` and :attr:`y_expr` instead
            of using direct trace/column selection. Defaults to ``False``.
        x_expr (str):
            Python expression used to compute x data in advanced mode.
            Defaults to ``""``.
        y_expr (str):
            Python expression used to compute y data in advanced mode.
            Defaults to ``""``.
        inverse (bool):
            When ``False``, compute a forward Fourier transform. When ``True``,
            treat the input as shifted frequency-domain data and compute an
            inverse transform. Defaults to ``False``.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Notes:
        Non-uniform input spacing is handled by interpolation to a uniform grid
        before applying FFT routines. The output trace contains four columns:
        magnitude, real part, imaginary part, and angle. The output x-axis
        unit is converted to the reciprocal of the input x unit where
        practical.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.transform.fourier_transform import FourierTransformPlugin
        >>> plugin = FourierTransformPlugin()
        >>> plugin.name
        'Fourier Transform'
        >>> plugin.output_trace_names
        ['fft']
    """

    def __init__(self, parent=None) -> None:
        """Initialise the Fourier transform plugin with defaults."""
        super().__init__(parent)
        self.trace_key: str = ""
        self.column_key: str = ""
        self.advanced_mode: bool = False
        self.x_expr: str = ""
        self.y_expr: str = ""

        self.inverse: bool = False

    @property
    def name(self) -> str:
        """Return the plugin display name.

        Returns:
            (str):
                ``"Fourier Transform"``.
        """
        return "Fourier Transform"

    @property
    def required_inputs(self) -> list[str]:
        """Return the runtime inputs required by this plugin.

        Returns:
            (list[str]):
                An empty list because the plugin reads from selected trace data
                rather than direct named inputs.
        """
        return []

    @property
    def output_names(self) -> list[str]:
        """Return all plugin output names.

        Returns:
            (list[str]):
                List containing the output trace key ``"fft"``.
        """
        return [_OUTPUT_TRACE_KEY]

    @property
    def output_trace_names(self) -> list[str]:
        """Return the trace outputs produced by this plugin.

        Returns:
            (list[str]):
                List containing the output trace key ``"fft"``.
        """
        return [_OUTPUT_TRACE_KEY]

    @property
    def output_value_names(self) -> list[str]:
        """Return scalar output names produced by this plugin.

        Returns:
            (list[str]):
                An empty list because this plugin does not report scalar
                outputs.
        """
        return []

    def transform(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return Fourier-domain or time-domain data for the selected trace.

        Args:
            data (dict[str, Any]):
                Unused transform input mapping. Present for API compatibility.

        Returns:
            (dict[str, Any]):
                Mapping containing the output :class:`TraceData` under the
                ``"fft"`` key, or an empty dict when the transform cannot be
                performed.
        """
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

        component_columns = _component_column_names(y_col_name)
        df = pd.DataFrame(
            {
                component_columns["magnitude"]: np.abs(y_out),
                component_columns["real"]: np.real(y_out),
                component_columns["imag"]: np.imag(y_out),
                component_columns["angle"]: np.angle(y_out),
            },
            index=pd.Index(x_out, name="x"),
        )

        names = dict(source_names)
        names.setdefault("x", default_x_name)
        for component, column_name in component_columns.items():
            names.setdefault(column_name, column_name)

        units = dict(source_units)
        units["x"] = x_unit
        value_unit = source_units.get(y_col_name, "")
        for component, column_name in component_columns.items():
            if component == "angle":
                units.setdefault(column_name, "rad")
            else:
                units.setdefault(column_name, value_unit)

        return {
            _OUTPUT_TRACE_KEY: TraceData(
                df=df,
                column_roles={
                    component_columns["magnitude"]: COLUMN_ROLE_Y,
                    component_columns["real"]: COLUMN_ROLE_Z,
                    component_columns["imag"]: COLUMN_ROLE_Z,
                    component_columns["angle"]: COLUMN_ROLE_Z,
                },
                names=names,
                units=units,
            )
        }

    def _forward_transform(self, x_uniform: np.ndarray, y_uniform: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
        """Compute a shifted forward FFT on a uniform grid.

        Args:
            x_uniform (np.ndarray):
                Uniform x-axis array.
            y_uniform (np.ndarray):
                Uniform y-data array.

        Returns:
            (np.ndarray):
                Shifted frequency axis.
            (np.ndarray):
                Shifted complex spectrum.
            (str):
                Output x-axis units.
        """
        delta = _mean_spacing(x_uniform)
        spectrum = np.fft.fft(y_uniform)
        frequencies = np.fft.fftfreq(len(y_uniform), d=delta)
        return np.fft.fftshift(frequencies), np.fft.fftshift(spectrum), _reciprocal_unit(self._x_unit())

    def _inverse_transform(self, x_uniform: np.ndarray, y_uniform: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
        """Compute an inverse FFT from shifted frequency-domain input data.

        Args:
            x_uniform (np.ndarray):
                Uniform frequency-axis array.
            y_uniform (np.ndarray):
                Uniform complex spectrum data.

        Returns:
            (np.ndarray):
                Reconstructed time axis.
            (np.ndarray):
                Reconstructed complex signal.
            (str):
                Output x-axis units.
        """
        shifted_spectrum = np.asarray(y_uniform, dtype=complex)
        unshifted_spectrum = np.fft.ifftshift(shifted_spectrum)
        signal = np.fft.ifft(unshifted_spectrum)

        delta_frequency = _mean_spacing(x_uniform)
        if delta_frequency == 0.0:
            delta_time = 1.0
        else:
            delta_time = 1.0 / (len(x_uniform) * delta_frequency)

        time_axis = np.arange(len(signal), dtype=float) * delta_time
        return time_axis, signal, _reciprocal_unit(self._x_unit())

    def _x_unit(self) -> str:
        """Return the x-axis unit from the selected trace context.

        Returns:
            (str):
                The selected trace x-axis unit, or ``""`` when unavailable.
        """
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
        """Build the data-selection tab.

        Keyword Parameters:
            parent (QWidget | None):
                Optional parent widget.

        Returns:
            (QWidget):
                Data-selection configuration widget.
        """
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        traces: dict[str, str] = self.engine_namespace.get("_traces", {})
        ws = self._create_data_source_widgets(widget, traces)
        self._add_data_selection_rows(layout, ws)
        self._wire_data_source_widgets(ws)

        widget.setLayout(layout)
        return widget

    def _build_transform_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build the Fourier-transform settings tab.

        Keyword Parameters:
            parent (QWidget | None):
                Optional parent widget.

        Returns:
            (QWidget):
                Transform-settings configuration widget.
        """
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        mode_combo = QComboBox(widget)
        mode_combo.addItem("Fourier transform", False)
        mode_combo.addItem("Inverse Fourier transform", True)
        mode_combo.setCurrentIndex(1 if self.inverse else 0)

        layout.addRow("Mode:", mode_combo)

        def _apply_mode(index: int) -> None:
            value = mode_combo.itemData(index)
            self.inverse = bool(value)

        mode_combo.currentIndexChanged.connect(_apply_mode)

        widget.setLayout(layout)
        return widget

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return plugin configuration tabs.

        Keyword Parameters:
            parent (QWidget | None):
                Optional parent widget.

        Returns:
            (list[tuple[str, QWidget]]):
                Cached list of configuration-tab title/widget pairs.
        """

        def _build_tabs() -> list[tuple[str, QWidget]]:
            tabs = super(FourierTransformPlugin, self).config_tabs(parent)
            tabs.insert(1, ("Transform", self._build_transform_tab(parent)))
            return tabs

        return self._get_cached_config_tabs(_build_tabs)

    def to_json(self) -> dict[str, Any]:
        """Serialise plugin configuration to JSON-compatible data.

        Returns:
            (dict[str, Any]):
                Serialised configuration dictionary including data-selection
                and transform-mode settings.
        """
        data = super().to_json()
        data["trace_key"] = self.trace_key
        data["column_key"] = self.column_key
        data["advanced_mode"] = self.advanced_mode
        data["x_expr"] = self.x_expr
        data["y_expr"] = self.y_expr
        data["inverse"] = self.inverse
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore plugin configuration from serialised JSON data.

        Args:
            data (dict[str, Any]):
                Serialised configuration dictionary.
        """
        self.trace_key = data.get("trace_key", "")
        self.column_key = data.get("column_key", "")
        self.advanced_mode = data.get("advanced_mode", False)
        self.x_expr = data.get("x_expr", "")
        self.y_expr = data.get("y_expr", "")
        self.inverse = bool(data.get("inverse", False))


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
        y_uniform = _interp_complex(x_uniform, x_arr, np.asarray(y_arr, dtype=complex))
    else:
        y_uniform = np.interp(x_uniform, x_arr, np.asarray(y_arr, dtype=float))
    return x_uniform, y_uniform


def _interp_complex(x_uniform: np.ndarray, x_arr: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Interpolate complex-valued data by interpolating real and imaginary parts."""
    return np.interp(x_uniform, x_arr, np.real(values)) + 1j * np.interp(x_uniform, x_arr, np.imag(values))


def _mean_spacing(x_arr: np.ndarray) -> float:
    """Return mean positive spacing for a uniform-like x grid."""
    diffs = np.diff(np.asarray(x_arr, dtype=float))
    positive_diffs = diffs[np.isfinite(diffs) & (diffs > 0.0)]
    if len(positive_diffs) == 0:
        return 1.0
    return float(np.mean(positive_diffs))


def _component_column_names(base_name: str) -> dict[str, str]:
    """Return output column names for all Fourier data components."""
    return {
        "magnitude": f"{base_name}_magnitude",
        "real": f"{base_name}_real",
        "imag": f"{base_name}_imag",
        "angle": f"{base_name}_angle",
    }


def _reciprocal_unit(unit: str) -> str:
    """Return reciprocal unit text where practical."""
    if not unit:
        return ""
    if unit.startswith("1/"):
        return unit.removeprefix("1/")
    return f"1/{unit}"
