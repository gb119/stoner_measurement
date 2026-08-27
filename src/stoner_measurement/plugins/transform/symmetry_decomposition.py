"""Symmetric and antisymmetric decomposition of irregular trace data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
from stoner_measurement.plugins.transform._trace_selection import TraceChannelSelectionMixin
from stoner_measurement.plugins.transform.base import TransformPlugin
from stoner_measurement.ui.widgets import SISpinBox

MODE_AUTO = "auto"
MODE_NON_HYSTERETIC = "non_hysteretic"
MODE_HYSTERETIC = "hysteretic"

CHANNELS_ALL = "all"
CHANNELS_SELECTED = "selected"

INTERPOLATION_PCHIP = "pchip"
INTERPOLATION_LINEAR = "linear"

OUT_OF_RANGE_NAN = "nan"
OUT_OF_RANGE_NEAREST = "nearest"
OUT_OF_RANGE_EXTRAPOLATE = "extrapolate"

DEFAULT_SMOOTHING_WINDOW = 11
DEFAULT_SMOOTHING_POLYORDER = 2
DEFAULT_TURNING_PROMINENCE = 0.01
DEFAULT_MINIMUM_BRANCH_LENGTH = 10
DEFAULT_INTERPOLATION = INTERPOLATION_PCHIP
DEFAULT_OUT_OF_RANGE = OUT_OF_RANGE_NAN

_MODE_LABELS = {
    MODE_AUTO: "Auto-detect hysteresis",
    MODE_NON_HYSTERETIC: "Non-hysteretic",
    MODE_HYSTERETIC: "Hysteretic branches",
}
_CHANNEL_LABELS = {
    CHANNELS_ALL: "All data channels",
    CHANNELS_SELECTED: "Selected channels",
}
_INTERPOLATION_LABELS = {
    INTERPOLATION_PCHIP: "Shape-preserving PCHIP",
    INTERPOLATION_LINEAR: "Linear",
}
_OUT_OF_RANGE_LABELS = {
    OUT_OF_RANGE_NAN: "NaN (recommended)",
    OUT_OF_RANGE_NEAREST: "Nearest boundary value",
    OUT_OF_RANGE_EXTRAPOLATE: "Extrapolate",
}


@dataclass(frozen=True)
class _Branch:
    """One monotonic acquisition-order branch."""

    indices: np.ndarray
    direction: int


class SymmetryDecompositionPlugin(TraceChannelSelectionMixin, TransformPlugin):
    """Decompose selected trace channels into symmetric and antisymmetric parts.

    For non-hysteretic data, the plugin interpolates each selected channel and
    evaluates it at ``-x``. For hysteretic data, it smooths x in acquisition
    order, locates prominent turning points, splits the trace into monotonic
    branches, and mirrors each branch against the best-overlapping branch with
    the opposite direction. Output rows retain the original acquisition order.

    The General tab places the instance name and comment first, followed by
    the input trace, processing mode, channel scope, and output trace names.
    The Advanced tab configures turning-point detection,
    interpolation, and out-of-range behavior. Advanced settings are omitted
    from JSON when they retain their defaults.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.trace_key: str = ""
        self.column_key: str = ""
        self.advanced_mode: bool = False
        self.x_expr: str = ""
        self.y_expr: str = ""

        self.mode: str = MODE_AUTO
        self.channel_mode: str = CHANNELS_ALL
        self.x_channel_key: str = "x"
        self.channel_keys: list[str] = []
        self.symmetric_trace_name: str = "symmetric"
        self.antisymmetric_trace_name: str = "antisymmetric"

        self.smoothing_window: int = DEFAULT_SMOOTHING_WINDOW
        self.smoothing_polyorder: int = DEFAULT_SMOOTHING_POLYORDER
        self.turning_point_prominence: float = DEFAULT_TURNING_PROMINENCE
        self.minimum_branch_length: int = DEFAULT_MINIMUM_BRANCH_LENGTH
        self.interpolation: str = DEFAULT_INTERPOLATION
        self.out_of_range: str = DEFAULT_OUT_OF_RANGE

        self.turning_points: list[int] = []
        self.branch_directions: list[int] = []

    @property
    def name(self) -> str:
        return "Symmetry Decomposition"

    @property
    def required_inputs(self) -> list[str]:
        return []

    @property
    def output_names(self) -> list[str]:
        return [self.symmetric_trace_name, self.antisymmetric_trace_name]

    @property
    def output_trace_names(self) -> list[str]:
        return self.output_names

    @property
    def output_value_names(self) -> list[str]:
        return []

    def reported_traces(self) -> dict[str, str]:
        """Report custom output keys using safely quoted data expressions."""
        var = self.instance_name
        return {f"{var}:{name}": f"{var}.data[{name!r}]" for name in self.output_trace_names}

    def transform(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return symmetric and antisymmetric copies of the selected trace."""
        del data
        try:
            source = self._get_selected_trace_data()
            x_column = self._selected_x_column(source)
            x = source.df[x_column].to_numpy(dtype=float)
            columns = self._selected_columns(source)
            self._validate_input(x, source.row_count, columns)
            output_names = self._validated_output_names()
            branches = self._analysis_branches(x)

            symmetric = self._build_output_trace(source, x_column, columns)
            antisymmetric = self._build_output_trace(source, x_column, columns)
            for column in columns:
                y = source.df[column].to_numpy(dtype=float)
                sym, anti = self._decompose_channel(x, y, branches)
                symmetric.df[column] = sym
                antisymmetric.df[column] = anti
                base_name = source.names.get(column, column)
                symmetric.names[column] = f"Symmetric {base_name}"
                antisymmetric.names[column] = f"Antisymmetric {base_name}"
        except Exception as exc:
            self.log.error("SymmetryDecomposition: decomposition failed — %s", exc)
            return {}

        return {output_names[0]: symmetric, output_names[1]: antisymmetric}

    def _build_output_trace(
        self, source: TraceData, x_column: str, columns: list[str]
    ) -> TraceData:
        """Return an output trace containing the configured channel scope."""
        if self.channel_mode == CHANNELS_ALL:
            return self._copy_trace_data(source)

        output_columns = [x_column, *columns]
        roles = {column: source.column_roles[column] for column in output_columns}
        roles[x_column] = COLUMN_ROLE_X
        return TraceData(
            source.df.loc[:, output_columns],
            column_roles=roles,
            names={column: source.names[column] for column in output_columns},
            units={column: source.units[column] for column in output_columns},
        )

    def _selected_x_column(self, source: TraceData) -> str:
        """Resolve the configured x-axis choice against a live trace."""
        default_x = source.get_columns_by_role(COLUMN_ROLE_X)
        primary_y = source.get_columns_by_role(COLUMN_ROLE_Y)
        if self.channel_mode != CHANNELS_SELECTED or self.x_channel_key == "x":
            if len(default_x) != 1:
                raise ValueError("The source trace must contain exactly one x channel.")
            return default_x[0]
        column = primary_y[0] if self.x_channel_key == "" and primary_y else self.x_channel_key
        if column not in source.df.columns:
            raise ValueError("The selected x channel is not available in the source trace.")
        return column

    def _channel_items_for_ui(self) -> dict[str, str]:
        """Return selectable y/z channel labels for the current source trace."""
        items = trace_target_column_items(
            self, self.engine_namespace.get("_traces", {}), self.trace_key
        )
        try:
            source = self._get_selected_trace_data()
        except Exception:
            return {label: key for label, key in items.items() if key != "x"}
        if not any(
            source.column_roles.get(column) in {COLUMN_ROLE_Y, COLUMN_ROLE_Z}
            for column in source.df.columns
        ):
            allowed = {
                column
                for column, role in source.expected_column_roles.items()
                if role in {COLUMN_ROLE_Y, COLUMN_ROLE_Z}
            }
            primary_y = [
                column
                for column, role in source.expected_column_roles.items()
                if role == COLUMN_ROLE_Y
            ]
            return {
                label: key
                for label, key in items.items()
                if (primary_y[0] if key == "" and primary_y else key) in allowed
            }
        allowed = {
            column
            for column in source.df.columns
            if source.column_roles.get(column) in {COLUMN_ROLE_Y, COLUMN_ROLE_Z}
        }
        primary_y = source.get_columns_by_role(COLUMN_ROLE_Y)
        return {
            label: key
            for label, key in items.items()
            if (primary_y[0] if key == "" and primary_y else key) in allowed
        }

    def _selected_columns(self, source) -> list[str]:
        """Resolve the configured source columns against a live trace."""
        allowed = [
            column
            for column in source.df.columns
            if source.column_roles.get(column) in {COLUMN_ROLE_Y, COLUMN_ROLE_Z}
        ]
        if self.channel_mode == CHANNELS_ALL:
            return allowed

        primary_y = source.get_columns_by_role(COLUMN_ROLE_Y)
        resolved = [primary_y[0] if key == "" and primary_y else key for key in self.channel_keys]
        selected_x = self._selected_x_column(source)
        selected = [column for column in resolved if column in allowed]
        selected = [column for column in selected if column != selected_x]
        if not selected:
            raise ValueError("No selected data channels are available in the source trace.")
        return list(dict.fromkeys(selected))

    @staticmethod
    def _validate_input(x: np.ndarray, row_count: int, columns: list[str]) -> None:
        if x.ndim != 1 or len(x) != row_count:
            raise ValueError("The source x data must be a one-dimensional row-aligned array.")
        if len(x) < 2:
            raise ValueError("At least two data points are required.")
        if not np.all(np.isfinite(x)):
            raise ValueError("The source x data contains non-finite values.")
        if not columns:
            raise ValueError("The source trace has no processable data channels.")

    def _validated_output_names(self) -> tuple[str, str]:
        symmetric = self.symmetric_trace_name.strip()
        antisymmetric = self.antisymmetric_trace_name.strip()
        if not symmetric or not antisymmetric:
            raise ValueError("Both output trace names must be non-empty.")
        if symmetric == antisymmetric:
            raise ValueError("Symmetric and antisymmetric output trace names must differ.")
        return symmetric, antisymmetric

    def _analysis_branches(self, x: np.ndarray) -> list[_Branch] | None:
        """Return branch definitions, or ``None`` for global interpolation."""
        self.turning_points = []
        self.branch_directions = []
        if self.mode == MODE_NON_HYSTERETIC:
            return None

        branches, turning_points = _detect_branches(
            x,
            smoothing_window=self.smoothing_window,
            smoothing_polyorder=self.smoothing_polyorder,
            prominence_fraction=self.turning_point_prominence,
            minimum_length=self.minimum_branch_length,
        )
        usable = len(branches) >= 2 and {branch.direction for branch in branches} == {-1, 1}
        if not usable:
            if self.mode == MODE_HYSTERETIC:
                raise ValueError("Could not identify both rising and falling x branches.")
            return None
        self.turning_points = turning_points
        self.branch_directions = [branch.direction for branch in branches]
        return branches

    def _decompose_channel(
        self, x: np.ndarray, y: np.ndarray, branches: list[_Branch] | None
    ) -> tuple[np.ndarray, np.ndarray]:
        if branches is None:
            mirror = self._interpolate(x, y, -x)
        else:
            mirror = np.full(len(x), np.nan, dtype=float)
            for index, branch in enumerate(branches):
                counterpart = _best_counterpart(index, branches, x)
                target_x = x[counterpart.indices]
                target_y = y[counterpart.indices]
                mirror[branch.indices] = self._interpolate(target_x, target_y, -x[branch.indices])
        return 0.5 * (y + mirror), 0.5 * (y - mirror)

    def _interpolate(
        self, source_x: np.ndarray, source_y: np.ndarray, query_x: np.ndarray
    ) -> np.ndarray:
        unique_x, unique_y = _consolidate_duplicate_x(source_x, source_y)
        if len(unique_x) < 2:
            return np.full(len(query_x), np.nan, dtype=float)
        interpolator = _make_interpolator(
            unique_x,
            unique_y,
            method=self.interpolation,
            out_of_range=self.out_of_range,
        )
        return np.asarray(interpolator(query_x), dtype=float)

    def _build_data_tab(self, parent: QWidget | None = None) -> QWidget:
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        traces = self.engine_namespace.get("_traces", {})
        ws = self._create_data_source_widgets(widget, traces, show_column_selector=False)
        layout.addRow("Trace:", ws["trace_combo"])

        mode_combo = QComboBox(widget)
        mode_combo.setObjectName("symmetry_mode")
        for value, label in _MODE_LABELS.items():
            mode_combo.addItem(label, value)
        mode_combo.setCurrentIndex(max(0, mode_combo.findData(self.mode)))
        layout.addRow("Mode:", mode_combo)

        channel_mode = QComboBox(widget)
        channel_mode.setObjectName("symmetry_channel_mode")
        for value, label in _CHANNEL_LABELS.items():
            channel_mode.addItem(label, value)
        channel_mode.setCurrentIndex(max(0, channel_mode.findData(self.channel_mode)))
        layout.addRow("Process:", channel_mode)

        x_channel = QComboBox(widget)
        x_channel.setObjectName("symmetry_x_channel")
        layout.addRow("X channel:", x_channel)

        channel_list = QListWidget(widget)
        channel_list.setObjectName("symmetry_channels")
        channel_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        channel_list.setMaximumHeight(140)
        layout.addRow("Channels:", channel_list)

        symmetric_name = QLineEdit(self.symmetric_trace_name, widget)
        symmetric_name.setObjectName("symmetric_trace_name")
        antisymmetric_name = QLineEdit(self.antisymmetric_trace_name, widget)
        antisymmetric_name.setObjectName("antisymmetric_trace_name")
        layout.addRow("Symmetric trace name:", symmetric_name)
        layout.addRow("Antisymmetric trace name:", antisymmetric_name)

        updating_channels = False

        def refresh_channels() -> None:
            nonlocal updating_channels
            updating_channels = True
            channel_list.clear()
            all_items = trace_target_column_items(
                self, self.engine_namespace.get("_traces", {}), self.trace_key
            )
            x_channel.blockSignals(True)
            x_channel.clear()
            for label, key in all_items.items():
                x_channel.addItem(label, key)
            selected_x_index = x_channel.findData(self.x_channel_key)
            if selected_x_index < 0:
                self.x_channel_key = "x"
                selected_x_index = x_channel.findData("x")
            x_channel.setCurrentIndex(max(0, selected_x_index))
            x_channel.setEnabled(self.channel_mode == CHANNELS_SELECTED)
            x_channel.blockSignals(False)

            items = self._channel_items_for_ui()
            for label, key in items.items():
                if key in {"x", self.x_channel_key}:
                    continue
                item = QListWidgetItem(label, channel_list)
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                checked = self.channel_mode == CHANNELS_ALL or key in self.channel_keys
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            channel_list.setEnabled(self.channel_mode == CHANNELS_SELECTED)
            updating_channels = False

        def apply_selected_channels() -> None:
            if updating_channels or self.channel_mode != CHANNELS_SELECTED:
                return
            self.channel_keys = [
                str(channel_list.item(row).data(Qt.ItemDataRole.UserRole))
                for row in range(channel_list.count())
                if channel_list.item(row).checkState() == Qt.CheckState.Checked
            ]

        def apply_channel_mode(_index: int) -> None:
            self.channel_mode = str(channel_mode.currentData())
            if self.channel_mode == CHANNELS_SELECTED and not self.channel_keys:
                self.channel_keys = [
                    str(channel_list.item(row).data(Qt.ItemDataRole.UserRole))
                    for row in range(channel_list.count())
                ]
            refresh_channels()

        def apply_x_channel(_index: int) -> None:
            self.x_channel_key = str(x_channel.currentData())
            refresh_channels()

        def apply_output_name(attribute: str, edit: QLineEdit, fallback: str) -> None:
            previous = getattr(self, attribute)
            value = edit.text().strip() or fallback
            setattr(self, attribute, value)
            edit.setText(value)
            self.rename_trace_output(previous, value)

        mode_combo.currentIndexChanged.connect(
            lambda _index: setattr(self, "mode", str(mode_combo.currentData()))
        )
        channel_mode.currentIndexChanged.connect(apply_channel_mode)
        x_channel.currentIndexChanged.connect(apply_x_channel)
        channel_list.itemChanged.connect(lambda _item: apply_selected_channels())
        symmetric_name.editingFinished.connect(
            lambda: apply_output_name("symmetric_trace_name", symmetric_name, "symmetric")
        )
        antisymmetric_name.editingFinished.connect(
            lambda: apply_output_name(
                "antisymmetric_trace_name",
                antisymmetric_name,
                "antisymmetric",
            )
        )
        self._wire_data_source_widgets(ws, show_column_selector=False, on_change=refresh_channels)
        refresh_channels()
        return widget

    def _build_advanced_tab(self, parent: QWidget | None = None) -> QWidget:
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        window = QSpinBox(widget)
        window.setObjectName("symmetry_smoothing_window")
        window.setRange(3, 1_000_001)
        window.setSingleStep(2)
        window.setValue(self.smoothing_window)
        polynomial = QSpinBox(widget)
        polynomial.setObjectName("symmetry_smoothing_polyorder")
        polynomial.setRange(0, 100)
        polynomial.setValue(self.smoothing_polyorder)
        prominence = SISpinBox(widget)
        prominence.setObjectName("symmetry_turning_prominence")
        prominence.setOpts(bounds=(0.0, 1.0), decimals=6, step=0.01)
        prominence.setValue(self.turning_point_prominence)
        prominence.setToolTip("Fraction of the robust x range required for a turning point.")
        minimum_length = QSpinBox(widget)
        minimum_length.setObjectName("symmetry_minimum_branch_length")
        minimum_length.setRange(2, 1_000_000)
        minimum_length.setValue(self.minimum_branch_length)

        interpolation = QComboBox(widget)
        interpolation.setObjectName("symmetry_interpolation")
        for value, label in _INTERPOLATION_LABELS.items():
            interpolation.addItem(label, value)
        interpolation.setCurrentIndex(max(0, interpolation.findData(self.interpolation)))

        out_of_range = QComboBox(widget)
        out_of_range.setObjectName("symmetry_out_of_range")
        for value, label in _OUT_OF_RANGE_LABELS.items():
            out_of_range.addItem(label, value)
        out_of_range.setCurrentIndex(max(0, out_of_range.findData(self.out_of_range)))

        layout.addRow("S-G window:", window)
        layout.addRow("S-G polynomial:", polynomial)
        layout.addRow("Turning-point prominence:", prominence)
        layout.addRow("Minimum branch length:", minimum_length)
        layout.addRow("Interpolation:", interpolation)
        layout.addRow("Out of range:", out_of_range)

        window.valueChanged.connect(lambda value: setattr(self, "smoothing_window", int(value)))
        polynomial.valueChanged.connect(
            lambda value: setattr(self, "smoothing_polyorder", int(value))
        )
        prominence.sigValueChanged.connect(
            lambda spin: setattr(self, "turning_point_prominence", float(spin.value()))
        )
        minimum_length.valueChanged.connect(
            lambda value: setattr(self, "minimum_branch_length", int(value))
        )
        interpolation.currentIndexChanged.connect(
            lambda _index: setattr(self, "interpolation", str(interpolation.currentData()))
        )
        out_of_range.currentIndexChanged.connect(
            lambda _index: setattr(self, "out_of_range", str(out_of_range.currentData()))
        )
        return widget

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        def build_tabs() -> list[tuple[str, QWidget]]:
            tabs = super(SymmetryDecompositionPlugin, self).config_tabs(parent)
            tabs[0] = ("General", tabs[0][1])
            tabs.insert(1, ("Advanced", self._build_advanced_tab(parent)))
            return tabs

        return self._get_cached_config_tabs(build_tabs)

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data.update(
            {
                "trace_key": self.trace_key,
                "mode": self.mode,
                "channel_mode": self.channel_mode,
                "x_channel_key": self.x_channel_key,
                "channel_keys": list(self.channel_keys),
                "symmetric_trace_name": self.symmetric_trace_name,
                "antisymmetric_trace_name": self.antisymmetric_trace_name,
            }
        )
        defaults = {
            "smoothing_window": DEFAULT_SMOOTHING_WINDOW,
            "smoothing_polyorder": DEFAULT_SMOOTHING_POLYORDER,
            "turning_point_prominence": DEFAULT_TURNING_PROMINENCE,
            "minimum_branch_length": DEFAULT_MINIMUM_BRANCH_LENGTH,
            "interpolation": DEFAULT_INTERPOLATION,
            "out_of_range": DEFAULT_OUT_OF_RANGE,
        }
        for key, default in defaults.items():
            value = getattr(self, key)
            if value != default:
                data[key] = value
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        self.trace_key = str(data.get("trace_key", ""))
        mode = str(data.get("mode", MODE_AUTO))
        self.mode = mode if mode in _MODE_LABELS else MODE_AUTO
        channel_mode = str(data.get("channel_mode", CHANNELS_ALL))
        self.channel_mode = channel_mode if channel_mode in _CHANNEL_LABELS else CHANNELS_ALL
        self.x_channel_key = str(data.get("x_channel_key", "x"))
        keys = data.get("channel_keys", [])
        self.channel_keys = [str(key) for key in keys] if isinstance(keys, list) else []
        self.symmetric_trace_name = str(data.get("symmetric_trace_name", "symmetric"))
        self.antisymmetric_trace_name = str(data.get("antisymmetric_trace_name", "antisymmetric"))
        self.smoothing_window = int(data.get("smoothing_window", DEFAULT_SMOOTHING_WINDOW))
        self.smoothing_polyorder = int(data.get("smoothing_polyorder", DEFAULT_SMOOTHING_POLYORDER))
        self.turning_point_prominence = float(
            data.get("turning_point_prominence", DEFAULT_TURNING_PROMINENCE)
        )
        self.minimum_branch_length = int(
            data.get("minimum_branch_length", DEFAULT_MINIMUM_BRANCH_LENGTH)
        )
        interpolation = str(data.get("interpolation", DEFAULT_INTERPOLATION))
        self.interpolation = (
            interpolation if interpolation in _INTERPOLATION_LABELS else DEFAULT_INTERPOLATION
        )
        out_of_range = str(data.get("out_of_range", DEFAULT_OUT_OF_RANGE))
        self.out_of_range = (
            out_of_range if out_of_range in _OUT_OF_RANGE_LABELS else DEFAULT_OUT_OF_RANGE
        )


def _detect_branches(
    x: np.ndarray,
    *,
    smoothing_window: int,
    smoothing_polyorder: int,
    prominence_fraction: float,
    minimum_length: int,
) -> tuple[list[_Branch], list[int]]:
    """Smooth x and split it at prominent acquisition-order extrema."""
    from scipy.signal import find_peaks, savgol_filter  # type: ignore[import-untyped]  # noqa: PLC0415, I001

    n_points = len(x)
    if n_points < 3:
        return [], []
    window = _valid_savgol_window(smoothing_window, n_points)
    polyorder = min(max(0, int(smoothing_polyorder)), window - 1)
    smoothed = savgol_filter(x, window, polyorder, mode="interp")
    robust_span = float(np.percentile(smoothed, 95) - np.percentile(smoothed, 5))
    span = robust_span if robust_span > 0.0 else float(np.ptp(smoothed))
    prominence = max(0.0, float(prominence_fraction)) * span
    distance = max(2, int(minimum_length))
    peaks, peak_info = find_peaks(smoothed, prominence=prominence, distance=distance)
    troughs, trough_info = find_peaks(-smoothed, prominence=prominence, distance=distance)
    candidates = [
        (int(index), 1, float(value))
        for index, value in zip(peaks, peak_info["prominences"], strict=True)
    ]
    candidates.extend(
        (int(index), -1, float(value))
        for index, value in zip(troughs, trough_info["prominences"], strict=True)
    )
    candidates.sort()
    alternating: list[tuple[int, int, float]] = []
    for candidate in candidates:
        if alternating and candidate[1] == alternating[-1][1]:
            if candidate[2] > alternating[-1][2]:
                alternating[-1] = candidate
        else:
            alternating.append(candidate)

    turns = [item[0] for item in alternating]
    turns = _remove_short_segments(turns, n_points, distance)
    boundaries = [0, *(turn + 1 for turn in turns), n_points]
    branches: list[_Branch] = []
    for start, stop in zip(boundaries[:-1], boundaries[1:], strict=True):
        indices: np.ndarray = np.arange(start, stop, dtype=int)
        if len(indices) < 2:
            continue
        delta = float(smoothed[indices[-1]] - smoothed[indices[0]])
        if delta == 0.0:
            continue
        branches.append(_Branch(indices=indices, direction=1 if delta > 0.0 else -1))
    return branches, turns


def _valid_savgol_window(requested: int, n_points: int) -> int:
    window = max(3, int(requested))
    if window % 2 == 0:
        window += 1
    if window > n_points:
        window = n_points if n_points % 2 else n_points - 1
    return max(3, window)


def _remove_short_segments(turns: list[int], n_points: int, minimum: int) -> list[int]:
    retained = list(turns)
    while retained:
        boundaries = [0, *(turn + 1 for turn in retained), n_points]
        lengths = np.diff(np.asarray(boundaries, dtype=int))
        short = np.flatnonzero(lengths < minimum)
        if not len(short):
            break
        segment = int(short[0])
        if segment == 0:
            del retained[0]
        elif segment == len(boundaries) - 2:
            retained.pop()
        else:
            left = lengths[segment - 1]
            right = lengths[segment + 1]
            del retained[segment - 1 if left >= right else segment]
    return retained


def _best_counterpart(index: int, branches: list[_Branch], x: np.ndarray) -> _Branch:
    branch = branches[index]
    source_low = -float(np.max(x[branch.indices]))
    source_high = -float(np.min(x[branch.indices]))
    paired_neighbor = index + 1 if index % 2 == 0 else index - 1
    if paired_neighbor >= len(branches):
        paired_neighbor = -1
    choices: list[tuple[float, int, int, _Branch]] = []
    for other_index, other in enumerate(branches):
        if other.direction == branch.direction:
            continue
        other_low = float(np.min(x[other.indices]))
        other_high = float(np.max(x[other.indices]))
        overlap = max(0.0, min(source_high, other_high) - max(source_low, other_low))
        preferred_pair = int(other_index == paired_neighbor)
        choices.append((overlap, preferred_pair, -abs(other_index - index), other))
    if not choices:
        raise ValueError("No opposite-direction branch is available for decomposition.")
    return max(choices, key=lambda item: (item[0], item[1], item[2]))[3]


def _consolidate_duplicate_x(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    finite = np.isfinite(x) & np.isfinite(y)
    x = np.asarray(x[finite], dtype=float)
    y = np.asarray(y[finite], dtype=float)
    order = np.argsort(x, kind="stable")
    sorted_x = np.asarray(x[order], dtype=float)
    sorted_y = np.asarray(y[order], dtype=float)
    unique, starts = np.unique(sorted_x, return_index=True)
    medians = np.array(
        [
            np.median(sorted_y[start:stop])
            for start, stop in zip(starts, [*starts[1:], len(sorted_x)], strict=True)
        ],
        dtype=float,
    )
    return unique, medians


def _make_interpolator(
    x: np.ndarray,
    y: np.ndarray,
    *,
    method: str,
    out_of_range: str,
) -> Callable[[np.ndarray], np.ndarray]:
    """Return an interpolation callable with the configured edge policy."""
    from scipy.interpolate import PchipInterpolator, interp1d  # type: ignore[import-untyped]  # noqa: PLC0415, I001

    if out_of_range not in _OUT_OF_RANGE_LABELS:
        raise ValueError(f"Unknown out-of-range policy {out_of_range!r}.")
    extrapolate = out_of_range == OUT_OF_RANGE_EXTRAPOLATE
    if method == INTERPOLATION_PCHIP:
        base = PchipInterpolator(x, y, extrapolate=extrapolate)
    elif method == INTERPOLATION_LINEAR:
        fill_value: str | float | tuple[float, float]
        if extrapolate:
            fill_value = "extrapolate"
        elif out_of_range == OUT_OF_RANGE_NEAREST:
            fill_value = (float(y[0]), float(y[-1]))
        else:
            fill_value = np.nan
        base = interp1d(
            x, y, kind="linear", bounds_error=False, fill_value=fill_value, assume_sorted=True
        )
    else:
        raise ValueError(f"Unknown interpolation method {method!r}.")

    if out_of_range != OUT_OF_RANGE_NEAREST or method == INTERPOLATION_LINEAR:
        return base

    def nearest_edge(query: np.ndarray) -> np.ndarray:
        return np.asarray(base(np.clip(query, x[0], x[-1])), dtype=float)

    return nearest_edge
