"""Central PyQtGraph plotting widget — middle 50 % of the main window.

Supports multiple named traces (each with its own colour) and multiple
independent x- and y-axes implemented via linked
:class:`pyqtgraph.ViewBox` instances.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from itertools import cycle
from typing import Literal

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Colour palette used when automatically assigning colours to new traces.
_TRACE_COLOURS = [
    "#1f77b4",  # blue
    "#ff7f0e",  # orange
    "#2ca02c",  # green
    "#d62728",  # red
    "#9467bd",  # purple
    "#8c564b",  # brown
    "#e377c2",  # pink
    "#7f7f7f",  # grey
    "#bcbd22",  # yellow-green
    "#17becf",  # cyan
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
        controls.addWidget(QLabel("Trace:", self))
        self._trace_selector = QComboBox(self)
        self._trace_selector.currentTextChanged.connect(self._on_selected_trace_changed)
        controls.addWidget(self._trace_selector)

        controls.addWidget(QLabel("Colour:", self))
        self._colour_editor = QLineEdit(self)
        self._colour_editor.setPlaceholderText("#1f77b4")
        self._colour_editor.editingFinished.connect(self._on_style_changed)
        controls.addWidget(self._colour_editor)

        controls.addWidget(QLabel("Line:", self))
        self._line_selector = QComboBox(self)
        self._line_selector.addItems(list(_LINE_STYLES))
        self._line_selector.currentTextChanged.connect(self._on_style_changed)
        controls.addWidget(self._line_selector)

        controls.addWidget(QLabel("Points:", self))
        self._point_selector = QComboBox(self)
        self._point_selector.addItems(list(_POINT_STYLES))
        self._point_selector.currentTextChanged.connect(self._on_style_changed)
        controls.addWidget(self._point_selector)

        controls.addWidget(QLabel("X axis:", self))
        self._x_axis_selector = QComboBox(self)
        self._x_axis_selector.currentTextChanged.connect(self._on_axis_selection_changed)
        controls.addWidget(self._x_axis_selector)

        controls.addWidget(QLabel("Y axis:", self))
        self._y_axis_selector = QComboBox(self)
        self._y_axis_selector.currentTextChanged.connect(self._on_axis_selection_changed)
        controls.addWidget(self._y_axis_selector)

        self._add_x_axis_button = QPushButton("+X Axis", self)
        self._add_x_axis_button.clicked.connect(self._prompt_add_x_axis)
        controls.addWidget(self._add_x_axis_button)
        self._add_y_axis_button = QPushButton("+Y Axis", self)
        self._add_y_axis_button.clicked.connect(self._prompt_add_y_axis)
        controls.addWidget(self._add_y_axis_button)
        controls.addStretch(1)
        layout.addLayout(controls)

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

        # Legend — items are registered manually when traces are created.
        self._legend = self._plot_item.addLegend()
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
        return sorted(
            name for name, orientation in self._axis_orientations.items() if orientation == "x"
        )

    def _y_axis_names(self) -> list[str]:
        """Return sorted names of registered y-axes."""
        return sorted(
            name for name, orientation in self._axis_orientations.items() if orientation == "y"
        )

    def _refresh_trace_and_axis_controls(self) -> None:
        """Refresh combo-box entries after trace/axis changes."""
        current_trace = self._trace_selector.currentText()
        self._trace_selector.blockSignals(True)
        self._trace_selector.clear()
        self._trace_selector.addItems(self.trace_names)
        if current_trace and current_trace in self.trace_names:
            self._trace_selector.setCurrentText(current_trace)
        self._trace_selector.blockSignals(False)

        current_x = self._x_axis_selector.currentText()
        self._x_axis_selector.blockSignals(True)
        self._x_axis_selector.clear()
        self._x_axis_selector.addItems(self._x_axis_names())
        if current_x and current_x in self._x_axis_names():
            self._x_axis_selector.setCurrentText(current_x)
        self._x_axis_selector.blockSignals(False)

        current_y = self._y_axis_selector.currentText()
        self._y_axis_selector.blockSignals(True)
        self._y_axis_selector.clear()
        self._y_axis_selector.addItems(self._y_axis_names())
        if current_y and current_y in self._y_axis_names():
            self._y_axis_selector.setCurrentText(current_y)
        self._y_axis_selector.blockSignals(False)

        self._on_selected_trace_changed(self._trace_selector.currentText())

    def _on_selected_trace_changed(self, trace_name: str) -> None:
        """Update style/axis editors to match the selected trace."""
        style = self._trace_style.get(trace_name)
        axes = self._trace_axes.get(trace_name)

        self._colour_editor.blockSignals(True)
        self._line_selector.blockSignals(True)
        self._point_selector.blockSignals(True)
        self._x_axis_selector.blockSignals(True)
        self._y_axis_selector.blockSignals(True)
        if style is None:
            self._colour_editor.setText("")
            self._line_selector.setCurrentText("solid")
            self._point_selector.setCurrentText("none")
        else:
            self._colour_editor.setText(style["colour"])
            self._line_selector.setCurrentText(style["line"])
            self._point_selector.setCurrentText(style["point"])
        if axes is None:
            self._x_axis_selector.setCurrentText("bottom")
            self._y_axis_selector.setCurrentText("left")
        else:
            self._x_axis_selector.setCurrentText(axes[0])
            self._y_axis_selector.setCurrentText(axes[1])
        self._colour_editor.blockSignals(False)
        self._line_selector.blockSignals(False)
        self._point_selector.blockSignals(False)
        self._x_axis_selector.blockSignals(False)
        self._y_axis_selector.blockSignals(False)

    def _on_style_changed(self, *_args: object) -> None:
        """Apply style editor values to the selected trace."""
        trace_name = self._trace_selector.currentText()
        if not trace_name:
            return
        self.set_trace_style(
            trace_name=trace_name,
            colour=self._colour_editor.text().strip() or None,
            line_style=self._line_selector.currentText(),
            point_style=self._point_selector.currentText(),
        )

    def _on_axis_selection_changed(self, *_args: object) -> None:
        """Apply selected axis pair to the selected trace."""
        trace_name = self._trace_selector.currentText()
        if not trace_name:
            return
        x_axis = self._x_axis_selector.currentText() or "bottom"
        y_axis = self._y_axis_selector.currentText() or "left"
        self.assign_trace_axes(trace_name=trace_name, x_axis=x_axis, y_axis=y_axis)

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
            self._legend.addItem(curve, trace_name)
            self._refresh_trace_and_axis_controls()
        return self._traces[trace_name]

    # ------------------------------------------------------------------
    # Public API — trace management
    # ------------------------------------------------------------------

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
        curve = self._get_or_create_trace(trace_name)
        xs, ys = self._trace_data[trace_name]
        xs.append(float(x))
        ys.append(float(y))
        curve.setData(np.array(xs, dtype=float), np.array(ys, dtype=float))

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
        curve = self._get_or_create_trace(trace_name)
        xs = list(map(float, x_data))
        ys = list(map(float, y_data))
        self._trace_data[trace_name] = (xs, ys)
        curve.setData(np.array(xs, dtype=float), np.array(ys, dtype=float))

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
    ) -> None:
        """Set colour, line style, and point style for a trace.

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

        Raises:
            ValueError:
                If *line_style* or *point_style* are unknown values.
        """
        curve = self._get_or_create_trace(trace_name)
        if line_style not in _LINE_STYLES:
            valid_line_styles = ", ".join(_LINE_STYLES)
            raise ValueError(
                f"Unknown line style: {line_style!r}. "
                f"Valid options are: {valid_line_styles}."
            )
        if point_style not in _POINT_STYLES:
            valid_point_styles = ", ".join(_POINT_STYLES)
            raise ValueError(
                f"Unknown point style: {point_style!r}. "
                f"Valid options are: {valid_point_styles}."
            )

        style = self._trace_style[trace_name]
        if colour is not None:
            style["colour"] = colour
        style["line"] = line_style
        style["point"] = point_style
        pen = pg.mkPen(color=style["colour"], width=2, style=_LINE_STYLES[line_style])
        curve.setPen(pen)
        symbol = _POINT_STYLES[point_style]
        curve.setSymbol(symbol)
        if symbol is None:
            curve.setSymbolBrush(None)
            curve.setSymbolPen(None)
        else:
            curve.setSymbolBrush(style["colour"])
            curve.setSymbolPen(pen)

        if self._trace_selector.currentText() == trace_name:
            self._on_selected_trace_changed(trace_name)

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
        self._legend.removeItem(curve)
        del self._trace_data[trace_name]
        self._trace_style.pop(trace_name, None)
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
        for name in list(self._traces.keys()):
            self.remove_trace(name)
        # Explicitly clear legend to guard against any residual items.
        self._legend.clear()

    def clear_data(self) -> None:
        """Clear all plotted data.

        .. deprecated::
            Use :meth:`clear_all` instead.  This method is kept for
            backward compatibility and simply delegates to :meth:`clear_all`.
        """
        warnings.warn(
            "clear_data() is deprecated; use clear_all() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.clear_all()

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
        if self._trace_selector.currentText() == trace_name:
            self._on_selected_trace_changed(trace_name)

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

    # ------------------------------------------------------------------
    # Backward-compatibility shims
    # ------------------------------------------------------------------

    def append_data(self, x: float, y: float) -> None:
        """Append a data point to the default trace.

        .. deprecated::
            Use :meth:`append_point` with an explicit trace name instead.
            This method is kept for backward compatibility and delegates to
            ``append_point("default", x, y)``.

        Args:
            x (float):
                Horizontal axis value.
            y (float):
                Vertical axis value.
        """
        warnings.warn(
            "append_data() is deprecated; use append_point(trace_name, x, y) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.append_point("default", x, y)

    @property
    def pg_widget(self) -> pg.PlotWidget:
        """The underlying :class:`pyqtgraph.PlotWidget`."""
        return self._pg_widget
