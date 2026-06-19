"""DataFrameTracePlugin — convert collected state-plugin DataFrames into traces."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from stoner_measurement.plugins.trace.base import (
    COLUMN_ROLE_D,
    COLUMN_ROLE_E,
    COLUMN_ROLE_F,
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
)
from stoner_measurement.plugins.transform.base import TransformPlugin

_INDEX_X_SOURCE = "__index__"
_DEFAULT_CHANNEL_NAME = "DataFrame"
_ROLE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Data (y)", COLUMN_ROLE_Y),
    ("Y error (e)", COLUMN_ROLE_E),
    ("X error (d)", COLUMN_ROLE_D),
    ("Aux data (z)", COLUMN_ROLE_Z),
    ("Aux error (f)", COLUMN_ROLE_F),
)
_VALID_COLUMN_ROLES = {role for _, role in _ROLE_OPTIONS}


class DataFrameTracePlugin(TransformPlugin):
    """Build a trace from a selected state plugin's collected :class:`pandas.DataFrame`."""

    def __init__(self, parent=None) -> None:
        """Initialise source and column-selection settings."""
        super().__init__(parent)
        self.source_plugin: str = ""
        self.x_source: str = _INDEX_X_SOURCE
        self.selected_columns: list[str] = []
        self.selected_column_roles: dict[str, str] = {}

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
        column_roles = self._resolve_selected_column_roles(selected_columns)
        names: dict[str, str] = {"x": x_label}
        units: dict[str, str] = {"x": ""}
        for column in selected_columns:
            column_data = pd.to_numeric(source_df[column], errors="coerce").to_numpy(dtype=float)
            trace_df[column] = column_data
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

    def _resolve_selected_column_roles(
        self,
        selected_columns: list[str],
        configured_roles: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Return a validated role mapping for selected output columns."""
        configured = self.selected_column_roles if configured_roles is None else configured_roles
        roles: dict[str, str] = {}
        for ix, column in enumerate(selected_columns):
            configured_role = configured.get(column, "")
            default_role = COLUMN_ROLE_Y if ix == 0 else COLUMN_ROLE_Z
            if configured_role in _VALID_COLUMN_ROLES:
                roles[column] = configured_role
            else:
                roles[column] = default_role
        if selected_columns and all(role != COLUMN_ROLE_Y for role in roles.values()):
            roles[selected_columns[0]] = COLUMN_ROLE_Y
        self.selected_column_roles = dict(roles)
        return roles

    def _build_data_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build source-dataframe and column-selection settings controls."""
        widget = QWidget(parent)
        form = QFormLayout(widget)

        source_combo = QComboBox(widget)
        x_combo = QComboBox(widget)
        columns_table = QTableWidget(widget)
        columns_table.setColumnCount(3)
        columns_table.setHorizontalHeaderLabels(["Include", "Column", "Role"])
        columns_table.verticalHeader().setVisible(False)
        columns_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        columns_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        columns_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

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
            source_obj = self.engine_namespace.get(source_name)
            source_df = getattr(source_obj, "data", None)
            if isinstance(source_df, pd.DataFrame) and not source_df.empty:
                available_columns = [str(column) for column in source_df.columns]

            x_combo.blockSignals(True)
            x_combo.clear()
            x_combo.addItem("Index", _INDEX_X_SOURCE)
            columns_table.blockSignals(True)
            columns_table.setRowCount(0)
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
                selected_roles = self._resolve_selected_column_roles(self.selected_columns)
                columns_table.setRowCount(len(output_columns))
                for row, column_name in enumerate(output_columns):
                    include_item = QTableWidgetItem()
                    include_item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsSelectable
                    )
                    include_item.setCheckState(
                        Qt.CheckState.Checked
                        if column_name in self.selected_columns
                        else Qt.CheckState.Unchecked
                    )
                    columns_table.setItem(row, 0, include_item)

                    name_item = QTableWidgetItem(column_name)
                    name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    columns_table.setItem(row, 1, name_item)

                    role_combo = QComboBox(columns_table)
                    for role_label, role_value in _ROLE_OPTIONS:
                        role_combo.addItem(role_label, role_value)
                    role = selected_roles.get(column_name, COLUMN_ROLE_Z)
                    combo_index = role_combo.findData(role)
                    if combo_index < 0:
                        combo_index = role_combo.findData(COLUMN_ROLE_Z)
                    role_combo.setCurrentIndex(combo_index)

                    def _apply_role(
                        _index: int, *, col_name: str = column_name, combo: QComboBox = role_combo
                    ) -> None:
                        selected_role = combo.currentData()
                        if isinstance(selected_role, str):
                            self.selected_column_roles[col_name] = selected_role
                        _apply_selected_columns()

                    role_combo.currentIndexChanged.connect(_apply_role)
                    columns_table.setCellWidget(row, 2, role_combo)
            columns_table.blockSignals(False)
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
            selected: list[str] = []
            collected_roles: dict[str, str] = {}
            for row in range(columns_table.rowCount()):
                include_item = columns_table.item(row, 0)
                name_item = columns_table.item(row, 1)
                role_combo = columns_table.cellWidget(row, 2)
                if (
                    include_item is None
                    or name_item is None
                    or include_item.checkState() != Qt.CheckState.Checked
                    or not isinstance(role_combo, QComboBox)
                ):
                    continue
                col_name = name_item.text()
                role = role_combo.currentData()
                selected.append(col_name)
                collected_roles[col_name] = role if isinstance(role, str) else COLUMN_ROLE_Z
            self.selected_columns = selected
            self.selected_column_roles = self._resolve_selected_column_roles(selected, collected_roles)
            for row in range(columns_table.rowCount()):
                name_item = columns_table.item(row, 1)
                role_combo = columns_table.cellWidget(row, 2)
                if name_item is None or not isinstance(role_combo, QComboBox):
                    continue
                col_name = name_item.text()
                resolved_role = self.selected_column_roles.get(col_name)
                if resolved_role is None:
                    continue
                combo_index = role_combo.findData(resolved_role)
                if combo_index >= 0 and role_combo.currentIndex() != combo_index:
                    role_combo.blockSignals(True)
                    role_combo.setCurrentIndex(combo_index)
                    role_combo.blockSignals(False)

        _populate_source_combo()
        _populate_x_and_columns()

        source_combo.currentTextChanged.connect(_apply_source)
        x_combo.currentIndexChanged.connect(_apply_x)
        columns_table.itemChanged.connect(_apply_selected_columns)

        form.addRow("Source dataframe plugin:", source_combo)
        form.addRow("X source:", x_combo)
        form.addRow("Trace columns:", columns_table)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise plugin settings."""
        data = super().to_json()
        data["source_plugin"] = self.source_plugin
        data["x_source"] = self.x_source
        data["selected_columns"] = list(self.selected_columns)
        data["selected_column_roles"] = dict(self.selected_column_roles)
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
        raw_roles = data.get("selected_column_roles", {})
        if isinstance(raw_roles, dict):
            self.selected_column_roles = {
                str(column): str(role)
                for column, role in raw_roles.items()
                if str(role) in _VALID_COLUMN_ROLES
            }
        else:
            self.selected_column_roles = {}

    def _channel_name(self) -> str:
        """Return output channel name based on source selection."""
        source_name = self.source_plugin.strip()
        return source_name or _DEFAULT_CHANNEL_NAME
