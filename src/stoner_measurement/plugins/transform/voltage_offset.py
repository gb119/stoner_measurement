"""X-offset removal transform for x/y trace data."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from qtpy.QtWidgets import QComboBox, QFormLayout, QWidget

from stoner_measurement.core.trace_data import COLUMN_ROLE_Y, TraceData
from stoner_measurement.plugins.transform._trace_selection import (
    TraceChannelSelectionMixin,
)
from stoner_measurement.plugins.transform.base import TransformPlugin
from stoner_measurement.ui.widgets import SISpinBox

_OUTPUT_TRACE_KEY = "offset_removed"
_OFFSET_VALUE_KEY = "dx"

METHOD_MEAN = "mean"
METHOD_RANGE_MIDPOINT = "range_midpoint"
METHOD_NEAR_ZERO_Y = "near_zero_y"

_METHOD_LABELS = {
    METHOD_MEAN: "Mean x: mean(x)",
    METHOD_RANGE_MIDPOINT: "Range midpoint: (max(x) + min(x)) / 2",
    METHOD_NEAR_ZERO_Y: "Near y=0: mean(x[abs(y) < factor × max(y)])",
}


class XOffsetRemovalPlugin(TraceChannelSelectionMixin, TransformPlugin):
    """Remove a constant x-axis offset from selected x/y data.

    The transform estimates ``dx`` using one of three methods and returns the
    original y data against ``x - dx``. Data may be selected from a trace and
    y column, or supplied as custom x/y expressions in advanced mode.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.trace_key: str = ""
        self.column_key: str = ""
        self.advanced_mode: bool = False
        self.x_expr: str = ""
        self.y_expr: str = ""
        self.method: str = METHOD_MEAN
        self.factor: float | str = 0.05

    @property
    def name(self) -> str:
        """Return the plugin display name."""
        return "X Offset Removal"

    @property
    def required_inputs(self) -> list[str]:
        """Data is obtained through the configured trace selection."""
        return []

    @property
    def output_names(self) -> list[str]:
        """Return the corrected trace and calculated offset outputs."""
        return [_OUTPUT_TRACE_KEY, _OFFSET_VALUE_KEY]

    @property
    def output_trace_names(self) -> list[str]:
        """Return the corrected trace output name."""
        return [_OUTPUT_TRACE_KEY]

    @property
    def output_value_names(self) -> list[str]:
        """Return the calculated scalar offset output name."""
        return [_OFFSET_VALUE_KEY]

    def _calculate_offset(self, x_arr: np.ndarray, y_arr: np.ndarray) -> float:
        """Calculate ``dx`` using the configured method."""
        if self.method == METHOD_MEAN:
            return float(np.mean(x_arr))
        if self.method == METHOD_RANGE_MIDPOINT:
            return 0.5 * float(np.max(x_arr) + np.min(x_arr))
        if self.method == METHOD_NEAR_ZERO_Y:
            factor = self.eval_float(self.factor)
            if factor < 0.0:
                raise ValueError("factor must be non-negative")
            mask = np.abs(y_arr) < factor * np.max(y_arr)
            if not np.any(mask):
                raise ValueError("No data points satisfy the near-zero-y offset criterion")
            return float(np.mean(x_arr[mask]))
        raise ValueError(f"Unknown voltage-offset method {self.method!r}")

    def transform(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return the selected trace with its calculated x offset removed."""
        del data
        try:
            x_arr, y_arr, y_col_name, source_names, source_units = (
                self._get_selected_data_arrays()
            )
            x_arr = np.asarray(x_arr, dtype=float)
            y_arr = np.asarray(y_arr, dtype=float)
            if x_arr.shape != y_arr.shape:
                raise ValueError("x and y data must have matching shapes")
            if x_arr.size == 0:
                raise ValueError("input data is empty")
            if not np.all(np.isfinite(x_arr)) or not np.all(np.isfinite(y_arr)):
                raise ValueError("x and y data must contain only finite values")
            dx = self._calculate_offset(x_arr, y_arr)
        except Exception as exc:
            self.log.error("XOffsetRemoval: failed to calculate offset — %s", exc)
            return {}

        corrected_x = x_arr - dx
        df = pd.DataFrame({y_col_name: y_arr}, index=pd.Index(corrected_x, name="x"))
        names = {
            "x": source_names.get("x", "x"),
            y_col_name: source_names.get(y_col_name, y_col_name),
        }
        units = {
            "x": source_units.get("x", ""),
            y_col_name: source_units.get(y_col_name, ""),
        }
        return {
            _OUTPUT_TRACE_KEY: TraceData(
                df=df,
                column_roles={y_col_name: COLUMN_ROLE_Y},
                names=names,
                units=units,
            ),
            _OFFSET_VALUE_KEY: dx,
        }

    def _build_data_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build trace/channel selection controls."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        ws = self._create_data_source_widgets(
            widget, self.engine_namespace.get("_traces", {})
        )
        self._add_data_selection_rows(layout, ws)
        self._wire_data_source_widgets(ws)
        return widget

    def _build_method_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build offset-method controls."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        method_combo = QComboBox(widget)
        for method, label in _METHOD_LABELS.items():
            method_combo.addItem(label, method)
        index = method_combo.findData(self.method)
        method_combo.setCurrentIndex(max(0, index))

        factor_spin = SISpinBox(widget, allow_expressions=True)
        factor_spin.setOpts(bounds=(0.0, 1.0), decimals=6)
        factor_spin.setValue(self.factor)
        factor_spin.setToolTip(
            "Select points satisfying abs(y) < factor × max(y). Used only by the near-y=0 method."
        )

        layout.addRow("Offset method:", method_combo)
        layout.addRow("Factor:", factor_spin)

        def apply_method(_index: int) -> None:
            self.method = str(method_combo.currentData())
            factor_spin.setEnabled(self.method == METHOD_NEAR_ZERO_Y)

        method_combo.currentIndexChanged.connect(apply_method)
        factor_spin.valueChanged.connect(lambda value: setattr(self, "factor", value))
        apply_method(method_combo.currentIndex())
        return widget

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return Data, Offset, and optional About tabs."""

        def build_tabs() -> list[tuple[str, QWidget]]:
            tabs = super(XOffsetRemovalPlugin, self).config_tabs(parent)
            tabs.insert(1, ("Offset", self._build_method_tab(parent)))
            return tabs

        return self._get_cached_config_tabs(build_tabs)

    def to_json(self) -> dict[str, Any]:
        """Serialise trace selection and offset settings."""
        result = super().to_json()
        result.update(
            {
                "trace_key": self.trace_key,
                "column_key": self.column_key,
                "advanced_mode": self.advanced_mode,
                "x_expr": self.x_expr,
                "y_expr": self.y_expr,
                "method": self.method,
                "factor": self.factor,
            }
        )
        return result

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore trace selection and offset settings."""
        self.trace_key = str(data.get("trace_key", ""))
        self.column_key = str(data.get("column_key", ""))
        self.advanced_mode = bool(data.get("advanced_mode", False))
        self.x_expr = str(data.get("x_expr", ""))
        self.y_expr = str(data.get("y_expr", ""))
        method = str(data.get("method", METHOD_MEAN))
        self.method = method if method in _METHOD_LABELS else METHOD_MEAN
        self.factor = data.get("factor", 0.05)
