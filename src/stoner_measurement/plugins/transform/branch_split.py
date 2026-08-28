"""Split a trace into rising-x and falling-x acquisition branches."""

from __future__ import annotations

from typing import Any

import numpy as np
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QWidget,
)

from stoner_measurement.core.trace_data import (
    COLUMN_ROLE_X,
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
)
from stoner_measurement.plugins.trace_catalog_ui import trace_target_column_items
from stoner_measurement.plugins.transform._branch_splitting import (
    DEFAULT_MINIMUM_BRANCH_LENGTH,
    DEFAULT_SMOOTHING_POLYORDER,
    DEFAULT_SMOOTHING_WINDOW,
    DEFAULT_TURNING_PROMINENCE,
    BranchSplittingMixin,
)
from stoner_measurement.plugins.transform._trace_selection import TraceChannelSelectionMixin
from stoner_measurement.plugins.transform.base import TransformPlugin
from stoner_measurement.ui.widgets import SISpinBox

CHANNELS_ALL = "all"
CHANNELS_SELECTED = "selected"
_CHANNEL_LABELS = {CHANNELS_ALL: "All channels", CHANNELS_SELECTED: "Selected channels"}


class BranchSplitPlugin(BranchSplittingMixin, TraceChannelSelectionMixin, TransformPlugin):
    """Create separate traces containing rows from rising and falling x branches."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.trace_key = ""
        self.column_key = ""
        self.advanced_mode = False
        self.x_expr = ""
        self.y_expr = ""
        self.channel_mode = CHANNELS_ALL
        self.x_channel_key = "x"
        self.channel_keys: list[str] = []
        self.rising_trace_name = "rising"
        self.falling_trace_name = "falling"
        self._init_branch_splitting()

    @property
    def name(self) -> str:
        return "Branch Split"

    @property
    def required_inputs(self) -> list[str]:
        return []

    @property
    def output_names(self) -> list[str]:
        return [self.rising_trace_name, self.falling_trace_name]

    @property
    def output_trace_names(self) -> list[str]:
        return self.output_names

    @property
    def output_value_names(self) -> list[str]:
        return []

    def transform(self, data: dict[str, Any]) -> dict[str, Any]:
        del data
        try:
            source = self._get_selected_trace_data()
            x_column = self._selected_x_column(source)
            x = source.df[x_column].to_numpy(dtype=float)
            if len(x) < 3 or not np.all(np.isfinite(x)):
                raise ValueError("The selected x channel requires at least three finite values.")
            columns = self._output_columns(source, x_column)
            rising_name, falling_name = self._validated_output_names()
            branches = self._split_branches(x)
            if {branch.direction for branch in branches} != {-1, 1}:
                raise ValueError("Could not identify both rising and falling x branches.")
            rising = np.concatenate([branch.indices for branch in branches if branch.direction > 0])
            falling = np.concatenate(
                [branch.indices for branch in branches if branch.direction < 0]
            )
            return {
                rising_name: self._subset_trace(source, columns, x_column, rising),
                falling_name: self._subset_trace(source, columns, x_column, falling),
            }
        except Exception as exc:
            self.log.error("BranchSplit: splitting failed — %s", exc)
            return {}

    def _selected_x_column(self, source: TraceData) -> str:
        default_x = source.get_columns_by_role(COLUMN_ROLE_X)
        if self.x_channel_key == "x":
            if len(default_x) != 1:
                raise ValueError("The source trace must contain exactly one x channel.")
            return default_x[0]
        primary_y = source.get_columns_by_role(COLUMN_ROLE_Y)
        column = primary_y[0] if self.x_channel_key == "" and primary_y else self.x_channel_key
        if column not in source.df.columns:
            raise ValueError("The selected x channel is not available in the source trace.")
        return column

    def _output_columns(self, source: TraceData, x_column: str) -> list[str]:
        if self.channel_mode == CHANNELS_ALL:
            return [x_column, *(column for column in source.columns if column != x_column)]
        primary_y = source.get_columns_by_role(COLUMN_ROLE_Y)
        resolved = [primary_y[0] if key == "" and primary_y else key for key in self.channel_keys]
        selected = [
            column for column in resolved if column in source.df.columns and column != x_column
        ]
        if not selected:
            raise ValueError("No selected output channels are available in the source trace.")
        return [x_column, *dict.fromkeys(selected)]

    @staticmethod
    def _subset_trace(
        source: TraceData, columns: list[str], x_column: str, indices: np.ndarray
    ) -> TraceData:
        roles = {column: source.column_roles[column] for column in columns}
        roles[x_column] = COLUMN_ROLE_X
        for column in columns:
            if column != x_column and roles[column] == COLUMN_ROLE_X:
                roles[column] = COLUMN_ROLE_Z
        return TraceData(
            source.df.iloc[indices].loc[:, columns],
            column_roles=roles,
            names={column: source.names[column] for column in columns},
            units={column: source.units[column] for column in columns},
        )

    def _validated_output_names(self) -> tuple[str, str]:
        rising = self.rising_trace_name.strip()
        falling = self.falling_trace_name.strip()
        if not rising or not falling or rising == falling:
            raise ValueError("Rising and falling output names must be non-empty and different.")
        return rising, falling

    def _build_data_tab(self, parent: QWidget | None = None) -> QWidget:
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        ws = self._create_data_source_widgets(
            widget, self.engine_namespace.get("_traces", {}), show_column_selector=False
        )
        layout.addRow("Trace:", ws["trace_combo"])
        channel_mode = QComboBox(widget)
        channel_mode.setObjectName("branch_split_channel_mode")
        for value, label in _CHANNEL_LABELS.items():
            channel_mode.addItem(label, value)
        channel_mode.setCurrentIndex(max(0, channel_mode.findData(self.channel_mode)))
        layout.addRow("Output:", channel_mode)
        x_channel = QComboBox(widget)
        x_channel.setObjectName("branch_split_x_channel")
        layout.addRow("Independent variable:", x_channel)
        channels = QListWidget(widget)
        channels.setObjectName("branch_split_channels")
        channels.setMaximumHeight(140)
        layout.addRow("Channels:", channels)
        rising_name = QLineEdit(self.rising_trace_name, widget)
        falling_name = QLineEdit(self.falling_trace_name, widget)
        rising_name.setObjectName("rising_trace_name")
        falling_name.setObjectName("falling_trace_name")
        layout.addRow("Rising trace name:", rising_name)
        layout.addRow("Falling trace name:", falling_name)
        updating = False

        def refresh() -> None:
            nonlocal updating
            updating = True
            items = trace_target_column_items(
                self, self.engine_namespace.get("_traces", {}), self.trace_key
            )
            x_channel.blockSignals(True)
            x_channel.clear()
            for label, key in items.items():
                x_channel.addItem(label, key)
            index = x_channel.findData(self.x_channel_key)
            if index < 0:
                self.x_channel_key = "x"
                index = x_channel.findData("x")
            x_channel.setCurrentIndex(max(0, index))
            x_channel.blockSignals(False)
            channels.clear()
            for label, key in items.items():
                if key in {"x", self.x_channel_key}:
                    continue
                item = QListWidgetItem(label, channels)
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                checked = self.channel_mode == CHANNELS_ALL or key in self.channel_keys
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            channels.setEnabled(self.channel_mode == CHANNELS_SELECTED)
            updating = False

        def apply_channels() -> None:
            if not updating and self.channel_mode == CHANNELS_SELECTED:
                self.channel_keys = [
                    str(channels.item(row).data(Qt.ItemDataRole.UserRole))
                    for row in range(channels.count())
                    if channels.item(row).checkState() == Qt.CheckState.Checked
                ]

        def apply_mode(_index: int) -> None:
            self.channel_mode = str(channel_mode.currentData())
            if self.channel_mode == CHANNELS_SELECTED and not self.channel_keys:
                self.channel_keys = [
                    str(channels.item(row).data(Qt.ItemDataRole.UserRole))
                    for row in range(channels.count())
                ]
            refresh()

        def apply_name(attribute: str, edit: QLineEdit, fallback: str) -> None:
            old = getattr(self, attribute)
            value = edit.text().strip() or fallback
            setattr(self, attribute, value)
            edit.setText(value)
            self.rename_trace_output(old, value)

        channel_mode.currentIndexChanged.connect(apply_mode)
        x_channel.currentIndexChanged.connect(
            lambda _index: (setattr(self, "x_channel_key", str(x_channel.currentData())), refresh())
        )
        channels.itemChanged.connect(lambda _item: apply_channels())
        rising_name.editingFinished.connect(
            lambda: apply_name("rising_trace_name", rising_name, "rising")
        )
        falling_name.editingFinished.connect(
            lambda: apply_name("falling_trace_name", falling_name, "falling")
        )
        self._wire_data_source_widgets(ws, show_column_selector=False, on_change=refresh)
        refresh()
        return widget

    def _build_advanced_tab(self, parent: QWidget | None = None) -> QWidget:
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        window = QSpinBox(widget)
        window.setRange(3, 1_000_001)
        window.setSingleStep(2)
        window.setValue(self.smoothing_window)
        polynomial = QSpinBox(widget)
        polynomial.setRange(0, 100)
        polynomial.setValue(self.smoothing_polyorder)
        prominence = SISpinBox(widget)
        prominence.setOpts(bounds=(0.0, 1.0), decimals=6, step=0.01)
        prominence.setValue(self.turning_point_prominence)
        minimum = QSpinBox(widget)
        minimum.setRange(2, 1_000_000)
        minimum.setValue(self.minimum_branch_length)
        layout.addRow("S-G window:", window)
        layout.addRow("S-G polynomial:", polynomial)
        layout.addRow("Turning-point prominence:", prominence)
        layout.addRow("Minimum branch length:", minimum)
        window.valueChanged.connect(lambda value: setattr(self, "smoothing_window", int(value)))
        polynomial.valueChanged.connect(
            lambda value: setattr(self, "smoothing_polyorder", int(value))
        )
        prominence.sigValueChanged.connect(
            lambda spin: setattr(self, "turning_point_prominence", float(spin.value()))
        )
        minimum.valueChanged.connect(
            lambda value: setattr(self, "minimum_branch_length", int(value))
        )
        return widget

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        def build_tabs() -> list[tuple[str, QWidget]]:
            tabs = super(BranchSplitPlugin, self).config_tabs(parent)
            tabs[0] = ("General", tabs[0][1])
            tabs.insert(1, ("Advanced", self._build_advanced_tab(parent)))
            return tabs

        return self._get_cached_config_tabs(build_tabs)

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data.update(
            {
                "trace_key": self.trace_key,
                "channel_mode": self.channel_mode,
                "x_channel_key": self.x_channel_key,
                "channel_keys": list(self.channel_keys),
                "rising_trace_name": self.rising_trace_name,
                "falling_trace_name": self.falling_trace_name,
            }
        )
        defaults = {
            "smoothing_window": DEFAULT_SMOOTHING_WINDOW,
            "smoothing_polyorder": DEFAULT_SMOOTHING_POLYORDER,
            "turning_point_prominence": DEFAULT_TURNING_PROMINENCE,
            "minimum_branch_length": DEFAULT_MINIMUM_BRANCH_LENGTH,
        }
        for key, default in defaults.items():
            if getattr(self, key) != default:
                data[key] = getattr(self, key)
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        self.trace_key = str(data.get("trace_key", ""))
        mode = str(data.get("channel_mode", CHANNELS_ALL))
        self.channel_mode = mode if mode in _CHANNEL_LABELS else CHANNELS_ALL
        self.x_channel_key = str(data.get("x_channel_key", "x"))
        keys = data.get("channel_keys", [])
        self.channel_keys = [str(key) for key in keys] if isinstance(keys, list) else []
        self.rising_trace_name = str(data.get("rising_trace_name", "rising"))
        self.falling_trace_name = str(data.get("falling_trace_name", "falling"))
        self.smoothing_window = int(data.get("smoothing_window", DEFAULT_SMOOTHING_WINDOW))
        self.smoothing_polyorder = int(data.get("smoothing_polyorder", DEFAULT_SMOOTHING_POLYORDER))
        self.turning_point_prominence = float(
            data.get("turning_point_prominence", DEFAULT_TURNING_PROMINENCE)
        )
        self.minimum_branch_length = int(
            data.get("minimum_branch_length", DEFAULT_MINIMUM_BRANCH_LENGTH)
        )
