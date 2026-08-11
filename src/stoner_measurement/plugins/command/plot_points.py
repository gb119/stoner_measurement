"""PlotPointsCommand — built-in command plugin for live scatter-plot updates.

:class:`PlotPointsCommand` is a concrete :class:`CommandPlugin` that appends
a single (x, y) data point to one or more named plot traces each time it is
executed.  This is intended for use inside a state-control loop to provide a
live view of measured data points as a function of a swept parameter.

The x value is taken from a single entry in the sequence engine's ``_values``
catalogue and any number of y values may be added, each mapped to a
separately named plot trace.  Each y series may be given a custom label
(which becomes the trace name in the plot legend), a y-axis name to control
which axis the series is plotted against, and a default label is derived from
the value's human-readable name and units.

If a y-axis name that does not yet exist on the plot widget is specified for a
series, it is created automatically (on the right-hand side) when
:meth:`~PlotPointsCommand.execute` runs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from qtpy.QtCore import Qt
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.theme import button_swatch_stylesheet, contrasting_text_colour

if TYPE_CHECKING:
    from stoner_measurement.core.sequence_engine import SequenceEngine

_DEFAULT_X_AXIS = "bottom"
_DEFAULT_Y_AXIS = "left"

#: Valid line-style names accepted by the plot widget.
_LINE_STYLE_OPTIONS = ("solid", "dash", "dot", "dash-dot", "none")
#: Valid point-style names accepted by the plot widget.
_POINT_STYLE_OPTIONS = ("none", "circle", "square", "triangle", "diamond", "plus", "cross")

_PLOT_SIGNAL_BINDINGS = (
    ("plot_point", "append_point"),
    ("plot_update_queued", "mark_data_update_queued"),
    ("plot_ensure_y_axis", "ensure_y_axis"),
    ("plot_ensure_x_axis", "ensure_x_axis"),
    ("plot_trace_axes", "assign_trace_axes"),
    ("plot_trace_style", "set_trace_style_from_dict"),
    ("plot_rename_trace", "rename_trace"),
)


@dataclass(frozen=True)
class _YSeriesWidgets:
    """Widgets belonging to one configured y-series column."""

    value: QComboBox
    label: QComboBox
    y_axis: QComboBox
    colour: QPushButton
    line_style: QComboBox
    point_style: QComboBox
    line_width: QDoubleSpinBox
    point_size: QDoubleSpinBox
    remove: QPushButton


@dataclass(frozen=True)
class _YSeriesEditorContext:
    """Shared state used while rebuilding the y-series editor grid."""

    container: QWidget
    layout: QGridLayout
    value_keys: list[str]
    y_axis_names: list[str]
    namespace: dict[str, Any]
    rebuild: Callable[[], None]


def _safe_disconnect(signal: Any, slot: Any) -> None:
    """Disconnect *signal* from *slot*, silently ignoring errors if not connected.

    Args:
        signal (Any):
            The PyQt signal from which to disconnect.
        slot (Any):
            The callable slot to disconnect.
    """
    try:
        signal.disconnect(slot)
    except (TypeError, RuntimeError):
        pass


def _default_label(key: str, engine_namespace: dict) -> str:
    """Build a default legend label for a ``_values`` catalogue entry.

    Attempts to derive a ``"{name} ({units})"`` label by:

    1. Splitting *key* on ``":"`` to get the instance name and quantity name.
    2. Looking up the plugin instance in *engine_namespace*.
    3. Inspecting ``plugin.units`` (a ``str`` for
       :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`,
       or a ``dict[str, str]`` for
       :class:`~stoner_measurement.plugins.monitor.MonitorPlugin`).

    If units cannot be determined the quantity name is returned unchanged.

    Args:
        key (str):
            Key from the ``_values`` catalogue, e.g. ``"field:Magnetic Field"``.
        engine_namespace (dict):
            Live engine namespace dict.

    Returns:
        (str):
            A human-readable label such as ``"Magnetic Field (T)"`` or, when
            units are unknown, just ``"Magnetic Field"``.
    """
    parts = key.split(":", 1)
    if len(parts) != 2:
        return key
    instance_name, quantity_name = parts
    plugin = engine_namespace.get(instance_name)
    if plugin is None:
        return quantity_name
    raw_units = getattr(plugin, "units", None)
    if isinstance(raw_units, str) and raw_units:
        return f"{quantity_name} ({raw_units})"
    if isinstance(raw_units, dict):
        unit = raw_units.get(quantity_name, "")
        if unit:
            return f"{quantity_name} ({unit})"
    return quantity_name


class PlotPointsCommand(CommandPlugin):
    """Append live data points to one or more plot traces.

    Use this command inside loops or repeated measurement sections when you
    want to build up a plot point-by-point during the run. It is especially
    useful for live displays of quantities such as resistance vs temperature,
    voltage vs field, or any other scalar value against another scalar value
    already available in the sequence value catalogue.

    In the configuration panel you choose:

    * one **X value**
    * one or more **Y series**
    * optional trace labels
    * which plot axes those series should use
    * optional formatting such as colour, line style, marker style, and sizes

    The configuration tab therefore acts as a small live-plot series editor.
    One control chooses the x source, while a scrollable list of y-series rows
    lets you add or remove plotted quantities and customise their presentation.
    The Help/About tab uses this docstring to explain how catalogue keys,
    axis names, and style overrides affect the emitted live plot updates.

    Each time the command runs, it reads the current scalar x value and the
    current scalar y value for each configured series, then appends those
    points to the plot. New axes are created automatically if you assign a
    series to an axis name that does not already exist.

    Attributes:
        x_key (str):
            Key in the ``_values`` catalogue for the x data. The current
            value is read each time the command executes.
        y_entries (list[dict[str, str]]):
            Key in the ``_values`` catalogue for the x data.  Format is
            ``"{instance_name}:{quantity_name}"``.
            Ordered list of y-series definitions.  Each entry is a dict with
            keys ``"key"`` (catalogue key), ``"label"`` (trace name shown
            in the legend), ``"y_axis"`` (y-axis name; defaults to
            ``"left"`` when absent), and optional format keys ``"colour"``,
            ``"line_style"``, ``"point_style"``, ``"line_width"``, and
            ``"point_size"``.  Empty string values and ``0.0`` numeric values
            mean "use the plot panel default".
        x_axis_name (str):
            Name of the x-axis shared by all y series.  Defaults to
            ``"bottom"``.
        plot_point (pyqtSignal[str, float, float]):
            Emitted once per y series by :meth:`execute` as
            ``(label, x_value, y_value)``.  Automatically connected to
            :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.append_point`
            when the plugin is attached to an engine with a plot widget.
        plot_trace_style (pyqtSignal[str, object]):
            Emitted once per y series by :meth:`execute` as
            ``(label, style_dict)`` when format overrides are configured for
            that series.  Automatically connected to
            :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.set_trace_style_from_dict`
            when the plugin is attached to an engine with a plot widget.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command.plot_points import PlotPointsCommand
        >>> cmd = PlotPointsCommand()
        >>> cmd.name
        'Plot Points'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        False
    """

    #: Signal emitted by execute() — (trace_label, x_value, y_value).
    plot_point = pyqtSignal(str, float, float)
    #: Signal emitted by execute() before each queued point update.
    plot_update_queued = pyqtSignal()
    #: Signal emitted by execute() to ensure x-axis exists — (axis_name, axis_label).
    plot_ensure_x_axis = pyqtSignal(str, str)
    #: Signal emitted by execute() to ensure y-axis exists — (axis_name, axis_label).
    plot_ensure_y_axis = pyqtSignal(str, str)
    #: Signal emitted by execute() to assign trace axes — (trace_name, x_axis, y_axis).
    plot_trace_axes = pyqtSignal(str, str, str)
    #: Signal emitted by execute() to set trace style — (trace_name, style_dict).
    plot_trace_style = pyqtSignal(str, object)
    #: Signal emitted when a configured series label changes — (old_name, new_name).
    plot_rename_trace = pyqtSignal(str, str)

    def __init__(self, parent=None) -> None:
        """Initialise with default configuration."""
        super().__init__(parent)
        self._sequence_engine_ref: SequenceEngine | None = None
        self.x_key: str = ""
        self.y_entries: list[dict[str, str]] = []
        self.x_axis_name: str = _DEFAULT_X_AXIS

    # ------------------------------------------------------------------
    # sequence_engine property — auto-wires plot_point signal
    # ------------------------------------------------------------------

    @property  # type: ignore[override]
    def sequence_engine(self) -> SequenceEngine | None:
        """Active sequence engine, or ``None`` when the plugin is detached.

        Overrides the class-level attribute from
        :class:`~stoner_measurement.plugins.base_plugin.BasePlugin` with a
        full property so that the setter can automatically connect the
        :attr:`plot_point` signal to the engine's plot widget.

        Returns:
            (SequenceEngine | None):
                The owning engine, or ``None`` if not attached.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_points import PlotPointsCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> cmd = PlotPointsCommand()
            >>> cmd.sequence_engine is None
            True
            >>> engine.add_plugin("plot_points", cmd)
            >>> cmd.sequence_engine is engine
            True
            >>> engine.shutdown()
        """
        return self._sequence_engine_ref

    @sequence_engine.setter
    def sequence_engine(self, engine: SequenceEngine | None) -> None:
        """Set the owning engine, wiring :attr:`plot_point` to its plot widget.

        Args:
            engine (SequenceEngine | None):
                New owning engine, or ``None`` to detach.
        """
        old_plot_widget = getattr(self._sequence_engine_ref, "plot_widget", None)
        if old_plot_widget is not None:
            self._set_plot_widget_connections(old_plot_widget, connect=False)

        self._sequence_engine_ref = engine

        new_plot_widget = getattr(engine, "plot_widget", None)
        if new_plot_widget is not None:
            self._set_plot_widget_connections(new_plot_widget, connect=True)
            self._ensure_configured_axes_exist(new_plot_widget)

    def _set_plot_widget_connections(self, plot_widget: Any, *, connect: bool) -> None:
        """Connect or disconnect all plot signals supported by *plot_widget*."""
        for signal_name, slot_name in _PLOT_SIGNAL_BINDINGS:
            slot = getattr(plot_widget, slot_name, None)
            if slot is None:
                continue
            signal = getattr(self, signal_name)
            if connect:
                signal.connect(slot)
            else:
                _safe_disconnect(signal, slot)

    @property
    def name(self) -> str:
        """Unique identifier for the plot-points command.

        Returns:
            (str):
                ``"Plot Points"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_points import PlotPointsCommand
            >>> PlotPointsCommand().name
            'Plot Points'
        """
        return "Plot Points"

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self) -> None:
        """Read x and y scalar values and emit :attr:`plot_point` for each y series.

        For each entry in :attr:`y_entries`, the x value (from :attr:`x_key`)
        and the y value (from the entry's ``"key"``) are evaluated against the
        engine namespace and :attr:`plot_point` is emitted as
        ``(label, x_value, y_value)``.  The trace is then assigned to the
        axes specified by :attr:`x_axis_name` and the entry's ``"y_axis"``
        field.  If the specified y-axis does not yet exist on the plot widget
        it is created automatically (on the right-hand side).

        Missing or unconfigured keys are logged as warnings and the
        corresponding series is skipped.

        Raises:
            TimeoutError:
                If the plot widget does not acknowledge a queued point update
                before the response timeout expires.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_points import PlotPointsCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> cmd = PlotPointsCommand()
            >>> engine.add_plugin("plot_points", cmd)
            >>> received = []
            >>> cmd.plot_point.connect(lambda l, x, y: received.append((l, x, y)))
            >>> engine._namespace["_values"] = {"p:x": "p_x_val", "p:y": "p_y_val"}
            >>> engine._namespace["p_x_val"] = 1.0
            >>> engine._namespace["p_y_val"] = 2.0
            >>> cmd.x_key = "p:x"
            >>> cmd.y_entries = [{"key": "p:y", "label": "My Y"}]
            >>> cmd.execute()
            >>> received
            [('My Y', 1.0, 2.0)]
            >>> engine.shutdown()
        """
        if not self.x_key:
            self.log.warning("PlotPoints: x_key is not set — skipping.")
            return
        if not self.y_entries:
            self.log.warning("PlotPoints: no y series configured — skipping.")
            return

        values: dict[str, str] = self.engine_namespace.get("_values", {})

        if self.x_key not in values:
            self.log.warning(
                "PlotPoints: x_key %r not found in _values catalogue — skipping.",
                self.x_key,
            )
            return

        x_expr = values[self.x_key]
        try:
            x_val = float(self.eval(x_expr))
        except Exception as exc:
            self.log.warning(
                "PlotPoints: could not evaluate x expression %r: %s — skipping.",
                x_expr,
                exc,
            )
            return

        for entry in self.y_entries:
            y_key = entry.get("key", "")
            label = entry.get("label", y_key)
            x_axis = self.x_axis_name or _DEFAULT_X_AXIS
            y_axis = entry.get("y_axis", _DEFAULT_Y_AXIS) or _DEFAULT_Y_AXIS
            if not y_key:
                continue
            if y_key not in values:
                self.log.warning(
                    "PlotPoints: y key %r not found in _values catalogue — skipping.",
                    y_key,
                )
                continue
            y_expr = values[y_key]
            try:
                y_val = float(self.eval(y_expr))
            except Exception as exc:
                self.log.warning(
                    "PlotPoints: could not evaluate y expression %r: %s — skipping.",
                    y_expr,
                    exc,
                )
                continue
            if not self._wait_for_plot_ready(timeout=None):
                self.log.debug("PlotPoints: wait for plot readiness interrupted for %r.", label)
                # Stop waiting/plotting for this step when interrupted
                # (e.g. user stop requested).
                return
            self.plot_ensure_x_axis.emit(x_axis, x_axis)
            self.plot_ensure_y_axis.emit(y_axis, y_axis)
            self._queue_plot_update_request(self.plot_update_queued)
            self.plot_point.emit(label, x_val, y_val)
            self.plot_trace_axes.emit(label, x_axis, y_axis)
            self._wait_for_plot_response_or_raise(label)
            style = _entry_style_dict(entry)
            if style:
                self.plot_trace_style.emit(label, style)
            self.log.debug("PlotPoints: emitted point (%s, %g, %g)", label, x_val, y_val)

    # ------------------------------------------------------------------
    # Configuration UI
    # ------------------------------------------------------------------

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a settings widget for configuring the plot-points command.

        The widget contains:

        * An **X value** dropdown populated from the ``_values`` catalogue.
        * An **X axis** dropdown for the shared x-axis.
        * A scrollable list of **Y series** rows, each with a value
          dropdown, a label line-edit (defaulting to
          ``"{quantity name} ({units})"``) an editable **Y axis** dropdown,
          and a **Remove** button.
        * An **Add Y series** button that appends a new row.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The settings widget for the *PlotPoints* configuration tab.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_points import PlotPointsCommand
            >>> from qtpy.QtWidgets import QWidget
            >>> isinstance(PlotPointsCommand().config_widget(), QWidget)
            True
        """
        ns = self.engine_namespace
        values: dict[str, str] = ns.get("_values", {})
        value_keys = list(values.keys())
        x_axis_names, y_axis_names = _available_plot_axes(self.sequence_engine)

        outer = QWidget(parent)
        outer_layout = QFormLayout(outer)

        self._build_x_combos_section(outer, outer_layout, value_keys, x_axis_names)

        outer_layout.addRow(QLabel("<b>Y series:</b>", outer))
        self._build_y_series_section(outer, outer_layout, value_keys, y_axis_names, ns)

        outer.setLayout(outer_layout)
        return outer

    def _build_x_combos_section(
        self,
        outer: QWidget,
        outer_layout: QFormLayout,
        value_keys: list[str],
        x_axis_names: list[str],
    ) -> None:
        x_combo = QComboBox(outer)
        if value_keys:
            x_combo.addItems(value_keys)
            if self.x_key in value_keys:
                x_combo.setCurrentText(self.x_key)
            else:
                self.x_key = value_keys[0]
                x_combo.setCurrentText(self.x_key)
        else:
            x_combo.addItem("(no values available)")

        def _apply_x(text: str) -> None:
            if text != "(no values available)":
                self.x_key = text

        x_combo.currentTextChanged.connect(_apply_x)
        outer_layout.addRow("X value:", x_combo)

        x_axis_combo = QComboBox(outer)
        x_axis_combo.addItems(x_axis_names)
        if self.x_axis_name in x_axis_names:
            x_axis_combo.setCurrentText(self.x_axis_name)
        else:
            self.x_axis_name = x_axis_names[0]
            x_axis_combo.setCurrentText(self.x_axis_name)
        x_axis_combo.currentTextChanged.connect(lambda text: setattr(self, "x_axis_name", text))
        outer_layout.addRow("X axis:", x_axis_combo)

    def _build_y_series_section(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        outer: QWidget,
        outer_layout: QFormLayout,
        value_keys: list[str],
        y_axis_names: list[str],
        ns: dict[str, Any],
    ) -> None:
        scroll_area = QScrollArea(outer)
        scroll_area.setWidgetResizable(True)
        scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll_area.setMinimumHeight(150)

        series_container = QWidget()
        series_layout = QGridLayout(series_container)
        series_layout.setColumnStretch(0, 0)
        series_layout.setRowStretch(9, 1)

        scroll_area.setWidget(series_container)
        outer_layout.addRow(scroll_area)

        def _rebuild_columns() -> None:
            context = _YSeriesEditorContext(
                container=series_container,
                layout=series_layout,
                value_keys=value_keys,
                y_axis_names=y_axis_names,
                namespace=ns,
                rebuild=_rebuild_columns,
            )
            self._populate_y_series_grid(context)

        _rebuild_columns()

        add_btn = QPushButton("Add Y series", outer)
        add_btn.clicked.connect(partial(self._add_y_series, value_keys, ns, _rebuild_columns))
        outer_layout.addRow(add_btn)

    def _populate_y_series_grid(self, context: _YSeriesEditorContext) -> None:
        """Recreate all y-series columns and connect their editors."""
        self._clear_y_series_grid(context.layout)
        self._add_y_series_headers(context.container, context.layout)
        for index, entry in enumerate(self.y_entries):
            widgets = self._create_y_series_widgets(context, entry, index)
            self._place_y_series_widgets(context, widgets, index)
            self._connect_y_series_widgets(widgets, index, context.namespace, context.rebuild)

    @staticmethod
    def _clear_y_series_grid(layout: QGridLayout) -> None:
        """Detach every widget currently owned by the y-series grid."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    @staticmethod
    def _add_y_series_headers(container: QWidget, layout: QGridLayout) -> None:
        """Add the fixed option labels down the first grid column."""
        layout.addWidget(QLabel("<b>Option</b>", container), 0, 0)
        titles = ("Value", "Label", "Y axis", "Colour", "Line", "Points", "Width", "Pt size", "")
        for row_index, title in enumerate(titles, start=1):
            layout.addWidget(QLabel(f"<b>{title}</b>", container), row_index, 0)

    def _create_y_series_widgets(
        self,
        context: _YSeriesEditorContext,
        entry: dict[str, Any],
        index: int,
    ) -> _YSeriesWidgets:
        """Create and initialise the editors for one y-series."""
        value = self._create_value_combo(context.container, entry, context.value_keys)

        label = QComboBox(context.container)
        label.setEditable(True)
        label.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        label.lineEdit().setText(entry.get("label", ""))

        y_axis = self._create_y_axis_combo(context.container, entry, context.y_axis_names)

        colour = QPushButton(context.container)
        colour.setObjectName(f"colour_btn_{index}")
        colour.setToolTip(
            "Click to choose a colour. Right-click to reset to automatic (no colour override)."
        )
        self._update_colour_button(colour, entry.get("colour", ""))

        return _YSeriesWidgets(
            value=value,
            label=label,
            y_axis=y_axis,
            colour=colour,
            line_style=self._create_style_combo(
                context.container, _LINE_STYLE_OPTIONS, entry.get("line_style", "")
            ),
            point_style=self._create_style_combo(
                context.container, _POINT_STYLE_OPTIONS, entry.get("point_style", "")
            ),
            line_width=self._create_size_spinbox(
                context.container, entry.get("line_width", 0.0), 0.5
            ),
            point_size=self._create_size_spinbox(
                context.container, entry.get("point_size", 0.0), 1.0
            ),
            remove=QPushButton("Remove", context.container),
        )

    @staticmethod
    def _create_value_combo(
        container: QWidget, entry: dict[str, Any], value_keys: list[str]
    ) -> QComboBox:
        """Create a catalogue-value combo and normalise an invalid saved key."""
        combo = QComboBox(container)
        if not value_keys:
            combo.addItem("(no values available)")
            return combo
        combo.addItems(value_keys)
        key = entry.get("key", "")
        if key in value_keys:
            combo.setCurrentText(key)
        else:
            combo.setCurrentIndex(0)
            entry["key"] = value_keys[0]
        return combo

    @staticmethod
    def _create_y_axis_combo(
        container: QWidget, entry: dict[str, Any], y_axis_names: list[str]
    ) -> QComboBox:
        """Create the editable y-axis selector for a series."""
        combo = QComboBox(container)
        combo.setEditable(True)
        combo.addItems(y_axis_names)
        entry_y_axis = entry.get("y_axis", _DEFAULT_Y_AXIS)
        if entry_y_axis in y_axis_names:
            combo.setCurrentText(entry_y_axis)
        else:
            combo.setEditText(entry_y_axis)
        return combo

    @staticmethod
    def _create_style_combo(
        container: QWidget, options: tuple[str, ...], current: str
    ) -> QComboBox:
        """Create a style selector with an explicit default option."""
        combo = QComboBox(container)
        all_options = ("",) + options
        for option in all_options:
            combo.addItem(option if option else "(default)", option)
        combo.setCurrentIndex(all_options.index(current) if current in all_options else 0)
        return combo

    @staticmethod
    def _create_size_spinbox(container: QWidget, value: Any, step: float) -> QDoubleSpinBox:
        """Create a shared line-width or point-size editor."""
        spinbox = QDoubleSpinBox(container)
        spinbox.setRange(0.0, 100.0)
        spinbox.setSingleStep(step)
        spinbox.setDecimals(1)
        spinbox.setSpecialValueText("def")
        spinbox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        spinbox.setValue(float(value))
        return spinbox

    @staticmethod
    def _place_y_series_widgets(
        context: _YSeriesEditorContext, widgets: _YSeriesWidgets, index: int
    ) -> None:
        """Place one y-series header and its editors into the grid."""
        column = index + 1
        context.layout.setColumnStretch(column, 1)
        context.layout.addWidget(QLabel(f"<b>Series {index + 1}</b>", context.container), 0, column)
        ordered_widgets = (
            widgets.value,
            widgets.label,
            widgets.y_axis,
            widgets.colour,
            widgets.line_style,
            widgets.point_style,
            widgets.line_width,
            widgets.point_size,
            widgets.remove,
        )
        for row, widget in enumerate(ordered_widgets, start=1):
            context.layout.addWidget(widget, row, column)

    def _connect_y_series_widgets(
        self,
        widgets: _YSeriesWidgets,
        index: int,
        namespace: dict[str, Any],
        rebuild: Callable[[], None],
    ) -> None:
        """Connect one y-series column to its backing configuration entry."""
        widgets.value.currentTextChanged.connect(
            partial(self._apply_y_key, index, widgets, namespace)
        )
        widgets.label.lineEdit().editingFinished.connect(
            partial(self._apply_y_label, index, widgets)
        )
        widgets.y_axis.currentTextChanged.connect(partial(self._apply_y_axis, index))
        widgets.colour.clicked.connect(partial(self._apply_y_colour, index, widgets))
        widgets.colour.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widgets.colour.customContextMenuRequested.connect(
            partial(self._reset_y_colour, index, widgets)
        )
        widgets.line_style.currentIndexChanged.connect(
            partial(self._apply_y_style, index, "line_style", widgets.line_style)
        )
        widgets.point_style.currentIndexChanged.connect(
            partial(self._apply_y_style, index, "point_style", widgets.point_style)
        )
        widgets.line_width.valueChanged.connect(partial(self._apply_y_number, index, "line_width"))
        widgets.point_size.valueChanged.connect(partial(self._apply_y_number, index, "point_size"))
        widgets.remove.clicked.connect(partial(self._remove_y_series, index, rebuild))

    def _apply_y_key(
        self,
        index: int,
        widgets: _YSeriesWidgets,
        namespace: dict[str, Any],
        text: str,
    ) -> None:
        """Store a selected value key and update an automatic label."""
        if text == "(no values available)":
            return
        entry = self.y_entries[index]
        old_key = entry.get("key", "")
        old_label = entry.get("label", "")
        automatic_label = _default_label(text, namespace)
        entry["key"] = text
        if not old_label or old_label == _default_label(old_key, namespace):
            entry["label"] = automatic_label
            widgets.label.lineEdit().setText(automatic_label)
            if old_label and old_label != automatic_label:
                self.plot_rename_trace.emit(old_label, automatic_label)

    def _apply_y_label(self, index: int, widgets: _YSeriesWidgets) -> None:
        """Store the edited legend label for one y-series."""
        line_edit = widgets.label.lineEdit()
        new_label = line_edit.text().strip() if line_edit else ""
        old_label = self.y_entries[index].get("label", "")
        self.y_entries[index]["label"] = new_label
        if old_label and new_label and old_label != new_label:
            self.plot_rename_trace.emit(old_label, new_label)

    def _apply_y_axis(self, index: int, text: str) -> None:
        """Store an edited y-axis name, falling back to the default axis."""
        self.y_entries[index]["y_axis"] = text.strip() or _DEFAULT_Y_AXIS

    def _apply_y_colour(self, index: int, widgets: _YSeriesWidgets, _checked: bool = False) -> None:
        """Choose and store a colour override for one y-series."""
        current = self.y_entries[index].get("colour", "")
        chosen = self._choose_colour(
            current, f"Select colour for series {index + 1}", widgets.colour
        )
        self.y_entries[index]["colour"] = chosen
        self._update_colour_button(widgets.colour, chosen)

    def _reset_y_colour(self, index: int, widgets: _YSeriesWidgets, pos: Any) -> None:
        """Offer a context action that clears a colour override."""
        menu = QMenu(widgets.colour)
        action = menu.addAction("Auto (clear colour)")
        if menu.exec(widgets.colour.mapToGlobal(pos)) == action:
            self.y_entries[index]["colour"] = ""
            self._update_colour_button(widgets.colour, "")

    def _apply_y_style(self, index: int, field: str, combo: QComboBox, _current_index: int) -> None:
        """Store a line or point style selected by the user."""
        self.y_entries[index][field] = combo.currentData() or ""

    def _apply_y_number(self, index: int, field: str, value: float) -> None:
        """Store a numeric line-width or point-size override."""
        self.y_entries[index][field] = value

    def _remove_y_series(
        self, index: int, rebuild: Callable[[], None], _checked: bool = False
    ) -> None:
        """Remove one y-series entry and rebuild the editor grid."""
        del self.y_entries[index]
        rebuild()

    def _add_y_series(
        self,
        value_keys: list[str],
        namespace: dict[str, Any],
        rebuild: Callable[[], None],
        _checked: bool = False,
    ) -> None:
        """Append a default y-series entry and rebuild the editor grid."""
        default_key = value_keys[0] if value_keys else ""
        default_label = _default_label(default_key, namespace) if default_key else ""
        self.y_entries.append(
            {"key": default_key, "label": default_label, "y_axis": _DEFAULT_Y_AXIS}
        )
        rebuild()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Serialise the plot-points command configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict from
                :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                extended with ``"x_key"``, ``"x_axis_name"``, and
                ``"y_entries"`` (each entry includes ``"y_axis"`` and optional
                format fields ``"colour"``, ``"line_style"``, ``"point_style"``,
                ``"line_width"``, and ``"point_size"``).

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_points import PlotPointsCommand
            >>> d = PlotPointsCommand().to_json()
            >>> d["type"]
            'command'
            >>> "x_key" in d and "y_entries" in d
            True
        """
        d = super().to_json()
        d["x_key"] = self.x_key
        d["x_axis_name"] = self.x_axis_name
        d["y_entries"] = [dict(e) for e in self.y_entries]
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore configuration from a serialised dict.

        Handles backward compatibility: old configs with a top-level
        ``"y_axis_name"`` (before per-entry y-axis was added) migrate that
        value into each restored y-entry when no ``"y_axis"`` key is present.

        Args:
            data (dict[str, Any]):
                Serialised dict as produced by :meth:`to_json`.
        """
        self.x_key = data.get("x_key", "")
        self.x_axis_name = data.get("x_axis_name", _DEFAULT_X_AXIS)
        # Backward-compat: old format stored a global y_axis_name.
        legacy_y_axis = data.get("y_axis_name", _DEFAULT_Y_AXIS)
        raw_entries = data.get("y_entries", [])
        self.y_entries = []
        for e in raw_entries:
            entry = dict(e)
            if "y_axis" not in entry:
                entry["y_axis"] = legacy_y_axis
            # Ensure format fields are typed correctly when loaded from JSON.
            for key in ("line_width", "point_size"):
                if key in entry:
                    entry[key] = float(entry[key])
            self.y_entries.append(entry)
        self._ensure_configured_axes_exist()

    def _update_colour_button(self, button: QPushButton, colour: str) -> None:
        """Apply swatch styling and text to a colour selector button.

        Args:
            button (QPushButton):
                The button to update.
            colour (str):
                Colour string (hex, named, or empty for auto).
        """
        if not colour:
            button.setText("(auto)")
            button.setStyleSheet("")
            return
        if not QColor(colour).isValid():
            button.setText(colour)
            button.setStyleSheet("")
            return
        hex_colour = QColor(colour).name(QColor.NameFormat.HexRgb)
        button.setText(hex_colour)
        button.setStyleSheet(
            button_swatch_stylesheet(hex_colour, contrasting_text_colour(hex_colour))
        )

    def _choose_colour(self, current_colour: str, title: str, parent: QWidget | None = None) -> str:
        """Open a colour picker and return the selected hex colour or current value.

        Args:
            current_colour (str):
                The currently stored colour string; used as the initial picker colour.
            title (str):
                Title string for the colour dialog window.
            parent (QWidget | None):
                Parent widget for the dialog, ensuring correct modality.
        """
        base_colour = (
            QColor(current_colour) if QColor(current_colour).isValid() else QColor("black")
        )
        selected = QColorDialog.getColor(
            base_colour,
            parent,
            title,
            QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if not selected.isValid():
            return current_colour
        return selected.name(QColor.NameFormat.HexRgb)

    def _ensure_configured_axes_exist(self, plot_widget: Any | None = None) -> None:
        """Ensure configured x/y axes exist on the attached plot widget."""
        pw = plot_widget
        if pw is None and self.sequence_engine is not None:
            pw = getattr(self.sequence_engine, "plot_widget", None)
        if pw is None:
            return

        ensure_x = getattr(pw, "ensure_x_axis", None)
        if callable(ensure_x):
            ensure_x = cast(Callable[[str, str], None], ensure_x)
            x_axis = self.x_axis_name or _DEFAULT_X_AXIS
            ensure_x(x_axis, x_axis)  # pylint: disable=not-callable

        ensure_y = getattr(pw, "ensure_y_axis", None)
        if callable(ensure_y):
            ensure_y = cast(Callable[[str, str], None], ensure_y)
            for entry in self.y_entries:
                y_axis = entry.get("y_axis", _DEFAULT_Y_AXIS) or _DEFAULT_Y_AXIS
                ensure_y(y_axis, y_axis)  # pylint: disable=not-callable


def _entry_style_dict(entry: dict) -> dict:
    """Build a style dict from a y-entry, omitting default/empty values.

    Args:
        entry (dict):
            A y-series entry from :attr:`PlotPointsCommand.y_entries`.

    Returns:
        (dict):
            Style dict suitable for
            :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.set_trace_style_from_dict`.
            Empty when no format overrides are configured.
    """
    style: dict = {}
    if entry.get("colour"):
        style["colour"] = entry["colour"]
    if entry.get("line_style"):
        style["line_style"] = entry["line_style"]
    if entry.get("point_style"):
        style["point_style"] = entry["point_style"]
    lw = float(entry.get("line_width", 0.0))
    if lw > 0.0:
        style["line_width"] = lw
    ps = float(entry.get("point_size", 0.0))
    if ps > 0.0:
        style["point_size"] = ps
    return style


def _available_plot_axes(engine: SequenceEngine | None) -> tuple[list[str], list[str]]:
    """Return available x-axis and y-axis names from the current plot widget.

    Args:
        engine (SequenceEngine | None):
            Owning sequence engine for this command plugin.

    Returns:
        (tuple[list[str], list[str]]):
            A pair ``(x_axes, y_axes)`` where each entry is a sorted list of
            available axis names. Defaults to ``(["bottom"], ["left"])`` when
            no plot widget (or axis orientation map) is available.
    """
    if engine is None:
        return [_DEFAULT_X_AXIS], [_DEFAULT_Y_AXIS]

    plot_widget = getattr(engine, "plot_widget", None)
    orientations = getattr(plot_widget, "_axis_orientations", None)
    if not isinstance(orientations, dict):
        return [_DEFAULT_X_AXIS], [_DEFAULT_Y_AXIS]

    x_axes = sorted(name for name, orientation in orientations.items() if orientation == "x")
    y_axes = sorted(name for name, orientation in orientations.items() if orientation == "y")
    return x_axes or [_DEFAULT_X_AXIS], y_axes or [_DEFAULT_Y_AXIS]
