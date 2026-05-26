"""DataFrameTracePlugin — convert collected state-plugin DataFrames into traces."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from stoner_measurement.plugins.trace.base import (
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
)
from stoner_measurement.plugins.transform.base import TransformPlugin

_INDEX_X_SOURCE = "__index__"
_DEFAULT_CHANNEL_NAME = "DataFrame"


class DataFrameTracePlugin(TransformPlugin):
    """Build a trace from a selected state plugin's collected :class:`pandas.DataFrame`."""

    def __init__(self, parent=None) -> None:
        """Initialise source and column-selection settings."""
        super().__init__(parent)
        self.source_plugin: str = ""
        self.x_source: str = _INDEX_X_SOURCE
        self.selected_columns: list[str] = []

    @property
    def name(self) -> str:
        """Return plugin display name."""
        return "DataFrame Trace"

    @property
    def required_inputs(self) -> list[str]:
        """No direct runtime inputs are required."""
        return []

    @property
    def output_names(self) -> list[str]:
        """Return all plugin output names."""
        return [self._channel_name()]

    @property
    def output_trace_names(self) -> list[str]:
        """Return the trace outputs produced by this plugin."""
        return [self._channel_name()]

    @property
    def output_value_names(self) -> list[str]:
        """This plugin does not report scalar outputs."""
        return []

    def transform(self, data: dict[str, Any]) -> dict[str, TraceData]:
        """Convert the selected source DataFrame into a multi-column trace."""
        del data
        source_name, source_df = self._resolve_source_dataframe()
        x_values, x_label = self._select_x_values(source_df)
        selected_columns = self._select_output_columns(source_df)

        trace_df = pd.DataFrame(index=pd.Index(np.asarray(x_values, dtype=float), name="x"))
        column_roles: dict[str, str] = {}
        names: dict[str, str] = {"x": x_label}
        units: dict[str, str] = {"x": ""}
        for ix, column in enumerate(selected_columns):
            column_data = pd.to_numeric(source_df[column], errors="coerce").to_numpy(dtype=float)
            trace_df[column] = column_data
            column_roles[column] = COLUMN_ROLE_Y if ix == 0 else COLUMN_ROLE_Z
            names[column] = column
            units[column] = ""

        channel_name = source_name or _DEFAULT_CHANNEL_NAME
        return {
            channel_name: TraceData(
                df=trace_df,
                column_roles=column_roles,
                names=names,
                units=units,
            )
        }

    def _dataframe_catalog(self) -> dict[str, list[str]]:
        """Return state-plugin dataframe metadata from the engine namespace."""
        raw_catalog = self.engine_namespace.get("_dataframes", {})
        if not isinstance(raw_catalog, dict):
            return {}
        catalog: dict[str, list[str]] = {}
        for key, columns in raw_catalog.items():
            if isinstance(columns, list):
                catalog[str(key)] = [str(column) for column in columns]
            else:
                catalog[str(key)] = []
        return catalog

    def _available_dataframes(self) -> list[str]:
        """Return available state-plugin instance names that expose DataFrames."""
        return list(self._dataframe_catalog().keys())

    def _catalog_columns_for_source(self, source_name: str) -> list[str]:
        """Return expected dataframe columns for *source_name* from the engine catalog."""
        return list(self._dataframe_catalog().get(source_name, []))

    def _resolve_source_dataframe(self) -> tuple[str, pd.DataFrame]:
        """Return the selected source plugin name and its collected DataFrame."""
        source_name = self.source_plugin.strip()
        available = self._available_dataframes()
        if not source_name and available:
            source_name = available[0]
            self.source_plugin = source_name
        if not source_name:
            raise ValueError("No source DataFrame plugin selected.")

        source_obj = self.engine_namespace.get(source_name)
        if source_obj is None:
            raise ValueError(f"Source plugin {source_name!r} is not available in the engine namespace.")

        source_df = getattr(source_obj, "data", None)
        if not isinstance(source_df, pd.DataFrame):
            raise ValueError(f"Source plugin {source_name!r} does not expose a pandas DataFrame.")
        if source_df.empty:
            raise ValueError(f"Source plugin {source_name!r} has an empty DataFrame.")
        return source_name, source_df

    def _select_x_values(self, source_df: pd.DataFrame) -> tuple[np.ndarray, str]:
        """Return the x-axis values and axis label from *source_df*."""
        if self.x_source and self.x_source != _INDEX_X_SOURCE:
            if self.x_source not in source_df.columns:
                raise ValueError(f"Selected x column {self.x_source!r} not found in source DataFrame.")
            x_values = pd.to_numeric(source_df[self.x_source], errors="coerce").to_numpy(dtype=float)
            return x_values, self.x_source
        return source_df.index.to_numpy(dtype=float), "Index"

    def _select_output_columns(self, source_df: pd.DataFrame) -> list[str]:
        """Return output columns to include in the converted trace."""
        excluded = {self.x_source} if self.x_source != _INDEX_X_SOURCE else set()
        available = [str(column) for column in source_df.columns if str(column) not in excluded]
        if not available:
            raise ValueError("No output columns available after applying x-axis selection.")
        seen: set[str] = set()
        selected = []
        for column in self.selected_columns:
            if column in available and column not in seen:
                selected.append(column)
                seen.add(column)
        if not selected:
            selected = available
            self.selected_columns = list(selected)
        return selected

    def _build_data_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build source-dataframe and column-selection settings controls."""
        widget = QWidget(parent)
        form = QFormLayout(widget)

        source_combo = QComboBox(widget)
        x_combo = QComboBox(widget)
        columns_list = QListWidget(widget)
        columns_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

        def _populate_source_combo() -> None:
            source_combo.blockSignals(True)
            source_combo.clear()
            sources = self._available_dataframes()
            if sources:
                source_combo.addItems(sources)
                if self.source_plugin in sources:
                    source_combo.setCurrentText(self.source_plugin)
                else:
                    self.source_plugin = sources[0]
                    source_combo.setCurrentIndex(0)
            else:
                source_combo.addItem("(no collected dataframes)")
            source_combo.blockSignals(False)

        def _populate_x_and_columns() -> None:
            source_name = self.source_plugin.strip()
            available_columns = self._catalog_columns_for_source(source_name)
            if not available_columns:
                source_obj = self.engine_namespace.get(source_name)
                source_df = getattr(source_obj, "data", None)
                if isinstance(source_df, pd.DataFrame):
                    available_columns = [str(column) for column in source_df.columns]

            x_combo.blockSignals(True)
            x_combo.clear()
            x_combo.addItem("Index", _INDEX_X_SOURCE)
            columns_list.clear()
            if available_columns:
                for column_name in available_columns:
                    x_combo.addItem(column_name, column_name)
                selected_x = self.x_source if self.x_source in available_columns else _INDEX_X_SOURCE
                x_idx = x_combo.findData(selected_x)
                if x_idx >= 0:
                    x_combo.setCurrentIndex(x_idx)
                    self.x_source = selected_x
                output_columns = [
                    column
                    for column in available_columns
                    if self.x_source == _INDEX_X_SOURCE or column != self.x_source
                ]
                seen: set[str] = set()
                selected_columns = []
                for column in self.selected_columns:
                    if column in output_columns and column not in seen:
                        selected_columns.append(column)
                        seen.add(column)
                if not selected_columns:
                    selected_columns = list(output_columns)
                self.selected_columns = selected_columns
                for column_name in output_columns:
                    if self.x_source != _INDEX_X_SOURCE and column_name == self.x_source:
                        continue
                    item = QListWidgetItem(column_name)
                    columns_list.addItem(item)
                    item.setSelected(column_name in self.selected_columns)
            x_combo.blockSignals(False)

        def _apply_source(text: str) -> None:
            if text != "(no collected dataframes)":
                self.source_plugin = text
                _populate_x_and_columns()

        def _apply_x(index: int) -> None:
            data = x_combo.itemData(index)
            if isinstance(data, str):
                self.x_source = data
                _populate_x_and_columns()

        def _apply_selected_columns() -> None:
            self.selected_columns = [
                columns_list.item(row).text() for row in range(columns_list.count()) if columns_list.item(row).isSelected()
            ]

        _populate_source_combo()
        _populate_x_and_columns()

        source_combo.currentTextChanged.connect(_apply_source)
        x_combo.currentIndexChanged.connect(_apply_x)
        columns_list.itemSelectionChanged.connect(_apply_selected_columns)

        form.addRow("Source dataframe plugin:", source_combo)
        form.addRow("X source:", x_combo)
        form.addRow("Trace columns:", columns_list)
        widget.setLayout(form)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise plugin settings."""
        data = super().to_json()
        data["source_plugin"] = self.source_plugin
        data["x_source"] = self.x_source
        data["selected_columns"] = list(self.selected_columns)
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore plugin settings from JSON data."""
        super()._restore_from_json(data)
        self.source_plugin = str(data.get("source_plugin", ""))
        self.x_source = str(data.get("x_source", _INDEX_X_SOURCE))
        raw_columns = data.get("selected_columns", [])
        if isinstance(raw_columns, list):
            self.selected_columns = [str(column) for column in raw_columns]
        else:
            self.selected_columns = []

    def _channel_name(self) -> str:
        """Return output channel name based on source selection."""
        source_name = self.source_plugin.strip()
        return source_name or _DEFAULT_CHANNEL_NAME
