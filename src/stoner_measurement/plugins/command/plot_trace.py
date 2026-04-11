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

from typing import Any

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


class PlotTraceCommand(CommandPlugin):
    """Command plugin that plots trace data to the main plot window.

    The plugin supports two operating modes selected via the configuration UI:

    * **Simple mode** — choose a single trace from the sequence's trace
      catalogue.  The ``x`` and ``y`` arrays of the corresponding
      :class:`~stoner_measurement.plugins.trace.TraceData` are used and the
      trace key becomes the plot title.
    * **Advanced mode** — independently specify Python expressions for the
      x data, y data, and plot title.  This allows x and y data to be taken
      from different trace channels.  The title expression is evaluated via
      :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`.

    At runtime :meth:`execute` emits the :attr:`plot_trace` signal with the
    resolved title string and the x/y NumPy arrays.  The application wires
    this signal to :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.set_trace`
    so that the data appears in the main plot window.

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
            The application connects this signal to
            :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.set_trace`.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
        >>> cmd = PlotTraceCommand()
        >>> cmd.name
        'PlotTrace'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        False
    """

    #: Signal emitted by execute() — (title, x_array, y_array).
    plot_trace = pyqtSignal(str, object, object)

    def __init__(self, parent=None) -> None:
        """Initialise with default configuration."""
        super().__init__(parent)
        self.trace_key: str = ""
        self.advanced_mode: bool = False
        self.x_expr: str = ""
        self.y_expr: str = ""
        self.title_expr: str = "'plot'"

    @property
    def name(self) -> str:
        """Unique identifier for the plot-trace command.

        Returns:
            (str):
                ``"PlotTrace"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
            >>> PlotTraceCommand().name
            'PlotTrace'
        """
        return "PlotTrace"

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
                self.log.warning(
                    "PlotTrace: x_expr or y_expr is empty — skipping plot."
                )
                return
            x_data = self.eval(self.x_expr)
            y_data = self.eval(self.y_expr)
            title = str(self.eval(self.title_expr)) if self.title_expr else "plot"
        else:
            traces = self.engine_namespace.get("_traces", {})
            if not self.trace_key or self.trace_key not in traces:
                self.log.warning(
                    "PlotTrace: trace %r not found in _traces catalogue — "
                    "skipping plot.",
                    self.trace_key,
                )
                return
            trace_expr = traces[self.trace_key]
            trace_data = self.eval(trace_expr)
            x_data = trace_data.x
            y_data = trace_data.y
            title = self.trace_key

        self.plot_trace.emit(
            title,
            np.asarray(x_data, dtype=float),
            np.asarray(y_data, dtype=float),
        )
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

        # Build trace lists from the engine namespace.
        traces: dict[str, str] = self.engine_namespace.get("_traces", {})
        trace_keys = list(traces.keys())

        # Build a mapping of display-name → expression for individual
        # x/y data arrays across all trace channels.
        channel_items: dict[str, str] = {}
        for key, expr in traces.items():
            channel_items[f"{key} (x)"] = f"{expr}.x"
            channel_items[f"{key} (y)"] = f"{expr}.y"
        channel_names = list(channel_items.keys())

        # --- Trace dropdown (simple mode) ---
        trace_combo = QComboBox(widget)
        if trace_keys:
            trace_combo.addItems(trace_keys)
            if self.trace_key in trace_keys:
                trace_combo.setCurrentText(self.trace_key)
        else:
            trace_combo.addItem("(no traces available)")

        # --- Advanced mode checkbox ---
        advanced_check = QCheckBox(widget)
        advanced_check.setChecked(self.advanced_mode)

        # --- X data dropdown (advanced mode) ---
        x_combo = QComboBox(widget)
        if channel_names:
            x_combo.addItems(channel_names)
            _set_combo_to_expr(x_combo, channel_items, self.x_expr)
        else:
            x_combo.addItem("(no channels available)")

        # --- Y data dropdown (advanced mode) ---
        y_combo = QComboBox(widget)
        if channel_names:
            y_combo.addItems(channel_names)
            _set_combo_to_expr(y_combo, channel_items, self.y_expr)
        else:
            y_combo.addItem("(no channels available)")

        # --- Title expression (advanced mode) ---
        title_edit = QLineEdit(self.title_expr, widget)
        title_edit.setToolTip(
            "Python expression evaluated at runtime in the engine namespace. "
            "Must produce a string.  Example: f'Run {run_index}'"
        )

        # Populate form layout.
        layout.addRow("Trace:", trace_combo)
        layout.addRow("Advanced mode:", advanced_check)
        layout.addRow("X data:", x_combo)
        layout.addRow("Y data:", y_combo)
        layout.addRow("Title expression:", title_edit)
        layout.addRow(
            QLabel(
                "<i>In advanced mode, x/y data and title expressions are "
                "evaluated at runtime in the engine namespace.</i>",
                widget,
            )
        )
        widget.setLayout(layout)

        # --- Enable/disable logic ---
        def _update_enabled(advanced: bool) -> None:
            trace_combo.setEnabled(not advanced)
            x_combo.setEnabled(advanced)
            y_combo.setEnabled(advanced)
            title_edit.setEnabled(advanced)

        _update_enabled(self.advanced_mode)
        advanced_check.toggled.connect(_update_enabled)

        # --- Callbacks to persist state ---
        def _apply_trace(text: str) -> None:
            if text != "(no traces available)":
                self.trace_key = text

        def _apply_advanced(checked: bool) -> None:
            self.advanced_mode = checked

        def _apply_x(text: str) -> None:
            if text != "(no channels available)":
                self.x_expr = channel_items.get(text, self.x_expr)

        def _apply_y(text: str) -> None:
            if text != "(no channels available)":
                self.y_expr = channel_items.get(text, self.y_expr)

        def _apply_title() -> None:
            self.title_expr = title_edit.text().strip()

        trace_combo.currentTextChanged.connect(_apply_trace)
        advanced_check.toggled.connect(_apply_advanced)
        x_combo.currentTextChanged.connect(_apply_x)
        y_combo.currentTextChanged.connect(_apply_y)
        title_edit.editingFinished.connect(_apply_title)

        return widget

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


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _set_combo_to_expr(
    combo: QComboBox,
    items: dict[str, str],
    expr: str,
) -> None:
    """Set *combo* to the entry whose value in *items* matches *expr*.

    If no match is found the combo selection is left unchanged.

    Args:
        combo (QComboBox):
            The combo box whose current index is to be set.
        items (dict[str, str]):
            Mapping of display name to expression string.
        expr (str):
            Expression string to search for.
    """
    for display_name, item_expr in items.items():
        if item_expr == expr:
            combo.setCurrentText(display_name)
            return
