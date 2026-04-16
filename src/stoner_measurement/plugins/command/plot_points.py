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

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from stoner_measurement.plugins.command.base import CommandPlugin

if TYPE_CHECKING:
    from stoner_measurement.core.sequence_engine import SequenceEngine

_DEFAULT_X_AXIS = "bottom"
_DEFAULT_Y_AXIS = "left"


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
    """Command plugin that appends live scatter-plot points to the main plot.

    Each time :meth:`execute` is called it reads the current x value (a
    scalar from the ``_values`` catalogue) and each configured y value
    (also scalars from the catalogue) and emits :attr:`plot_point` once per
    y series as ``(label, x, y)``.  The signal is automatically connected to
    :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.append_point` so
    that the data appears in real-time in the main plot window.

    Each y-series entry can independently target a different y-axis on the
    plot widget.  If the specified y-axis does not yet exist it is created
    automatically (on the right-hand side) when :meth:`execute` runs.

    The configuration UI lets the user:

    * Select an **x value** from the ``_values`` catalogue.
    * Select the **X axis** (shared for all series).
    * Add one or more **y series**, each with its own value from the
      catalogue, a customisable label, and an independently selectable
      **y axis**.

    Attributes:
        x_key (str):
            Key in the ``_values`` catalogue for the x data.  Format is
            ``"{instance_name}:{quantity_name}"``.
        y_entries (list[dict[str, str]]):
            Ordered list of y-series definitions.  Each entry is a dict with
            keys ``"key"`` (catalogue key), ``"label"`` (trace name shown
            in the legend), and ``"y_axis"`` (y-axis name; defaults to
            ``"left"`` when absent).
        x_axis_name (str):
            Name of the x-axis shared by all y series.  Defaults to
            ``"bottom"``.
        plot_point (pyqtSignal[str, float, float]):
            Emitted once per y series by :meth:`execute` as
            ``(label, x_value, y_value)``.  Automatically connected to
            :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.append_point`
            when the plugin is attached to an engine with a plot widget.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
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
        if self._sequence_engine_ref is not None:
            old_pw = getattr(self._sequence_engine_ref, "plot_widget", None)
            if old_pw is not None:
                old_append_point = getattr(old_pw, "append_point", None)
                if old_append_point is not None:
                    _safe_disconnect(self.plot_point, old_append_point)
                old_mark_queued = getattr(old_pw, "mark_data_update_queued", None)
                if old_mark_queued is not None:
                    _safe_disconnect(self.plot_update_queued, old_mark_queued)
                old_ensure_y_axis = getattr(old_pw, "ensure_y_axis", None)
                if old_ensure_y_axis is not None:
                    _safe_disconnect(self.plot_ensure_y_axis, old_ensure_y_axis)
                old_ensure_x_axis = getattr(old_pw, "ensure_x_axis", None)
                if old_ensure_x_axis is not None:
                    _safe_disconnect(self.plot_ensure_x_axis, old_ensure_x_axis)
                old_assign_axes = getattr(old_pw, "assign_trace_axes", None)
                if old_assign_axes is not None:
                    _safe_disconnect(self.plot_trace_axes, old_assign_axes)

        self._sequence_engine_ref = engine

        if engine is not None:
            new_pw = getattr(engine, "plot_widget", None)
            if new_pw is not None:
                new_append_point = getattr(new_pw, "append_point", None)
                if new_append_point is not None:
                    self.plot_point.connect(new_append_point)
                new_mark_queued = getattr(new_pw, "mark_data_update_queued", None)
                if new_mark_queued is not None:
                    self.plot_update_queued.connect(new_mark_queued)
                new_ensure_y_axis = getattr(new_pw, "ensure_y_axis", None)
                if new_ensure_y_axis is not None:
                    self.plot_ensure_y_axis.connect(new_ensure_y_axis)
                new_ensure_x_axis = getattr(new_pw, "ensure_x_axis", None)
                if new_ensure_x_axis is not None:
                    self.plot_ensure_x_axis.connect(new_ensure_x_axis)
                new_assign_axes = getattr(new_pw, "assign_trace_axes", None)
                if new_assign_axes is not None:
                    self.plot_trace_axes.connect(new_assign_axes)

    @property
    def name(self) -> str:
        """Unique identifier for the plot-points command.

        Returns:
            (str):
                ``"Plot Points"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
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
            RuntimeError:
                If the plugin is not attached to a sequence engine.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
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
            self.plot_ensure_x_axis.emit(x_axis, x_axis)
            self.plot_ensure_y_axis.emit(y_axis, y_axis)
            self.plot_update_queued.emit()
            self.plot_point.emit(label, x_val, y_val)
            self.plot_trace_axes.emit(label, x_axis, y_axis)
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_points import PlotPointsCommand
            >>> from PyQt6.QtWidgets import QWidget
            >>> isinstance(PlotPointsCommand().config_widget(), QWidget)
            True
        """
        ns = self.engine_namespace
        values: dict[str, str] = ns.get("_values", {})
        value_keys = list(values.keys())
        x_axis_names, y_axis_names = _available_plot_axes(self.sequence_engine)

        outer = QWidget(parent)
        outer_layout = QFormLayout(outer)

        # --- X value dropdown ---
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

        # --- Shared X axis dropdown ---
        x_axis_combo = QComboBox(outer)
        x_axis_combo.addItems(x_axis_names)
        if self.x_axis_name in x_axis_names:
            x_axis_combo.setCurrentText(self.x_axis_name)
        else:
            self.x_axis_name = x_axis_names[0]
            x_axis_combo.setCurrentText(self.x_axis_name)
        x_axis_combo.currentTextChanged.connect(lambda text: setattr(self, "x_axis_name", text))
        outer_layout.addRow("X axis:", x_axis_combo)

        # --- Y series area ---
        outer_layout.addRow(QLabel("<b>Y series:</b>", outer))

        scroll_area = QScrollArea(outer)
        scroll_area.setWidgetResizable(True)
        scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll_area.setMinimumHeight(150)

        series_container = QWidget()
        series_layout = QGridLayout(series_container)
        series_layout.setColumnStretch(1, 1)

        # Header row
        series_layout.addWidget(QLabel("<b>Value</b>"), 0, 0)
        series_layout.addWidget(QLabel("<b>Label</b>"), 0, 1)
        series_layout.addWidget(QLabel("<b>Y axis</b>"), 0, 2)

        scroll_area.setWidget(series_container)
        outer_layout.addRow(scroll_area)

        # Track current row widgets so we can rebuild on add/remove.
        row_widgets: list[tuple[QComboBox, QLineEdit, QComboBox, QPushButton]] = []

        def _rebuild_rows() -> None:
            """Clear and re-populate the y-series grid from self.y_entries."""
            # Remove all widgets except the header (row 0).
            for _combo, _edit, _yax, _btn in row_widgets:
                _combo.setParent(None)
                _edit.setParent(None)
                _yax.setParent(None)
                _btn.setParent(None)
            row_widgets.clear()

            for i, entry in enumerate(self.y_entries):
                grid_row = i + 1
                combo = QComboBox(series_container)
                if value_keys:
                    combo.addItems(value_keys)
                    key = entry.get("key", "")
                    if key in value_keys:
                        combo.setCurrentText(key)
                    else:
                        combo.setCurrentIndex(0)
                        entry["key"] = value_keys[0] if value_keys else ""
                else:
                    combo.addItem("(no values available)")

                label_edit = QLineEdit(entry.get("label", ""), series_container)

                # Editable y-axis combo: pre-populated with known axes but
                # allows the user to type a new name that is auto-created on
                # execute().
                y_axis_entry = QComboBox(series_container)
                y_axis_entry.setEditable(True)
                y_axis_entry.addItems(y_axis_names)
                entry_y_axis = entry.get("y_axis", _DEFAULT_Y_AXIS)
                if entry_y_axis in y_axis_names:
                    y_axis_entry.setCurrentText(entry_y_axis)
                else:
                    y_axis_entry.setEditText(entry_y_axis)

                remove_btn = QPushButton("✕", series_container)
                remove_btn.setFixedWidth(28)

                series_layout.addWidget(combo, grid_row, 0)
                series_layout.addWidget(label_edit, grid_row, 1)
                series_layout.addWidget(y_axis_entry, grid_row, 2)
                series_layout.addWidget(remove_btn, grid_row, 3)
                row_widgets.append((combo, label_edit, y_axis_entry, remove_btn))

                # Capture index in closures.
                def _make_key_handler(idx: int) -> Any:
                    def _apply_key(text: str, _idx: int = idx) -> None:
                        if text != "(no values available)":
                            self.y_entries[_idx]["key"] = text
                            # Update label default only if the label still
                            # matches a previously auto-generated value.
                            auto = _default_label(text, ns)
                            current_label = self.y_entries[_idx].get("label", "")
                            if not current_label or current_label == _default_label(
                                self.y_entries[_idx].get("key", ""), ns
                            ):
                                self.y_entries[_idx]["label"] = auto
                                row_widgets[_idx][1].setText(auto)

                    return _apply_key

                def _make_label_handler(idx: int) -> Any:
                    def _apply_label(_idx: int = idx) -> None:
                        self.y_entries[_idx]["label"] = row_widgets[_idx][1].text().strip()

                    return _apply_label

                def _make_y_axis_handler(idx: int) -> Any:
                    def _apply_y_axis(text: str, _idx: int = idx) -> None:
                        self.y_entries[_idx]["y_axis"] = text.strip() or _DEFAULT_Y_AXIS

                    return _apply_y_axis

                def _make_remove_handler(idx: int) -> Any:
                    def _remove(_idx: int = idx) -> None:
                        del self.y_entries[_idx]
                        _rebuild_rows()

                    return _remove

                combo.currentTextChanged.connect(_make_key_handler(i))
                label_edit.editingFinished.connect(_make_label_handler(i))
                y_axis_entry.currentTextChanged.connect(_make_y_axis_handler(i))
                remove_btn.clicked.connect(_make_remove_handler(i))

        _rebuild_rows()

        # --- Add Y series button ---
        add_btn = QPushButton("Add Y series", outer)

        def _add_series() -> None:
            default_key = value_keys[0] if value_keys else ""
            default_label = _default_label(default_key, ns) if default_key else ""
            self.y_entries.append(
                {"key": default_key, "label": default_label, "y_axis": _DEFAULT_Y_AXIS}
            )
            _rebuild_rows()

        add_btn.clicked.connect(_add_series)
        outer_layout.addRow(add_btn)
        outer.setLayout(outer_layout)
        return outer

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
                ``"y_entries"`` (each entry includes a ``"y_axis"`` field).

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
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
            self.y_entries.append(entry)


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
