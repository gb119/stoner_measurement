"""DataFrameTracePlugin — convert collected state-plugin DataFrames into traces."""

from __future__ import annotations

from collections.abc import Generator
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
    TracePlugin,
    TraceStatus,
)

_INDEX_X_SOURCE = "__index__"
_DEFAULT_CHANNEL_NAME = "DataFrame"


class DataFrameTracePlugin(TracePlugin):
    """Build a trace from a selected state plugin's collected :class:`pandas.DataFrame`."""

    def __init__(self, parent=None) -> None:
        """Initialise source and column-selection settings."""
        super().__init__(parent)
        self.source_plugin: str = ""
        self.x_source: str = _INDEX_X_SOURCE
        self.selected_columns: list[str] = []
        self._x_label_cache: str = "Index"

    @property
    def name(self) -> str:
        """Return plugin display name."""
        return "DataFrame Trace"

    @property
    def channel_names(self) -> list[str]:
        """Return the single output channel name."""
        return [self._channel_name()]

    @property
    def x_label(self) -> str:
        """Return display label for the x axis."""
        return self._x_label_cache

    @property
    def y_label(self) -> str:
        """Return display label for the primary y axis."""
        return "Value"

    def execute(self, parameters: dict[str, Any]) -> Generator[tuple[float, float]]:
        """Yield x/y pairs from the first selected column for compatibility."""
        del parameters
        trace = self.measure({})[self._channel_name()]
        y_columns = trace.get_columns_by_role(COLUMN_ROLE_Y)
        if not y_columns:
            return
        first_y = y_columns[0]
        x_arr = trace.x
        y_arr = trace.df[first_y].to_numpy(dtype=float)
        yield from zip(x_arr, y_arr)

    def measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Convert the selected source DataFrame into a multi-column trace."""
        del parameters
        self._set_status(TraceStatus.MEASURING)
        try:
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
            self._x_label_cache = x_label
            self.data = {
                channel_name: TraceData(
                    df=trace_df,
                    column_roles=column_roles,
                    names=names,
                    units=units,
                )
            }
            self._update_channel_statistics()
            return self.data
        finally:
            self._set_status(TraceStatus.DATA_AVAILABLE)

    def _available_dataframes(self) -> list[str]:
        """Return available state-plugin instance names that expose DataFrames."""
        values = self.engine_namespace.get("_dataframes", [])
        return [str(value) for value in values]

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
        selected = [column for column in self.selected_columns if column in available]
        if not selected:
            selected = available
            self.selected_columns = list(selected)
        return selected

    def _plugin_config_tabs(self) -> QWidget:
        """Build source-dataframe and column-selection settings controls."""
        widget = QWidget()
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

        def _current_source_dataframe() -> pd.DataFrame | None:
            source_name = self.source_plugin.strip()
            source_obj = self.engine_namespace.get(source_name)
            if source_obj is None:
                return None
            source_df = getattr(source_obj, "data", None)
            if isinstance(source_df, pd.DataFrame):
                return source_df
            return None

        def _populate_x_and_columns() -> None:
            source_df = _current_source_dataframe()

            x_combo.blockSignals(True)
            x_combo.clear()
            x_combo.addItem("Index", _INDEX_X_SOURCE)
            columns_list.clear()
            if source_df is not None and not source_df.empty:
                for column in source_df.columns:
                    column_name = str(column)
                    x_combo.addItem(column_name, column_name)
                selected_x = self.x_source if self.x_source in source_df.columns else _INDEX_X_SOURCE
                x_idx = x_combo.findData(selected_x)
                if x_idx >= 0:
                    x_combo.setCurrentIndex(x_idx)
                    self.x_source = selected_x
                for column in source_df.columns:
                    column_name = str(column)
                    if self.x_source != _INDEX_X_SOURCE and column_name == self.x_source:
                        continue
                    item = QListWidgetItem(column_name)
                    item.setSelected(column_name in self.selected_columns)
                    columns_list.addItem(item)
                if columns_list.count() > 0 and not self.selected_columns:
                    for row in range(columns_list.count()):
                        columns_list.item(row).setSelected(True)
                    self.selected_columns = [columns_list.item(row).text() for row in range(columns_list.count())]
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
