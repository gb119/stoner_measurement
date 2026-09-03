"""Central PyQtGraph plotting widget — middle 50 % of the main window.

Supports multiple named traces (each with its own colour) and multiple
independent x- and y-axes implemented via linked
:class:`pyqtgraph.ViewBox` instances.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import cycle
from typing import Literal, TypedDict, cast

import numpy as np
import pyqtgraph as pg
from qtpy.QtCore import QPoint, QPointF, Qt
from qtpy.QtGui import QColor, QCursor
from qtpy.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.qt_compat import pyqtSlot
from stoner_measurement.ui.axis_mappings import (
    AXIS_SCALES,
    AxisLabel,
    AxisScale,
    MappedAxisItem,
    inverse_values,
    transform_values,
    validate_scale,
)
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.icons import make_home_icon
from stoner_measurement.ui.theme import (
    apply_pyqtgraph_dark_theme,
    button_swatch_stylesheet,
    colour,
    contrasting_text_colour,
)

logger = logging.getLogger(__name__)


def configure_chart_legend(tree) -> None:
    """Configure a two-column chart legend to favour the trace label column."""
    tree.setHeaderLabels(["Trace", "Value"])
    header = tree.header()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)


# Plot grid opacity used by pyqtgraph AxisItem.setGrid().
_PLOT_GRID_ALPHA = 0.15

# PlotItem reserves row 0 for its title and row 1 for top axes.  Placing an
# axis in row 0 overlays its labels on the ViewBox instead of reducing the
# data area to the axis spine.
_AXIS_LAYOUT_ROW = {"top": 1, "bottom": 4}
_LEFT_AXIS_BASE_COLUMN = 0
_RIGHT_AXIS_BASE_COLUMN = 3

# Colour palette used when automatically assigning colours to new traces.
_TRACE_COLOURS = [
    colour("trace_blue"),
    colour("trace_orange"),
    colour("trace_green"),
    colour("trace_red"),
    colour("trace_purple"),
    colour("trace_brown"),
    "deeppink",
    "dimgray",
    "olive",
    colour("trace_teal"),
]

_LINE_STYLES: dict[str, Qt.PenStyle] = {
    "solid": Qt.PenStyle.SolidLine,
    "dash": Qt.PenStyle.DashLine,
    "dot": Qt.PenStyle.DotLine,
    "dash-dot": Qt.PenStyle.DashDotLine,
    "none": Qt.PenStyle.NoPen,
}

_POINT_STYLES: dict[str, str | None] = {
    "none": None,
    "circle": "o",
    "square": "s",
    "triangle": "t",
    "diamond": "d",
    "plus": "+",
    "cross": "x",
}

_POINT_PICTOGRAMS: dict[str, str] = {
    "none": "·",
    "circle": "○",
    "square": "□",
    "triangle": "△",
    "diamond": "◇",
    "plus": "+",
    "cross": "×",
}

_MAX_VISIBLE_TRACE_ROWS = 3
_MIN_LINE_WIDTH = 0.1
_MAX_LINE_WIDTH = 20.0
_LINE_WIDTH_STEP = 0.5
_MIN_POINT_SIZE = 1.0
_MAX_POINT_SIZE = 30.0
_POINT_SIZE_STEP = 1.0
_DEFAULT_LINE_WIDTH = 2.0
_DEFAULT_POINT_SIZE = 8.0
_TRACE_TITLE_COLUMN_WIDTH = 180
_COLOUR_COLUMN_WIDTH = 90
_AXIS_COLUMN_WIDTH = 120
_TRACE_NAME_PROPERTY = "trace_name"
_TRACE_AXIS_PROPERTY = "axis"
_MARKER_HIT_RADIUS = 14.0


@dataclass
class _DataMarker:
    """One labelled marker anchored to raw named-axis coordinates."""

    marker_id: int
    x: float
    y: float
    x_axis: str
    y_axis: str
    item: pg.TargetItem


def _safe_remove_graphics_item(parent: object, item: object) -> None:
    """Best-effort removal for pyqtgraph/Qt graphics items during teardown."""
    remove_item = getattr(parent, "removeItem", None)
    if callable(remove_item):
        try:
            remove_item(item)
        except RuntimeError:
            logger.debug("Graphics item was already deleted during teardown.", exc_info=True)


def _safe_detach_graphics_item(item: object) -> None:
    """Best-effort detach for graphics items that may already be half-destroyed."""
    try:
        hide = getattr(item, "hide", None)
        if callable(hide):
            hide()
        set_parent_item = getattr(item, "setParentItem", None)
        if callable(set_parent_item):
            set_parent_item(None)
        scene = getattr(item, "scene", lambda: None)()
        if scene is not None:
            _safe_remove_graphics_item(scene, item)
    except RuntimeError:
        logger.debug("Graphics item was already deleted during detach.", exc_info=True)


class _AxisDialogEntry(TypedDict):
    name: str
    label: str
    log_scale: bool
    scale: AxisScale
    scale_parameter: float
    grid: bool
    side: str
    visible: bool
    minimum: float | None
    maximum: float | None
    removable: bool


class _AxisNameBuckets(TypedDict):
    x: list[str]
    y: list[str]


class _AxisDialogChanges(TypedDict):
    labels: dict[str, str]
    log_scale: dict[str, bool]
    scale: dict[str, AxisScale]
    scale_parameter: dict[str, float]
    grid: dict[str, bool]
    side: dict[str, str]
    removed: _AxisNameBuckets
    ranges: dict[str, tuple[float | None, float | None]]
    visible_axes: dict[str, bool]


class _AxisRowState(TypedDict):
    """Normalised values collected from one axis-dialog table row."""

    name: str
    label: str
    scale: AxisScale
    scale_parameter: float
    grid: bool
    side: str
    range: tuple[float | None, float | None]
    visible: bool


class _CoupledViewBox(pg.ViewBox):
    """ViewBox that notifies its owning PlotWidget about drag lifecycle."""

    def __init__(self, owner: PlotWidget, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._owner = owner

    def mouseDragEvent(self, ev, axis=None):  # type: ignore[override]
        """Track drag start/finish so axis coupling is only active while dragging."""
        if hasattr(ev, "isStart") and ev.isStart():
            self._owner._begin_mouse_axis_coupling(self)
        try:
            super().mouseDragEvent(ev, axis=axis)
        finally:
            if hasattr(ev, "isFinish") and ev.isFinish():
                self._owner._end_mouse_axis_coupling(self)

    def wheelEvent(self, ev, axis=None):  # type: ignore[override]
        """Treat wheel zoom as a short manual interaction on this view box."""
        self._owner._begin_mouse_axis_coupling(self)
        try:
            super().wheelEvent(ev, axis=axis)
        finally:
            self._owner._end_mouse_axis_coupling(self)

    def mouseClickEvent(self, ev):  # type: ignore[override]
        """Ensure transient coupling is cancelled on click release paths."""
        try:
            super().mouseClickEvent(ev)
        finally:
            self._owner._end_mouse_axis_coupling(self)


class AxesConfigDialog(QDialog):
    """Dialog for configuring x/y axes on the plot widget.

    Keyword Parameters:
        x_axes (list[_AxisDialogEntry]):
            Existing x-axis configuration rows.
        y_axes (list[_AxisDialogEntry]):
            Existing y-axis configuration rows.
        parent (QWidget | None):
            Optional parent widget.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> dlg = AxesConfigDialog(x_axes=[], y_axes=[])
        >>> dlg.windowTitle()
        'Configure Axes'
    """

    def __init__(
        self,
        *,
        x_axes: list[_AxisDialogEntry],
        y_axes: list[_AxisDialogEntry],
        on_range_changed: Callable[[str, float | None, float | None], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configure Axes")
        self.resize(760, 420)
        self._removed_axes: dict[str, set[str]] = {"x": set(), "y": set()}
        self._tables: dict[str, QTableWidget] = {}
        self._add_name_inputs: dict[str, QLineEdit] = {}
        self._on_range_changed = on_range_changed
        self._add_label_inputs: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        tabs = FontAwareTabWidget(self)
        tabs.addTab(self._build_axis_tab("x", x_axes), "X Axes")
        tabs.addTab(self._build_axis_tab("y", y_axes), "Y Axes")
        help_text = (
            "Grid lines are enabled per axis but displayed once per orientation. "
            "Use Min/Max to set a manual visible range for an axis, or leave "
            "either field blank to keep that axis on auto-range."
        )
        help_label = QLabel(self)
        help_label.setWordWrap(True)
        help_label.setText(help_text)
        root.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(help_label)
        root.addWidget(buttons)

    def _build_axis_tab(
        self, axis_kind: Literal["x", "y"], axes: list[_AxisDialogEntry]
    ) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        table = QTableWidget(tab)
        table.setColumnCount(10)
        table.setHorizontalHeaderLabels(
            [
                "Show",
                "Name",
                "Title",
                "Position",
                "Scale",
                "Parameter",
                "Grid lines",
                "Min",
                "Max",
                "Remove",
            ]
        )
        table.setShowGrid(True)
        table.setGridStyle(Qt.PenStyle.SolidLine)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.ResizeToContents)
        table.setStyleSheet(
            "QTableWidget { "
            f"border: 1px solid {colour('border')}; "
            f"gridline-color: {colour('border')}; "
            "} "
            "QTableCornerButton::section { "
            f"border: 1px solid {colour('border')}; "
            "}"
        )
        layout.addWidget(table)
        self._tables[axis_kind] = table

        add_layout = QFormLayout()
        name_input = QLineEdit(tab)
        label_input = QLineEdit(tab)
        add_button = QPushButton("Add Axis", tab)
        add_button.clicked.connect(
            lambda _checked=False, kind=axis_kind: self._add_axis_row_from_inputs(kind)
        )
        add_layout.addRow("Name", name_input)
        add_layout.addRow("Title", label_input)
        add_layout.addRow(add_button)
        layout.addLayout(add_layout)
        self._add_name_inputs[axis_kind] = name_input
        self._add_label_inputs[axis_kind] = label_input

        for axis in axes:
            self._add_axis_row(
                axis_kind=axis_kind,
                axis_name=str(axis["name"]),
                axis_label=str(axis["label"]),
                scale=axis.get("scale", "log" if bool(axis.get("log_scale", False)) else "linear"),
                scale_parameter=float(axis.get("scale_parameter", 1.0)),
                side=str(axis["side"]),
                visible=bool(axis["visible"]),
                grid_enabled=bool(axis["grid"]),
                minimum=axis["minimum"],
                maximum=axis["maximum"],
                removable=bool(axis["removable"]),
            )
        return tab

    def _axis_names_in_table(self, axis_kind: Literal["x", "y"]) -> set[str]:
        table = self._tables[axis_kind]
        names: set[str] = set()
        for row in range(table.rowCount()):
            item = table.item(row, 1)
            if item is None:
                continue
            names.add(item.text())
        return names

    def _axis_names_in_tables(self) -> set[str]:
        return self._axis_names_in_table("x") | self._axis_names_in_table("y")

    def _add_axis_row_from_inputs(self, axis_kind: Literal["x", "y"]) -> None:
        name_input = self._add_name_inputs[axis_kind]
        label_input = self._add_label_inputs[axis_kind]
        axis_name = name_input.text().strip()
        if not axis_name or axis_name in self._axis_names_in_tables():
            return
        axis_label = label_input.text().strip() or axis_name
        self._add_axis_row(
            axis_kind=axis_kind,
            axis_name=axis_name,
            axis_label=axis_label,
            scale="linear",
            scale_parameter=1.0,
            side="top" if axis_kind == "x" else "right",
            visible=True,
            grid_enabled=False,
            minimum=None,
            maximum=None,
            removable=True,
        )
        name_input.clear()
        label_input.clear()

    def _add_axis_row(
        self,
        *,
        axis_kind: Literal["x", "y"],
        axis_name: str,
        axis_label: str,
        scale: AxisScale,
        scale_parameter: float,
        side: str,
        visible: bool,
        grid_enabled: bool,
        minimum: float | None,
        maximum: float | None,
        removable: bool,
    ) -> None:
        table = self._tables[axis_kind]
        row = table.rowCount()
        table.insertRow(row)

        visible_checkbox = QCheckBox(table)
        visible_checkbox.setChecked(visible)
        table.setCellWidget(row, 0, visible_checkbox)

        name_item = QTableWidgetItem(axis_name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, 1, name_item)

        label_edit = QLineEdit(axis_label, table)
        table.setCellWidget(row, 2, label_edit)

        side_combo = QComboBox(table)
        side_combo.addItems(["top", "bottom"] if axis_kind == "x" else ["left", "right"])
        side_combo.setCurrentText(side)
        table.setCellWidget(row, 3, side_combo)

        scale_combo = QComboBox(table)
        scale_combo.addItems(list(AXIS_SCALES))
        scale_combo.setCurrentText(scale)
        table.setCellWidget(row, 4, scale_combo)

        parameter_edit = QLineEdit(f"{scale_parameter:g}", table)
        parameter_edit.setToolTip("Linear threshold for symlog; scale factor for asinh")
        parameter_edit.setEnabled(scale in {"symlog", "asinh"})
        scale_combo.currentTextChanged.connect(
            lambda value, widget=parameter_edit: widget.setEnabled(value in {"symlog", "asinh"})
        )
        table.setCellWidget(row, 5, parameter_edit)

        grid_checkbox = QCheckBox(table)
        grid_checkbox.setChecked(grid_enabled)
        table.setCellWidget(row, 6, grid_checkbox)

        minimum_edit = QLineEdit("" if minimum is None else f"{minimum:g}", table)
        minimum_edit.setPlaceholderText("auto")
        minimum_edit.editingFinished.connect(
            lambda kind=axis_kind, row_index=row: self._emit_range_change(kind, row_index)
        )
        table.setCellWidget(row, 7, minimum_edit)

        maximum_edit = QLineEdit("" if maximum is None else f"{maximum:g}", table)
        maximum_edit.setPlaceholderText("auto")
        maximum_edit.editingFinished.connect(
            lambda kind=axis_kind, row_index=row: self._emit_range_change(kind, row_index)
        )
        table.setCellWidget(row, 8, maximum_edit)

        remove_button = QPushButton("Remove", table)
        remove_button.setEnabled(removable)
        remove_button.clicked.connect(
            lambda _checked=False, kind=axis_kind, row_index=row: self._mark_axis_removed(
                kind, row_index
            )
        )
        table.setCellWidget(row, 9, remove_button)

    def _mark_axis_removed(self, axis_kind: Literal["x", "y"], row: int) -> None:
        table = self._tables[axis_kind]
        item = table.item(row, 1)
        if item is None:
            return
        self._removed_axes[axis_kind].add(item.text())
        table.setRowHidden(row, True)

    def _emit_range_change(self, axis_kind: Literal["x", "y"], row: int) -> None:
        """Emit a live range update for the given table row."""
        if self._on_range_changed is None:
            return
        table = self._tables[axis_kind]
        if table.isRowHidden(row):
            return
        item = table.item(row, 1)
        if item is None:
            return
        axis_name = item.text()
        minimum_widget = table.cellWidget(row, 7)
        maximum_widget = table.cellWidget(row, 8)
        minimum = None
        maximum = None
        if isinstance(minimum_widget, QLineEdit):
            minimum_text = minimum_widget.text().strip()
            if minimum_text:
                try:
                    minimum = float(minimum_text)
                except ValueError:
                    return
        if isinstance(maximum_widget, QLineEdit):
            maximum_text = maximum_widget.text().strip()
            if maximum_text:
                try:
                    maximum = float(maximum_text)
                except ValueError:
                    return
        if minimum is not None and maximum is not None and minimum >= maximum:
            return
        self._on_range_changed(axis_name, minimum, maximum)

    def axis_changes(self) -> _AxisDialogChanges:
        """Return staged axis operations from the dialog.

        Returns:
            (_AxisDialogChanges):
                Mapping containing updated labels, log/grid states, removed axes,
                and visible axes to keep/add.
        """
        changes: _AxisDialogChanges = {
            "labels": {},
            "log_scale": {},
            "scale": {},
            "scale_parameter": {},
            "grid": {},
            "side": {},
            "removed": {
                "x": sorted(self._removed_axes["x"]),
                "y": sorted(self._removed_axes["y"]),
            },
            "ranges": {},
            "visible_axes": {},
        }
        for axis_kind in ("x", "y"):
            table = self._tables[axis_kind]
            for row in range(table.rowCount()):
                if table.isRowHidden(row):
                    continue
                state = self._axis_row_state(table, row)
                if state is None:
                    continue
                axis_name = state["name"]
                changes["labels"][axis_name] = state["label"]
                changes["scale"][axis_name] = state["scale"]
                changes["log_scale"][axis_name] = state["scale"] == "log"
                changes["scale_parameter"][axis_name] = state["scale_parameter"]
                changes["grid"][axis_name] = state["grid"]
                changes["side"][axis_name] = state["side"]
                changes["ranges"][axis_name] = state["range"]
                changes["visible_axes"][axis_name] = state["visible"]
        return changes

    @staticmethod
    def _optional_float(editor: QLineEdit) -> float | None:
        """Return the editor's numeric value, treating blank or invalid text as auto."""
        text = editor.text().strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @classmethod
    def _axis_row_state(cls, table: QTableWidget, row: int) -> _AxisRowState | None:
        """Collect and normalise the controls from one visible axis row."""
        name_item = table.item(row, 1)
        if name_item is None:
            return None

        axis_name = name_item.text()
        visible_editor = cast(QCheckBox, table.cellWidget(row, 0))
        label_editor = cast(QLineEdit, table.cellWidget(row, 2))
        side_editor = cast(QComboBox, table.cellWidget(row, 3))
        scale_editor = cast(QComboBox, table.cellWidget(row, 4))
        parameter_editor = cast(QLineEdit, table.cellWidget(row, 5))
        grid_editor = cast(QCheckBox, table.cellWidget(row, 6))
        minimum_editor = cast(QLineEdit, table.cellWidget(row, 7))
        maximum_editor = cast(QLineEdit, table.cellWidget(row, 8))

        scale_name = scale_editor.currentText()
        scale = cast(AxisScale, scale_name if scale_name in AXIS_SCALES else "linear")
        try:
            scale_parameter = float(parameter_editor.text())
        except ValueError:
            scale_parameter = 1.0

        return {
            "name": axis_name,
            "label": label_editor.text().strip() or axis_name,
            "scale": scale,
            "scale_parameter": scale_parameter,
            "grid": grid_editor.isChecked(),
            "side": side_editor.currentText(),
            "range": (
                cls._optional_float(minimum_editor),
                cls._optional_float(maximum_editor),
            ),
            "visible": visible_editor.isChecked(),
        }


class PlotWidget(QWidget):
    """PyQtGraph-based plot area for displaying measurement data.

    The widget supports:

    * **Named traces** — each trace is an independent
      :class:`pyqtgraph.PlotDataItem` with its own colour.  Traces are
      created on first use and can be updated point-by-point or in bulk.
    * **Multiple axes** — additional y-axes (left or right) and x-axes
      (top or bottom) can be added, and individual traces can be assigned
      to any axis pair.

    Attributes:
        pg_widget (pg.PlotWidget):
            The underlying :class:`pyqtgraph.PlotWidget`.

    Keyword Parameters:
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> widget = PlotWidget()
        >>> widget.append_point("my_trace", 1.0, 2.0)
        >>> widget.x_data("my_trace")
        [1.0]
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        show_axis_controls: bool = True,
        show_trace_table: bool = True,
    ) -> None:
        super().__init__(parent)

        self._show_axis_controls = show_axis_controls
        self._show_trace_table = show_trace_table

        # Per-trace data storage: name → (x_list, y_list)
        self._trace_data: dict[str, tuple[list[float], list[float]]] = {}
        # Per-trace plot item
        self._traces: dict[str, pg.PlotDataItem] = {}
        # Per-trace error-bar item (optional)
        self._error_bar_items: dict[str, pg.ErrorBarItem] = {}
        self._trace_error_data: dict[str, tuple[np.ndarray | None, np.ndarray | None]] = {}
        # Per-trace axis assignment: name → (x_axis_name, y_axis_name)
        self._trace_axes: dict[str, tuple[str, str]] = {}
        # Per-trace style: name → {"colour": str, "line": str, "point": str}
        self._trace_style: dict[str, dict[str, str]] = {}
        self._trace_line_width: dict[str, float] = {}
        self._trace_point_size: dict[str, float] = {}
        self._trace_visible: dict[str, bool] = {}
        self._pending_data_updates: int = 0
        self._right_dragged = False
        self._pending_data_updates_lock = threading.Lock()
        self._updating_trace_controls = False
        self._trace_controls_state: tuple | None = None
        self._mouse_axis_coupling_active = False
        self._active_mouse_view_box: pg.ViewBox | None = None
        self._updating_mouse_axis_coupling = False
        self._autoscale_new_data = True
        self._data_markers: list[_DataMarker] = []
        self._next_data_marker_id = 1
        # Colour cycle for auto-assignment
        self._colour_cycle = cycle(_TRACE_COLOURS)

        # ViewBox registry: axis_name → ViewBox for backwards compatibility.
        self._view_boxes: dict[str, pg.ViewBox] = {}
        # Pair registry: (x_axis, y_axis) → ViewBox.
        self._pair_view_boxes: dict[tuple[str, str], pg.ViewBox] = {}
        # AxisItem registry: axis_name → AxisItem
        self._axis_items: dict[str, pg.AxisItem] = {}
        # Distinct quantity labels received for each plot axis.
        self._axis_labels: dict[str, set[AxisLabel]] = {
            "bottom": set(),
            "left": set(),
        }
        # Axis orientation registry: axis_name → "x" | "y".
        self._axis_orientations: dict[str, Literal["x", "y"]] = {}
        # Axis side/position registry: y → left|right, x → top|bottom.
        self._axis_sides: dict[str, str] = {}
        # Axis visibility registry.
        self._axis_visible: dict[str, bool] = {}
        # Axis offset ordering on each side.
        self._axis_order: dict[tuple[str, str], list[str]] = {}
        self._axis_log_scale: dict[str, bool] = {}
        self._axis_scale: dict[str, AxisScale] = {}
        self._axis_scale_parameter: dict[str, float] = {}
        self._axis_grid: dict[str, bool] = {}
        self._axis_manual_range: dict[str, tuple[float | None, float | None]] = {}
        self._axis_auto_range: dict[str, tuple[bool, bool]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if self._show_axis_controls:
            self._setup_axis_config_controls(layout)

        if self._show_trace_table:
            self._setup_trace_table(layout)

        self._setup_pg_widget(layout)
        self._refresh_trace_and_axis_controls()
        self.setLayout(layout)

    def _setup_axis_config_controls(self, layout: QVBoxLayout) -> None:
        """Build axis configuration controls and add to layout."""
        controls = QHBoxLayout()
        self._configure_axes_button = QPushButton("Configure Axes…", self)
        self._configure_axes_button.clicked.connect(self._open_axes_dialog)
        style = self.style()
        self._home_button = QPushButton(self)
        self._home_button.setIcon(make_home_icon())
        self._home_button.setToolTip("Fit all plotted data in the view")
        self._home_button.setAccessibleName("Home")
        self._home_button.clicked.connect(self.reset_all_view_ranges)
        self._autoscale_button = QPushButton(self)
        self._autoscale_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self._autoscale_button.setToolTip("Autoscale when new data is plotted")
        self._autoscale_button.setAccessibleName("Autoscale new data")
        self._autoscale_button.setCheckable(True)
        self._autoscale_button.setChecked(True)
        self._autoscale_button.setStyleSheet(
            "QPushButton:checked { "
            f"background-color: {colour('highlight')}; "
            f"color: {colour('highlighted_text')}; "
            f"border: 2px solid {colour('link')}; "
            "}"
        )
        self._autoscale_button.toggled.connect(self._set_autoscale_new_data)
        self._clear_button = QPushButton(self)
        self._clear_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogDiscardButton))
        self._clear_button.setToolTip("Clear all plotted data")
        self._clear_button.setAccessibleName("Clear plot")
        self._clear_button.clicked.connect(self.clear_all)
        controls.addWidget(self._configure_axes_button)
        controls.addWidget(self._home_button)
        controls.addWidget(self._autoscale_button)
        controls.addWidget(self._clear_button)
        controls.addStretch(1)
        self._coordinate_label = QLabel("", self)
        self._coordinate_label.setObjectName("plotCoordinateDisplay")
        self._coordinate_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._coordinate_label.setMinimumWidth(150)
        self._coordinate_label.setToolTip("Pointer coordinates for the visible plot axes")
        controls.addWidget(self._coordinate_label)
        layout.addLayout(controls)

    def _set_autoscale_new_data(self, enabled: bool) -> None:
        """Control whether incoming data is allowed to change the visible ranges."""
        self._autoscale_new_data = bool(enabled)
        if enabled:
            self._refresh_all_auto_ranges()
            return
        for view_box in self._pair_view_boxes.values():
            view_box.enableAutoRange(enable=False)

    def _setup_trace_table(self, layout: QVBoxLayout) -> None:
        """Create and configure the trace table widget and add to layout."""
        self._trace_table = QTableWidget(self)
        self._trace_table.setColumnCount(9)
        self._trace_table.setHorizontalHeaderLabels(
            ["Show", "Trace", "Colour", "Line", "Width", "Points", "Point Size", "X axis", "Y axis"]
        )
        self._trace_table.verticalHeader().setVisible(False)
        self._trace_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._trace_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._trace_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._trace_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header = self._trace_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(1, 9):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        self._trace_table.setColumnWidth(1, _TRACE_TITLE_COLUMN_WIDTH)
        self._trace_table.setColumnWidth(2, _COLOUR_COLUMN_WIDTH)
        self._trace_table.setColumnWidth(7, _AXIS_COLUMN_WIDTH)
        self._trace_table.setColumnWidth(8, _AXIS_COLUMN_WIDTH)
        layout.addWidget(self._trace_table)

    def _setup_pg_widget(self, layout: QVBoxLayout) -> None:
        """Create the pyqtgraph PlotWidget, register default axes, and add to layout."""
        axis_items = {side: MappedAxisItem(side) for side in ("left", "right", "top", "bottom")}
        self._pg_widget = pg.PlotWidget(viewBox=_CoupledViewBox(self), axisItems=axis_items)
        self._pg_widget.setObjectName("pgPlotWidget")
        self._pg_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._pg_widget.setBackground(colour("plot_background"))
        scene = self._pg_widget.scene()
        scene.sigMouseClicked.connect(self._on_scene_mouse_clicked)
        self._mouse_move_proxy = pg.SignalProxy(
            scene.sigMouseMoved,
            rateLimit=30,
            slot=self._on_scene_mouse_moved,
        )
        if hasattr(scene, "sigMouseDragged"):
            scene.sigMouseDragged.connect(self._on_scene_mouse_dragged)
        axis_items["left"].set_axis_label(AxisLabel("Value"))
        axis_items["bottom"].set_axis_label(AxisLabel("Step"))
        plot_item: pg.PlotItem = self._pg_widget.getPlotItem()
        plot_item.setMenuEnabled(False)
        self._plot_item = plot_item
        self._default_top_axis = plot_item.getAxis("top")
        self._default_top_axis_removed = False
        self._default_right_axis = plot_item.getAxis("right")
        self._default_right_axis_removed = False
        # PlotItem keeps placeholder axes on all four sides.  They are not
        # user-configured axes, so keep the unused top/right placeholders out
        # of view until a named axis replaces them.
        plot_item.hideAxis("top")
        plot_item.hideAxis("right")
        self._view_boxes["left"] = plot_item.vb
        self._view_boxes["bottom"] = plot_item.vb
        self._pair_view_boxes[("bottom", "left")] = plot_item.vb
        self._axis_items["left"] = plot_item.getAxis("left")
        self._axis_items["bottom"] = plot_item.getAxis("bottom")
        self._axis_orientations["left"] = "y"
        self._axis_orientations["bottom"] = "x"
        self._axis_sides["left"] = "left"
        self._axis_sides["bottom"] = "bottom"
        self._axis_visible["left"] = True
        self._axis_visible["bottom"] = True
        self._axis_log_scale["bottom"] = False
        self._axis_log_scale["left"] = False
        self._axis_scale["bottom"] = "linear"
        self._axis_scale["left"] = "linear"
        self._axis_scale_parameter["bottom"] = 1.0
        self._axis_scale_parameter["left"] = 1.0
        self._axis_auto_range["bottom"] = (True, True)
        self._axis_auto_range["left"] = (True, True)
        self._axis_order[("y", "left")] = ["left"]
        self._axis_order[("x", "bottom")] = ["bottom"]
        self._axis_grid["bottom"] = True
        self._axis_grid["left"] = True
        self._plot_item.vb.sigResized.connect(self._sync_view_box_geometry)
        self._axis_manual_range["bottom"] = self._axis_range("bottom")
        self._axis_manual_range["left"] = self._axis_range("left")
        self._register_view_box_signals(self._plot_item.vb)
        self._update_grid_state()
        apply_pyqtgraph_dark_theme(self._plot_item, self._axis_items)
        layout.addWidget(self._pg_widget)

    # ------------------------------------------------------------------
    # Named-trace helpers
    # ------------------------------------------------------------------

    def _sync_view_box_geometry(self) -> None:
        """Keep additional ViewBoxes aligned with the main plot ViewBox."""
        rect = self._plot_item.vb.sceneBoundingRect()
        for key, view_box in self._pair_view_boxes.items():
            if key == ("bottom", "left"):
                continue
            view_box.setGeometry(rect)
        self._layout_additional_axes()

    def _layout_additional_axes(self) -> None:
        """Place axes on the plot layout with offsets for shared sides."""
        for side in ("left", "right"):
            if self._axis_order.get(("y", side)):
                self._remove_default_auxiliary_axis(side)
            for offset, axis_name in enumerate(self._axis_order.get(("y", side), [])):
                axis_item = self._axis_items.get(axis_name)
                if axis_item is None:
                    continue
                column = (
                    _LEFT_AXIS_BASE_COLUMN - offset
                    if side == "left"
                    else _RIGHT_AXIS_BASE_COLUMN + offset
                )
                self._plot_item.layout.addItem(axis_item, 2, column)

        for side in ("top", "bottom"):
            if self._axis_order.get(("x", side)):
                self._remove_default_auxiliary_axis(side)
            for offset, axis_name in enumerate(self._axis_order.get(("x", side), [])):
                axis_item = self._axis_items.get(axis_name)
                if axis_item is None:
                    continue
                row = (
                    _AXIS_LAYOUT_ROW["top"] - offset
                    if side == "top"
                    else _AXIS_LAYOUT_ROW["bottom"] + offset
                )
                self._plot_item.layout.addItem(axis_item, row, 1)

    def _remove_default_auxiliary_axis(self, side: str) -> None:
        """Remove PyQtGraph's unused top/right placeholder for a named axis."""
        if side not in {"top", "right"}:
            return
        removed_attribute = f"_default_{side}_axis_removed"
        if getattr(self, removed_attribute):
            return
        axis_attribute = f"_default_{side}_axis"
        axis_item = getattr(self, axis_attribute)
        # Close before removing from the layout so the AxisItem disposes of
        # its LabelItem while the graphics scene is still alive.
        axis_item.unlinkFromView()
        axis_item.close()
        self._plot_item.layout.removeItem(axis_item)
        setattr(self, axis_attribute, None)
        setattr(self, removed_attribute, True)

    def _capture_manual_axis_range(self, name: str) -> None:
        """Store the current visible range as the manual range for an axis."""
        self._axis_manual_range[name] = self._axis_range(name)
        self._axis_auto_range[name] = (False, False)

    def _reapply_manual_axis_ranges(self) -> None:
        """Re-apply stored auto/manual range states after structural axis changes."""
        for axis_name in list(self._axis_items):
            self._apply_axis_range_state(axis_name)

    def _set_axis_auto_state(
        self,
        name: str,
        min_auto: bool,
        max_auto: bool | None = None,
    ) -> None:
        """Record per-bound auto-range state for an axis."""
        if max_auto is None:
            max_auto = min_auto
        current_minimum, current_maximum = self._axis_manual_range.get(name, self._axis_range(name))
        visible_minimum, visible_maximum = self._axis_range(name)
        self._axis_auto_range[name] = (bool(min_auto), bool(max_auto))
        self._axis_manual_range[name] = (
            visible_minimum if min_auto else current_minimum,
            visible_maximum if max_auto else current_maximum,
        )

    def _apply_axis_range_state(self, name: str) -> None:
        """Apply the stored auto/manual range state for an axis."""
        min_auto, max_auto = self._axis_auto_range.get(name, (True, True))
        minimum, maximum = self._axis_manual_range.get(name, self._axis_range(name))
        self.set_axis_range(
            name,
            minimum=None if min_auto else minimum,
            maximum=None if max_auto else maximum,
        )

    def _axis_range_display_values(self, name: str) -> tuple[float | None, float | None]:
        """Return dialog/display range values, blanking auto bounds."""
        min_auto, max_auto = self._axis_auto_range.get(name, (True, True))
        minimum, maximum = self._axis_manual_range.get(name, self._axis_range(name))
        return (None if min_auto else minimum, None if max_auto else maximum)

    def _on_axis_view_range_changed(self, _view_box=None, changed=None) -> None:
        """Mark affected axes as manual when the user pans/zooms."""
        if not changed:
            return
        source_view_box = (
            _view_box if isinstance(_view_box, pg.ViewBox) else self._active_mouse_view_box
        )
        x_changed = bool(changed[0])
        y_changed = bool(changed[1])
        if self._mouse_axis_coupling_active and not self._updating_mouse_axis_coupling:
            self._updating_mouse_axis_coupling = True
            try:
                if x_changed and source_view_box is not None:
                    self._synchronise_mouse_managed_axes("x", source_view_box)
                if y_changed and source_view_box is not None:
                    self._synchronise_mouse_managed_axes("y", source_view_box)
            finally:
                self._updating_mouse_axis_coupling = False
        if x_changed:
            for axis_name in self._x_axis_names():
                self._capture_manual_axis_range(axis_name)
        if y_changed:
            for axis_name in self._y_axis_names():
                self._capture_manual_axis_range(axis_name)

    def _mouse_event_in_plot(self, ev) -> bool:
        """Return whether a scene mouse event occurred inside the plot view box."""
        if not hasattr(ev, "scenePos"):
            return False
        scene_pos = ev.scenePos()
        if scene_pos is None:
            return False
        return self._plot_item.vb.sceneBoundingRect().contains(scene_pos)

    def _begin_mouse_axis_coupling(self, view_box: pg.ViewBox) -> None:
        """Enable temporary multi-axis coupling for a specific active view box."""
        self._active_mouse_view_box = view_box
        self._mouse_axis_coupling_active = True

    def _end_mouse_axis_coupling(self, view_box: pg.ViewBox | None = None) -> None:
        """Disable temporary coupling when the active mouse interaction ends."""
        if (
            view_box is not None
            and self._active_mouse_view_box is not None
            and view_box is not self._active_mouse_view_box
        ):
            return
        self._mouse_axis_coupling_active = False
        self._active_mouse_view_box = None

    def _synchronise_mouse_managed_axes(
        self,
        orientation: Literal["x", "y"],
        source_view_box: pg.ViewBox,
    ) -> None:
        """Copy the active mouse-driven range across axes of one orientation."""
        source_range = source_view_box.viewRange()[0 if orientation == "x" else 1]
        source_minimum = float(source_range[0])
        source_maximum = float(source_range[1])
        axis_constant = pg.ViewBox.XAxis if orientation == "x" else pg.ViewBox.YAxis
        for view_box in self._pair_view_boxes.values():
            if view_box is source_view_box:
                continue
            view_box.enableAutoRange(axis=axis_constant, enable=False)
            if orientation == "x":
                view_box.setRange(xRange=(source_minimum, source_maximum), padding=0.0)
            else:
                view_box.setRange(yRange=(source_minimum, source_maximum), padding=0.0)

    def _register_view_box_signals(self, view_box: pg.ViewBox) -> None:
        """Connect range-change tracking for a view box."""
        if hasattr(view_box, "sigRangeChangedManually"):
            view_box.sigRangeChangedManually.connect(self._on_axis_view_range_changed)

    def _register_axis_side(self, name: str, orientation: Literal["x", "y"], side: str) -> None:
        """Register axis side and ordering metadata."""
        self._axis_sides[name] = side
        key = (orientation, side)
        order = self._axis_order.setdefault(key, [])
        if name not in order:
            order.append(name)

    def _unregister_axis_side(self, name: str, orientation: Literal["x", "y"]) -> None:
        """Remove axis from side-order registries."""
        side = self._axis_sides.pop(name, None)
        if side is None:
            return
        key = (orientation, side)
        if key in self._axis_order and name in self._axis_order[key]:
            self._axis_order[key].remove(name)
            if not self._axis_order[key]:
                self._axis_order.pop(key, None)

    def _on_scene_mouse_dragged(self, ev) -> None:
        """Ignore drag events for context-menu purposes."""
        if (
            hasattr(ev, "buttonDownScenePos")
            and ev.buttonDownScenePos(Qt.MouseButton.RightButton) is not None
        ):
            self._right_dragged = True

    def _on_scene_mouse_clicked(self, ev) -> None:
        """Open the plot context menu for a plain right-click release."""
        self._end_mouse_axis_coupling()
        if ev.button() == Qt.MouseButton.RightButton:
            if getattr(self, "_right_dragged", False):
                self._right_dragged = False
                return
            scene_pos = ev.scenePos()
            if not self._plot_item.vb.sceneBoundingRect().contains(scene_pos):
                return
            menu = self._build_plot_context_menu(scene_pos)
            screen_pos = ev.screenPos() if hasattr(ev, "screenPos") else QCursor.pos()
            if hasattr(screen_pos, "toPoint"):
                screen_pos = screen_pos.toPoint()
            menu.exec(screen_pos)

    def _on_scene_mouse_moved(self, event) -> None:
        """Update the throttled toolbar coordinate display from a scene position."""
        if not hasattr(self, "_coordinate_label"):
            return
        scene_pos = event[0] if isinstance(event, (tuple, list)) else event
        if not self._plot_item.vb.sceneBoundingRect().contains(scene_pos):
            self._coordinate_label.clear()
            return
        x_values, y_values = self._axis_values_at_scene_position(scene_pos)
        self._coordinate_label.setText(self._format_pointer_coordinates(x_values, y_values))

    def _axis_values_at_scene_position(self, scene_pos: QPointF) -> tuple[list[float], list[float]]:
        """Return raw pointer values for every registered x and y axis."""
        x_values = [
            self._axis_value_at_scene_position(name, scene_pos) for name in self._x_axis_names()
        ]
        y_values = [
            self._axis_value_at_scene_position(name, scene_pos) for name in self._y_axis_names()
        ]
        return x_values, y_values

    def _axis_value_at_scene_position(self, axis_name: str, scene_pos: QPointF) -> float:
        """Map one scene coordinate into the raw units of *axis_name*."""
        orientation = self._axis_orientations[axis_name]
        index = 0 if orientation == "x" else 1
        pair = next(
            (axes for axes in self._pair_view_boxes if axes[index] == axis_name),
            ("bottom", "left"),
        )
        point = self._pair_view_boxes[pair].mapSceneToView(scene_pos)
        mapped = point.x() if orientation == "x" else point.y()
        return float(self._inverse_axis_values(axis_name, [mapped])[0])

    @staticmethod
    def _format_pointer_coordinates(x_values: list[float], y_values: list[float]) -> str:
        """Format one or multiple axis-coordinate pairs compactly."""

        def values_text(values: list[float]) -> str:
            rendered = [f"{value:.6g}" for value in values]
            return rendered[0] if len(rendered) == 1 else f"[{', '.join(rendered)}]"

        return f"({values_text(x_values)}, {values_text(y_values)})"

    def _build_plot_context_menu(self, scene_pos: QPointF) -> QMenu:
        """Build the context-sensitive menu for one plot-area position."""
        menu = QMenu(self)
        configure = menu.addAction("Configure Axes…")
        configure.triggered.connect(self._open_axes_dialog)
        nearby = self._nearest_data_marker(scene_pos)
        if nearby is None:
            add = menu.addAction("Add Data Marker")
            add.triggered.connect(lambda: self._add_data_marker_at_scene_position(scene_pos))
        else:
            remove = menu.addAction("Remove Data Marker")
            remove.triggered.connect(lambda: self.remove_data_marker(nearby.marker_id))
        remove_all = menu.addAction("Remove All Data Markers")
        remove_all.setEnabled(bool(self._data_markers))
        remove_all.triggered.connect(self.clear_data_markers)
        return menu

    def _add_data_marker_at_scene_position(self, scene_pos: QPointF) -> None:
        """Add a labelled marker at the primary axes' raw data coordinates."""
        point = self._plot_item.vb.mapSceneToView(scene_pos)
        x = float(self._inverse_axis_values("bottom", [point.x()])[0])
        y = float(self._inverse_axis_values("left", [point.y()])[0])
        self.add_data_marker(x, y)

    @pyqtSlot(float, float)
    @pyqtSlot(float, float, object)
    def add_data_marker(
        self,
        x: float,
        y: float,
        label: str | None = None,
        *,
        x_axis: str = "bottom",
        y_axis: str = "left",
    ) -> int:
        """Add a fixed data-coordinate marker and return its stable ID.

        The optional axis names allow callers to anchor a marker to any
        registered x/y pair. The marker follows zooming, panning, and scale
        mapping changes. When *label* is omitted its raw coordinates are used.
        """
        if self._axis_orientations.get(x_axis) != "x":
            raise KeyError(f"Unknown x-axis: {x_axis!r}")
        if self._axis_orientations.get(y_axis) != "y":
            raise KeyError(f"Unknown y-axis: {y_axis!r}")
        view_box = self._create_pair_view_box(x_axis, y_axis)
        marker_id = self._next_data_marker_id
        self._next_data_marker_id += 1
        item = pg.TargetItem(
            pos=(
                float(self._mapped_axis_values(x_axis, [x])[0]),
                float(self._mapped_axis_values(y_axis, [y])[0]),
            ),
            size=12,
            symbol="o",
            pen=pg.mkPen(colour("trace_orange"), width=2),
            brush=pg.mkBrush(colour("plot_background")),
            movable=False,
            label=label or self._format_pointer_coordinates([x], [y]),
            labelOpts={"color": colour("plot_foreground")},
        )
        marker = _DataMarker(
            marker_id=marker_id,
            x=float(x),
            y=float(y),
            x_axis=x_axis,
            y_axis=y_axis,
            item=item,
        )
        self._data_markers.append(marker)
        view_box.addItem(item)
        return marker_id

    def _nearest_data_marker(self, scene_pos: QPointF) -> _DataMarker | None:
        """Return a marker within the fixed screen-space hit radius."""
        nearest: _DataMarker | None = None
        nearest_distance = _MARKER_HIT_RADIUS
        for marker in self._data_markers:
            view_box = self._pair_view_boxes[(marker.x_axis, marker.y_axis)]
            marker_scene_pos = view_box.mapViewToScene(marker.item.pos())
            delta = marker_scene_pos - scene_pos
            distance = float(np.hypot(delta.x(), delta.y()))
            if distance <= nearest_distance:
                nearest = marker
                nearest_distance = distance
        return nearest

    def remove_data_marker(self, marker_id: int) -> bool:
        """Remove the marker with *marker_id* and report whether it existed."""
        marker = next(
            (candidate for candidate in self._data_markers if candidate.marker_id == marker_id),
            None,
        )
        if marker is None:
            return False
        view_box = self._pair_view_boxes[(marker.x_axis, marker.y_axis)]
        view_box.removeItem(marker.item)
        self._data_markers.remove(marker)
        return True

    def clear_data_markers(self) -> None:
        """Remove every labelled data marker from the plot."""
        for marker_id in [marker.marker_id for marker in self._data_markers]:
            self.remove_data_marker(marker_id)

    def _refresh_data_markers(self) -> None:
        """Reposition markers after changing the primary axis mapping."""
        for marker in self._data_markers:
            marker.item.setPos(
                float(self._mapped_axis_values(marker.x_axis, [marker.x])[0]),
                float(self._mapped_axis_values(marker.y_axis, [marker.y])[0]),
            )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """Track right-button press state."""
        if event.button() == Qt.MouseButton.RightButton:
            self._right_dragged = False
        super().mousePressEvent(event)

    def _x_axis_names(self) -> list[str]:
        """Return sorted names of registered x-axes."""
        return sorted(
            name for name, orientation in self._axis_orientations.items() if orientation == "x"
        )

    def _y_axis_names(self) -> list[str]:
        """Return sorted names of registered y-axes."""
        return sorted(
            name for name, orientation in self._axis_orientations.items() if orientation == "y"
        )

    def _refresh_trace_and_axis_controls(self) -> None:
        """Refresh table rows after trace or axis changes."""
        if not hasattr(self, "_trace_table"):
            return

        x_axes = self._x_axis_names()
        y_axes = self._y_axis_names()
        controls_state = (
            tuple(x_axes),
            tuple(y_axes),
            tuple(
                (
                    trace_name,
                    self._trace_visible.get(trace_name, True),
                    *self._trace_axes.get(trace_name, ("bottom", "left")),
                    self._trace_style.get(trace_name, {}).get("colour"),
                    self._trace_style.get(trace_name, {}).get("line"),
                    self._trace_style.get(trace_name, {}).get("point"),
                    self._trace_line_width.get(trace_name, _DEFAULT_LINE_WIDTH),
                    self._trace_point_size.get(trace_name, _DEFAULT_POINT_SIZE),
                )
                for trace_name in self.trace_names
            ),
        )
        if controls_state == self._trace_controls_state:
            return

        self._updating_trace_controls = True
        try:
            self._trace_table.clearContents()
            self._trace_table.setRowCount(len(self.trace_names))
            for row, trace_name in enumerate(self.trace_names):
                style = self._trace_style.get(trace_name, {})
                x_axis, y_axis = self._trace_axes.get(trace_name, ("bottom", "left"))
                self._build_trace_table_row(row, trace_name, style, x_axis, y_axis, x_axes, y_axes)
        finally:
            self._updating_trace_controls = False
        self._trace_controls_state = controls_state
        self._update_trace_table_height()

    def _build_trace_table_row(  # pylint: disable=too-many-arguments
        self,
        row: int,
        trace_name: str,
        style: dict,
        x_axis: str,
        y_axis: str,
        x_axes: list[str],
        y_axes: list[str],
    ) -> None:
        """Create all cell widgets for a single trace table row."""
        visible_checkbox = QCheckBox(self._trace_table)
        visible_checkbox.setChecked(self._trace_visible.get(trace_name, True))
        visible_checkbox.setProperty(_TRACE_NAME_PROPERTY, trace_name)
        visible_checkbox.toggled.connect(self._on_trace_visibility_toggled)
        self._trace_table.setCellWidget(row, 0, visible_checkbox)

        trace_item = QTableWidgetItem(trace_name)
        trace_item.setFlags(trace_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        trace_item.setToolTip(trace_name)
        self._trace_table.setItem(row, 1, trace_item)

        colour_button = QPushButton(self._trace_table)
        colour_button.setProperty(_TRACE_NAME_PROPERTY, trace_name)
        self._update_colour_button(colour_button, style["colour"])
        colour_button.clicked.connect(self._on_trace_colour_button_clicked)
        self._trace_table.setCellWidget(row, 2, colour_button)

        line_selector = QComboBox(self._trace_table)
        line_selector.addItems(list(_LINE_STYLES))
        line_selector.setCurrentText(style["line"])
        line_selector.setProperty(_TRACE_NAME_PROPERTY, trace_name)
        line_selector.currentTextChanged.connect(self._on_trace_line_style_changed)
        self._trace_table.setCellWidget(row, 3, line_selector)

        line_width = QDoubleSpinBox(self._trace_table)
        line_width.setRange(_MIN_LINE_WIDTH, _MAX_LINE_WIDTH)
        line_width.setSingleStep(_LINE_WIDTH_STEP)
        line_width.setDecimals(2)
        line_width.setValue(self._trace_line_width.get(trace_name, _DEFAULT_LINE_WIDTH))
        line_width.setProperty(_TRACE_NAME_PROPERTY, trace_name)
        line_width.valueChanged.connect(self._on_trace_line_width_changed)
        self._trace_table.setCellWidget(row, 4, line_width)

        point_selector = QComboBox(self._trace_table)
        point_names = list(_POINT_STYLES)
        for point_name in point_names:
            point_selector.addItem(_POINT_PICTOGRAMS[point_name], point_name)
        point_selector.setCurrentIndex(point_selector.findData(style["point"]))
        point_selector.setProperty(_TRACE_NAME_PROPERTY, trace_name)
        point_selector.currentIndexChanged.connect(self._on_trace_point_style_changed)
        self._trace_table.setCellWidget(row, 5, point_selector)

        point_size = QDoubleSpinBox(self._trace_table)
        point_size.setRange(_MIN_POINT_SIZE, _MAX_POINT_SIZE)
        point_size.setSingleStep(_POINT_SIZE_STEP)
        point_size.setDecimals(2)
        point_size.setValue(self._trace_point_size.get(trace_name, _DEFAULT_POINT_SIZE))
        point_size.setProperty(_TRACE_NAME_PROPERTY, trace_name)
        point_size.valueChanged.connect(self._on_trace_point_size_changed)
        self._trace_table.setCellWidget(row, 6, point_size)

        x_axis_selector = QComboBox(self._trace_table)
        x_axis_selector.addItems(x_axes)
        x_axis_selector.setCurrentText(x_axis)
        x_axis_selector.setProperty(_TRACE_NAME_PROPERTY, trace_name)
        x_axis_selector.setProperty(_TRACE_AXIS_PROPERTY, "x")
        x_axis_selector.currentTextChanged.connect(self._on_trace_axis_changed)
        self._trace_table.setCellWidget(row, 7, x_axis_selector)

        y_axis_selector = QComboBox(self._trace_table)
        y_axis_selector.addItems(y_axes)
        y_axis_selector.setCurrentText(y_axis)
        y_axis_selector.setProperty(_TRACE_NAME_PROPERTY, trace_name)
        y_axis_selector.setProperty(_TRACE_AXIS_PROPERTY, "y")
        y_axis_selector.currentTextChanged.connect(self._on_trace_axis_changed)
        self._trace_table.setCellWidget(row, 8, y_axis_selector)

    def _update_trace_table_height(self) -> None:
        """Limit visible trace rows to three before scrolling."""
        if not hasattr(self, "_trace_table"):
            return

        visible_rows = min(_MAX_VISIBLE_TRACE_ROWS, self._trace_table.rowCount())
        height = (
            self._trace_table.horizontalHeader().height()
            + (visible_rows * self._trace_table.verticalHeader().defaultSectionSize())
            + (2 * self._trace_table.frameWidth())
        )
        self._trace_table.setFixedHeight(height)

    def _set_trace_visibility(self, trace_name: str, visible: bool) -> None:
        """Show or hide a specific trace."""
        if self._updating_trace_controls:
            return
        if trace_name not in self._traces:
            return
        self._trace_visible[trace_name] = visible
        self._traces[trace_name].setVisible(visible)

    def set_trace_visible(self, trace_name: str, visible: bool) -> None:
        """Public wrapper for changing trace visibility."""
        self._set_trace_visibility(trace_name, visible)

    def trace_style(self, trace_name: str) -> dict[str, str]:
        """Return the current style dictionary for a trace."""
        return dict(self._trace_style.get(trace_name, {}))

    def _on_trace_visibility_toggled(self, visible: bool) -> None:
        """Handle trace visibility checkbox changes."""
        sender = self.sender()
        if sender is None:
            return
        self._set_trace_visibility(str(sender.property(_TRACE_NAME_PROPERTY)), visible)

    def _update_colour_button(self, button: QPushButton, colour: str) -> None:
        """Apply swatch styling and text to a trace-colour button.

        Args:
            button (QPushButton):
                Button widget representing the trace colour control.
            colour (str):
                Colour value to display on the button.
        """
        if not QColor(colour).isValid():
            return
        hex_colour = QColor(colour).name(QColor.NameFormat.HexRgb)
        button.setText(hex_colour)
        button.setStyleSheet(
            button_swatch_stylesheet(hex_colour, contrasting_text_colour(hex_colour))
        )

    def _on_trace_colour_button_clicked(self) -> None:
        """Open a colour picker dialog and apply the chosen trace colour."""
        if self._updating_trace_controls:
            return
        sender = self.sender()
        if sender is None:
            return
        trace_name = str(sender.property(_TRACE_NAME_PROPERTY))
        current_colour = self._trace_style.get(trace_name, {}).get("colour", "black")
        selected = QColorDialog.getColor(
            QColor(current_colour),
            self,
            f"Select colour for {trace_name}",
            QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if not selected.isValid():
            return
        self.set_trace_style(trace_name=trace_name, colour=selected.name(QColor.NameFormat.HexRgb))
        self._update_colour_button(sender, selected.name(QColor.NameFormat.HexRgb))

    def _on_trace_line_style_changed(self, line_style: str) -> None:
        """Update trace line style from a table control."""
        if self._updating_trace_controls:
            return
        sender = self.sender()
        if sender is None:
            return
        self.set_trace_style(
            trace_name=str(sender.property(_TRACE_NAME_PROPERTY)), line_style=line_style
        )

    def _on_trace_line_width_changed(self, line_width: float) -> None:
        """Update trace line width from a table control."""
        if self._updating_trace_controls:
            return
        sender = self.sender()
        if sender is None:
            return
        self.set_trace_style(
            trace_name=str(sender.property(_TRACE_NAME_PROPERTY)), line_width=line_width
        )

    def _on_trace_point_style_changed(self, index: int) -> None:
        """Update trace point style from a table control."""
        if self._updating_trace_controls:
            return
        sender = self.sender()
        if sender is None:
            return
        point_style = str(sender.itemData(index))
        self.set_trace_style(
            trace_name=str(sender.property(_TRACE_NAME_PROPERTY)), point_style=point_style
        )

    def _on_trace_point_size_changed(self, point_size: float) -> None:
        """Update trace point size from a table control."""
        if self._updating_trace_controls:
            return
        sender = self.sender()
        if sender is None:
            return
        self.set_trace_style(
            trace_name=str(sender.property(_TRACE_NAME_PROPERTY)), point_size=point_size
        )

    def _on_trace_axis_changed(self, axis_name: str) -> None:
        """Update trace axis assignment from a table control."""
        if self._updating_trace_controls:
            return
        sender = self.sender()
        if sender is None:
            return
        trace_name = str(sender.property(_TRACE_NAME_PROPERTY))
        axis_kind = str(sender.property(_TRACE_AXIS_PROPERTY))
        current_x, current_y = self._trace_axes.get(trace_name, ("bottom", "left"))
        self.assign_trace_axes(
            trace_name=trace_name,
            x_axis=axis_name if axis_kind == "x" else current_x,
            y_axis=axis_name if axis_kind == "y" else current_y,
        )

    def _axis_entries(self, axis_kind: Literal["x", "y"]) -> list[_AxisDialogEntry]:
        """Return axis metadata for the configuration dialog."""
        names = self._x_axis_names() if axis_kind == "x" else self._y_axis_names()
        entries: list[_AxisDialogEntry] = []
        for name in names:
            axis = self._axis_items[name]
            entries.append(
                {
                    "name": name,
                    "label": str(axis.axis_label) or name,
                    "log_scale": self._axis_log_scale.get(name, False),
                    "scale": self._axis_scale.get(name, "linear"),
                    "scale_parameter": self._axis_scale_parameter.get(name, 1.0),
                    "side": self._axis_sides.get(
                        name,
                        (
                            "bottom"
                            if axis_kind == "x" and name == "bottom"
                            else "left"
                            if axis_kind == "y" and name == "left"
                            else "top"
                            if axis_kind == "x"
                            else "right"
                        ),
                    ),
                    "visible": self._axis_visible.get(name, name in {"bottom", "left"}),
                    "minimum": self._axis_range_display_values(name)[0],
                    "maximum": self._axis_range_display_values(name)[1],
                    "grid": self._axis_grid.get(name, False),
                    "removable": name not in {"bottom", "left"},
                }
            )
        return entries

    def _open_axes_dialog(self, _pos: QPoint | None = None) -> None:
        """Open the axis configuration dialog and apply accepted changes.

        Args:
            _pos (QPoint | None):
                Position from the custom-context-menu signal. Present for signal
                compatibility and not otherwise used.
        """
        existing_x = set(self._x_axis_names())
        existing_y = set(self._y_axis_names())
        dialog = AxesConfigDialog(
            x_axes=self._axis_entries("x"),
            y_axes=self._axis_entries("y"),
            on_range_changed=self.set_axis_range,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        changes = dialog.axis_changes()
        scales: dict[str, AxisScale] = changes.get(
            "scale",
            {
                name: "log" if enabled else "linear"
                for name, enabled in changes["log_scale"].items()
            },
        )
        previous_manual = dict(self._axis_manual_range)
        previous_auto = dict(self._axis_auto_range)

        self._apply_existing_axis_properties(changes, scales)
        self._apply_dialog_axis_ranges(changes["ranges"], previous_manual, previous_auto)
        self._remove_dialog_axes(changes["removed"])
        self._add_dialog_axes("x", existing_x, changes, scales)
        self._add_dialog_axes("y", existing_y, changes, scales)
        self._apply_dialog_axis_visibility(changes["visible_axes"])

    def _apply_existing_axis_properties(
        self,
        changes: _AxisDialogChanges,
        scales: dict[str, AxisScale],
    ) -> None:
        """Apply non-range settings to axes that already exist."""
        for axis_name, axis_label in changes["labels"].items():
            if axis_name in self._axis_items:
                self.set_axis_label(axis_name, axis_label)
        for axis_name, side in changes["side"].items():
            if axis_name in self._axis_items:
                self.set_axis_side(axis_name, side)
        for axis_name, scale in scales.items():
            if axis_name in self._axis_items:
                parameter = changes.get("scale_parameter", {}).get(axis_name, 1.0)
                self.set_axis_scale(axis_name, scale, parameter)
        for axis_name, enabled in changes["grid"].items():
            if axis_name in self._axis_items:
                self.set_axis_grid(axis_name, enabled)

    def _apply_dialog_axis_ranges(
        self,
        ranges: dict[str, tuple[float | None, float | None]],
        previous_manual: dict[str, tuple[float, float]],
        previous_auto: dict[str, tuple[bool, bool]],
    ) -> None:
        """Apply changed ranges while preserving untouched auto-range state."""
        for axis_name, requested_range in ranges.items():
            if axis_name not in self._axis_items:
                continue
            manual_range = previous_manual.get(axis_name, self._axis_range(axis_name))
            auto_range = previous_auto.get(axis_name, (True, True))
            if self._dialog_range_needs_update(requested_range, manual_range, auto_range):
                self.set_axis_range(
                    axis_name,
                    minimum=requested_range[0],
                    maximum=requested_range[1],
                )

    @staticmethod
    def _dialog_range_needs_update(
        requested: tuple[float | None, float | None],
        manual: tuple[float, float],
        automatic: tuple[bool, bool],
    ) -> bool:
        """Return whether applying a dialog range can change current state."""
        displayed = (
            None if automatic[0] else manual[0],
            None if automatic[1] else manual[1],
        )
        if requested != displayed:
            return True
        if automatic[0] and automatic[1]:
            return False
        return requested != manual

    def _remove_dialog_axes(self, removed: _AxisNameBuckets) -> None:
        """Remove axes marked for deletion in the accepted dialog."""
        for axis_name in removed["x"] + removed["y"]:
            if axis_name in self._axis_items:
                self.remove_axis(axis_name)

    def _add_dialog_axes(
        self,
        axis_kind: Literal["x", "y"],
        existing_axes: set[str],
        changes: _AxisDialogChanges,
        scales: dict[str, AxisScale],
    ) -> None:
        """Create axes newly declared by the accepted dialog."""
        valid_sides = {"top", "bottom"} if axis_kind == "x" else {"left", "right"}
        removed_axes = changes["removed"][axis_kind]
        new_axes = sorted(
            name
            for name in changes["labels"]
            if name not in existing_axes
            and name not in removed_axes
            and changes["side"].get(name) in valid_sides
        )

        for axis_name in new_axes:
            self._add_dialog_axis(axis_kind, axis_name, changes)
            self.set_axis_scale(
                axis_name,
                scales.get(axis_name, "linear"),
                changes.get("scale_parameter", {}).get(axis_name, 1.0),
            )
            self.set_axis_grid(axis_name, changes["grid"].get(axis_name, False))
            minimum, maximum = changes["ranges"].get(axis_name, (None, None))
            self.set_axis_range(axis_name, minimum=minimum, maximum=maximum)

    def _add_dialog_axis(
        self,
        axis_kind: Literal["x", "y"],
        axis_name: str,
        changes: _AxisDialogChanges,
    ) -> None:
        """Create one x or y axis using its validated dialog side."""
        label = changes["labels"].get(axis_name, axis_name)
        side = changes["side"][axis_name]
        if axis_kind == "x":
            self.add_x_axis(
                axis_name,
                label,
                position=cast(Literal["bottom", "top"], side),
            )
            return
        self.add_y_axis(
            axis_name,
            label,
            side=cast(Literal["left", "right"], side),
        )

    def _apply_dialog_axis_visibility(self, visible_axes: dict[str, bool]) -> None:
        """Apply final visibility after axis additions and removals."""
        for axis_name, visible in visible_axes.items():
            if axis_name in self._axis_items:
                self.set_axis_visible(axis_name, visible)

    def _create_pair_view_box(self, x_axis: str, y_axis: str) -> pg.ViewBox:
        """Create a view box for the given axis pair."""
        if (x_axis, y_axis) in self._pair_view_boxes:
            return self._pair_view_boxes[(x_axis, y_axis)]

        view_box = _CoupledViewBox(self)
        self._plot_item.scene().addItem(view_box)
        self._register_view_box_signals(view_box)
        view_box.enableAutoRange()
        if not self._autoscale_new_data:
            view_box.enableAutoRange(enable=False)

        self._pair_view_boxes[(x_axis, y_axis)] = view_box
        self._sync_view_box_geometry()
        if x_axis != "bottom":
            self._axis_items[x_axis].linkToView(view_box)
        if y_axis != "left":
            self._axis_items[y_axis].linkToView(view_box)
        view_box.setLogMode("x", self._axis_scale.get(x_axis) == "log")
        view_box.setLogMode("y", self._axis_scale.get(y_axis) == "log")
        return view_box

    def _get_or_create_trace(self, trace_name: str) -> pg.PlotDataItem:
        """Return the PlotDataItem for *trace_name*, creating it if needed."""
        if trace_name not in self._traces:
            colour = next(self._colour_cycle)
            pen = pg.mkPen(color=colour, width=2, style=_LINE_STYLES["solid"])
            curve = pg.PlotDataItem(pen=pen, name=trace_name)
            curve.setLogMode(False, False)
            # Add to the default ViewBox initially
            self._plot_item.vb.addItem(curve)
            self._traces[trace_name] = curve
            self._trace_data[trace_name] = ([], [])
            self._trace_axes[trace_name] = ("bottom", "left")
            self._trace_style[trace_name] = {
                "colour": colour,
                "line": "solid",
                "point": "none",
            }
            self._trace_line_width[trace_name] = _DEFAULT_LINE_WIDTH
            self._trace_point_size[trace_name] = _DEFAULT_POINT_SIZE
            self._trace_visible[trace_name] = True
            self._refresh_trace_and_axis_controls()
        return self._traces[trace_name]

    def _mapped_axis_values(self, axis_name: str, values) -> np.ndarray:
        """Return raw values transformed for one named axis."""
        return transform_values(
            values,
            self._axis_scale.get(axis_name, "linear"),
            self._axis_scale_parameter.get(axis_name, 1.0),
        )

    def _inverse_axis_values(self, axis_name: str, values) -> np.ndarray:
        """Return ViewBox coordinates converted back to raw axis values."""
        return inverse_values(
            values,
            self._axis_scale.get(axis_name, "linear"),
            self._axis_scale_parameter.get(axis_name, 1.0),
        )

    def _update_trace_display(self, trace_name: str, *, update_errors: bool = True) -> None:
        """Render one trace from its retained raw data using its axis mappings."""
        curve = self._traces[trace_name]
        x_axis, y_axis = self._trace_axes.get(trace_name, ("bottom", "left"))
        xs, ys = self._trace_data[trace_name]
        curve.setLogMode(False, False)
        curve.setData(
            self._mapped_axis_values(x_axis, xs),
            self._mapped_axis_values(y_axis, ys),
        )
        if update_errors:
            self._update_error_bar_display(trace_name)

    def _update_error_bar_display(self, trace_name: str) -> None:
        """Transform and redraw retained error-bar endpoints for one trace."""
        if trace_name not in self._error_bar_items:
            return
        self._error_bar_items[trace_name].setData(**self._mapped_error_bar_data(trace_name))

    def _mapped_error_bar_data(self, trace_name: str) -> dict[str, np.ndarray]:
        """Build transformed pyqtgraph error-bar data for one trace."""
        x_axis, y_axis = self._trace_axes.get(trace_name, ("bottom", "left"))
        xs, ys = (np.asarray(values, dtype=float) for values in self._trace_data[trace_name])
        mapped_x = self._mapped_axis_values(x_axis, xs)
        mapped_y = self._mapped_axis_values(y_axis, ys)
        x_err, y_err = self._trace_error_data.get(trace_name, (None, None))
        kwargs: dict[str, np.ndarray] = {"x": mapped_x, "y": mapped_y}
        if x_err is not None and len(x_err) == len(xs):
            kwargs["left"] = mapped_x - self._mapped_axis_values(x_axis, xs - x_err)
            kwargs["right"] = self._mapped_axis_values(x_axis, xs + x_err) - mapped_x
        if y_err is not None and len(y_err) == len(ys):
            kwargs["bottom"] = mapped_y - self._mapped_axis_values(y_axis, ys - y_err)
            kwargs["top"] = self._mapped_axis_values(y_axis, ys + y_err) - mapped_y
        return kwargs

    def _refresh_auto_ranges_for_view_box(
        self, view_box: pg.ViewBox, x_axis: str, y_axis: str
    ) -> None:
        """Re-apply auto/manual range policy for one axis pair after data changes."""
        x_min_auto, x_max_auto = self._axis_auto_range.get(x_axis, (True, True))
        y_min_auto, y_max_auto = self._axis_auto_range.get(y_axis, (True, True))
        if x_min_auto and x_max_auto and y_min_auto and y_max_auto:
            view_box.enableAutoRange()
            view_box.autoRange()
            return
        if x_min_auto or x_max_auto:
            view_box.enableAutoRange(axis=pg.ViewBox.XAxis, enable=True)
        else:
            view_box.enableAutoRange(axis=pg.ViewBox.XAxis, enable=False)
        if y_min_auto or y_max_auto:
            view_box.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        else:
            view_box.enableAutoRange(axis=pg.ViewBox.YAxis, enable=False)
        view_box.autoRange()
        self._apply_axis_range_state(x_axis)
        self._apply_axis_range_state(y_axis)

    def _refresh_auto_ranges_for_trace(self, trace_name: str) -> None:
        """Update auto-ranged axes for the axis pair used by one trace."""
        if not self._autoscale_new_data:
            return
        x_axis, y_axis = self._trace_axes.get(trace_name, ("bottom", "left"))
        view_box = self._pair_view_boxes.get((x_axis, y_axis), self._plot_item.vb)
        self._refresh_auto_ranges_for_view_box(view_box, x_axis, y_axis)

    def _refresh_all_auto_ranges(self) -> None:
        """Update auto-ranged axes for all registered axis pairs."""
        for (x_axis, y_axis), view_box in self._pair_view_boxes.items():
            self._refresh_auto_ranges_for_view_box(view_box, x_axis, y_axis)

    # ------------------------------------------------------------------
    # Public API — trace management
    # ------------------------------------------------------------------

    @pyqtSlot(str, float, float)
    def append_point(self, trace_name: str, x: float, y: float) -> None:
        """Append a single (x, y) data point to the named trace.

        The trace is created automatically if it does not already exist.

        Args:
            trace_name (str):
                Name of the trace to update.
            x (float):
                Horizontal axis value.
            y (float):
                Vertical axis value.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.append_point("sig", 0.0, 1.0)
            >>> widget.x_data("sig")
            [0.0]
        """
        try:
            self._get_or_create_trace(trace_name)
            xs, ys = self._trace_data[trace_name]
            xs.append(float(x))
            ys.append(float(y))
            self._update_trace_display(trace_name)
            self._refresh_auto_ranges_for_trace(trace_name)
        finally:
            self._mark_data_update_processed()

    @pyqtSlot(str, object, object)
    def set_trace(
        self,
        trace_name: str,
        x_data: Sequence[float],
        y_data: Sequence[float],
    ) -> None:
        """Replace the complete data series for a named trace.

        The trace is created automatically if it does not already exist.

        Args:
            trace_name (str):
                Name of the trace to update.
            x_data (Sequence[float]):
                New horizontal axis data.
            y_data (Sequence[float]):
                New vertical axis data.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.set_trace("sig", [0.0, 1.0], [2.0, 3.0])
            >>> widget.y_data("sig")
            [2.0, 3.0]
        """
        try:
            self._set_trace_data(trace_name, x_data, y_data)
        finally:
            self._mark_data_update_processed()

    def _set_trace_data(
        self,
        trace_name: str,
        x_data: Sequence[float],
        y_data: Sequence[float],
        *,
        update_errors: bool = True,
    ) -> None:
        """Set the x/y arrays for a trace without touching update counters."""
        self._get_or_create_trace(trace_name)
        xs = list(map(float, x_data))
        ys = list(map(float, y_data))
        self._trace_data[trace_name] = (xs, ys)
        self._update_trace_display(trace_name, update_errors=update_errors)
        self._refresh_auto_ranges_for_trace(trace_name)

    @pyqtSlot(str, object, object, object, object)
    def set_trace_with_errors(
        self,
        trace_name: str,
        x_data: Sequence[float],
        y_data: Sequence[float],
        x_err: Sequence[float] | None,
        y_err: Sequence[float] | None,
    ) -> None:
        """Replace the complete data series for a named trace, including error bars.

        The trace is created automatically if it does not already exist.
        Error bars are drawn using :class:`pyqtgraph.ErrorBarItem` when the
        supplied error arrays are non-empty and contain at least one non-zero
        value.  If a previous error-bar item exists for *trace_name* it is
        updated in place; if the new call carries no error data the old item
        is removed.

        Args:
            trace_name (str):
                Name of the trace to update.
            x_data (Sequence[float]):
                New horizontal axis data.
            y_data (Sequence[float]):
                New vertical axis data.
            x_err (Sequence[float] | None):
                Symmetric x-axis error values (half-lengths), or ``None`` /
                empty array for no x-error bars.
            y_err (Sequence[float] | None):
                Symmetric y-axis error values (half-lengths), or ``None`` /
                empty array for no y-error bars.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> import numpy as np
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.set_trace_with_errors("sig", [0.0, 1.0], [2.0, 3.0], None, [0.1, 0.1])
            >>> widget.y_data("sig")
            [2.0, 3.0]
        """
        try:
            self._set_trace_data(trace_name, x_data, y_data, update_errors=False)

            x_arr = np.asarray(x_data, dtype=float)
            y_arr = np.asarray(y_data, dtype=float)

            x_err_arr = (
                np.asarray(x_err, dtype=float) if x_err is not None else np.array([], dtype=float)
            )
            y_err_arr = (
                np.asarray(y_err, dtype=float) if y_err is not None else np.array([], dtype=float)
            )
            has_x_err = len(x_err_arr) == len(x_arr) and np.any(x_err_arr != 0)
            has_y_err = len(y_err_arr) == len(y_arr) and np.any(y_err_arr != 0)

            x_ax, y_ax = self._trace_axes.get(trace_name, ("bottom", "left"))
            vb = self._pair_view_boxes.get((x_ax, y_ax), self._plot_item.vb)

            if has_x_err or has_y_err:
                self._trace_error_data[trace_name] = (
                    x_err_arr if has_x_err else None,
                    y_err_arr if has_y_err else None,
                )
                if trace_name in self._error_bar_items:
                    self._update_error_bar_display(trace_name)
                else:
                    ebi = pg.ErrorBarItem(**self._mapped_error_bar_data(trace_name))
                    vb.addItem(ebi)
                    self._error_bar_items[trace_name] = ebi
            elif trace_name in self._error_bar_items:
                ebi = self._error_bar_items.pop(trace_name)
                self._trace_error_data.pop(trace_name, None)
                parent = ebi.parentItem()
                if hasattr(parent, "removeItem"):
                    parent.removeItem(ebi)
                elif ebi.parentItem() is vb.childGroup:
                    vb.removeItem(ebi)
        finally:
            self._mark_data_update_processed()

    @pyqtSlot()
    def mark_data_update_queued(self) -> None:
        """Record that a plot data update has been queued for processing."""
        with self._pending_data_updates_lock:
            self._pending_data_updates += 1

    def _mark_data_update_processed(self) -> None:
        """Record completion of one previously queued plot data update."""
        with self._pending_data_updates_lock:
            self._pending_data_updates = max(0, self._pending_data_updates - 1)

    def is_busy_for_data(self) -> bool:
        """Return ``True`` when queued plot data updates are still pending."""
        with self._pending_data_updates_lock:
            return self._pending_data_updates > 0

    @pyqtSlot(object, object)
    def set_default_axis_labels(self, x_label: AxisLabel | str, y_label: AxisLabel | str) -> None:
        """Accumulate and display labels for the default bottom and left axes.

        Called by :class:`~stoner_measurement.plugins.command.PlotTraceCommand`
        when trace metadata (names and units from
        :class:`~stoner_measurement.core.TraceData`) is available so
        that the plot axes reflect the physical quantities being displayed.

        Args:
            x_label (str):
                Label for the bottom (x) axis.  If empty the axis label is
                left unchanged.
            y_label (str):
                Label for the left (y) axis.  If empty the axis label is left
                unchanged.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.set_default_axis_labels("Current (A)", "Voltage (V)")
            >>> widget._pg_widget.getPlotItem().getAxis("bottom").axis_label
            AxisLabel(label='Current', unit='A')
        """
        self._accumulate_axis_label("bottom", x_label)
        self._accumulate_axis_label("left", y_label)

    def _accumulate_axis_label(self, axis_name: str, label: AxisLabel | str) -> None:
        """Add one distinct quantity label to an axis and refresh its title."""
        metadata = AxisLabel.coerce(label)
        if not str(metadata) or metadata == AxisLabel(axis_name):
            return
        labels = self._axis_labels.setdefault(axis_name, set())
        if metadata in labels:
            return
        labels.add(metadata)
        ordered_labels = sorted(labels, key=lambda item: str(item).casefold())
        display_label = (
            ordered_labels[0]
            if len(ordered_labels) == 1
            else AxisLabel(", ".join(str(item) for item in ordered_labels))
        )
        self.set_axis_label(axis_name, display_label)

    def set_rolling_time_window(self, duration_seconds: float) -> None:
        """Fix the bottom axis to a real-time window ending at the present.

        Rolling controller charts express sample timestamps as negative seconds
        relative to the current time. Keeping this axis manual prevents the
        data extent and polling density from changing the apparent time scale.
        """
        duration = float(duration_seconds)
        if not np.isfinite(duration) or duration <= 0.0:
            raise ValueError("Rolling time-window duration must be positive and finite.")
        self.set_axis_range("bottom", minimum=-duration, maximum=0.0)

    def set_trace_style(  # pylint: disable=too-many-arguments
        self,
        trace_name: str,
        *,
        colour: str | None = None,
        line_style: str | None = None,
        point_style: str | None = None,
        line_width: float | None = None,
        point_size: float | None = None,
    ) -> None:
        """Set visual style properties for a trace.

        Args:
            trace_name (str):
                Name of the trace to style.

        Keyword Parameters:
            colour (str | None):
                Colour string accepted by pyqtgraph (e.g. ``"#ff0000"``). If
                ``None``, the trace's existing colour is preserved.
            line_style (str):
                One of ``"solid"``, ``"dash"``, ``"dot"``, ``"dash-dot"``,
                or ``"none"``.
            point_style (str):
                One of ``"none"``, ``"circle"``, ``"square"``, ``"triangle"``,
                ``"diamond"``, ``"plus"``, or ``"cross"``.
            line_width (float | None):
                Width of the plotted line. If ``None`` the existing width is
                preserved.
            point_size (float | None):
                Size of plotted points. If ``None`` the existing size is
                preserved.

        Raises:
            ValueError:
                If *line_style* or *point_style* are unknown values.
        """
        curve = self._get_or_create_trace(trace_name)
        if not (line_style is None or line_style in _LINE_STYLES):
            valid_line_styles = ", ".join(_LINE_STYLES)
            raise ValueError(
                f"Unknown line style: {line_style!r}. Valid options are: {valid_line_styles}."
            )
        if not (point_style is None or point_style in _POINT_STYLES):
            valid_point_styles = ", ".join(_POINT_STYLES)
            raise ValueError(
                f"Unknown point style: {point_style!r}. Valid options are: {valid_point_styles}."
            )
        if line_width is not None and line_width <= 0:
            raise ValueError(f"Line width must be greater than zero, got {line_width}.")
        if point_size is not None and point_size <= 0:
            raise ValueError(f"Point size must be greater than zero, got {point_size}.")

        style = self._trace_style[trace_name]
        if colour is not None:
            if not QColor(colour).isValid():
                raise ValueError(f"Invalid colour value: {colour!r}")
            style["colour"] = colour
        if line_style is not None:
            style["line"] = line_style
        else:
            style.setdefault("line", "solid")
        if point_style is not None:
            style["point"] = point_style
        else:
            style.setdefault("point", "none")
        if line_width is not None:
            self._trace_line_width[trace_name] = line_width
        if point_size is not None:
            self._trace_point_size[trace_name] = point_size

        pen = pg.mkPen(
            color=style["colour"],
            width=self._trace_line_width.get(trace_name, _DEFAULT_LINE_WIDTH),
            style=_LINE_STYLES[style["line"]],
        )
        curve.setPen(pen)
        symbol = _POINT_STYLES.get(style["point"], None)
        curve.setSymbol(symbol)
        if symbol is None:
            curve.setSymbolBrush(None)
            curve.setSymbolPen(None)
        else:
            curve.setSymbolBrush(style["colour"])
            curve.setSymbolPen(pen)
        curve.setSymbolSize(self._trace_point_size.get(trace_name, _DEFAULT_POINT_SIZE))
        self._refresh_trace_and_axis_controls()

    @pyqtSlot(str, object)
    def set_trace_style_from_dict(self, trace_name: str, style: dict) -> None:
        """Apply visual style properties supplied in a dict from a command plugin.

        Calls :meth:`set_trace_style` using only the keys present in *style*
        that carry non-empty, non-zero values.  Unknown keys are silently
        ignored so that callers do not need to know the exact parameter names.

        Args:
            trace_name (str):
                Name of the trace to style.
            style (dict):
                Mapping containing any subset of ``"colour"``, ``"line_style"``,
                ``"point_style"``, ``"line_width"``, and ``"point_size"``.
                Empty string values and zero numeric values are treated as
                *"use widget default"* and are not forwarded to
                :meth:`set_trace_style`.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.append_point("sig", 0.0, 1.0)
            >>> widget.set_trace_style_from_dict("sig", {"colour": "red", "line_style": "dash"})
            >>> widget._trace_style["sig"]["colour"]
            '#ff0000'
            >>> widget._trace_style["sig"]["line"]
            'dash'
        """
        if not style:
            return
        colour = style.get("colour") or None
        line_style = style.get("line_style") or None
        point_style = style.get("point_style") or None
        # Zero is treated as "use widget default" — only forward positive values.
        raw_width = style.get("line_width")
        raw_size = style.get("point_size")
        try:
            width_val = float(raw_width) if raw_width is not None else 0.0
            line_width = width_val if width_val > 0 else None
            size_val = float(raw_size) if raw_size is not None else 0.0
            point_size = size_val if size_val > 0 else None
            self.set_trace_style(
                trace_name,
                colour=colour,
                line_style=line_style,
                point_style=point_style,
                line_width=line_width,
                point_size=point_size,
            )
        except (TypeError, ValueError) as exc:
            logger.warning(
                "set_trace_style_from_dict: invalid style value for %r: %s", trace_name, exc
            )

    def remove_trace(self, trace_name: str) -> None:
        """Remove a named trace and all its data.

        If *trace_name* does not exist this call is a no-op.

        Args:
            trace_name (str):
                Name of the trace to remove.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.append_point("sig", 0.0, 1.0)
            >>> widget.remove_trace("sig")
            >>> widget.trace_names
            []
        """
        if trace_name not in self._traces:
            return
        curve = self._traces.pop(trace_name)
        # Determine which ViewBox owns the curve and remove it from there.
        x_ax, y_ax = self._trace_axes.pop(trace_name, ("bottom", "left"))
        vb = self._pair_view_boxes.get((x_ax, y_ax), self._plot_item.vb)
        vb.removeItem(curve)
        if trace_name in self._error_bar_items:
            vb.removeItem(self._error_bar_items.pop(trace_name))
        self._trace_error_data.pop(trace_name, None)
        del self._trace_data[trace_name]
        self._trace_style.pop(trace_name, None)
        self._trace_line_width.pop(trace_name, None)
        self._trace_point_size.pop(trace_name, None)
        self._trace_visible.pop(trace_name, None)
        self._refresh_trace_and_axis_controls()

    @pyqtSlot(str, str)
    def rename_trace(self, old_name: str, new_name: str) -> None:
        """Rename a trace without losing its data, axes, style, or visibility.

        Missing source traces are ignored so command plugins may request a
        rename before their first point has been plotted. Renaming onto an
        existing trace is rejected to avoid silently merging or overwriting
        data.

        Args:
            old_name (str):
                Current trace name.
            new_name (str):
                Replacement trace name.

        Raises:
            ValueError:
                If *new_name* is empty or already belongs to another trace.
        """
        old_name = old_name.strip()
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("Trace name cannot be empty.")
        if old_name == new_name or old_name not in self._traces:
            return
        if new_name in self._traces:
            raise ValueError(f"Trace {new_name!r} already exists.")

        for mapping in (
            self._traces,
            self._trace_data,
            self._error_bar_items,
            self._trace_error_data,
            self._trace_axes,
            self._trace_style,
            self._trace_line_width,
            self._trace_point_size,
            self._trace_visible,
        ):
            if old_name in mapping:
                mapping[new_name] = mapping.pop(old_name)

        self._traces[new_name].opts["name"] = new_name
        self._trace_controls_state = None
        self._refresh_trace_and_axis_controls()

    def clear_all(self) -> None:
        """Remove all traces, their data, and accumulated axis labels.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.append_point("a", 1.0, 2.0)
            >>> widget.clear_all()
            >>> widget.trace_names
            []
        """
        self._colour_cycle = cycle(_TRACE_COLOURS)
        self.clear_data_markers()
        for name in list(self._traces.keys()):
            self.remove_trace(name)
        for labels in self._axis_labels.values():
            labels.clear()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Detach pyqtgraph items before Qt tears down the graphics scene."""
        self._teardown_plot_items()
        super().closeEvent(event)

    def _teardown_plot_items(self) -> None:
        """Remove traces and error bars while the plot scene is still valid."""
        if not hasattr(self, "_plot_item"):
            return

        self.clear_data_markers()

        for trace_name, error_bar_item in list(self._error_bar_items.items()):
            x_ax, y_ax = self._trace_axes.get(trace_name, ("bottom", "left"))
            view_box = self._pair_view_boxes.get((x_ax, y_ax), self._plot_item.vb)
            _safe_remove_graphics_item(view_box, error_bar_item)
            _safe_detach_graphics_item(error_bar_item)
        self._error_bar_items.clear()
        self._trace_error_data.clear()

        for trace_name, curve in list(self._traces.items()):
            x_ax, y_ax = self._trace_axes.get(trace_name, ("bottom", "left"))
            view_box = self._pair_view_boxes.get((x_ax, y_ax), self._plot_item.vb)
            _safe_remove_graphics_item(view_box, curve)
            _safe_detach_graphics_item(curve)

        self._traces.clear()
        self._trace_data.clear()
        self._trace_axes.clear()
        self._trace_style.clear()
        self._trace_line_width.clear()
        self._trace_point_size.clear()
        self._trace_visible.clear()

    # ------------------------------------------------------------------
    # Public API — axis management
    # ------------------------------------------------------------------

    def _axis_range(self, name: str) -> tuple[float | None, float | None]:
        """Return the currently visible range for an axis."""
        if name not in self._axis_items:
            raise KeyError(f"Unknown axis: {name!r}")
        orientation = self._axis_orientations[name]
        if orientation == "x":
            linked_y = "left"
            for x_axis, y_axis in self._pair_view_boxes:
                if x_axis == name:
                    linked_y = y_axis
                    break
            view_box = self._pair_view_boxes.get((name, linked_y), self._plot_item.vb)
            minimum, maximum = view_box.viewRange()[0]
        else:
            linked_x = "bottom"
            for x_axis, y_axis in self._pair_view_boxes:
                if y_axis == name:
                    linked_x = x_axis
                    break
            view_box = self._pair_view_boxes.get((linked_x, name), self._plot_item.vb)
            minimum, maximum = view_box.viewRange()[1]
        raw = self._inverse_axis_values(name, [minimum, maximum])
        return float(raw[0]), float(raw[1])

    def set_axis_label(self, name: str, label: AxisLabel | str) -> None:
        """Set the displayed title for an axis.

        Args:
            name (str):
                Registered axis name.
            label (str):
                Label text to display on the axis.

        Raises:
            KeyError:
                If *name* is unknown.
        """
        if name not in self._axis_items:
            raise KeyError(f"Unknown axis: {name!r}")
        self._axis_items[name].set_axis_label(label)
        apply_pyqtgraph_dark_theme(self._plot_item, self._axis_items)

    def set_axis_log_scale(self, name: str, log_scale: bool) -> None:
        """Set logarithmic scaling mode for an axis.

        Args:
            name (str):
                Registered axis name.
            log_scale (bool):
                ``True`` to use log scale, ``False`` for linear scale.

        Raises:
            KeyError:
                If *name* is unknown.
        """
        self.set_axis_scale(name, "log" if log_scale else "linear")

    def set_axis_scale(self, name: str, scale: AxisScale, parameter: float = 1.0) -> None:
        """Set an axis to linear, log, symlog, logit, or asinh mapping."""
        if name not in self._axis_items:
            raise KeyError(f"Unknown axis: {name!r}")
        scale, parameter = validate_scale(scale, parameter)
        min_auto, max_auto = self._axis_auto_range.get(name, (True, True))
        stored_minimum, stored_maximum = self._axis_manual_range.get(name, self._axis_range(name))
        manual_values = [
            value
            for value, automatic in (
                (stored_minimum, min_auto),
                (stored_maximum, max_auto),
            )
            if not automatic and value is not None
        ]
        if manual_values and not np.all(
            np.isfinite(transform_values(manual_values, scale, parameter))
        ):
            raise ValueError(f"Existing manual range is outside the domain of the {scale} scale.")
        self._axis_scale[name] = scale
        self._axis_scale_parameter[name] = parameter
        self._axis_log_scale[name] = scale == "log"
        axis_item = self._axis_items[name]
        if isinstance(axis_item, MappedAxisItem):
            axis_item.set_scale_mapping(scale, parameter)
        else:
            axis_item.setLogMode(scale == "log")
        for (x_axis, y_axis), view_box in self._pair_view_boxes.items():
            view_box.setLogMode("x", self._axis_scale.get(x_axis) == "log")
            view_box.setLogMode("y", self._axis_scale.get(y_axis) == "log")
        for trace_name in self._traces:
            self._update_trace_display(trace_name)
        self._refresh_data_markers()
        self._refresh_all_auto_ranges()
        self._reapply_manual_axis_ranges()

    def set_axis_side(self, name: str, side: str) -> None:
        """Move an axis to a different side of the plot."""
        if name not in self._axis_items:
            raise KeyError(f"Unknown axis: {name!r}")
        orientation = self._axis_orientations[name]
        valid_sides = {"x": {"top", "bottom"}, "y": {"left", "right"}}[orientation]
        if side not in valid_sides:
            raise ValueError(f"Invalid side {side!r} for {orientation}-axis.")
        self._unregister_axis_side(name, orientation)
        self._register_axis_side(name, orientation, side)
        axis_item = self._axis_items[name]
        self._plot_item.layout.removeItem(axis_item)
        self._layout_additional_axes()
        self._reapply_manual_axis_ranges()
        if self._axis_visible.get(name, True):
            axis_item.show()
        else:
            axis_item.hide()
        apply_pyqtgraph_dark_theme(self._plot_item, self._axis_items)

    def set_axis_visible(self, name: str, visible: bool) -> None:
        """Show or hide an axis item."""
        if name not in self._axis_items:
            raise KeyError(f"Unknown axis: {name!r}")
        self._axis_visible[name] = bool(visible)
        if visible:
            self._axis_items[name].show()
        else:
            self._axis_items[name].hide()

    def reset_all_view_ranges(self) -> None:
        """Reset all axis view ranges to their auto-ranged home state."""
        for axis_name in self._axis_items:
            self._set_axis_auto_state(axis_name, True, True)
        for view_box in self._pair_view_boxes.values():
            view_box.enableAutoRange()
            view_box.autoRange()
        self._refresh_all_auto_ranges()
        if not self._autoscale_new_data:
            for view_box in self._pair_view_boxes.values():
                view_box.enableAutoRange(enable=False)

    def set_axis_range(
        self, name: str, minimum: float | None = None, maximum: float | None = None
    ) -> None:
        """Set the visible range for an axis with independent auto/manual bounds.

        Passing ``None`` for either bound leaves that bound on auto-range while
        a numeric value fixes it manually.
        """
        if name not in self._axis_items:
            raise KeyError(f"Unknown axis: {name!r}")
        min_auto = minimum is None
        max_auto = maximum is None
        orientation = self._axis_orientations[name]
        if minimum is not None and maximum is not None and minimum >= maximum:
            raise ValueError(f"Axis minimum must be less than maximum for {name!r}.")
        supplied_bounds = [value for value in (minimum, maximum) if value is not None]
        if supplied_bounds and not np.all(
            np.isfinite(self._mapped_axis_values(name, supplied_bounds))
        ):
            raise ValueError(
                f"Axis range is outside the domain of the {self._axis_scale[name]} scale."
            )
        current_minimum, current_maximum = self._axis_range(name)
        stored_minimum, stored_maximum = self._axis_manual_range.get(
            name, (current_minimum, current_maximum)
        )
        manual_minimum = current_minimum if min_auto else minimum
        manual_maximum = current_maximum if max_auto else maximum
        if minimum is not None:
            stored_minimum = minimum
        if maximum is not None:
            stored_maximum = maximum
        if minimum is None and maximum is None:
            stored_minimum, stored_maximum = current_minimum, current_maximum
        self._axis_manual_range[name] = (stored_minimum, stored_maximum)
        self._axis_auto_range[name] = (min_auto, max_auto)
        targets = [
            view_box
            for (x_axis, y_axis), view_box in self._pair_view_boxes.items()
            if (orientation == "x" and x_axis == name) or (orientation == "y" and y_axis == name)
        ]
        if not targets:
            targets = [self._plot_item.vb]
        axis_constant = pg.ViewBox.XAxis if orientation == "x" else pg.ViewBox.YAxis
        for view_box in targets:
            if min_auto and max_auto:
                view_box.enableAutoRange(axis=axis_constant, enable=True)
            else:
                view_box.enableAutoRange(axis=axis_constant, enable=True)
                view_box.autoRange()
                mapped_autorange_minimum, mapped_autorange_maximum = (
                    view_box.viewRange()[0] if orientation == "x" else view_box.viewRange()[1]
                )
                autorange_minimum, autorange_maximum = self._inverse_axis_values(
                    name, [mapped_autorange_minimum, mapped_autorange_maximum]
                )
                final_minimum = autorange_minimum if min_auto else manual_minimum
                final_maximum = autorange_maximum if max_auto else manual_maximum
                if final_minimum is None or final_maximum is None:
                    raise RuntimeError(f"Could not resolve axis range for {name!r}.")
                if final_minimum >= final_maximum:
                    raise ValueError(f"Axis minimum must be less than maximum for {name!r}.")
                mapped_range = self._mapped_axis_values(name, [final_minimum, final_maximum])
                if not np.all(np.isfinite(mapped_range)):
                    raise ValueError(
                        f"Axis range is outside the domain of the {self._axis_scale[name]} scale."
                    )
                view_box.enableAutoRange(axis=axis_constant, enable=False)
                if orientation == "x":
                    view_box.setRange(xRange=tuple(mapped_range), padding=0.0)
                else:
                    view_box.setRange(yRange=tuple(mapped_range), padding=0.0)

    def _update_grid_state(self) -> None:
        """Apply grid visibility directly to each axis item.

        PyQtGraph's PlotItem.showGrid() only exposes one shared x-grid and one
        shared y-grid for the whole plot, which cannot represent independent
        per-axis visibility for top/bottom or left/right axes. Applying the
        grid state to each AxisItem allows those axis-specific preferences to
        be preserved even while traces are updated dynamically.
        """
        for name, axis_item in self._axis_items.items():
            if self._axis_grid.get(name, False):
                axis_item.setGrid(_PLOT_GRID_ALPHA)
            else:
                axis_item.setGrid(False)

    def set_axis_grid(self, name: str, enabled: bool) -> None:
        """Set grid visibility preference for an axis.

        Args:
            name (str):
                Registered axis name.
            enabled (bool):
                Whether this axis contributes to aggregate grid visibility.

        Raises:
            KeyError:
                If *name* is unknown.
        """
        if name not in self._axis_items:
            raise KeyError(f"Unknown axis: {name!r}")
        self._axis_grid[name] = bool(enabled)
        self._update_grid_state()

    def remove_axis(self, name: str) -> None:
        """Remove a non-default axis and reassign traces using it.

        Args:
            name (str):
                Registered axis name to remove.

        Raises:
            KeyError:
                If *name* is unknown.
            ValueError:
                If attempting to remove the built-in ``"bottom"`` or ``"left"``
                axis.
        """
        if name not in self._axis_items:
            raise KeyError(f"Unknown axis: {name!r}")
        if name in {"bottom", "left"}:
            raise ValueError(f"Cannot remove default axis: {name!r}")

        orientation = self._axis_orientations[name]
        default_axis = "bottom" if orientation == "x" else "left"
        for trace_name, (x_axis, y_axis) in list(self._trace_axes.items()):
            if orientation == "x" and x_axis == name:
                self.assign_trace_axes(trace_name, x_axis=default_axis, y_axis=y_axis)
            if orientation == "y" and y_axis == name:
                self.assign_trace_axes(trace_name, x_axis=x_axis, y_axis=default_axis)

        for key, view_box in list(self._pair_view_boxes.items()):
            if key == ("bottom", "left"):
                continue
            if name not in key:
                continue
            self._plot_item.scene().removeItem(view_box)
            self._pair_view_boxes.pop(key, None)

        axis_item = self._axis_items.pop(name)
        self._plot_item.layout.removeItem(axis_item)
        axis_item.hide()
        self._axis_visible.pop(name, None)
        self._unregister_axis_side(name, orientation)
        self._axis_orientations.pop(name, None)
        self._view_boxes.pop(name, None)
        self._axis_log_scale.pop(name, None)
        self._axis_scale.pop(name, None)
        self._axis_scale_parameter.pop(name, None)
        self._axis_grid.pop(name, None)
        self._axis_auto_range.pop(name, None)
        self._axis_manual_range.pop(name, None)
        self._axis_labels.pop(name, None)
        self._update_grid_state()
        self._refresh_trace_and_axis_controls()

    def add_y_axis(
        self,
        name: str,
        label: AxisLabel | str,
        side: Literal["left", "right"] = "right",
    ) -> None:
        """Add a new y-axis with an independent :class:`pyqtgraph.ViewBox`.

        The new ViewBox is linked to the main plot's x-axis so that panning
        and zooming in x remain synchronised across all y-axes.

        Args:
            name (str):
                Unique identifier for the new axis.
            label (str):
                Text label shown on the axis.

        Keyword Parameters:
            side (Literal["left", "right"]):
                Side of the plot on which the axis appears.  Defaults to
                ``"right"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.add_y_axis("temperature", "Temperature (K)", side="right")
            >>> "temperature" in widget.axis_names
            True
        """
        if name in self._axis_items:
            return
        axis = MappedAxisItem(side)
        axis.set_axis_label(label)
        axis.setGrid(False)
        self._axis_items[name] = axis
        self._axis_labels[name] = set()
        self._accumulate_axis_label(name, label)
        apply_pyqtgraph_dark_theme(self._plot_item, self._axis_items)
        self._axis_orientations[name] = "y"
        self._register_axis_side(name, "y", side)
        self._axis_visible[name] = True
        self._axis_log_scale[name] = False
        self._axis_scale[name] = "linear"
        self._axis_scale_parameter[name] = 1.0
        self._axis_auto_range[name] = (True, True)
        self._axis_manual_range[name] = self._axis_range("left")
        self._axis_grid[name] = False
        self._view_boxes[name] = self._create_pair_view_box("bottom", name)
        self._layout_additional_axes()
        self._reapply_manual_axis_ranges()
        self._update_grid_state()
        self._refresh_trace_and_axis_controls()

    def ensure_y_axis(self, name: str, label: AxisLabel | str = "") -> None:
        """Ensure a y-axis with *name* exists, creating it on the right if absent.

        If the axis already exists its label metadata is refreshed.  Otherwise
        a new right-hand y-axis is added using :meth:`add_y_axis`, with *label*
        as the displayed axis label (falling back to *name* when empty).

        This is intended for use by command plugins that direct trace data to a
        named axis — they call this method before :meth:`assign_trace_axes` so
        that axes are created on demand without requiring the user to add them
        manually first.

        Args:
            name (str):
                Identifier for the y-axis.  One of the default ``"left"``
                axis names or a custom name.

        Keyword Parameters:
            label (str):
                Text label shown on the axis.  Defaults to *name* when empty.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.ensure_y_axis("temp", "Temperature (K)")
            >>> "temp" in widget.axis_names
            True
            >>> widget.ensure_y_axis("temp")  # idempotent
            >>> widget.axis_names.count("temp")
            1
        """
        if name in self._axis_items:
            self._accumulate_axis_label(name, label)
            return
        self.add_y_axis(name, label or name)

    def add_x_axis(
        self,
        name: str,
        label: AxisLabel | str,
        position: Literal["bottom", "top"] = "top",
    ) -> None:
        """Add a new x-axis with an independent :class:`pyqtgraph.ViewBox`.

        The new ViewBox is linked to the main plot's y-axis so that panning
        and zooming in y remain synchronised.

        Args:
            name (str):
                Unique identifier for the new axis.
            label (str):
                Text label shown on the axis.

        Keyword Parameters:
            position (Literal["bottom", "top"]):
                Position of the axis relative to the plot.  Defaults to
                ``"top"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.add_x_axis("freq", "Frequency (Hz)", position="top")
            >>> "freq" in widget.axis_names
            True
        """
        if name in self._axis_items:
            return
        axis = MappedAxisItem(position)
        axis.set_axis_label(label)
        axis.setGrid(False)
        self._axis_items[name] = axis
        self._axis_labels[name] = set()
        self._accumulate_axis_label(name, label)
        apply_pyqtgraph_dark_theme(self._plot_item, self._axis_items)
        self._axis_orientations[name] = "x"
        self._register_axis_side(name, "x", position)
        self._axis_visible[name] = True
        self._axis_log_scale[name] = False
        self._axis_scale[name] = "linear"
        self._axis_scale_parameter[name] = 1.0
        self._axis_auto_range[name] = (True, True)
        self._axis_manual_range[name] = self._axis_range("bottom")
        self._axis_grid[name] = False
        self._view_boxes[name] = self._create_pair_view_box(name, "left")
        self._layout_additional_axes()
        self._reapply_manual_axis_ranges()
        self._update_grid_state()
        self._refresh_trace_and_axis_controls()

    def ensure_x_axis(self, name: str, label: AxisLabel | str = "") -> None:
        """Ensure an x-axis with *name* exists, creating it at the top if absent.

        Args:
            name (str):
                Identifier for the x-axis. One of the default ``"bottom"``
                axis names or a custom name.

        Keyword Parameters:
            label (str):
                Text label shown on the axis. Defaults to *name* when empty.
        """
        if name in self._axis_items:
            self._accumulate_axis_label(name, label)
            return
        self.add_x_axis(name, label or name)

    @pyqtSlot(str, str, str)
    def assign_trace_axes(
        self,
        trace_name: str,
        x_axis: str = "bottom",
        y_axis: str = "left",
    ) -> None:
        """Assign a trace to a specific pair of axes.

        The trace is moved from its current :class:`pyqtgraph.ViewBox` to the
        ViewBox associated with *y_axis*.  This controls which axis range is
        used when the trace is rendered.

        Args:
            trace_name (str):
                Name of the trace to reassign.

        Keyword Parameters:
            x_axis (str):
                Name of the x-axis to use (must have been created via
                :meth:`add_x_axis` or be ``"bottom"``).  Defaults to
                ``"bottom"``.
            y_axis (str):
                Name of the y-axis to use (must have been created via
                :meth:`add_y_axis` or be ``"left"``).  Defaults to
                ``"left"``.

        Raises:
            KeyError:
                If *trace_name*, *x_axis*, or *y_axis* are not registered.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.add_y_axis("temp", "Temperature (K)")
            >>> widget.append_point("sig", 0.0, 300.0)
            >>> widget.assign_trace_axes("sig", y_axis="temp")
        """
        if trace_name not in self._traces:
            raise KeyError(f"Unknown trace: {trace_name!r}")
        if x_axis not in self._axis_items:
            raise KeyError(f"Unknown x-axis: {x_axis!r}")
        if y_axis not in self._axis_items:
            raise KeyError(f"Unknown y-axis: {y_axis!r}")
        if self._axis_orientations.get(x_axis) != "x":
            raise KeyError(f"Unknown x-axis: {x_axis!r}")
        if self._axis_orientations.get(y_axis) != "y":
            raise KeyError(f"Unknown y-axis: {y_axis!r}")

        curve = self._traces[trace_name]
        old_axes = self._trace_axes[trace_name]
        if old_axes == (x_axis, y_axis):
            return
        old_vb = self._pair_view_boxes.get(old_axes, self._plot_item.vb)
        new_vb = self._create_pair_view_box(x_axis, y_axis)

        if old_vb is not new_vb:
            old_vb.removeItem(curve)
            new_vb.addItem(curve)
            if trace_name in self._error_bar_items:
                ebi = self._error_bar_items[trace_name]
                old_vb.removeItem(ebi)
                new_vb.addItem(ebi)

        self._trace_axes[trace_name] = (x_axis, y_axis)
        self._update_trace_display(trace_name)
        self._refresh_trace_and_axis_controls()

    # ------------------------------------------------------------------
    # Public API — data accessors
    # ------------------------------------------------------------------

    def x_data(self, trace_name: str = "default") -> list[float]:
        """Return the horizontal axis data for *trace_name*.

        Args:
            trace_name (str):
                Name of the trace.  Defaults to ``"default"``.

        Returns:
            (list[float]):
                Copy of the x data list.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.append_point("sig", 1.0, 2.0)
            >>> widget.x_data("sig")
            [1.0]
        """
        if trace_name not in self._trace_data:
            return []
        return list(self._trace_data[trace_name][0])

    def y_data(self, trace_name: str = "default") -> list[float]:
        """Return the vertical axis data for *trace_name*.

        Args:
            trace_name (str):
                Name of the trace.  Defaults to ``"default"``.

        Returns:
            (list[float]):
                Copy of the y data list.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.append_point("sig", 1.0, 2.0)
            >>> widget.y_data("sig")
            [2.0]
        """
        if trace_name not in self._trace_data:
            return []
        return list(self._trace_data[trace_name][1])

    @property
    def trace_names(self) -> list[str]:
        """Sorted list of currently registered trace names.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.append_point("b", 0.0, 1.0)
            >>> widget.append_point("a", 0.0, 1.0)
            >>> widget.trace_names
            ['a', 'b']
        """
        return sorted(self._traces)

    @property
    def axis_names(self) -> list[str]:
        """Sorted list of all registered axis names (x and y combined).

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> sorted(widget.axis_names)
            ['bottom', 'left']
        """
        return sorted(self._axis_items)

    @property
    def pg_widget(self) -> pg.PlotWidget:
        """The underlying :class:`pyqtgraph.PlotWidget`."""
        return self._pg_widget
