"""WindowFilterPlugin — convolution filtering using scipy.signal.windows."""

from __future__ import annotations

import ast
from typing import Any

import numpy as np
import pandas as pd
from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLineEdit, QWidget

from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData
from stoner_measurement.plugins.transform._trace_selection import (
    TraceChannelSelectionMixin,
)
from stoner_measurement.plugins.transform.base import TransformPlugin

_FILTER_TRACE_KEY = "filtered"
_WINDOW_NAMES = [
    "boxcar",
    "triang",
    "blackman",
    "hamming",
    "hann",
    "bartlett",
    "flattop",
    "parzen",
    "bohman",
    "blackmanharris",
    "nuttall",
    "barthann",
    "cosine",
    "exponential",
    "tukey",
    "taylor",
    "lanczos",
    "kaiser",
    "kaiser_bessel_derived",
    "gaussian",
    "general_cosine",
    "general_gaussian",
    "general_hamming",
    "dpss",
    "chebwin",
]


class WindowFilterPlugin(TraceChannelSelectionMixin, TransformPlugin):
    """Smooth a selected trace by convolving it with a configurable window.

    Use this transform when you want a simple configurable smoothing or
    windowed averaging operation. It applies a window function to the selected
    y data and returns a filtered trace on the same x-axis.

    In the configuration tabs, choose the input trace or advanced x/y
    expressions, then select the SciPy window type, length, optional window
    parameters, and whether the kernel should be normalised.

    Attributes:
        trace_key (str):
            Selected trace key used when advanced mode is disabled.
        column_key (str):
            Selected y-column key from the chosen trace.
        advanced_mode (bool):
            trace/column selection.
        x_expr (str):
            Expression used to compute x data in advanced mode.
        y_expr (str):
            Expression used to compute y data in advanced mode.
        window_name (str):
            Name of the SciPy window function.
        window_length (int):
            Number of points in the generated window kernel.
        window_parameters (str):
            Optional Python literal text parsed as additional window
            parameters (for example, shape parameters).
        symmetric_window (bool):
            When ``True``, create a symmetric window. When ``False``, create an
            FFT-style periodic window.
        normalise_kernel (bool):
            When ``True``, divide the kernel by its sum to preserve DC level.

    Notes:
        Invalid kernel settings (for example, malformed parameters or
        zero-sum normalisation) are logged and produce no transform output.

    Examples:
        Select a trace and y column, then choose a window type and length on
        the Window tab to smooth noisy data while keeping the original x axis.
    """

    def __init__(self, parent=None) -> None:
        """Initialise the window filter plugin with defaults."""
        super().__init__(parent)
        self.trace_key: str = ""
        self.column_key: str = ""
        self.advanced_mode: bool = False
        self.x_expr: str = ""
        self.y_expr: str = ""

        self.window_name: str = "hann"
        self.window_length: int = 11
        self.window_parameters: str = ""
        self.symmetric_window: bool = True
        self.normalise_kernel: bool = True

    @property
    def name(self) -> str:
        """Return the plugin display name."""
        return "Window Filter"

    @property
    def required_inputs(self) -> list[str]:
        """No direct runtime inputs are required."""
        return []

    @property
    def output_names(self) -> list[str]:
        """Return all plugin output names."""
        return [_FILTER_TRACE_KEY]

    @property
    def output_trace_names(self) -> list[str]:
        """Return the trace outputs produced by this plugin."""
        return [_FILTER_TRACE_KEY]

    @property
    def output_value_names(self) -> list[str]:
        """This plugin does not report scalar outputs."""
        return []

    def transform(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return the selected trace with y filtered by window convolution."""
        del data
        try:
            x_arr, y_arr, y_col_name, source_names, source_units = self._get_selected_data_arrays()
            y_arr = np.asarray(y_arr, dtype=float)
        except Exception as exc:
            self.log.error("WindowFilter: failed to retrieve data — %s", exc)
            return {}

        if len(x_arr) == 0 or len(y_arr) == 0:
            self.log.warning("WindowFilter: empty input data.")
            return {}

        try:
            kernel = self._build_window_kernel()
        except Exception as exc:
            self.log.error("WindowFilter: failed to build window kernel — %s", exc)
            return {}

        if kernel.size == 0:
            self.log.warning("WindowFilter: empty window kernel.")
            return {}

        y_filtered = np.convolve(y_arr, kernel, mode="same")
        df = pd.DataFrame({y_col_name: y_filtered}, index=pd.Index(x_arr, name="x"))

        names: dict[str, str] = dict(source_names)
        names.setdefault("x", "x")
        names.setdefault(y_col_name, y_col_name)

        units: dict[str, str] = dict(source_units)
        units.setdefault("x", "")
        units.setdefault(y_col_name, "")

        return {
            _FILTER_TRACE_KEY: TraceData(
                df=df,
                column_roles={y_col_name: COLUMN_ROLE_Y},
                names=names,
                units=units,
            )
        }

    def _build_window_kernel(self) -> np.ndarray:
        """Build and return the configured window kernel for convolution."""
        try:
            from scipy.signal import windows  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("scipy is not installed") from exc

        window_length = max(1, int(self.window_length))
        spec = self.window_name

        if self.window_parameters.strip():
            parsed = ast.literal_eval(self.window_parameters)
            if isinstance(parsed, tuple):
                spec = (self.window_name, *parsed)
            elif isinstance(parsed, list):
                spec = (self.window_name, *parsed)
            else:
                spec = (self.window_name, parsed)

        kernel = np.asarray(
            windows.get_window(spec, window_length, fftbins=not self.symmetric_window),
            dtype=float,
        )
        if self.normalise_kernel:
            normalisation = float(np.sum(kernel))
            if normalisation == 0.0:
                raise ValueError("Window sum is zero; cannot normalise kernel.")
            kernel = kernel / normalisation
        return kernel

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

    def _build_window_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build the window-configuration tab."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        window_combo = QComboBox(widget)
        window_combo.addItems(_WINDOW_NAMES)
        if self.window_name in _WINDOW_NAMES:
            window_combo.setCurrentText(self.window_name)
        else:
            window_combo.setCurrentText("hann")
            self.window_name = "hann"

        length_edit = QLineEdit(str(self.window_length), widget)
        params_edit = QLineEdit(self.window_parameters, widget)
        params_edit.setToolTip(
            "Optional window parameters as a Python literal. "
            "Examples: 5, (5,), (2.5,), (3.0, 1.2)."
        )
        symmetric_check = QCheckBox(widget)
        symmetric_check.setChecked(self.symmetric_window)
        normalise_check = QCheckBox(widget)
        normalise_check.setChecked(self.normalise_kernel)

        layout.addRow("Window:", window_combo)
        layout.addRow("Window length:", length_edit)
        layout.addRow("Window parameters:", params_edit)
        layout.addRow("Symmetric window:", symmetric_check)
        layout.addRow("Normalise kernel:", normalise_check)
        widget.setLayout(layout)

        window_combo.currentTextChanged.connect(lambda text: setattr(self, "window_name", text))

        def _apply_length() -> None:
            try:
                self.window_length = max(1, int(length_edit.text().strip()))
            except ValueError:
                self.window_length = 1
                length_edit.setText("1")

        length_edit.editingFinished.connect(_apply_length)
        params_edit.editingFinished.connect(lambda: setattr(self, "window_parameters", params_edit.text().strip()))
        symmetric_check.toggled.connect(lambda checked: setattr(self, "symmetric_window", checked))
        normalise_check.toggled.connect(lambda checked: setattr(self, "normalise_kernel", checked))

        return widget

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return plugin configuration tabs."""

        def _build_tabs() -> list[tuple[str, QWidget]]:
            tabs = super(WindowFilterPlugin, self).config_tabs(parent)
            tabs.insert(1, ("Window", self._build_window_tab(parent)))
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
        data["window_name"] = self.window_name
        data["window_length"] = self.window_length
        data["window_parameters"] = self.window_parameters
        data["symmetric_window"] = self.symmetric_window
        data["normalise_kernel"] = self.normalise_kernel
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore plugin configuration from serialised JSON data."""
        self.trace_key = data.get("trace_key", "")
        self.column_key = data.get("column_key", "")
        self.advanced_mode = data.get("advanced_mode", False)
        self.x_expr = data.get("x_expr", "")
        self.y_expr = data.get("y_expr", "")

        self.window_name = data.get("window_name", "hann")
        self.window_length = int(data.get("window_length", 11))
        self.window_parameters = data.get("window_parameters", "")
        self.symmetric_window = bool(data.get("symmetric_window", True))
        self.normalise_kernel = bool(data.get("normalise_kernel", True))
