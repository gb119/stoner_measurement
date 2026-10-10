"""Native PyQtGraph surface graphics; OpenGL is loaded only for XYZ views."""

from math import isfinite

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from qtpy.QtCore import QRectF  # type: ignore[attr-defined]
from qtpy.QtGui import QColor, QPainter, QPicture, QVector3D
from qtpy.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from stoner_measurement.qt_compat import pyqtSlot


def colour_map(name):
    """Return a bundled palette without optional Matplotlib dependencies."""
    if name == "grey":
        return pg.ColorMap([0, 1], [(0, 0, 0), (255, 255, 255)])
    return pg.colormap.get(name)


def colour_values(update):
    """Bind the explicit value channel, or height for a plain XYZ plot."""
    key = update.binding.value or update.binding.z
    return update.data.channels[key], update.data.metadata[key]


def colour_scale(values, palette, limits=None):
    """Map finite source values to RGBA; omit unknown values when painting."""
    finite = values[np.isfinite(values)]
    lower, upper = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    if lower == upper:
        padding = max(abs(lower) * 0.01, 0.5)
        lower, upper = lower - padding, upper + padding
    if limits is not None:
        lower, upper = limits
    positions = (np.nan_to_num(values, nan=lower) - lower) / (upper - lower)
    return palette.map(np.clip(positions, 0, 1), mode="float"), (lower, upper)


def cell_edges(values):
    """Infer cell edges from sorted, possibly nonuniform, source centres."""
    centres = np.unique(values)
    if len(centres) == 1:
        return centres, np.array([centres[0] - 0.5, centres[0] + 0.5])
    midpoints = centres[:-1] / 2 + centres[1:] / 2
    return centres, np.r_[
        centres[0] - (midpoints[0] - centres[0]),
        midpoints,
        centres[-1] + (centres[-1] - midpoints[-1]),
    ]


def surface_triangles(update):
    """Triangulate complete adjacent rectilinear cells, leaving holes open.

    Memory and iteration scale with acquired cells, including sparse scans;
    no dense Cartesian product or scattered-data interpolation is created.
    """
    xs = update.data.channels[update.binding.x]
    ys = update.data.channels[update.binding.y]
    zs = update.data.channels[update.binding.z]
    x_grid, y_grid = np.unique(xs), np.unique(ys)
    next_x = dict(zip(x_grid[:-1], x_grid[1:], strict=True))
    next_y = dict(zip(y_grid[:-1], y_grid[1:], strict=True))
    cells = {(float(x), float(y)): i for i, (x, y) in enumerate(zip(xs, ys, strict=True))}
    values, _metadata = colour_values(update)
    triangles = []
    for (x, y), index in cells.items():
        if x not in next_x or y not in next_y:
            continue
        corners = [
            index,
            cells.get((next_x[x], y)),
            cells.get((next_x[x], next_y[y])),
            cells.get((x, next_y[y])),
        ]
        if any(corner is None for corner in corners):
            continue
        if not np.all(np.isfinite(zs[corners])) or not np.all(np.isfinite(values[corners])):
            continue
        triangles.extend(
            [(corners[0], corners[1], corners[2]), (corners[0], corners[2], corners[3])]
        )
    return np.asarray(triangles, dtype=np.uint32).reshape(-1, 3)


def label_text(metadata):
    """Format a source quantity and unit for labels and colour scales."""
    return metadata.name + (f" ({metadata.unit})" if metadata.unit else "")


class IntensityCellsItem(pg.GraphicsObject):
    """Draw only acquired finite cells, using an owned Qt picture cache."""

    def __init__(self, update, colours):
        super().__init__()
        xs = update.data.channels[update.binding.x]
        ys = update.data.channels[update.binding.y]
        values, _metadata = colour_values(update)
        x_grid, x_edges = cell_edges(xs)
        y_grid, y_edges = cell_edges(ys)
        x_indices = np.searchsorted(x_grid, xs)
        y_indices = np.searchsorted(y_grid, ys)
        self.picture = QPicture()
        self.source = update
        self.x_grid, self.y_grid = x_grid, y_grid
        self.x_edges, self.y_edges = x_edges, y_edges
        self.values = {
            (float(x), float(y)): float(value) for x, y, value in zip(xs, ys, values, strict=True)
        }
        painter = QPainter(self.picture)
        painter.setPen(pg.mkPen(None))
        for index, (column, row) in enumerate(zip(x_indices, y_indices, strict=True)):
            if not np.isfinite(values[index]):
                continue
            painter.setBrush(QColor.fromRgbF(*map(float, colours[index])))
            painter.drawRect(
                QRectF(
                    x_edges[column],
                    y_edges[row],
                    x_edges[column + 1] - x_edges[column],
                    y_edges[row + 1] - y_edges[row],
                )
            )
        painter.end()
        self._bounds = QRectF(
            x_edges[0], y_edges[0], x_edges[-1] - x_edges[0], y_edges[-1] - y_edges[0]
        )

    def paint(self, painter, option, widget=None):
        """Replay the cache in source coordinates."""
        painter.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        """Expose source-coordinate extent for pan, zoom and automatic limits."""
        return self._bounds


class IntensityCanvas(QWidget):
    """XY intensity graphics with independent colour bars for each series."""

    def __init__(self, parent):
        super().__init__(parent)
        self._closed = False
        self.graphics = pg.GraphicsLayoutWidget(self)
        self.plot = self.graphics.addPlot(row=0, col=0)
        self.plot.setMenuEnabled(True)
        self.bars = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.graphics)
        self.readout = QLabel("Move over an acquired cell to read source coordinates.", self)
        layout.addWidget(self.readout)
        self.graphics.scene().sigMouseMoved.connect(self._read_position)

    @pyqtSlot(object)
    def _read_position(self, position):
        if self._closed:
            return
        point = self.plot.vb.mapSceneToView(position)
        for item in reversed(self.plot.items):
            if not isinstance(item, IntensityCellsItem):
                continue
            column = np.searchsorted(item.x_edges, point.x(), side="right") - 1
            row = np.searchsorted(item.y_edges, point.y(), side="right") - 1
            if 0 <= column < len(item.x_grid) and 0 <= row < len(item.y_grid):
                x, y = float(item.x_grid[column]), float(item.y_grid[row])
                value = item.values.get((x, y))
                if value is not None and isfinite(value):
                    update = item.source
                    value_key = update.binding.value
                    self.readout.setText(
                        f"{update.title or update.series_id}: "
                        + "; ".join(
                            f"{label_text(update.data.metadata[key])} = {number:.6g}"
                            for key, number in (
                                (update.binding.x, x),
                                (update.binding.y, y),
                                (value_key, value),
                            )
                        )
                    )
                    return
        self.readout.setText("No acquired value at this position.")

    def render(self, updates, axes, palette_name, colour_limits=None):
        """Paint exact sparse cells without changing a manually zoomed view."""
        self.plot.clear()
        for bar in self.bars:
            self.graphics.removeItem(bar)
        self.bars.clear()
        palette = colour_map(palette_name)
        for update in updates:
            if not len(update.data.channels[update.binding.x]):
                continue
            values, metadata = colour_values(update)
            colours, limits = colour_scale(values, palette, colour_limits)
            self.plot.addItem(IntensityCellsItem(update, colours))
            bar = pg.ColorBarItem(
                values=limits,
                colorMap=palette,
                interactive=False,
                label=f"{update.title or update.series_id}: {label_text(metadata)}",
            )
            self.graphics.addItem(bar, row=0, col=len(self.bars) + 1)
            self.bars.append(bar)
        for axis in axes:
            side = "bottom" if axis.slot == "x" else "left"
            self.plot.setLabel(side, text=axis.label.name, units=axis.label.unit or None)
            self.plot.showAxis(side, axis.visible)
            self.plot.getAxis(side).setGrid(128 if axis.grid else False)
            if any(value is not None for value in axis.limits):
                index = 0 if axis.slot == "x" else 1
                limits = self.plot.vb.viewRange()[index]
                limits = tuple(
                    old if new is None else new
                    for old, new in zip(limits, axis.limits, strict=True)
                )
                self.plot.vb.setRange(**{"xRange" if index == 0 else "yRange": limits}, padding=0)

    def reset_view(self):
        """Restore automatic source-coordinate bounds."""
        self.plot.enableAutoRange()

    def export_view(self):
        """Persist pan/zoom independently of measurement data."""
        return {
            "ranges": self.plot.vb.viewRange(),
            "auto": [bool(value) for value in self.plot.vb.autoRangeEnabled()],
        }

    def import_view(self, settings):
        """Validate and restore source-coordinate pan/zoom."""
        if not settings:
            return
        ranges = np.asarray(settings.get("ranges"), dtype=float)
        auto = settings.get("auto", [True, True])
        if (
            ranges.shape != (2, 2)
            or not np.all(np.isfinite(ranges))
            or np.any(ranges[:, 0] >= ranges[:, 1])
        ):
            raise ValueError("Invalid intensity view ranges.")
        if len(auto) != 2 or any(not isinstance(value, bool) for value in auto):
            raise ValueError("Invalid intensity automatic bounds.")
        self.plot.setRange(xRange=ranges[0], yRange=ranges[1], padding=0)
        for axis, enabled in enumerate(auto):
            self.plot.enableAutoRange(axis=axis, enable=enabled)

    def closeEvent(self, event):
        """Close the owned PyQtGraph scene before Qt deletes its parent."""
        if not self._closed:
            self._closed = True
            self.graphics.close()
        super().closeEvent(event)


class Cartesian3DCanvas(QWidget):
    """Native OpenGL view with normalized geometry and physical tick labels."""

    def __init__(self, parent):
        super().__init__(parent)
        self._closed = False
        import pyqtgraph.opengl as gl  # type: ignore[import-untyped]

        self.gl = gl
        self.view = gl.GLViewWidget(self)
        self.view.setCameraPosition(distance=5, elevation=25, azimuth=-45)
        self.scales = pg.GraphicsLayoutWidget(self)
        self.scales.setFixedWidth(160)
        self._bounds = np.array([[-0.5, 0.5]] * 3)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.scales)
        self.setToolTip(
            "Drag to rotate; Ctrl-drag to pan; wheel to zoom. Reset view restores the camera."
        )

    def _positions(self, points):
        return (points - self._bounds[:, 0]) / np.diff(self._bounds, axis=1).ravel() * 2 - 1

    def render(self, updates, axes, palette_name, colour_limits=None):
        """Build native mesh/point items without interpolating missing cells."""
        self.view.clear()
        self.scales.clear()
        points = [
            np.column_stack(
                [update.data.channels[getattr(update.binding, slot)] for slot in ("x", "y", "z")]
            )
            for update in updates
        ]
        for index in range(3):
            finite = (
                np.concatenate([p[:, index][np.isfinite(p[:, index])] for p in points])
                if points
                else np.array([])
            )
            lower, upper = (
                (float(finite.min()), float(finite.max())) if finite.size else (-0.5, 0.5)
            )
            if lower == upper:
                padding = max(abs(lower) * 0.01, 0.5)
                lower, upper = lower - padding, upper + padding
            axis = next((axis for axis in axes if axis.slot == ("x", "y", "z")[index]), None)
            if axis:
                lower, upper = (
                    old if new is None else new
                    for old, new in zip((lower, upper), axis.limits, strict=True)
                )
            if lower >= upper:
                upper = lower + max(abs(lower) * 0.01, 1)
            self._bounds[index] = lower, upper
        self._draw_axes(axes)
        palette = colour_map(palette_name)
        for index, (update, source) in enumerate(zip(updates, points, strict=True)):
            positions = self._positions(source)
            values, metadata = colour_values(update)
            colours, limits = colour_scale(values, palette, colour_limits)
            finite = np.all(np.isfinite(positions), axis=1) & np.isfinite(values)
            if "colour" in update.style:
                colours[:] = pg.mkColor(update.style["colour"]).getRgbF()
            if update.presentation.value == "surface":
                faces = surface_triangles(update)
                if len(faces):
                    mesh = self.gl.GLMeshItem(
                        vertexes=positions.astype(np.float32),
                        faces=faces,
                        vertexColors=colours.astype(np.float32),
                        smooth=False,
                        shader="balloon",
                        drawEdges=False,
                    )
                    self.view.addItem(mesh)
            if update.presentation.value == "line":
                # Independent segments prevent bridging NaN breaks.
                valid = finite[:-1] & finite[1:]
                segments = np.stack((positions[:-1][valid], positions[1:][valid]), axis=1).reshape(
                    -1, 3
                )
                if len(segments):
                    self.view.addItem(
                        self.gl.GLLinePlotItem(
                            pos=segments,
                            mode="lines",
                            color=tuple(colours[finite][0]),
                            width=float(update.style.get("line_width", 1)),
                        )
                    )
            elif np.any(finite):
                self.view.addItem(
                    self.gl.GLScatterPlotItem(
                        pos=positions[finite],
                        color=colours[finite],
                        size=float(update.style.get("point_size", 5)),
                        pxMode=True,
                    )
                )
            if "colour" not in update.style:
                self.scales.addItem(
                    pg.ColorBarItem(
                        values=limits,
                        colorMap=palette,
                        interactive=False,
                        label=f"{update.title or update.series_id}: {label_text(metadata)}",
                    ),
                    row=index,
                    col=0,
                )

    def _draw_axes(self, axes):
        for index, slot in enumerate(("x", "y", "z")):
            axis = next((axis for axis in axes if axis.slot == slot), None)
            if axis and not axis.visible:
                continue
            start, end = np.full(3, -1.0), np.full(3, -1.0)
            end[index] = 1
            self.view.addItem(
                self.gl.GLLinePlotItem(pos=np.array([start, end]), color=(0.8, 0.8, 0.8, 1))
            )
            for fraction in (0, 0.25, 0.5, 0.75, 1):
                position = start.copy()
                position[index] = fraction * 2 - 1
                value = self._bounds[index, 0] + fraction * np.diff(self._bounds[index])[0]
                self.view.addItem(
                    self.gl.GLTextItem(pos=position, text=f"{value:.4g}", color="white")
                )
            label = end.copy()
            label[index] = 1.3
            self.view.addItem(
                self.gl.GLTextItem(
                    pos=label, text=label_text(axis.label) if axis else slot, color="white"
                )
            )
            if axis and axis.grid:
                other = (index + 1) % 3
                for fraction in (0, 0.25, 0.5, 0.75, 1):
                    a, b = start.copy(), start.copy()
                    a[index] = b[index] = fraction * 2 - 1
                    b[other] = 1
                    self.view.addItem(
                        self.gl.GLLinePlotItem(pos=np.array([a, b]), color=(0.3, 0.3, 0.3, 1))
                    )

    def reset_view(self):
        """Restore the camera without modifying source coordinates."""
        self.view.setCameraPosition(pos=QVector3D(0, 0, 0), distance=5, elevation=25, azimuth=-45)

    def export_view(self):
        """Capture the native camera as finite JSON values."""
        options = self.view.opts
        centre = options["center"]
        return {
            "centre": [centre.x(), centre.y(), centre.z()],
            **{key: float(options[key]) for key in ("distance", "elevation", "azimuth")},
        }

    def import_view(self, settings):
        """Validate camera preferences before changing the native view."""
        if not settings:
            return
        centre = settings.get("centre", [0, 0, 0])
        camera = {
            key: float(settings.get(key, self.view.opts[key]))
            for key in ("distance", "elevation", "azimuth")
        }
        if len(centre) != 3 or not all(isfinite(float(value)) for value in centre):
            raise ValueError("Invalid camera centre.")
        if not all(isfinite(value) for value in camera.values()) or camera["distance"] <= 0:
            raise ValueError("Invalid camera parameters.")
        self.view.setCameraPosition(pos=QVector3D(*map(float, centre)), **camera)

    def closeEvent(self, event):
        """Release owned GL items and the colour-scale scene."""
        if not self._closed:
            self._closed = True
            self.view.clear()
            self.view.close()
            self.scales.close()
        super().closeEvent(event)
