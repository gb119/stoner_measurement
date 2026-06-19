"""SavitzkyGolayPlugin - Savitzky-Golay smoothing/derivative transform plugin."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from qtpy.QtWidgets import QComboBox, QFormLayout, QLineEdit, QWidget

from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData
from stoner_measurement.plugins.transform._trace_selection import (
    TraceChannelSelectionMixin,
)
from stoner_measurement.plugins.transform.base import TransformPlugin

_OUTPUT_TRACE_KEY = "savgol"


class SavitzkyGolayPlugin(TraceChannelSelectionMixin, TransformPlugin):
    """Apply Savitzky-Golay smoothing or derivatives to a selected trace column.

    This transform plugin reads one x/y trace pair from either a selected trace
    channel or advanced expressions, applies ``scipy.signal.savgol_filter``, and
    outputs either the smoothed signal or one derivative order of the signal.

    Args:
        parent (QObject | None):
            Optional Qt parent object supplied by the plugin host.

    Attributes:
        trace_key (str):
            Selected trace key used when advanced mode is disabled.
        column_key (str):
            Selected y-column key from the chosen trace.
        advanced_mode (bool):
            When ``True``, evaluate ``x_expr`` and ``y_expr`` instead of direct
            trace/column selection.
        x_expr (str):
            Expression used to compute x data in advanced mode.
        y_expr (str):
            Expression used to compute y data in advanced mode.
        window_length (int):
            Window size supplied to the Savitzky-Golay filter. The runtime path
            coerces this to a valid odd length.
        polyorder (int):
            Polynomial order used for local fitting.
        derivative_order (int):
            Derivative order produced by the filter output.

    Notes:
        The plugin preserves source metadata where possible and derives output
        units for derivative outputs as ``y_unit/x_unit^n``.

    Examples:
        Add the plugin to a sequence, choose a source trace and y column on the
        Data tab, then choose filter settings on the Filter tab to generate a
        smoothed or differentiated output trace.
    """

    def __init__(self, parent=None) -> None:
        """Initialise the Savitzky-Golay plugin with defaults."""
        super().__init__(parent)
        self.trace_key: str = ""
        self.column_key: str = ""
        self.advanced_mode: bool = False
        self.x_expr: str = ""
        self.y_expr: str = ""

        self.window_length: int = 11
        self.polyorder: int = 3
        self.derivative_order: int = 0

    @property
    def name(self) -> str:
        """Return the plugin display name."""
        return "Savitzky-Golay"

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
        """Return the selected trace with Savitzky-Golay-smoothed derivative data."""
        del data
        try:
            from scipy.signal import savgol_filter  # noqa: PLC0415
        except ImportError:
            self.log.error("SavitzkyGolay: scipy is not installed.")
            return {}

        try:
            x_arr, y_arr, y_col_name, source_names, source_units = self._get_selected_data_arrays()
            y_arr = np.asarray(y_arr, dtype=float)
        except Exception as exc:
            self.log.error("SavitzkyGolay: failed to retrieve data — %s", exc)
            return {}

        if len(x_arr) < 3 or len(y_arr) < 3:
            self.log.warning("SavitzkyGolay: not enough points for filtering.")
            return {}

        window_length = _validated_odd_window_length(self.window_length, len(y_arr))
        polyorder = max(0, int(self.polyorder))
        polyorder = min(polyorder, window_length - 1)
        derivative_order = min(max(0, int(self.derivative_order)), polyorder)
        self.polyorder = polyorder
        self.derivative_order = derivative_order

        delta = _estimate_spacing(x_arr)

        try:
            y_filtered = savgol_filter(
                y_arr,
                window_length=window_length,
                polyorder=polyorder,
                deriv=derivative_order,
                delta=delta,
                mode="interp",
            )
        except Exception as exc:
            self.log.error("SavitzkyGolay: filtering failed — %s", exc)
            return {}

        output_col = y_col_name if derivative_order == 0 else f"d{derivative_order}_{y_col_name}"
        df = pd.DataFrame({output_col: y_filtered}, index=pd.Index(x_arr, name="x"))

        names = dict(source_names)
        names.setdefault("x", "x")
        if derivative_order == 0:
            names.setdefault(output_col, names.get(y_col_name, y_col_name))
        else:
            base_name = names.get(y_col_name, y_col_name)
            names.setdefault(output_col, f"d{derivative_order}_{base_name}_dx{derivative_order}")

        units = dict(source_units)
        units.setdefault("x", "")
        y_unit = units.get(y_col_name, "")
        x_unit = units.get("x", "")
        if derivative_order == 0:
            units.setdefault(output_col, y_unit)
        else:
            units.setdefault(output_col, _derive_unit(y_unit, x_unit, derivative_order))

        return {
            _OUTPUT_TRACE_KEY: TraceData(
                df=df,
                column_roles={output_col: COLUMN_ROLE_Y},
                names=names,
                units=units,
            )
        }

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

    def _build_filter_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build the Savitzky-Golay filter configuration tab."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        window_edit = QLineEdit(str(self.window_length), widget)
        polyorder_edit = QLineEdit(str(self.polyorder), widget)
        derivative_combo = QComboBox(widget)

        def _refresh_derivative_combo() -> None:
            max_derivative = max(0, int(self.polyorder))
            current = min(max(0, int(self.derivative_order)), max_derivative)
            derivative_combo.blockSignals(True)
            derivative_combo.clear()
            for order in range(max_derivative + 1):
                label = "Smoothed y" if order == 0 else f"d^{order}y/dx^{order}"
                derivative_combo.addItem(label, order)
            derivative_combo.setCurrentIndex(current)
            derivative_combo.blockSignals(False)
            self.derivative_order = current

        _refresh_derivative_combo()

        layout.addRow("Window length:", window_edit)
        layout.addRow("Polynomial order:", polyorder_edit)
        layout.addRow("Output:", derivative_combo)

        def _apply_window_length() -> None:
            try:
                self.window_length = max(3, int(window_edit.text().strip()))
            except ValueError:
                self.window_length = 3
            window_edit.setText(str(self.window_length))

        def _apply_polyorder() -> None:
            try:
                self.polyorder = max(0, int(polyorder_edit.text().strip()))
            except ValueError:
                self.polyorder = 0
            polyorder_edit.setText(str(self.polyorder))
            _refresh_derivative_combo()

        def _apply_derivative(index: int) -> None:
            value = derivative_combo.itemData(index)
            if isinstance(value, int):
                self.derivative_order = value

        window_edit.editingFinished.connect(_apply_window_length)
        polyorder_edit.editingFinished.connect(_apply_polyorder)
        derivative_combo.currentIndexChanged.connect(_apply_derivative)

        widget.setLayout(layout)
        return widget

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return plugin configuration tabs."""

        def _build_tabs() -> list[tuple[str, QWidget]]:
            tabs = super(SavitzkyGolayPlugin, self).config_tabs(parent)
            tabs.insert(1, ("Filter", self._build_filter_tab(parent)))
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
        data["window_length"] = self.window_length
        data["polyorder"] = self.polyorder
        data["derivative_order"] = self.derivative_order
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore plugin configuration from serialised JSON data."""
        self.trace_key = data.get("trace_key", "")
        self.column_key = data.get("column_key", "")
        self.advanced_mode = data.get("advanced_mode", False)
        self.x_expr = data.get("x_expr", "")
        self.y_expr = data.get("y_expr", "")
        self.window_length = int(data.get("window_length", 11))
        self.polyorder = int(data.get("polyorder", 3))
        self.derivative_order = int(data.get("derivative_order", 0))


def _validated_odd_window_length(length: int, n_points: int) -> int:
    """Return a valid odd window length for Savitzky-Golay filtering."""
    value = max(3, int(length))
    if value % 2 == 0:
        value += 1
    if value > n_points:
        value = n_points if n_points % 2 == 1 else n_points - 1
    return max(3, value)


def _estimate_spacing(x_arr: np.ndarray) -> float:
    """Estimate positive sample spacing from x-data for derivative scaling."""
    diffs = np.diff(np.asarray(x_arr, dtype=float))
    positive_diffs = diffs[np.isfinite(diffs) & (diffs > 0.0)]
    if len(positive_diffs) == 0:
        return 1.0
    return float(np.mean(positive_diffs))


def _derive_unit(y_unit: str, x_unit: str, derivative_order: int) -> str:
    """Return a derived unit string for ``d^n(y)/dx^n`` output."""
    if derivative_order <= 0:
        return y_unit
    if not x_unit:
        return y_unit
    if derivative_order == 1:
        return f"{y_unit}/{x_unit}" if y_unit else f"1/{x_unit}"
    return f"{y_unit}/{x_unit}^{derivative_order}" if y_unit else f"1/{x_unit}^{derivative_order}"
