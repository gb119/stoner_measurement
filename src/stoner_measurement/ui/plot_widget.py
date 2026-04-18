"""Central PyQtGraph plotting widget — middle 50 % of the main window.

Supports multiple named traces (each with its own colour) and multiple
independent x- and y-axes implemented via linked
:class:`pyqtgraph.ViewBox` instances.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from itertools import cycle
from typing import Literal

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Colour palette used when automatically assigning colours to new traces.
_TRACE_COLOURS = [
    "royalblue",
    "darkorange",
    "forestgreen",
    "firebrick",
    "mediumpurple",
    "saddlebrown",
    "deeppink",
    "dimgray",
    "olive",
    "teal",
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
_COLOUR_COLUMN_WIDTH = 90
_AXIS_COLUMN_WIDTH = 120
_TRACE_NAME_PROPERTY = "trace_name"
_TRACE_AXIS_PROPERTY = "axis"


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
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> widget = PlotWidget()
        >>> widget.append_point("my_trace", 1.0, 2.0)
        >>> widget.x_data("my_trace")
        [1.0]
    """

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        # Per-trace data storage: name → (x_list, y_list)
        self._trace_data: dict[str, tuple[list[float], list[float]]] = {}
        # Per-trace plot item
        self._traces: dict[str, pg.PlotDataItem] = {}
        # Per-trace axis assignment: name → (x_axis_name, y_axis_name)
        self._trace_axes: dict[str, tuple[str, str]] = {}
        # Per-trace style: name → {"colour": str, "line": str, "point": str}
        self._trace_style: dict[str, dict[str, str]] = {}
        self._trace_line_width: dict[str, float] = {}
        self._trace_point_size: dict[str, float] = {}
        self._trace_visible: dict[str, bool] = {}
        self._pending_data_updates: int = 0
        self._pending_data_updates_lock = threading.Lock()
        self._updating_trace_controls = False
        # Colour cycle for auto-assignment
        self._colour_cycle = cycle(_TRACE_COLOURS)

        # ViewBox registry: axis_name → ViewBox for backwards compatibility.
        self._view_boxes: dict[str, pg.ViewBox] = {}
        # Pair registry: (x_axis, y_axis) → ViewBox.
        self._pair_view_boxes: dict[tuple[str, str], pg.ViewBox] = {}
        # AxisItem registry: axis_name → AxisItem
        self._axis_items: dict[str, pg.AxisItem] = {}
        # Axis orientation registry: axis_name → "x" | "y".
        self._axis_orientations: dict[str, Literal["x", "y"]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        self._add_x_axis_button = QPushButton("+X Axis", self)
        self._add_x_axis_button.clicked.connect(self._prompt_add_x_axis)
        controls.addWidget(self._add_x_axis_button)
        self._add_y_axis_button = QPushButton("+Y Axis", self)
        self._add_y_axis_button.clicked.connect(self._prompt_add_y_axis)
        controls.addWidget(self._add_y_axis_button)
        controls.addStretch(1)
        layout.addLayout(controls)

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
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self._trace_table.setColumnWidth(2, _COLOUR_COLUMN_WIDTH)
        self._trace_table.setColumnWidth(7, _AXIS_COLUMN_WIDTH)
        self._trace_table.setColumnWidth(8, _AXIS_COLUMN_WIDTH)
        layout.addWidget(self._trace_table)

        # Create the pyqtgraph plot widget
        self._pg_widget = pg.PlotWidget()
        self._pg_widget.setObjectName("pgPlotWidget")
        self._pg_widget.setBackground("w")
        self._pg_widget.showGrid(x=True, y=True, alpha=0.3)
        self._pg_widget.setLabel("left", "Value")
        self._pg_widget.setLabel("bottom", "Step")

        # Register the default axes / ViewBox
        plot_item: pg.PlotItem = self._pg_widget.getPlotItem()
        self._plot_item = plot_item
        self._view_boxes["left"] = plot_item.vb
        self._view_boxes["bottom"] = plot_item.vb
        self._pair_view_boxes[("bottom", "left")] = plot_item.vb
        self._axis_items["left"] = plot_item.getAxis("left")
        self._axis_items["bottom"] = plot_item.getAxis("bottom")
        self._axis_orientations["left"] = "y"
        self._axis_orientations["bottom"] = "x"

        self._plot_item.vb.sigResized.connect(self._sync_view_box_geometry)

        layout.addWidget(self._pg_widget)
        self._refresh_trace_and_axis_controls()
        self.setLayout(layout)

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

    def _x_axis_names(self) -> list[str]:
        """Return sorted names of registered x-axes."""
        return sorted(name for name, orientation in self._axis_orientations.items() if orientation == "x")

    def _y_axis_names(self) -> list[str]:
        """Return sorted names of registered y-axes."""
        return sorted(name for name, orientation in self._axis_orientations.items() if orientation == "y")

    def _refresh_trace_and_axis_controls(self) -> None:
        """Refresh table rows after trace or axis changes."""
        x_axes = self._x_axis_names()
        y_axes = self._y_axis_names()
        self._updating_trace_controls = True
        try:
            self._trace_table.clearContents()
            self._trace_table.setRowCount(len(self.trace_names))
            for row, trace_name in enumerate(self.trace_names):
                style = self._trace_style[trace_name]
                x_axis, y_axis = self._trace_axes.get(trace_name, ("bottom", "left"))

                visible_checkbox = QCheckBox(self._trace_table)
                visible_checkbox.setChecked(self._trace_visible.get(trace_name, True))
                visible_checkbox.setProperty(_TRACE_NAME_PROPERTY, trace_name)
                visible_checkbox.toggled.connect(self._on_trace_visibility_toggled)
                self._trace_table.setCellWidget(row, 0, visible_checkbox)

                trace_item = QTableWidgetItem(trace_name)
                trace_item.setFlags(trace_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
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

                line_width = pg.SpinBox(self._trace_table)
                line_width.setOpts(bounds=(_MIN_LINE_WIDTH, _MAX_LINE_WIDTH), step=_LINE_WIDTH_STEP)
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

                point_size = pg.SpinBox(self._trace_table)
                point_size.setOpts(bounds=(_MIN_POINT_SIZE, _MAX_POINT_SIZE), step=_POINT_SIZE_STEP)
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
        finally:
            self._updating_trace_controls = False

        self._update_trace_table_height()

    def _update_trace_table_height(self) -> None:
        """Limit visible trace rows to three before scrolling."""
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
        button.setStyleSheet(f"QPushButton {{ background-color: {hex_colour}; }}")

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

    def _on_trace_line_style_changed(self, line_style: str) -> None:
        """Update trace line style from a table control."""
        if self._updating_trace_controls:
            return
        sender = self.sender()
        if sender is None:
            return
        self.set_trace_style(trace_name=str(sender.property(_TRACE_NAME_PROPERTY)), line_style=line_style)

    def _on_trace_line_width_changed(self, line_width: float) -> None:
        """Update trace line width from a table control."""
        if self._updating_trace_controls:
            return
        sender = self.sender()
        if sender is None:
            return
        self.set_trace_style(trace_name=str(sender.property(_TRACE_NAME_PROPERTY)), line_width=line_width)

    def _on_trace_point_style_changed(self, index: int) -> None:
        """Update trace point style from a table control."""
        if self._updating_trace_controls:
            return
        sender = self.sender()
        if sender is None:
            return
        point_style = str(sender.itemData(index))
        self.set_trace_style(trace_name=str(sender.property(_TRACE_NAME_PROPERTY)), point_style=point_style)

    def _on_trace_point_size_changed(self, point_size: float) -> None:
        """Update trace point size from a table control."""
        if self._updating_trace_controls:
            return
        sender = self.sender()
        if sender is None:
            return
        self.set_trace_style(trace_name=str(sender.property(_TRACE_NAME_PROPERTY)), point_size=point_size)

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

    def _prompt_add_x_axis(self) -> None:
        """Prompt for a new x-axis name/label and add it."""
        name, ok = QInputDialog.getText(self, "Add X axis", "Axis name:")
        if not ok or not name.strip():
            return
        clean_name = name.strip()
        label, _ = QInputDialog.getText(self, "Add X axis", "Axis label:", text=clean_name)
        self.add_x_axis(clean_name, label.strip() or clean_name, position="top")

    def _prompt_add_y_axis(self) -> None:
        """Prompt for a new y-axis name/label and add it."""
        name, ok = QInputDialog.getText(self, "Add Y axis", "Axis name:")
        if not ok or not name.strip():
            return
        clean_name = name.strip()
        label, _ = QInputDialog.getText(self, "Add Y axis", "Axis label:", text=clean_name)
        self.add_y_axis(clean_name, label.strip() or clean_name, side="right")

    def _create_pair_view_box(self, x_axis: str, y_axis: str) -> pg.ViewBox:
        """Create a view box for the given axis pair."""
        if (x_axis, y_axis) in self._pair_view_boxes:
            return self._pair_view_boxes[(x_axis, y_axis)]

        view_box = pg.ViewBox()
        self._plot_item.scene().addItem(view_box)
        if x_axis == "bottom":
            view_box.setXLink(self._plot_item.vb)
        if y_axis == "left":
            view_box.setYLink(self._plot_item.vb)

        self._pair_view_boxes[(x_axis, y_axis)] = view_box
        self._sync_view_box_geometry()
        if x_axis != "bottom":
            self._axis_items[x_axis].linkToView(view_box)
        if y_axis != "left":
            self._axis_items[y_axis].linkToView(view_box)
        return view_box

    def _get_or_create_trace(self, trace_name: str) -> pg.PlotDataItem:
        """Return the PlotDataItem for *trace_name*, creating it if needed."""
        if trace_name not in self._traces:
            colour = next(self._colour_cycle)
            pen = pg.mkPen(color=colour, width=2, style=_LINE_STYLES["solid"])
            curve = pg.PlotDataItem(pen=pen, name=trace_name)
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.append_point("sig", 0.0, 1.0)
            >>> widget.x_data("sig")
            [0.0]
        """
        try:
            curve = self._get_or_create_trace(trace_name)
            xs, ys = self._trace_data[trace_name]
            xs.append(float(x))
            ys.append(float(y))
            curve.setData(np.array(xs, dtype=float), np.array(ys, dtype=float))
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.set_trace("sig", [0.0, 1.0], [2.0, 3.0])
            >>> widget.y_data("sig")
            [2.0, 3.0]
        """
        try:
            curve = self._get_or_create_trace(trace_name)
            xs = list(map(float, x_data))
            ys = list(map(float, y_data))
            self._trace_data[trace_name] = (xs, ys)
            curve.setData(np.array(xs, dtype=float), np.array(ys, dtype=float))
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

    @pyqtSlot(str, str)
    def set_default_axis_labels(self, x_label: str, y_label: str) -> None:
        """Update the default bottom and left axis labels.

        Called by :class:`~stoner_measurement.plugins.command.PlotTraceCommand`
        when trace metadata (names and units from
        :class:`~stoner_measurement.plugins.trace.TraceData`) is available so
        that the plot axes reflect the physical quantities being displayed.

        Args:
            x_label (str):
                Label for the bottom (x) axis.  If empty the axis label is
                left unchanged.
            y_label (str):
                Label for the left (y) axis.  If empty the axis label is left
                unchanged.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.set_default_axis_labels("Current (A)", "Voltage (V)")
            >>> widget._pg_widget.getPlotItem().getAxis("bottom").labelText
            'Current (A)'
        """
        if x_label:
            self._pg_widget.setLabel("bottom", x_label)
        if y_label:
            self._pg_widget.setLabel("left", y_label)

    def set_trace_style(
        self,
        trace_name: str,
        colour: str | None = None,
        line_style: str = "solid",
        point_style: str = "none",
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
        if line_style not in _LINE_STYLES:
            valid_line_styles = ", ".join(_LINE_STYLES)
            raise ValueError(f"Unknown line style: {line_style!r}. " f"Valid options are: {valid_line_styles}.")
        if point_style not in _POINT_STYLES:
            valid_point_styles = ", ".join(_POINT_STYLES)
            raise ValueError(f"Unknown point style: {point_style!r}. " f"Valid options are: {valid_point_styles}.")
        if line_width is not None and line_width <= 0:
            raise ValueError(f"Line width must be greater than zero, got {line_width}.")
        if point_size is not None and point_size <= 0:
            raise ValueError(f"Point size must be greater than zero, got {point_size}.")

        style = self._trace_style[trace_name]
        if colour is not None:
            if not QColor(colour).isValid():
                raise ValueError(f"Invalid colour value: {colour!r}")
            style["colour"] = colour
        style["line"] = line_style
        style["point"] = point_style
        if line_width is not None:
            self._trace_line_width[trace_name] = line_width
        if point_size is not None:
            self._trace_point_size[trace_name] = point_size

        pen = pg.mkPen(
            color=style["colour"],
            width=self._trace_line_width.get(trace_name, _DEFAULT_LINE_WIDTH),
            style=_LINE_STYLES[line_style],
        )
        curve.setPen(pen)
        symbol = _POINT_STYLES[point_style]
        curve.setSymbol(symbol)
        if symbol is None:
            curve.setSymbolBrush(None)
            curve.setSymbolPen(None)
        else:
            curve.setSymbolBrush(style["colour"])
            curve.setSymbolPen(pen)
        curve.setSymbolSize(self._trace_point_size.get(trace_name, _DEFAULT_POINT_SIZE))

    def remove_trace(self, trace_name: str) -> None:
        """Remove a named trace and all its data.

        If *trace_name* does not exist this call is a no-op.

        Args:
            trace_name (str):
                Name of the trace to remove.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
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
        del self._trace_data[trace_name]
        self._trace_style.pop(trace_name, None)
        self._trace_line_width.pop(trace_name, None)
        self._trace_point_size.pop(trace_name, None)
        self._trace_visible.pop(trace_name, None)
        self._refresh_trace_and_axis_controls()

    def clear_all(self) -> None:
        """Remove all traces and their data.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.append_point("a", 1.0, 2.0)
            >>> widget.clear_all()
            >>> widget.trace_names
            []
        """
        self._colour_cycle = cycle(_TRACE_COLOURS)
        for name in list(self._traces.keys()):
            self.remove_trace(name)

    # ------------------------------------------------------------------
    # Public API — axis management
    # ------------------------------------------------------------------

    def add_y_axis(
        self,
        name: str,
        label: str,
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.add_y_axis("temperature", "Temperature (K)", side="right")
            >>> "temperature" in widget.axis_names
            True
        """
        if name in self._axis_items:
            return
        axis = pg.AxisItem(side)
        axis.setLabel(label)
        self._plot_item.layout.addItem(axis, 2, 3 if side == "right" else 0)
        self._axis_items[name] = axis
        self._axis_orientations[name] = "y"
        self._view_boxes[name] = self._create_pair_view_box("bottom", name)
        self._refresh_trace_and_axis_controls()

    def ensure_y_axis(self, name: str, label: str = "") -> None:
        """Ensure a y-axis with *name* exists, creating it on the right if absent.

        If the axis already exists this is a no-op.  If it does not exist a new
        right-hand y-axis is added using :meth:`add_y_axis`, with *label* as
        the displayed axis label (falling back to *name* when *label* is empty).

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
            >>> from PyQt6.QtWidgets import QApplication
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
            return
        self.add_y_axis(name, label or name)

    def add_x_axis(
        self,
        name: str,
        label: str,
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> widget = PlotWidget()
            >>> widget.add_x_axis("freq", "Frequency (Hz)", position="top")
            >>> "freq" in widget.axis_names
            True
        """
        if name in self._axis_items:
            return
        axis = pg.AxisItem(position)
        axis.setLabel(label)
        self._plot_item.layout.addItem(axis, 0 if position == "top" else 4, 1)
        self._axis_items[name] = axis
        self._axis_orientations[name] = "x"
        self._view_boxes[name] = self._create_pair_view_box(name, "left")
        self._refresh_trace_and_axis_controls()

    def ensure_x_axis(self, name: str, label: str = "") -> None:
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
            >>> from PyQt6.QtWidgets import QApplication
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
        old_vb = self._pair_view_boxes.get(old_axes, self._plot_item.vb)
        new_vb = self._create_pair_view_box(x_axis, y_axis)

        if old_vb is not new_vb:
            old_vb.removeItem(curve)
            new_vb.addItem(curve)

        self._trace_axes[trace_name] = (x_axis, y_axis)
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
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
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
