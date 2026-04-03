"""Central PyQtGraph plotting widget — middle 50 % of the main window.

Supports multiple named traces (each with its own colour) and multiple
independent x- and y-axes implemented via linked
:class:`pyqtgraph.ViewBox` instances.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from itertools import cycle
from typing import TYPE_CHECKING, Literal

import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QVBoxLayout, QWidget

if TYPE_CHECKING:
    from stoner_measurement.core.runner import SequenceRunner

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
        runner (SequenceRunner | None):
            Optional
            :class:`~stoner_measurement.core.runner.SequenceRunner` whose
            ``data_ready`` signal is connected to :meth:`append_point`.
            Pass ``None`` (the default) when using the new
            :class:`~stoner_measurement.core.sequence_engine.SequenceEngine`
            workflow where plugin signals are wired directly.
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.core.runner import SequenceRunner
        >>> runner = SequenceRunner()
        >>> widget = PlotWidget(runner=runner)
        >>> widget.append_point("my_trace", 1.0, 2.0)
        >>> widget.x_data("my_trace")
        [1.0]
    """

    def __init__(
        self,
        runner: SequenceRunner | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner

        # Per-trace data storage: name → (x_list, y_list)
        self._trace_data: dict[str, tuple[list[float], list[float]]] = {}
        # Per-trace plot item
        self._traces: dict[str, pg.PlotDataItem] = {}
        # Per-trace axis assignment: name → (x_axis_name, y_axis_name)
        self._trace_axes: dict[str, tuple[str, str]] = {}
        # Colour cycle for auto-assignment
        self._colour_cycle = cycle(_TRACE_COLOURS)

        # ViewBox registry: axis_name → ViewBox
        # The main plot's default ViewBox is registered as "left"/"bottom".
        self._view_boxes: dict[str, pg.ViewBox] = {}
        # AxisItem registry: axis_name → AxisItem
        self._axis_items: dict[str, pg.AxisItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

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
        self._axis_items["left"] = plot_item.getAxis("left")
        self._axis_items["bottom"] = plot_item.getAxis("bottom")

        layout.addWidget(self._pg_widget)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Named-trace helpers
    # ------------------------------------------------------------------

    def _get_or_create_trace(self, trace_name: str) -> pg.PlotDataItem:
        """Return the PlotDataItem for *trace_name*, creating it if needed."""
        if trace_name not in self._traces:
            colour = next(self._colour_cycle)
            pen = pg.mkPen(color=colour, width=2)
            curve = pg.PlotDataItem(pen=pen, name=trace_name)
            # Add to the default ViewBox initially
            self._plot_item.vb.addItem(curve)
            self._traces[trace_name] = curve
            self._trace_data[trace_name] = ([], [])
            self._trace_axes[trace_name] = ("bottom", "left")
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
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
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
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
            >>> widget.set_trace("sig", [0.0, 1.0], [2.0, 3.0])
            >>> widget.y_data("sig")
            [2.0, 3.0]
        """
        curve = self._get_or_create_trace(trace_name)
        xs = list(map(float, x_data))
        ys = list(map(float, y_data))
        self._trace_data[trace_name] = (xs, ys)
        curve.setData(np.array(xs, dtype=float), np.array(ys, dtype=float))

    def remove_trace(self, trace_name: str) -> None:
        """Remove a named trace and all its data.

        If *trace_name* does not exist this call is a no-op.

        Args:
            trace_name (str):
                Name of the trace to remove.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
            >>> widget.append_point("sig", 0.0, 1.0)
            >>> widget.remove_trace("sig")
            >>> widget.trace_names
            []
        """
        if trace_name not in self._traces:
            return
        curve = self._traces.pop(trace_name)
        # Determine which ViewBox owns the curve and remove it from there.
        _x_ax, y_ax = self._trace_axes.pop(trace_name, ("bottom", "left"))
        vb = self._view_boxes.get(y_ax, self._plot_item.vb)
        vb.removeItem(curve)
        del self._trace_data[trace_name]

    def clear_all(self) -> None:
        """Remove all traces and their data.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
            >>> widget.append_point("a", 1.0, 2.0)
            >>> widget.clear_all()
            >>> widget.trace_names
            []
        """
        for name in list(self._traces.keys()):
            self.remove_trace(name)

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
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
            >>> widget.add_y_axis("temperature", "Temperature (K)", side="right")
            >>> "temperature" in widget.axis_names
            True
        """
        if name in self._view_boxes:
            return
        view_box = pg.ViewBox()
        self._plot_item.scene().addItem(view_box)
        axis = pg.AxisItem(side)
        axis.setLabel(label)
        self._plot_item.layout.addItem(axis, 2, 3 if side == "right" else 0)
        axis.linkToView(view_box)
        view_box.setXLink(self._plot_item.vb)
        self._view_boxes[name] = view_box
        self._axis_items[name] = axis

        # Keep geometry in sync with the main view
        self._plot_item.vb.sigResized.connect(
            lambda: view_box.setGeometry(self._plot_item.vb.sceneBoundingRect())
        )

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
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
            >>> widget.add_x_axis("freq", "Frequency (Hz)", position="top")
            >>> "freq" in widget.axis_names
            True
        """
        if name in self._view_boxes:
            return
        view_box = pg.ViewBox()
        self._plot_item.scene().addItem(view_box)
        axis = pg.AxisItem(position)
        axis.setLabel(label)
        self._plot_item.layout.addItem(axis, 0 if position == "top" else 4, 1)
        axis.linkToView(view_box)
        view_box.setYLink(self._plot_item.vb)
        self._view_boxes[name] = view_box
        self._axis_items[name] = axis

        self._plot_item.vb.sigResized.connect(
            lambda: view_box.setGeometry(self._plot_item.vb.sceneBoundingRect())
        )

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
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
            >>> widget.add_y_axis("temp", "Temperature (K)")
            >>> widget.append_point("sig", 0.0, 300.0)
            >>> widget.assign_trace_axes("sig", y_axis="temp")
        """
        if trace_name not in self._traces:
            raise KeyError(f"Unknown trace: {trace_name!r}")
        if y_axis not in self._view_boxes:
            raise KeyError(f"Unknown y-axis: {y_axis!r}")

        curve = self._traces[trace_name]
        old_x_ax, old_y_ax = self._trace_axes[trace_name]
        old_vb = self._view_boxes.get(old_y_ax, self._plot_item.vb)
        new_vb = self._view_boxes[y_axis]

        if old_vb is not new_vb:
            old_vb.removeItem(curve)
            new_vb.addItem(curve)

        self._trace_axes[trace_name] = (x_axis, y_axis)

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
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
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
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
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
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
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
            >>> from stoner_measurement.core.runner import SequenceRunner
            >>> widget = PlotWidget(runner=SequenceRunner())
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
