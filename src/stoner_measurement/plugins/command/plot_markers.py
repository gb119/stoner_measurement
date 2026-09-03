"""Commands for adding and clearing fixed data-coordinate plot markers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qtpy.QtWidgets import QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.qt_compat import pyqtSignal

if TYPE_CHECKING:
    from stoner_measurement.core.sequence_engine import SequenceEngine


def _safe_disconnect(signal: Any, slot: Any) -> None:
    """Disconnect a Qt signal without failing when it is not connected."""
    try:
        signal.disconnect(slot)
    except (TypeError, RuntimeError):
        pass


class AddPlotMarkerCommand(CommandPlugin):
    """Add a labelled marker at runtime-evaluated plot coordinates.

    The configuration page accepts Python expressions for **x**, **y**, and
    **label**. They are evaluated when the sequence reaches this command using
    the current sequence-engine namespace, so values calculated by earlier
    steps can be marked directly.

    The label expression may produce any value; its string representation is
    displayed beside the marker. A configured label that is blank or contains
    only whitespace is passed to the plot as ``None``, selecting the default
    coordinate label. Evaluated ``None`` and whitespace-only strings behave in
    the same way.

    Markers have fixed data coordinates and follow zooming, panning, and axis
    scale changes. They remain until removed through the plot context menu, a
    Remove Plot Markers command, or a plot clear.

    Attributes:
        x_expr (str): Runtime expression producing the x coordinate.
        y_expr (str): Runtime expression producing the y coordinate.
        label_expr (str): Runtime expression producing the optional label.
        add_plot_marker (pyqtSignal[float, float, object]): Signal connected to
            :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.add_data_marker`.
    """

    add_plot_marker = pyqtSignal(float, float, object)

    def __init__(self, parent=None) -> None:
        """Initialise with zero coordinates and the default plot label."""
        super().__init__(parent)
        self._sequence_engine_ref: SequenceEngine | None = None
        self.x_expr = "0.0"
        self.y_expr = "0.0"
        self.label_expr = ""

    @property  # type: ignore[override]
    def sequence_engine(self) -> SequenceEngine | None:
        """Return the owning sequence engine, if attached."""
        return self._sequence_engine_ref

    @sequence_engine.setter
    def sequence_engine(self, engine: SequenceEngine | None) -> None:
        """Attach to an engine and wire marker requests to its plot widget."""
        old_plot = getattr(self._sequence_engine_ref, "plot_widget", None)
        if old_plot is not None:
            _safe_disconnect(self.add_plot_marker, old_plot.add_data_marker)
        self._sequence_engine_ref = engine
        new_plot = getattr(engine, "plot_widget", None)
        if new_plot is not None:
            self.add_plot_marker.connect(new_plot.add_data_marker)

    @property
    def name(self) -> str:
        """Return the user-visible plugin name."""
        return "Add Plot Marker"

    def execute(self) -> None:
        """Evaluate the configured values and request a new plot marker."""
        x = self.eval_float(self.x_expr)
        y = self.eval_float(self.y_expr)
        label: str | None = None
        if self.label_expr.strip():
            evaluated = self.eval(self.label_expr)
            if evaluated is not None and str(evaluated).strip():
                label = str(evaluated)
        self.add_plot_marker.emit(x, y, label)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return editors for the runtime x, y, and label expressions."""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        controls = (
            ("X:", "plot_marker_x", self.x_expr, "x_expr"),
            ("Y:", "plot_marker_y", self.y_expr, "y_expr"),
            ("Label:", "plot_marker_label", self.label_expr, "label_expr"),
        )
        for title, object_name, value, attribute in controls:
            edit = QLineEdit(value, widget)
            edit.setObjectName(object_name)
            edit.setToolTip("Python expression evaluated in the sequence namespace at runtime.")
            edit.textChanged.connect(lambda text, attr=attribute: setattr(self, attr, text))
            form.addRow(title, edit)
        layout.addLayout(form)
        note = QLabel(
            "<i>All fields are evaluated at runtime. Leave Label blank to use the default coordinate label.</i>",
            widget,
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise the configured runtime expressions."""
        data = super().to_json()
        data.update(x_expr=self.x_expr, y_expr=self.y_expr, label_expr=self.label_expr)
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore runtime expressions from serialized configuration."""
        self.x_expr = str(data.get("x_expr", self.x_expr))
        self.y_expr = str(data.get("y_expr", self.y_expr))
        self.label_expr = str(data.get("label_expr", self.label_expr))


class RemovePlotMarkersCommand(CommandPlugin):
    """Remove all data markers from the main plot.

    This command has no configurable values. Execution calls the plot widget's
    :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.clear_data_markers`
    API. Plot traces and axis configuration are left unchanged.

    Attributes:
        clear_plot_markers (pyqtSignal): Signal connected to the main plot's
            marker-clearing API while attached to a sequence engine.
    """

    clear_plot_markers = pyqtSignal()

    def __init__(self, parent=None) -> None:
        """Initialise the marker-clear command."""
        super().__init__(parent)
        self._sequence_engine_ref: SequenceEngine | None = None

    @property  # type: ignore[override]
    def sequence_engine(self) -> SequenceEngine | None:
        """Return the owning sequence engine, if attached."""
        return self._sequence_engine_ref

    @sequence_engine.setter
    def sequence_engine(self, engine: SequenceEngine | None) -> None:
        """Attach to an engine and wire clearing to its plot widget."""
        old_plot = getattr(self._sequence_engine_ref, "plot_widget", None)
        if old_plot is not None:
            _safe_disconnect(self.clear_plot_markers, old_plot.clear_data_markers)
        self._sequence_engine_ref = engine
        new_plot = getattr(engine, "plot_widget", None)
        if new_plot is not None:
            self.clear_plot_markers.connect(new_plot.clear_data_markers)

    @property
    def name(self) -> str:
        """Return the user-visible plugin name."""
        return "Remove Plot Markers"

    def execute(self) -> None:
        """Request removal of every marker from the main plot."""
        self.clear_plot_markers.emit()

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return the informational configuration page."""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        label = QLabel(
            "<i>No configuration required. When executed, all data markers are removed; plot traces are unchanged.</i>",
            widget,
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch()
        return widget
