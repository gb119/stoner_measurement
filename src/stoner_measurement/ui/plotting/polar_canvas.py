"""Native PyQtGraph polar rendering with immutable source-coordinate replay."""

from dataclasses import replace
from math import isfinite

import numpy as np
import pyqtgraph as pg
from qtpy.QtCore import QSignalBlocker, Qt
from qtpy.QtGui import QColor
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
    AngularUnit,
    AxisDescription,
    ChannelMetadata,
    ClearPlot,
    ConfigureAxes,
    ModifySeries,
    PlotData,
    PlotRequest,
    RemoveSeries,
    SeriesDescription,
    SeriesUpdate,
    UpdateMode,
)
from stoner_measurement.core.plotting.service import UnsupportedDisplayOperation
from stoner_measurement.core.plotting.state import DisplayState, SeriesState
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.theme import colour

_LINES = {
    "solid": Qt.PenStyle.SolidLine,
    "dash": Qt.PenStyle.DashLine,
    "dot": Qt.PenStyle.DotLine,
    "dash-dot": Qt.PenStyle.DashDotLine,
    "none": None,
}
_POINTS = {
    "none": None,
    "circle": "o",
    "square": "s",
    "triangle": "t",
    "diamond": "d",
    "plus": "+",
    "cross": "x",
}


def project(radius, angle, coordinates):
    """Project source values without wrapping or changing acquisition order."""
    factor = np.pi / 180 if coordinates.angular_unit == AngularUnit.DEGREES else 1
    theta = np.asarray(angle) * factor
    theta = coordinates.angular_origin * factor + (-theta if coordinates.clockwise else theta)
    radius = np.asarray(radius)
    return radius * np.cos(theta), radius * np.sin(theta)


def _convention(coordinates):
    factor = np.pi / 180 if coordinates.angular_unit == AngularUnit.DEGREES else 1
    return coordinates.angular_origin * factor, coordinates.clockwise


class PolarCanvasDisplay(QWidget):
    """Render signed radii against angles; retain raw samples for replay/export.

    Source descriptors determine angular units, zero direction and handedness.
    Angle-label units are a separate saved display preference, defaulting to
    degrees. Multiple series must share zero direction and handedness. Negative
    radii follow the usual reflected-point convention, retaining their sign in
    source data and the nearest-sample pointer readout.
    """

    changed = pyqtSignal()
    supported_styles = frozenset(
        {"colour", "line_style", "point_style", "line_width", "point_size"}
    )

    def __init__(self, parent, capabilities):
        super().__init__(parent)
        self.capabilities = capabilities
        self._series = {}
        self._curves = {}
        self._errors = {}
        self._grid = []
        self._legend_state = ()
        self._closed = False
        self._axes = {
            "angle": AxisDescription("angle", "x", ChannelMetadata("Angle", "deg")),
            "radius": AxisDescription("radius", "y", ChannelMetadata("Radius")),
        }
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Angle labels:", self))
        self.angle_units = QComboBox(self)
        self.angle_units.setObjectName("polar_angle_units")
        self.angle_units.addItems(["degrees", "radians"])
        self.angle_units.currentTextChanged.connect(lambda _text: self._refresh())
        controls.addWidget(self.angle_units)
        self.auto_range = QCheckBox("Auto range", self)
        self.auto_range.setChecked(True)
        self.auto_range.toggled.connect(lambda _checked: self._refresh())
        controls.addWidget(self.auto_range)
        reset = QPushButton("Reset view", self)
        reset.clicked.connect(self._reset_view)
        controls.addWidget(reset)
        controls.addStretch()
        layout.addLayout(controls)
        self.plot = pg.PlotWidget(self, background=colour("plot_background"))
        self.plot.setAspectLocked(True)
        self.plot.hideAxis("bottom")
        self.plot.hideAxis("left")
        self.plot.setMenuEnabled(False)
        self.plot.getViewBox().disableAutoRange()
        self.plot.getViewBox().sigRangeChangedManually.connect(self._manual_range)
        self.legend = self.plot.addLegend()
        layout.addWidget(self.plot)
        self.pointer = QLabel("Angle / radius", self)
        layout.addWidget(self.pointer)
        self.plot.scene().sigMouseMoved.connect(self._pointer_moved)
        self.widget = self
        self._refresh()

    def _manual_range(self, _axes):
        with QSignalBlocker(self.auto_range):
            self.auto_range.setChecked(False)

    def _reset_view(self):
        self.auto_range.setChecked(True)
        self._refresh()

    def validate(self, payload):
        """Reject incompatible axes, source conventions and styles before mutation."""
        reasons = self.capabilities.unsupported_reasons(PlotRequest(payload))
        if reasons:
            raise UnsupportedDisplayOperation(" ".join(reasons))
        if isinstance(payload, SeriesUpdate):
            if any(
                name != {"x": "angle", "y": "radius"}[slot] for slot, name in payload.axes.items()
            ):
                raise ValueError("Polar traces use only the radius and angle axes.")
            for identity, state in self._series.items():
                if identity != payload.series_id and _convention(
                    state.update.coordinates
                ) != _convention(payload.coordinates):
                    raise ValueError("Polar series must share angular origin and direction.")
            if payload.mode == UpdateMode.APPEND and payload.series_id in self._series:
                previous = self._series[payload.series_id].update
                if (
                    payload.binding != previous.binding
                    or payload.coordinates != previous.coordinates
                    or payload.data.metadata != previous.data.metadata
                    or set(payload.data.uncertainties) != set(previous.data.uncertainties)
                ):
                    raise ValueError("Polar append must preserve the source binding and units.")
            self._validate_style(payload.style)
        elif isinstance(payload, ModifySeries):
            if payload.series_id not in self._series:
                raise KeyError(payload.series_id)
            self._validate_style(payload.style)
        elif isinstance(payload, ConfigureAxes):
            for axis in payload.axes:
                if (
                    axis.name != {"x": "angle", "y": "radius"}.get(axis.slot)
                    or axis.scale != "linear"
                    or axis.limits != (None, None)
                ):
                    raise ValueError(
                        "Polar display supports linear radius/angle axes with automatic limits."
                    )

    @staticmethod
    def _validate_style(style):
        if "colour" in style and not QColor(style["colour"]).isValid():
            raise ValueError("Invalid polar trace colour.")
        if "line_style" in style and style["line_style"] not in _LINES:
            raise ValueError("Unknown polar line style.")
        if "point_style" in style and style["point_style"] not in _POINTS:
            raise ValueError("Unknown polar point style.")
        for key in ("line_width", "point_size"):
            if key in style and (not isfinite(float(style[key])) or float(style[key]) <= 0):
                raise ValueError(f"{key} must be finite and positive.")

    def apply(self, payload):
        """Complete one logical operation and render on the GUI thread."""
        self.validate(payload)
        if isinstance(payload, SeriesUpdate):
            previous = self._series.get(payload.series_id)
            if previous is not None:
                if payload.mode == UpdateMode.APPEND:
                    data = PlotData(
                        {
                            key: np.concatenate((previous.update.data.channels[key], value))
                            for key, value in payload.data.channels.items()
                        },
                        payload.data.metadata,
                        {
                            key: np.concatenate((previous.update.data.uncertainties[key], value))
                            for key, value in payload.data.uncertainties.items()
                        },
                    )
                    payload = replace(payload, data=data, mode=UpdateMode.REPLACE)
                payload = replace(
                    payload,
                    title=payload.title if payload.title is not None else previous.update.title,
                    style={**previous.update.style, **payload.style},
                )
            self._series[payload.series_id] = SeriesState(
                payload, previous.visible if previous else True
            )
            self._axes["angle"] = replace(
                self._axes["angle"], label=payload.data.metadata[payload.binding.x]
            )
            self._axes["radius"] = replace(
                self._axes["radius"], label=payload.data.metadata[payload.binding.y]
            )
        elif isinstance(payload, ModifySeries):
            state = self._series[payload.series_id]
            self._series[payload.series_id] = SeriesState(
                replace(
                    state.update,
                    title=payload.title if payload.title is not None else state.update.title,
                    style={**state.update.style, **payload.style},
                ),
                state.visible if payload.visible is None else payload.visible,
            )
        elif isinstance(payload, RemoveSeries):
            self._series.pop(payload.series_id, None)
        elif isinstance(payload, ClearPlot):
            self._series.clear()
        elif isinstance(payload, ConfigureAxes):
            self._axes.update({axis.name: axis for axis in payload.axes})
        self._refresh()
        self.changed.emit()

    def _refresh(self):
        """Keep graphics separate from source-coordinate series and uncertainties."""
        if self._closed:
            return
        for collection in (self._curves, self._errors):
            for identity in set(collection).difference(self._series):
                item = collection.pop(identity)
                self.plot.removeItem(item)
                item.deleteLater()
        extent = 0.0
        for index, (identity, state) in enumerate(self._series.items()):
            update = state.update
            radius = update.data.channels[update.binding.y]
            radial_error = update.data.uncertainties.get(update.binding.y, np.zeros_like(radius))
            finite = np.abs(radius) + radial_error
            if state.visible and np.any(np.isfinite(finite)):
                extent = max(extent, float(np.max(finite[np.isfinite(finite)])))
            self._draw_series(identity, state, index)
        legend_state = tuple(
            (identity, state.update.title or identity) for identity, state in self._series.items()
        )
        if legend_state != self._legend_state:
            self.legend.clear()
            for identity, title in legend_state:
                self.legend.addItem(self._curves[identity], title)
            self._legend_state = legend_state
        extent = extent if extent > 0 else 1.0
        self._draw_grid(extent)
        if self.auto_range.isChecked():
            self.plot.setRange(
                xRange=(-extent * 1.22, extent * 1.22),
                yRange=(-extent * 1.22, extent * 1.22),
                padding=0,
            )
        label = self._axes["radius"].label
        self.plot.setTitle(f"{label.name}{' (' + label.unit + ')' if label.unit else ''}")

    def _draw_series(self, identity, state, index):
        update, style = state.update, state.update.style
        tint = style.get("colour", pg.intColor(index).name())
        line = _LINES[style.get("line_style", "solid" if update.presentation == "line" else "none")]
        pen = (
            pg.mkPen(tint, width=float(style.get("line_width", 1.5)), style=line)
            if line is not None
            else None
        )
        symbol = _POINTS[
            style.get("point_style", "circle" if update.presentation == "points" else "none")
        ]
        if identity not in self._curves:
            self._curves[identity] = pg.PlotDataItem()
            self.plot.addItem(self._curves[identity])
        curve = self._curves[identity]
        x, y = project(
            update.data.channels[update.binding.y],
            update.data.channels[update.binding.x],
            update.coordinates,
        )
        curve.setData(
            x,
            y,
            pen=pen,
            symbol=symbol,
            symbolSize=float(style.get("point_size", 6)),
            symbolPen=tint,
            symbolBrush=tint,
            connect="finite",
        )
        curve.setVisible(state.visible)
        errors = self._error_path(update)
        if errors is not None:
            if identity not in self._errors:
                self._errors[identity] = pg.PlotCurveItem()
                self.plot.addItem(self._errors[identity])
            item = self._errors[identity]
            item.setData(*errors, pen=pg.mkPen(tint), connect="finite")
            item.setVisible(state.visible)
        elif identity in self._errors:
            self._errors[identity].hide()

    @staticmethod
    def _error_path(update):
        if not update.data.uncertainties:
            return None
        r = update.data.channels[update.binding.y]
        a = update.data.channels[update.binding.x]
        parts = []
        if update.binding.y in update.data.uncertainties:
            error = update.data.uncertainties[update.binding.y]
            radii = np.column_stack((r - error, r + error, np.full(r.shape, np.nan))).ravel()
            angles = np.repeat(a, 3)
            parts.append(project(radii, angles, update.coordinates))
        if update.binding.x in update.data.uncertainties:
            error = update.data.uncertainties[update.binding.x]
            angles = a[:, None] + error[:, None] * np.linspace(-1, 1, 21)
            angles = np.column_stack((angles, np.full(r.shape, np.nan))).ravel()
            parts.append(project(np.repeat(r, 22), angles, update.coordinates))
        if not parts:
            return None
        return tuple(np.concatenate([part[index] for part in parts]) for index in (0, 1))

    def _draw_grid(self, extent):
        coords = next((state.update.coordinates for state in self._series.values()), None)
        origin, clockwise = _convention(coords) if coords is not None else (np.pi / 2, True)
        pen = pg.mkPen(colour("plot_foreground"), width=0.5)
        theta = np.linspace(0, 2 * np.pi, 181)
        for index, radial in enumerate(np.linspace(0, extent, 5)[1:]):
            curve = self._grid_item(2 * index, pg.PlotCurveItem)
            curve.setData(radial * np.cos(theta), radial * np.sin(theta), pen=pen)
            text = self._grid_item(
                2 * index + 1, lambda: pg.TextItem(color=colour("plot_foreground"), anchor=(0, 1))
            )
            text.setText(f"{radial:.3g}")
            text.setPos(radial * np.cos(origin), radial * np.sin(origin))
        for index, degrees in enumerate(range(0, 360, 45)):
            angle = origin + np.deg2rad(-degrees if clockwise else degrees)
            x, y = np.cos(angle), np.sin(angle)
            curve = self._grid_item(8 + 2 * index, pg.PlotCurveItem)
            curve.setData([0, extent * x], [0, extent * y], pen=pen)
            displayed = (
                degrees - 360
                if coords is not None and coords.wrapping == "signed" and degrees >= 180
                else degrees
            )
            label = (
                f"{displayed} deg"
                if self.angle_units.currentText() == "degrees"
                else f"{np.deg2rad(displayed):.3g} rad"
            )
            text = self._grid_item(
                9 + 2 * index,
                lambda: pg.TextItem(color=colour("plot_foreground"), anchor=(0.5, 0.5)),
            )
            text.setText(label)
            text.setPos(extent * 1.1 * x, extent * 1.1 * y)

    def _grid_item(self, index, factory):
        if index == len(self._grid):
            item = factory()
            item.setZValue(-10)
            self.plot.addItem(item)
            self._grid.append(item)
        return self._grid[index]

    def _pointer_moved(self, position):
        if not self.plot.sceneBoundingRect().contains(position):
            return
        nearest = None
        best_distance = float("inf")
        for state in self._series.values():
            if not state.visible:
                continue
            update = state.update
            r, a = update.data.channels[update.binding.y], update.data.channels[update.binding.x]
            x, y = project(r, a, update.coordinates)
            point = self.plot.getViewBox().mapSceneToView(position)
            distances = (x - point.x()) ** 2 + (y - point.y()) ** 2
            valid = np.flatnonzero(np.isfinite(distances))
            if len(valid):
                index = valid[np.argmin(distances[valid])]
                if distances[index] < best_distance:
                    best_distance = float(distances[index])
                    nearest = update, index
        if nearest is not None:
            update, index = nearest
            radius = update.data.channels[update.binding.y][index]
            angle = update.data.channels[update.binding.x][index]
            self.pointer.setText(
                f"{update.title or update.series_id}: angle {angle:.6g} {update.coordinates.angular_unit}, radius {radius:.6g} (nearest sample)"
            )

    def descriptions(self):
        return tuple(self._axes.values()), tuple(
            SeriesDescription(
                identity,
                state.update.title or identity,
                state.update.binding,
                state.update.coordinates,
                state.visible,
            )
            for identity, state in self._series.items()
        )

    def export_settings(self):
        settings = {
            "version": 1,
            "angle_units": self.angle_units.currentText(),
            "auto_range": self.auto_range.isChecked(),
        }
        if not self.auto_range.isChecked():
            settings["view_range"] = self.plot.getViewBox().viewRange()
        return settings

    def import_settings(self, settings):
        if settings.get("version", 1) != 1 or settings.get("angle_units", "degrees") not in (
            "degrees",
            "radians",
        ):
            raise ValueError("Invalid polar display settings.")
        if not isinstance(settings.get("auto_range", True), bool):
            raise ValueError("Auto range must be boolean.")
        ranges = settings.get("view_range")
        if ranges is not None:
            ranges = np.asarray(ranges, dtype=float)
            if (
                ranges.shape != (2, 2)
                or not np.all(np.isfinite(ranges))
                or np.any(ranges[:, 0] >= ranges[:, 1])
            ):
                raise ValueError("Invalid polar view ranges.")
        with QSignalBlocker(self.angle_units):
            self.angle_units.setCurrentText(settings.get("angle_units", "degrees"))
        with QSignalBlocker(self.auto_range):
            self.auto_range.setChecked(settings.get("auto_range", True))
        self._refresh()
        if ranges is not None and not self.auto_range.isChecked():
            self.plot.setRange(xRange=ranges[0], yRange=ranges[1], padding=0)

    def export_state(self):
        return DisplayState(
            tuple(self._axes.values()),
            tuple(self._series.values()),
            renderer_settings=self.export_settings(),
        )

    def import_state(self, state):
        if state.markers:
            raise UnsupportedDisplayOperation("Polar display does not support markers.")
        self.apply(ConfigureAxes(state.axes))
        self.import_settings(state.renderer_settings)
        for entry in state.series:
            self.apply(replace(entry.update, mode=UpdateMode.REPLACE))
            self.apply(ModifySeries(entry.update.series_id, visible=entry.visible))

    def close(self):
        return super().close()

    def closeEvent(self, event):
        if not self._closed:
            self._closed = True
            self.plot.scene().sigMouseMoved.disconnect(self._pointer_moved)
            self.plot.getViewBox().sigRangeChangedManually.disconnect(self._manual_range)
            self.legend.clear()
            self.plot.clear()
            self.plot.close()
            self._curves.clear()
            self._errors.clear()
            self._grid.clear()
            self._series.clear()
        super().closeEvent(event)
