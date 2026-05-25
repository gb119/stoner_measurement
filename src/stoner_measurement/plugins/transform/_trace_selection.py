"""Shared trace/channel selection helpers for transform plugins.

Provides a reusable mixin that mirrors the curve-fit plugin's data-selection
behaviour:

* Simple mode selects a trace (and optional y-column) from ``_traces``.
* Advanced mode selects ``x``/``y`` arrays via expressions evaluated against
  the sequence-engine namespace.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QWidget

from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y

_DEFAULT_COLUMN_OPTION = "(default)"


class TraceChannelSelectionMixin:
    """Mixin providing curve-fit-style trace/channel data selection."""

    trace_key: str
    column_key: str
    advanced_mode: bool
    x_expr: str
    y_expr: str

    def _get_trace_columns(self, trace_key: str) -> list[str]:
        """Return DataFrame columns for a trace key, or an empty list."""
        traces = self.engine_namespace.get("_traces", {})
        if not trace_key or trace_key not in traces:
            return []
        try:
            trace_data = self.eval(traces[trace_key])
            cols = getattr(trace_data, "columns", None)
            if isinstance(cols, list):
                return cols
        except Exception:
            pass
        return []

    def _populate_column_combo(self, combo: QComboBox, trace_key: str) -> None:
        """Populate the column combo with ``(default)`` and trace columns."""
        columns = self._get_trace_columns(trace_key)
        combo.clear()
        combo.addItem(_DEFAULT_COLUMN_OPTION)
        combo.addItems(columns)
        if self.column_key and self.column_key in columns:
            combo.setCurrentText(self.column_key)
        else:
            combo.setCurrentText(_DEFAULT_COLUMN_OPTION)

    def _build_column_combo(self, widget: QWidget) -> QComboBox:
        """Build the trace-column selection combo box."""
        combo = QComboBox(widget)
        self._populate_column_combo(combo, self.trace_key)
        return combo

    def _create_data_source_widgets(
        self,
        widget: QWidget,
        traces: dict[str, str],
        *,
        show_column_selector: bool = True,
    ) -> dict[str, Any]:
        """Create trace/channel selection widgets for a transform data tab."""
        trace_keys = list(traces.keys())
        channel_items: dict[str, str] = {}
        for key, expr in traces.items():
            channel_items[f"{key} (x)"] = f"{expr}.x"
            channel_items[f"{key} (y)"] = f"{expr}.y"
        channel_names = list(channel_items.keys())

        trace_combo = QComboBox(widget)
        if trace_keys:
            trace_combo.addItems(trace_keys)
            if self.trace_key in trace_keys:
                trace_combo.setCurrentText(self.trace_key)
            else:
                self.trace_key = trace_keys[0]
        else:
            trace_combo.addItem("(no traces available)")

        column_combo = self._build_column_combo(widget) if show_column_selector else None

        advanced_check = QCheckBox(widget)
        advanced_check.setChecked(self.advanced_mode)

        x_combo = QComboBox(widget)
        if channel_names:
            x_combo.addItems(channel_names)
            if not _set_combo_to_expr(x_combo, channel_items, self.x_expr):
                self.x_expr = channel_items[channel_names[0]]
                x_combo.setCurrentIndex(0)
        else:
            x_combo.addItem("(no channels available)")

        y_combo = QComboBox(widget)
        if channel_names:
            y_combo.addItems(channel_names)
            if not _set_combo_to_expr(y_combo, channel_items, self.y_expr):
                default_y_index = next(
                    (index for index, name in enumerate(channel_names) if name.endswith(" (y)")),
                    0,
                )
                self.y_expr = channel_items[channel_names[default_y_index]]
                y_combo.setCurrentIndex(default_y_index)
        else:
            y_combo.addItem("(no channels available)")

        return {
            "trace_combo": trace_combo,
            "column_combo": column_combo,
            "advanced_check": advanced_check,
            "x_combo": x_combo,
            "y_combo": y_combo,
            "channel_items": channel_items,
        }

    def _add_data_selection_rows(
        self,
        layout: QFormLayout,
        ws: dict[str, Any],
        *,
        show_column_selector: bool = True,
    ) -> None:
        """Add common data selection rows to a form layout."""
        layout.addRow("Trace:", ws["trace_combo"])
        if show_column_selector and ws["column_combo"] is not None:
            layout.addRow("Column:", ws["column_combo"])
        layout.addRow("Advanced mode:", ws["advanced_check"])
        layout.addRow("X data:", ws["x_combo"])
        layout.addRow("Y data:", ws["y_combo"])
        layout.addRow(
            QLabel(
                "<i>In advanced mode, expressions are evaluated against the engine namespace at runtime.</i>",
            )
        )

    def _wire_data_source_widgets(
        self,
        ws: dict[str, Any],
        *,
        show_column_selector: bool = True,
        on_change: Any | None = None,
    ) -> None:
        """Connect widget signals so plugin selection attributes stay in sync."""

        def _trigger_change() -> None:
            if callable(on_change):
                on_change()

        def _apply_trace(text: str) -> None:
            if text != "(no traces available)":
                self.trace_key = text
                columns = self._get_trace_columns(self.trace_key)
                if show_column_selector and ws["column_combo"] is not None:
                    ws["column_combo"].blockSignals(True)
                    self._populate_column_combo(ws["column_combo"], self.trace_key)
                    if self.column_key not in columns:
                        self.column_key = ""
                        ws["column_combo"].setCurrentText(_DEFAULT_COLUMN_OPTION)
                    ws["column_combo"].blockSignals(False)
            _trigger_change()

        def _apply_column(text: str) -> None:
            if text != _DEFAULT_COLUMN_OPTION:
                self.column_key = text
            else:
                self.column_key = ""
            _trigger_change()

        def _apply_advanced(checked: bool) -> None:
            self.advanced_mode = checked
            _trigger_change()

        def _apply_x(text: str) -> None:
            if text != "(no channels available)":
                self.x_expr = ws["channel_items"].get(text, self.x_expr)
            _trigger_change()

        def _apply_y(text: str) -> None:
            if text != "(no channels available)":
                self.y_expr = ws["channel_items"].get(text, self.y_expr)
            _trigger_change()

        ws["trace_combo"].currentTextChanged.connect(_apply_trace)
        if show_column_selector and ws["column_combo"] is not None:
            ws["column_combo"].currentTextChanged.connect(_apply_column)
        ws["advanced_check"].toggled.connect(_apply_advanced)
        ws["x_combo"].currentTextChanged.connect(_apply_x)
        ws["y_combo"].currentTextChanged.connect(_apply_y)

        def _update_enabled(advanced: bool) -> None:
            ws["trace_combo"].setEnabled(not advanced)
            if show_column_selector and ws["column_combo"] is not None:
                ws["column_combo"].setEnabled(not advanced)
            ws["x_combo"].setEnabled(advanced)
            ws["y_combo"].setEnabled(advanced)

        _update_enabled(self.advanced_mode)
        ws["advanced_check"].toggled.connect(_update_enabled)

    def _get_selected_data_arrays(
        self,
    ) -> tuple[np.ndarray, np.ndarray, str, dict[str, str], dict[str, str]]:
        """Return selected ``x``/``y`` arrays plus selected column metadata."""
        y_col_name = "y"
        source_names: dict[str, str] = {}
        source_units: dict[str, str] = {}

        if self.advanced_mode:
            if not self.x_expr or not self.y_expr:
                raise ValueError("x_expr and y_expr must be set in advanced mode.")
            x_data = self.eval(self.x_expr)
            y_data = self.eval(self.y_expr)
        else:
            traces = self.engine_namespace.get("_traces", {})
            if not self.trace_key or self.trace_key not in traces:
                raise ValueError(f"Trace {self.trace_key!r} not found in _traces catalogue.")
            trace_expr = traces[self.trace_key]
            trace_data = self.eval(trace_expr)
            x_data = trace_data.x
            source_names = dict(getattr(trace_data, "names", {}))
            source_units = dict(getattr(trace_data, "units", {}))

            col = self.column_key
            y_cols = trace_data.get_columns_by_role(COLUMN_ROLE_Y)
            if col and hasattr(trace_data, "df") and col in trace_data.df.columns:
                y_data = trace_data.df[col].to_numpy(dtype=float)
                y_col_name = col
            else:
                y_data = trace_data.y
                y_col_name = y_cols[0] if y_cols else "y"

        return (
            np.asarray(x_data, dtype=float),
            np.asarray(y_data),
            y_col_name,
            source_names,
            source_units,
        )


def _set_combo_to_expr(
    combo: QComboBox,
    items: dict[str, str],
    expr: str,
) -> bool:
    """Set *combo* to the display entry mapped to *expr* and report success."""
    for display_name, item_expr in items.items():
        if item_expr == expr:
            combo.setCurrentText(display_name)
            return True
    return False
