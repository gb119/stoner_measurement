"""Shared trace/channel selection helpers for transform plugins.

Provides a reusable mixin for transforms whose primary output is a trace:

* A source trace and target column are always selected from ``_traces``.
* Simple mode uses that trace's x axis and selected/default y column as inputs.
* Advanced mode keeps the same output trace/column context but obtains the
  calculation's ``x``/``y`` arrays from expressions evaluated against the
  sequence-engine namespace.
"""

from __future__ import annotations

import copy
from functools import partial
from typing import Any

import numpy as np
from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QWidget

from stoner_measurement.core.trace_data import COLUMN_ROLE_X, COLUMN_ROLE_Y, TraceData
from stoner_measurement.plugins.trace_catalog_ui import (
    TraceChannelComboBox,
    bind_trace_catalog_updates,
    bind_value_catalog_updates,
    refresh_trace_source_widgets,
    trace_channel_items,
    trace_channel_roles,
    trace_target_column_items,
)


class TraceChannelSelectionMixin:
    """Mixin separating output trace context from optional advanced inputs."""

    trace_key: str
    column_key: str
    advanced_mode: bool
    x_expr: str
    y_expr: str

    def _get_selected_trace_data(self) -> TraceData:
        """Resolve and return the source trace selected by :attr:`trace_key`."""
        traces = self.engine_namespace.get("_traces", {})
        if not self.trace_key or self.trace_key not in traces:
            raise ValueError(f"Trace {self.trace_key!r} not found in _traces catalogue.")
        trace_data = self.eval(traces[self.trace_key])
        if not isinstance(trace_data, TraceData):
            raise TypeError(f"Selected trace {self.trace_key!r} is not TraceData.")
        return trace_data

    def _selected_trace_column(self, trace_data: TraceData) -> str:
        """Return the selected target column, falling back to the primary y column."""
        if self.column_key and self.column_key in trace_data.df.columns:
            return self.column_key
        y_columns = trace_data.get_columns_by_role(COLUMN_ROLE_Y)
        if y_columns:
            return y_columns[0]
        if trace_data.columns:
            return trace_data.columns[0]
        raise ValueError(f"Selected trace {self.trace_key!r} has no data columns.")

    @staticmethod
    def _copy_trace_data(trace_data: TraceData) -> TraceData:
        """Return a fully independent copy of *trace_data*."""
        return copy.deepcopy(trace_data)

    def _populate_column_combo(self, combo: QComboBox, trace_key: str) -> None:
        """Populate the target combo with canonical labels for one trace."""
        traces = self.engine_namespace.get("_traces", {})
        items = trace_target_column_items(self, traces, trace_key)
        combo.clear()
        if not items:
            combo.addItem("(no channels available)", None)
            return
        for label, column_key in items.items():
            combo.addItem(label, column_key)
        target_key = self.column_key
        available_keys = list(items.values())
        if target_key not in available_keys:
            target_key = self._default_trace_column_key()
        if target_key not in available_keys:
            target_key = available_keys[0]
        combo.setCurrentIndex(combo.findData(target_key))
        self.column_key = target_key

    def _default_trace_column_key(self) -> str:
        """Return the target key selected when no persisted choice is available."""
        return ""

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
        show_advanced_inputs: bool = True,
    ) -> dict[str, Any]:
        """Create trace/channel selection widgets for a transform data tab."""
        trace_keys = list(traces.keys())
        channel_items = trace_channel_items(self, traces)
        channel_roles = trace_channel_roles(self, traces)

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

        advanced_check = None
        x_combo = None
        y_combo = None
        if show_advanced_inputs:
            advanced_check = QCheckBox(widget)
            advanced_check.setChecked(self.advanced_mode)

            x_combo = TraceChannelComboBox(widget)
            self.x_expr = x_combo.set_channels(
                channel_items,
                channel_roles,
                self.x_expr,
                preferred_role=COLUMN_ROLE_X,
            )

            y_combo = TraceChannelComboBox(widget)
            self.y_expr = y_combo.set_channels(
                channel_items,
                channel_roles,
                self.y_expr,
                preferred_role=COLUMN_ROLE_Y,
            )

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
        show_advanced_inputs: bool = True,
        on_change: Any | None = None,
    ) -> None:
        """Connect widget signals so plugin selection attributes stay in sync."""
        ws["trace_combo"].currentTextChanged.connect(
            partial(self._apply_trace_source, ws, show_column_selector, on_change)
        )
        if show_column_selector and ws["column_combo"] is not None:
            ws["column_combo"].currentIndexChanged.connect(
                partial(self._apply_column_source, ws["column_combo"], on_change)
            )
        if show_advanced_inputs:
            ws["advanced_check"].toggled.connect(partial(self._apply_advanced_source, on_change))
            ws["x_combo"].currentTextChanged.connect(
                partial(self._apply_channel_source, "x_expr", ws["channel_items"], on_change)
            )
            ws["y_combo"].currentTextChanged.connect(
                partial(self._apply_channel_source, "y_expr", ws["channel_items"], on_change)
            )

            update_enabled = partial(self._update_data_source_enabled, ws, show_column_selector)
            update_enabled(self.advanced_mode)
            ws["advanced_check"].toggled.connect(update_enabled)
        def _refresh_catalog(traces: dict[str, str]) -> None:
            refresh_trace_source_widgets(
                self,
                ws,
                traces,
                show_column_selector=show_column_selector,
                show_advanced_inputs=show_advanced_inputs,
                prefer_y_channel=True,
            )
            self._trigger_data_source_change(on_change)

        bind_trace_catalog_updates(
            self,
            ws["trace_combo"],
            _refresh_catalog,
        )
        bind_value_catalog_updates(
            self,
            ws["trace_combo"],
            lambda _values: _refresh_catalog(
                dict(self.engine_namespace.get("_traces", {}))
            ),
        )

    @staticmethod
    def _trigger_data_source_change(on_change: Any | None) -> None:
        """Notify a data-source configuration listener when one is present."""
        if callable(on_change):
            on_change()

    def _apply_trace_source(
        self,
        ws: dict[str, Any],
        show_column_selector: bool,
        on_change: Any | None,
        text: str,
    ) -> None:
        """Apply a trace selection and refresh its available columns."""
        if text != "(no traces available)":
            self.trace_key = text
            column_combo = ws["column_combo"]
            if show_column_selector and column_combo is not None:
                column_combo.blockSignals(True)
                self._populate_column_combo(column_combo, text)
                column_combo.blockSignals(False)
        self._trigger_data_source_change(on_change)

    def _apply_column_source(
        self, combo: QComboBox, on_change: Any | None, index: int
    ) -> None:
        """Apply a selected trace column."""
        column_key = combo.itemData(index)
        if column_key is not None:
            self.column_key = str(column_key)
        self._trigger_data_source_change(on_change)

    def _apply_advanced_source(self, on_change: Any | None, checked: bool) -> None:
        """Apply the advanced-mode selection."""
        self.advanced_mode = checked
        self._trigger_data_source_change(on_change)

    def _apply_channel_source(
        self,
        attribute: str,
        channel_items: dict[str, str],
        on_change: Any | None,
        text: str,
    ) -> None:
        """Apply an x or y channel expression selected by its display name."""
        if text != "(no channels available)":
            setattr(self, attribute, channel_items.get(text, getattr(self, attribute)))
        self._trigger_data_source_change(on_change)

    @staticmethod
    def _update_data_source_enabled(
        ws: dict[str, Any], show_column_selector: bool, advanced: bool
    ) -> None:
        """Keep the source trace active while toggling advanced array inputs."""
        ws["trace_combo"].setEnabled(True)
        if show_column_selector and ws["column_combo"] is not None:
            ws["column_combo"].setEnabled(True)
        ws["x_combo"].setEnabled(advanced)
        ws["y_combo"].setEnabled(advanced)

    def _get_selected_data_arrays(
        self,
    ) -> tuple[np.ndarray, np.ndarray, str, dict[str, str], dict[str, str], TraceData]:
        """Return input arrays together with their source-trace target context."""
        trace_data = self._get_selected_trace_data()
        y_col_name = self._selected_trace_column(trace_data)
        source_names = dict(trace_data.names)
        source_units = dict(trace_data.units)

        if self.advanced_mode:
            if not self.x_expr or not self.y_expr:
                raise ValueError("x_expr and y_expr must be set in advanced mode.")
            x_data = self.eval(self.x_expr)
            y_data = self.eval(self.y_expr)
        else:
            x_data = trace_data.x
            y_data = trace_data.df[y_col_name].to_numpy(dtype=float)

        return (
            np.asarray(x_data, dtype=float),
            np.asarray(y_data),
            y_col_name,
            source_names,
            source_units,
            trace_data,
        )
