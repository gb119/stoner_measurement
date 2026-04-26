"""PlotTraceCommand — built-in command plugin for plotting trace data.

:class:`PlotTraceCommand` is a concrete :class:`CommandPlugin` that retrieves
trace data from the sequence engine namespace and sends it to the main plot
window via a Qt signal.

Two operating modes are supported:

* **Simple mode** — the user selects a single named trace from the sequence's
  trace catalogue.  Both axes are taken from the :class:`~stoner_measurement.plugins.trace.TraceData`
  object that the expression in the catalogue evaluates to.
* **Advanced mode** — the user independently selects the x data, y data, and
  plot title using Python expressions.  The expressions are evaluated against
  the live engine namespace via
  :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`, allowing
  data from different trace channels to be mixed on a single plot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from stoner_measurement.plugins.command.base import CommandPlugin

if TYPE_CHECKING:
    from stoner_measurement.core.sequence_engine import SequenceEngine

_DEFAULT_X_AXIS = "bottom"
_DEFAULT_Y_AXIS = "left"


def _format_axis_label(name: str, unit: str) -> str:
    """Build an axis label string from a name and unit.

    Args:
        name (str):
            Human-readable name of the axis variable (e.g. ``"Current"``).
        unit (str):
            Physical unit string (e.g. ``"A"``).

    Returns:
        (str):
            ``"{name} ({unit})"`` when both are non-empty, ``"{name}"`` when
            only the name is provided, or ``""`` when both are empty.
    """
    if name and unit:
        return f"{name} ({unit})"
    return name


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


class PlotTraceCommand(CommandPlugin):
    """Command plugin that plots trace data to the main plot window.

    The plugin supports two operating modes selected via the configuration UI:

    * **Simple mode** — choose a single trace from the sequence's trace
      catalogue.  The ``x`` and ``y`` arrays of the corresponding
      :class:`~stoner_measurement.plugins.trace.TraceData` are used and the
      trace key becomes the plot title.  Axis labels are also updated from the
      :attr:`~stoner_measurement.plugins.trace.TraceData.names` and
      :attr:`~stoner_measurement.plugins.trace.TraceData.units` metadata.
    * **Advanced mode** — independently specify Python expressions for the
      x data, y data, and plot title.  This allows x and y data to be taken
      from different trace channels.  The title expression is evaluated via
      :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`.

    At runtime :meth:`execute` emits the :attr:`plot_trace` signal with the
    resolved title string and the x/y NumPy arrays.  The
    :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.sequence_engine`
    setter automatically wires this signal (and the :attr:`plot_axis_labels`
    signal) to the engine's
    :attr:`~stoner_measurement.core.sequence_engine.SequenceEngine.plot_widget`
    so that the data appears in the main plot window without any manual signal
    management in the application code.

    Attributes:
        trace_key (str):
            Key in the ``_traces`` catalogue for simple mode.  Format is
            ``"{instance_name}:{channel_name}"``.  Defaults to ``""``.
        advanced_mode (bool):
            When ``True``, ``x_expr``, ``y_expr`` and ``title_expr`` are used
            instead of ``trace_key``.  Defaults to ``False``.
        x_expr (str):
            Python expression (evaluated against the engine namespace) that
            produces the x-axis data array in advanced mode.  Defaults to
            ``""``.
        y_expr (str):
            Python expression (evaluated against the engine namespace) that
            produces the y-axis data array in advanced mode.  Defaults to
            ``""``.
        title_expr (str):
            Python expression evaluated via
            :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval` to
            obtain the plot trace title in advanced mode.  Defaults to
            ``"'plot'"``.
        plot_trace (pyqtSignal[str, object, object]):
            Emitted by :meth:`execute` with ``(title, x_array, y_array)``.
            Automatically connected to
            :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.set_trace`
            when the plugin is attached to a
            :class:`~stoner_measurement.core.sequence_engine.SequenceEngine`
            whose
            :attr:`~stoner_measurement.core.sequence_engine.SequenceEngine.plot_widget`
            is set.
        plot_axis_labels (pyqtSignal[str, str]):
            Emitted by :meth:`execute` in simple mode with
            ``(x_label, y_label)`` derived from
            :class:`~stoner_measurement.plugins.trace.TraceData` metadata.
            Automatically connected to
            :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.set_default_axis_labels`
            when the plugin is attached to an engine with a plot widget.
        plot_trace_axes (pyqtSignal[str, str, str]):
            Emitted by :meth:`execute` with ``(trace_name, x_axis_name, y_axis_name)``
            when the configured axes are available. Automatically connected to
            :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.assign_trace_axes`
            when attached to an engine with a plot widget.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
        >>> cmd = PlotTraceCommand()
        >>> cmd.name
        'Plot Trace'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        False
    """

    #: Signal emitted by execute() — (title, x_array, y_array).
    plot_trace = pyqtSignal(str, object, object)
    #: Signal emitted by execute() in simple mode — (x_label, y_label).
    plot_axis_labels = pyqtSignal(str, str)
    #: Signal emitted by execute() to ensure x-axis exists — (axis_name, axis_label).
    plot_ensure_x_axis = pyqtSignal(str, str)
    #: Signal emitted by execute() to ensure y-axis exists — (axis_name, axis_label).
    plot_ensure_y_axis = pyqtSignal(str, str)
    #: Signal emitted by execute() — (trace_name, x_axis_name, y_axis_name).
    plot_trace_axes = pyqtSignal(str, str, str)

    def __init__(self, parent=None) -> None:
        """Initialise with default configuration."""
        super().__init__(parent)
        # Backing store for the sequence_engine property that overrides the
        # class-level attribute from BasePlugin.
        self._sequence_engine_ref: SequenceEngine | None = None
        self.trace_key: str = ""
        self.advanced_mode: bool = False
        self.x_expr: str = ""
        self.y_expr: str = ""
        self.title_expr: str = "'plot'"
        self.x_axis_name: str = _DEFAULT_X_AXIS
        self.y_axis_name: str = _DEFAULT_Y_AXIS

    # ------------------------------------------------------------------
    # sequence_engine property — auto-wires plot signals to the plot widget
    # ------------------------------------------------------------------

    @property  # type: ignore[override]
    def sequence_engine(self) -> SequenceEngine | None:
        """Active sequence engine, or ``None`` when the plugin is detached.

        Overrides the class-level attribute defined in
        :class:`~stoner_measurement.plugins.base_plugin.BasePlugin` with a
        full property so that the setter can automatically connect the
        :attr:`plot_trace` and :attr:`plot_axis_labels` signals to the engine's
        :attr:`~stoner_measurement.core.sequence_engine.SequenceEngine.plot_widget`
        whenever the engine reference changes.

        Returns:
            (SequenceEngine | None):
                The owning engine, or ``None`` if not attached.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> cmd = PlotTraceCommand()
            >>> cmd.sequence_engine is None
            True
            >>> engine.add_plugin("plot_trace", cmd)
            >>> cmd.sequence_engine is engine
            True
            >>> engine.shutdown()
        """
        return self._sequence_engine_ref

    @sequence_engine.setter
    def sequence_engine(self, engine: SequenceEngine | None) -> None:
        """Set the owning engine, wiring plot signals to its plot widget.

        Disconnects signals from the old engine's plot widget (if any), then
        connects them to the new engine's plot widget (if any).

        Args:
            engine (SequenceEngine | None):
                New owning engine, or ``None`` to detach.
        """
        # Disconnect from the old engine's plot widget.
        if self._sequence_engine_ref is not None:
            old_pw = getattr(self._sequence_engine_ref, "plot_widget", None)
            if old_pw is not None:
                old_set_trace = getattr(old_pw, "set_trace", None)
                if old_set_trace is not None:
                    _safe_disconnect(self.plot_trace, old_set_trace)
                old_set_labels = getattr(old_pw, "set_default_axis_labels", None)
                if old_set_labels is not None:
                    _safe_disconnect(self.plot_axis_labels, old_set_labels)
                old_assign_axes = getattr(old_pw, "assign_trace_axes", None)
                if old_assign_axes is not None:
                    _safe_disconnect(self.plot_trace_axes, old_assign_axes)
                old_ensure_x_axis = getattr(old_pw, "ensure_x_axis", None)
                if old_ensure_x_axis is not None:
                    _safe_disconnect(self.plot_ensure_x_axis, old_ensure_x_axis)
                old_ensure_y_axis = getattr(old_pw, "ensure_y_axis", None)
                if old_ensure_y_axis is not None:
                    _safe_disconnect(self.plot_ensure_y_axis, old_ensure_y_axis)

        self._sequence_engine_ref = engine

        # Connect to the new engine's plot widget.
        if engine is not None:
            new_pw = getattr(engine, "plot_widget", None)
            if new_pw is not None:
                new_set_trace = getattr(new_pw, "set_trace", None)
                if new_set_trace is not None:
                    self.plot_trace.connect(new_set_trace)
                new_set_labels = getattr(new_pw, "set_default_axis_labels", None)
                if new_set_labels is not None:
                    self.plot_axis_labels.connect(new_set_labels)
                new_assign_axes = getattr(new_pw, "assign_trace_axes", None)
                if new_assign_axes is not None:
                    self.plot_trace_axes.connect(new_assign_axes)
                new_ensure_x_axis = getattr(new_pw, "ensure_x_axis", None)
                if new_ensure_x_axis is not None:
                    self.plot_ensure_x_axis.connect(new_ensure_x_axis)
                new_ensure_y_axis = getattr(new_pw, "ensure_y_axis", None)
                if new_ensure_y_axis is not None:
                    self.plot_ensure_y_axis.connect(new_ensure_y_axis)

    @property
    def name(self) -> str:
        """Unique identifier for the plot-trace command.

        Returns:
            (str):
                ``"Plot Trace"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
            >>> PlotTraceCommand().name
            'Plot Trace'
        """
        return "Plot Trace"

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self) -> None:
        """Retrieve trace data from the engine namespace and emit :attr:`plot_trace`.

        In **simple mode** the trace named by :attr:`trace_key` is looked up in
        the ``_traces`` namespace catalogue.  The catalogue expression is
        evaluated to obtain the
        :class:`~stoner_measurement.plugins.trace.TraceData` object whose ``.x``
        and ``.y`` arrays are used.  The trace key is used as the plot title.

        In **advanced mode** :attr:`x_expr`, :attr:`y_expr`, and
        :attr:`title_expr` are each evaluated against the engine namespace via
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval` to obtain
        the respective values.

        The :attr:`plot_trace` signal ``(title, x_array, y_array)`` is emitted
        after the data are resolved.  Warnings are logged and execution is
        skipped if required data are missing or expressions are empty.

        Raises:
            RuntimeError:
                If the plugin is not attached to a sequence engine.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> import numpy as np
            >>> engine = SequenceEngine()
            >>> cmd = PlotTraceCommand()
            >>> engine.add_plugin("plot_trace", cmd)
            >>> received = []
            >>> cmd.plot_trace.connect(lambda t, x, y: received.append((t, x, y)))
            >>> engine._namespace["my_x"] = np.array([1.0, 2.0])
            >>> engine._namespace["my_y"] = np.array([3.0, 4.0])
            >>> cmd.advanced_mode = True
            >>> cmd.x_expr = "my_x"
            >>> cmd.y_expr = "my_y"
            >>> cmd.title_expr = "'My Plot'"
            >>> cmd.execute()
            >>> received[0][0]
            'My Plot'
            >>> engine.shutdown()
        """
        if self.advanced_mode:
            if not self.x_expr or not self.y_expr:
                self.log.warning("PlotTrace: x_expr or y_expr is empty — skipping plot.")
                return
            x_data = self.eval(self.x_expr)
            y_data = self.eval(self.y_expr)
            title = str(self.eval(self.title_expr)) if self.title_expr else "plot"
        else:
            traces = self.engine_namespace.get("_traces", {})
            if not self.trace_key or self.trace_key not in traces:
                self.log.warning(
                    "PlotTrace: trace %r not found in _traces catalogue — " "skipping plot.",
                    self.trace_key,
                )
                return
            trace_expr = traces[self.trace_key]
            trace_data = self.eval(trace_expr)
            try:
                x_data = trace_data.x
                y_data = trace_data.y
            except AttributeError:
                self.log.warning(
                    "PlotTrace: expression for trace %r did not return an object "
                    "with .x/.y attributes — skipping plot.",
                    self.trace_key,
                )
                return
            title = self.trace_key

            self._emit_trace_axis_labels(trace_data)

        x_axis = self.x_axis_name or _DEFAULT_X_AXIS
        y_axis = self.y_axis_name or _DEFAULT_Y_AXIS
        self.plot_ensure_x_axis.emit(x_axis, x_axis)
        self.plot_ensure_y_axis.emit(y_axis, y_axis)
        self.plot_trace.emit(
            title,
            np.asarray(x_data, dtype=float),
            np.asarray(y_data, dtype=float),
        )
        self.plot_trace_axes.emit(title, x_axis, y_axis)
        self.log.debug("PlotTrace: emitted plot for %r (%d points)", title, len(x_data))

    # ------------------------------------------------------------------
    # Configuration UI
    # ------------------------------------------------------------------

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a settings widget for configuring the plot-trace command.

        The widget contains:

        * A **Trace** dropdown (simple mode) — populated from the current
          ``_traces`` catalogue in the engine namespace.
        * An **Advanced mode** checkbox — toggles between simple and advanced
          configuration.
        * An **X data** dropdown (advanced mode) — selects the array to use as
          the horizontal axis; populated from ``{trace_key}.x`` and
          ``{trace_key}.y`` entries for every trace in the catalogue.
        * A **Y data** dropdown (advanced mode) — selects the array to use as
          the vertical axis.
        * A **Title expression** line edit (advanced mode) — a Python
          expression evaluated to produce the plot title at runtime.

        The simple-mode trace dropdown is disabled (greyed out) when advanced
        mode is active; the advanced-mode controls are disabled when advanced
        mode is inactive.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The settings widget for the *PlotTrace* configuration tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
            >>> from PyQt6.QtWidgets import QWidget
            >>> isinstance(PlotTraceCommand().config_widget(), QWidget)
            True
        """
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        traces: dict[str, str] = self.engine_namespace.get("_traces", {})
        trace_keys = list(traces.keys())
        axes_pair = _available_plot_axes(self.sequence_engine)

        channel_items = {
            f"{k} ({axis})": f"{v}.{axis}"
            for k, v in traces.items()
            for axis in ("x", "y")
        }
        channel_names = list(channel_items.keys())

        trace_combo = self._build_trace_combo(widget, trace_keys)
        advanced_check = QCheckBox(widget)
        advanced_check.setChecked(self.advanced_mode)
        x_combo = self._build_channel_combo(widget, channel_names, channel_items, self.x_expr, "x_expr")
        y_combo = self._build_channel_combo(widget, channel_names, channel_items, self.y_expr, "y_expr")
        title_edit = QLineEdit(self.title_expr, widget)
        title_edit.setToolTip(
            "Python expression evaluated at runtime in the engine namespace. "
            "Must produce a string.  Example: f'Run {run_index}'"
        )
        x_axis_combo = self._build_plot_axis_combo(widget, axes_pair[0], self.x_axis_name, "x_axis_name")
        y_axis_combo = self._build_plot_axis_combo(widget, axes_pair[1], self.y_axis_name, "y_axis_name")

        layout.addRow("Trace:", trace_combo)
        layout.addRow("Advanced mode:", advanced_check)
        layout.addRow("X data:", x_combo)
        layout.addRow("Y data:", y_combo)
        layout.addRow("Title expression:", title_edit)
        layout.addRow("X axis:", x_axis_combo)
        layout.addRow("Y axis:", y_axis_combo)
        layout.addRow(
            QLabel(
                "<i>In advanced mode, x/y data and title expressions are "
                "evaluated at runtime in the engine namespace.</i>",
                widget,
            )
        )
        widget.setLayout(layout)

        self._wire_config_signals(
            trace_combo, advanced_check, x_combo, y_combo, title_edit, x_axis_combo, y_axis_combo, channel_items
        )
        return widget

    def _emit_trace_axis_labels(self, trace_data: Any) -> None:
        names = getattr(trace_data, "names", {})
        units = getattr(trace_data, "units", {})
        x_name = names.get("x", "")
        y_name = names.get("y", "")
        x_unit = units.get("x", "")
        y_unit = units.get("y", "")
        if x_name.strip().lower() == "x" and not x_unit:
            x_name = ""
        if y_name.strip().lower() == "y" and not y_unit:
            y_name = ""
        x_label = _format_axis_label(x_name, x_unit)
        y_label = _format_axis_label(y_name, y_unit)
        if x_label or y_label:
            self.plot_axis_labels.emit(x_label, y_label)

    def _build_trace_combo(self, widget: QWidget, trace_keys: list[str]) -> QComboBox:
        combo = QComboBox(widget)
        if trace_keys:
            combo.addItems(trace_keys)
            if self.trace_key in trace_keys:
                combo.setCurrentText(self.trace_key)
            else:
                self.trace_key = trace_keys[0]
        else:
            combo.addItem("(no traces available)")
        return combo

    def _build_channel_combo(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        widget: QWidget,
        channel_names: list[str],
        channel_items: dict[str, str],
        current_expr: str,
        fallback_attr: str,
    ) -> QComboBox:
        combo = QComboBox(widget)
        if channel_names:
            combo.addItems(channel_names)
            if not _set_combo_to_expr(combo, channel_items, current_expr):
                first_name = channel_names[0]
                setattr(self, fallback_attr, channel_items[first_name])
                combo.setCurrentText(first_name)
        else:
            combo.addItem("(no channels available)")
        return combo

    def _build_plot_axis_combo(
        self,
        widget: QWidget,
        axis_names: list[str],
        current_val: str,
        fallback_attr: str,
    ) -> QComboBox:
        combo = QComboBox(widget)
        combo.addItems(axis_names)
        if current_val in axis_names:
            combo.setCurrentText(current_val)
        else:
            setattr(self, fallback_attr, axis_names[0])
            combo.setCurrentText(axis_names[0])
        return combo

    def _wire_config_signals(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        trace_combo: QComboBox,
        advanced_check: QCheckBox,
        x_combo: QComboBox,
        y_combo: QComboBox,
        title_edit: QLineEdit,
        x_axis_combo: QComboBox,
        y_axis_combo: QComboBox,
        channel_items: dict[str, str],
    ) -> None:
        def _update_enabled(advanced: bool) -> None:
            trace_combo.setEnabled(not advanced)
            x_combo.setEnabled(advanced)
            y_combo.setEnabled(advanced)
            title_edit.setEnabled(advanced)

        _update_enabled(self.advanced_mode)
        advanced_check.toggled.connect(_update_enabled)

        def _apply_trace(text: str) -> None:
            if text != "(no traces available)":
                self.trace_key = text

        def _apply_x(text: str) -> None:
            if text != "(no channels available)":
                self.x_expr = channel_items.get(text, self.x_expr)

        def _apply_y(text: str) -> None:
            if text != "(no channels available)":
                self.y_expr = channel_items.get(text, self.y_expr)

        def _apply_title() -> None:
            self.title_expr = title_edit.text().strip()

        trace_combo.currentTextChanged.connect(_apply_trace)
        advanced_check.toggled.connect(lambda checked: setattr(self, "advanced_mode", checked))
        x_combo.currentTextChanged.connect(_apply_x)
        y_combo.currentTextChanged.connect(_apply_y)
        title_edit.editingFinished.connect(_apply_title)
        x_axis_combo.currentTextChanged.connect(lambda text: setattr(self, "x_axis_name", text))
        y_axis_combo.currentTextChanged.connect(lambda text: setattr(self, "y_axis_name", text))

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Serialise the plot-trace command configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict from :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                extended with ``"trace_key"``, ``"advanced_mode"``, ``"x_expr"``,
                ``"y_expr"``, and ``"title_expr"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
            >>> d = PlotTraceCommand().to_json()
            >>> d["type"]
            'command'
            >>> "trace_key" in d and "advanced_mode" in d
            True
        """
        d = super().to_json()
        d["trace_key"] = self.trace_key
        d["advanced_mode"] = self.advanced_mode
        d["x_expr"] = self.x_expr
        d["y_expr"] = self.y_expr
        d["title_expr"] = self.title_expr
        d["x_axis_name"] = self.x_axis_name
        d["y_axis_name"] = self.y_axis_name
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore configuration from a serialised dict.

        Args:
            data (dict[str, Any]):
                Serialised dict as produced by :meth:`to_json`.
        """
        self.trace_key = data.get("trace_key", "")
        self.advanced_mode = data.get("advanced_mode", False)
        self.x_expr = data.get("x_expr", "")
        self.y_expr = data.get("y_expr", "")
        self.title_expr = data.get("title_expr", "'plot'")
        self.x_axis_name = data.get("x_axis_name", _DEFAULT_X_AXIS)
        self.y_axis_name = data.get("y_axis_name", _DEFAULT_Y_AXIS)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _set_combo_to_expr(
    combo: QComboBox,
    items: dict[str, str],
    expr: str,
) -> bool:
    """Set *combo* to the entry whose value in *items* matches *expr*.

    If no match is found the combo selection is left unchanged.

    Args:
        combo (QComboBox):
            The combo box whose current index is to be set.
        items (dict[str, str]):
            Mapping of display name to expression string.
        expr (str):
            Expression string to search for.

    Returns:
        (bool):
            ``True`` if a matching entry was found and the combo was updated,
            ``False`` otherwise.
    """
    for display_name, item_expr in items.items():
        if item_expr == expr:
            combo.setCurrentText(display_name)
            return True
    return False


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
