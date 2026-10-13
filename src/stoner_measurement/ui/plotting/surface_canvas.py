"""GUI-owned surface state shared by the XYZ and intensity display adapters."""

from collections.abc import Mapping
from dataclasses import replace
from math import isfinite

import numpy as np
from qtpy.QtCore import QSignalBlocker, QTimer  # type: ignore[attr-defined]
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.plotting.contracts import (
    AxisDescription,
    ClearPlot,
    ConfigureAxes,
    ModifySeries,
    PlotData,
    PlotRequest,
    Presentation,
    RemoveSeries,
    SeriesDescription,
    SeriesUpdate,
    UpdateMode,
)
from stoner_measurement.core.plotting.service import UnsupportedDisplayOperation
from stoner_measurement.core.plotting.state import DisplayState, SeriesState
from stoner_measurement.core.plotting.surfaces import prepare_surface
from stoner_measurement.qt_compat import pyqtSignal, pyqtSlot
from stoner_measurement.ui.widgets import SISpinBox


class SurfaceCanvasDisplay(QWidget):
    """Apply logical requests immediately; coalesce graphics work at 25 Hz.

    Surface cells retain their exact source coordinates. Painting and export
    assemble snapshots on demand, never once per incoming point. Only this
    display's timer and graphics children are released during close.
    """

    changed = pyqtSignal()
    supported_styles = frozenset({"colour", "line_width", "point_size"})

    def __init__(self, parent, capabilities, *, three_dimensional):
        super().__init__(parent)
        self.capabilities = capabilities
        self.three_dimensional = three_dimensional
        self.supported_styles = self.supported_styles if three_dimensional else frozenset()
        self._series = {}
        self._surfaces = {}
        self._axes = {}
        self._closed = False
        self._dirty = False
        self._revision = 0
        self._prepared_payload = None
        self._prepared_revision = -1
        self._prepared_surface = None
        self._palette = "viridis"
        self._colour_limits = None
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Colour scale", self))
        self.palette_combo = QComboBox(self)
        self.palette_combo.addItems(["viridis", "plasma", "inferno", "magma", "grey"])
        self.palette_combo.currentTextChanged.connect(self._set_palette)
        controls.addWidget(self.palette_combo)
        reset = QPushButton("Reset view", self)
        reset.clicked.connect(self.reset_view)
        controls.addWidget(reset)
        controls.addStretch(1)
        layout.addLayout(controls)
        limits_controls = QHBoxLayout()
        self.auto_colour = QCheckBox("Auto colour range", self)
        self.auto_colour.setChecked(True)
        limits_controls.addWidget(self.auto_colour)
        self.colour_min = SISpinBox(self, value=0, siPrefix=True)
        self.colour_max = SISpinBox(self, value=1, siPrefix=True)
        for label, control in (("Min", self.colour_min), ("Max", self.colour_max)):
            limits_controls.addWidget(QLabel(label, self))
            limits_controls.addWidget(control)
            control.setEnabled(False)
            control.sigValueChanged.connect(self._set_colour_limits)
        self.auto_colour.toggled.connect(self._set_colour_limits)
        limits_controls.addStretch(1)
        layout.addLayout(limits_controls)
        from stoner_measurement.ui.plotting.surface_graphics import IntensityCanvas

        if three_dimensional:
            from stoner_measurement.ui.plotting.surface_graphics import Cartesian3DCanvas

            self.canvas = Cartesian3DCanvas(self)
        else:
            self.canvas = IntensityCanvas(self)
        layout.addWidget(self.canvas, 1)

    @property
    def widget(self):
        """Expose this adapter's widget without retaining a self-reference cycle."""
        return self

    @pyqtSlot(str)
    def _set_palette(self, name):
        self._palette = name
        self._schedule()

    @pyqtSlot()
    def _set_colour_limits(self):
        automatic = self.auto_colour.isChecked()
        self.colour_min.setEnabled(not automatic)
        self.colour_max.setEnabled(not automatic)
        lower, upper = float(self.colour_min.value()), float(self.colour_max.value())
        valid = isfinite(lower) and isfinite(upper) and lower < upper
        self.colour_max.setToolTip(
            "" if automatic or valid else "Maximum must be greater than minimum."
        )
        if automatic or valid:
            self._colour_limits = None if automatic else (lower, upper)
            self._schedule()

    def _schedule(self):
        self._dirty = True
        if not self._timer.isActive():
            self._timer.start()

    def validate(self, payload):
        """Reject unsupported operations, styles and topology before mutation."""
        if self._closed:
            raise ValueError("The display is closed.")
        if self._prepared_payload is payload and self._prepared_revision == self._revision:
            return
        self._prepared_payload = None
        self._prepared_surface = None
        reasons = self.capabilities.unsupported_reasons(PlotRequest(payload))
        if reasons:
            raise ValueError(" ".join(reasons))
        if isinstance(payload, (SeriesUpdate, ModifySeries)):
            self._validate_style(payload.style)
        if isinstance(payload, SeriesUpdate):
            self._validate_series_update(payload)
        elif isinstance(payload, (ModifySeries, RemoveSeries)):
            if payload.series_id not in self._series:
                raise ValueError("Unknown series ID.")
        elif isinstance(payload, ConfigureAxes):
            if len({axis.slot for axis in payload.axes}) != len(payload.axes):
                raise ValueError("This display supports one axis per coordinate slot.")
            axes = self._configured_axes(payload)
            slots = [axis.slot for axis in axes.values()]
            if len(set(slots)) != len(slots):
                raise ValueError("This display supports one axis per coordinate slot.")
            for axis in axes.values():
                if axis.slot == "z" and not self.three_dimensional:
                    raise ValueError("Intensity uses XY coordinates and a value colour scale.")
                if axis.scale != "linear":
                    raise UnsupportedDisplayOperation(
                        "Surface displays currently support linear axes only."
                    )
        self._prepared_payload = payload
        self._prepared_revision = self._revision

    def _validate_series_update(self, payload: SeriesUpdate) -> None:
        """Check surface topology, append schema and assigned axes."""
        existing = self._series.get(payload.series_id)
        if payload.surface is not None:
            if existing and payload.series_id not in self._surfaces:
                raise ValueError("Clear the existing non-surface series first.")
            self._prepared_surface = prepare_surface(payload, self._surfaces.get(payload.series_id))
        elif payload.presentation in (Presentation.SURFACE, Presentation.INTENSITY):
            raise ValueError("Grid presentations require an explicit surface binding.")
        elif existing:
            if payload.series_id in self._surfaces:
                raise ValueError("Clear the existing surface series first.")
            old = existing.update
            if payload.mode == UpdateMode.APPEND and (
                old.binding != payload.binding
                or old.coordinates != payload.coordinates
                or old.data.metadata != payload.data.metadata
                or tuple(old.data.channels) != tuple(payload.data.channels)
                or tuple(old.data.uncertainties) != tuple(payload.data.uncertainties)
                or old.presentation != payload.presentation
            ):
                raise ValueError("Appended points must preserve their series schema.")
        for slot, name in payload.axes.items():
            if name not in self._axes or self._axes[name].slot != slot:
                raise ValueError("Unknown axis assignment.")

    def _validate_style(self, style) -> None:
        """Check supported style keys, finite sizes and colours."""
        if set(style).difference(self.supported_styles):
            raise ValueError("Unsupported display style.")
        for key in ("line_width", "point_size"):
            if key in style:
                value = float(style[key])
                if not isfinite(value) or value <= 0:
                    raise ValueError("Style sizes must be finite and positive.")
        if "colour" in style:
            import pyqtgraph as pg  # type: ignore[import-untyped]

            if not pg.mkColor(style["colour"]).isValid():
                raise ValueError("Invalid series colour.")

    def _configured_axes(self, payload):
        axes = dict(self._axes)
        for axis in payload.axes:
            # A new name for a slot replaces its old name only when unreferenced.
            for name, previous in tuple(axes.items()):
                if previous.slot == axis.slot and name != axis.name:
                    if any(name in entry.update.axes.values() for entry in self._series.values()):
                        raise ValueError("An existing series still references this axis.")
                    del axes[name]
            axes[axis.name] = axis
        return axes

    def apply(self, payload):
        """Finish one validated logical operation on the GUI thread."""
        self.validate(payload)
        if isinstance(payload, SeriesUpdate):
            old = self._series.get(payload.series_id)
            if old:
                payload = replace(
                    payload,
                    title=old.update.title if payload.title is None else payload.title,
                    style={**old.update.style, **payload.style},
                )
            if payload.surface is not None:
                grid, keys = self._prepared_surface
                grid.commit(payload, keys)
                self._surfaces[payload.series_id] = grid
            elif old and payload.mode == UpdateMode.APPEND:
                payload = replace(
                    payload,
                    data=PlotData(
                        {
                            name: np.concatenate((old.update.data.channels[name], values))
                            for name, values in payload.data.channels.items()
                        },
                        payload.data.metadata,
                        {
                            name: np.concatenate((old.update.data.uncertainties[name], values))
                            for name, values in payload.data.uncertainties.items()
                        },
                    ),
                    mode=UpdateMode.REPLACE,
                )
            self._series[payload.series_id] = SeriesState(payload, old.visible if old else True)
        elif isinstance(payload, ModifySeries):
            old = self._series[payload.series_id]
            update = replace(
                old.update,
                title=old.update.title if payload.title is None else payload.title,
                style={**old.update.style, **payload.style},
            )
            self._series[payload.series_id] = SeriesState(
                update, old.visible if payload.visible is None else payload.visible
            )
            if payload.series_id in self._surfaces:
                self._surfaces[payload.series_id].template = update
        elif isinstance(payload, RemoveSeries):
            del self._series[payload.series_id]
            self._surfaces.pop(payload.series_id, None)
        elif isinstance(payload, ConfigureAxes):
            self._axes = self._configured_axes(payload)
        elif isinstance(payload, ClearPlot):
            self._series.clear()
            self._surfaces.clear()
        self._revision += 1
        self._prepared_payload = None
        self._prepared_surface = None
        self._schedule()
        self.changed.emit()
        return None

    def descriptions(self):
        """Return physical axis labels and immutable public series descriptions."""
        axes = dict(self._axes)
        if self._series:
            update = next(iter(self._series.values())).update
            for slot in ("x", "y", "z") if self.three_dimensional else ("x", "y"):
                if not any(axis.slot == slot for axis in axes.values()):
                    channel = getattr(update.binding, slot)
                    axes[slot] = AxisDescription(slot, slot, update.data.metadata[channel])
        return tuple(axes.values()), tuple(
            SeriesDescription(
                name,
                entry.update.title or name,
                entry.update.binding,
                entry.update.coordinates,
                entry.visible,
            )
            for name, entry in self._series.items()
        )

    def export_state(self):
        """Capture complete acquired cells and visibility for idle replay."""
        return DisplayState(
            axes=tuple(self._axes.values()),
            series=tuple(
                SeriesState(
                    self._surfaces[name].snapshot() if name in self._surfaces else entry.update,
                    entry.visible,
                )
                for name, entry in self._series.items()
            ),
            renderer_settings=self.export_settings(),
        )

    def import_state(self, state):
        """Hydrate a hidden fresh candidate, including its first rendered frame."""
        if self._series or self._axes:
            raise ValueError("State import requires an empty display.")
        if state.markers:
            raise ValueError("Surface displays do not support markers.")
        self.import_settings(state.renderer_settings)
        self.apply(ConfigureAxes(state.axes))
        for entry in state.series:
            self.apply(entry.update)
            self.apply(ModifySeries(entry.update.series_id, visible=entry.visible))
        self.refresh()

    def export_settings(self):
        """Return versioned JSON preferences without measurement arrays."""
        return {
            "version": 1,
            "palette": self._palette,
            "colour_limits": self._colour_limits,
            "view": self.canvas.export_view(),
        }

    def import_settings(self, settings: Mapping):
        """Restore validated palette and renderer-specific view preferences."""
        if settings.get("version", 1) != 1:
            raise ValueError("Unsupported renderer settings version.")
        palette = settings.get("palette", "viridis")
        if self.palette_combo.findText(palette) < 0:
            raise ValueError("Unknown colour palette.")
        limits = settings.get("colour_limits")
        if limits is not None and (
            len(limits) != 2
            or not all(isfinite(float(value)) for value in limits)
            or limits[0] >= limits[1]
        ):
            raise ValueError("Invalid colour limits.")
        self.canvas.import_view(settings.get("view", {}))
        blockers = [
            QSignalBlocker(control)
            for control in (self.colour_min, self.colour_max, self.auto_colour)
        ]
        self.auto_colour.setChecked(limits is None)
        if limits is not None:
            self.colour_min.setValue(limits[0])
            self.colour_max.setValue(limits[1])
        del blockers
        self._set_colour_limits()
        self.palette_combo.setCurrentText(palette)
        self._schedule()

    @pyqtSlot()
    def refresh(self):
        """Paint the latest complete logical state, retaining the current view."""
        self._timer.stop()
        if self._closed or not self._dirty:
            return
        entries = []
        for name, entry in self._series.items():
            if entry.visible:
                update = self._surfaces[name].snapshot() if name in self._surfaces else entry.update
                entries.append(update)
        self.canvas.render(entries, self.descriptions()[0], self._palette, self._colour_limits)
        self._dirty = False

    @pyqtSlot()
    def reset_view(self):
        """Restore the renderer's default camera and automatic coordinate limits."""
        self.canvas.reset_view()
        self._schedule()

    def closeEvent(self, event):
        """Stop pending painting before the host releases owned graphics."""
        if not self._closed:
            self._closed = True
            self._timer.stop()
            self.canvas.close()
            self._series.clear()
            self._surfaces.clear()
        super().closeEvent(event)
