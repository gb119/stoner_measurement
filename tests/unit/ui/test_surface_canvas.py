"""Actual native display adapters retain cells, replay and owned lifetimes."""

import json
from dataclasses import replace

import numpy as np
import pyqtgraph as pg
import pytest
from qtpy.QtGui import QImage, QPainter
from qtpy.QtWidgets import QWidget

from stoner_measurement.core.plotting.contracts import (
    AxisDescription,
    ClearPlot,
    ConfigureAxes,
    CoordinateBinding,
    ModifySeries,
    PlotData,
    Presentation,
    RemoveSeries,
    SeriesUpdate,
    SurfaceBinding,
    UpdateMode,
)
from stoner_measurement.ui.plotting.surface_displays import (
    Cartesian3DDisplayFactory,
    IntensityDisplayFactory,
)
from stoner_measurement.ui.plotting.surface_graphics import (
    IntensityCellsItem,
    cell_edges,
    surface_triangles,
)


@pytest.fixture(params=[Cartesian3DDisplayFactory, IntensityDisplayFactory])
def display(request, managed_qt_widget):
    parent = managed_qt_widget(QWidget())
    adapter = request.param().create(parent)
    managed_qt_widget(adapter.widget)
    yield adapter
    adapter.close()


def update(display, *, xs=(0, 2), ys=(1, 1), zs=(10, 20), kind="slice", **surface):
    binding = (
        CoordinateBinding("x", "y", "z")
        if display.three_dimensional
        else CoordinateBinding("x", "y", value="z")
    )
    return SeriesUpdate(
        "sample",
        PlotData({"x": xs, "y": ys, "z": zs}),
        binding,
        presentation=Presentation.SURFACE if display.three_dimensional else Presentation.INTENSITY,
        surface=SurfaceBinding(
            "sample", kind=kind, slice_id=str(ys[0]) if kind == "slice" else None, **surface
        ),
    )


def test_native_display_accumulates_replays_and_renders_source_cells(display, managed_qt_widget):
    display.import_settings({"palette": "plasma", "colour_limits": [0, 100]})
    display.apply(update(display))
    display.apply(update(display, ys=(3, 3), zs=(30, 40)))
    display.refresh()
    state = display.export_state()
    np.testing.assert_array_equal(state.series[0].update.data.channels["z"], [10, 20, 30, 40])
    assert state.series[0].update.surface.slices == (("1", 1.0), ("3", 3.0))
    assert {axis.slot for axis in display.descriptions()[0]} == (
        {"x", "y", "z"} if display.three_dimensional else {"x", "y"}
    )
    factory = Cartesian3DDisplayFactory if display.three_dimensional else IntensityDisplayFactory
    other = factory().create(display.parentWidget())
    managed_qt_widget(other)
    other.import_state(state)
    assert other.export_settings()["palette"] == "plasma"
    assert other.export_settings()["colour_limits"] == (0, 100)
    np.testing.assert_array_equal(
        other.export_state().series[0].update.data.channels["z"], [10, 20, 30, 40]
    )
    if display.three_dimensional:
        meshes = [
            item for item in other.canvas.view.items if isinstance(item, other.canvas.gl.GLMeshItem)
        ]
        assert len(meshes) == 1
        assert len(meshes[0].opts["meshdata"].faces()) == 2
    else:
        assert len(other.canvas.plot.items) == 1
        assert len(other.canvas.bars) == 1


def test_duplicate_and_wrong_grid_are_atomic_and_explicit_reset_works(display):
    display.apply(update(display))
    with pytest.raises(ValueError, match="Duplicate"):
        display.apply(update(display, zs=(90, 91)))
    with pytest.raises(ValueError, match="X grid"):
        display.apply(update(display, xs=(0, 3), ys=(2, 2)))
    np.testing.assert_array_equal(
        display.export_state().series[0].update.data.channels["z"], [10, 20]
    )
    display.apply(update(display, zs=(90, 91), duplicates="replace"))
    display.apply(update(display, ys=(2, 2), acquisition_id="second", reset_on_change=True))
    assert len(display.export_state().series[0].update.data.channels["z"]) == 2


def test_visibility_title_remove_clear_and_pending_close(display, qtbot):
    display.apply(update(display))
    with qtbot.waitSignal(display.changed):
        display.apply(ModifySeries("sample", title="Measured", visible=False))
    assert display.descriptions()[1][0].title == "Measured"
    assert not display.export_state().series[0].visible
    display.refresh()
    display.apply(RemoveSeries("sample"))
    assert display.export_state().series == ()
    display.apply(update(display))
    display.apply(ClearPlot())
    assert display.export_state().series == ()
    display.apply(update(display))
    display.close()
    display.close()
    display.refresh()
    with pytest.raises(ValueError, match="closed"):
        display.apply(update(display))


def test_settings_preserve_native_camera_or_source_zoom_on_updates(display):
    settings = {
        "version": 1,
        "palette": "plasma",
        "view": (
            {"distance": 7, "azimuth": 80, "elevation": 15, "centre": [0.1, 0.2, 0.3]}
            if display.three_dimensional
            else {"ranges": [[-5, 5], [-4, 4]], "auto": [False, False]}
        ),
    }
    display.import_settings(settings)
    display.apply(update(display))
    display.refresh()
    exported = display.export_settings()
    assert json.loads(json.dumps(exported))["palette"] == "plasma"
    if display.three_dimensional:
        assert exported["view"]["azimuth"] == 80
        assert exported["view"]["distance"] == 7
    else:
        np.testing.assert_allclose(exported["view"]["ranges"], settings["view"]["ranges"])
    with pytest.raises(ValueError):
        display.import_settings({"version": 2})
    with pytest.raises(ValueError):
        display.import_settings(
            {
                "view": {"distance": -1}
                if display.three_dimensional
                else {"ranges": [[2, 1], [0, 1]]}
            }
        )


def test_axes_are_fixed_linear_slots_and_validation_does_not_mutate(display):
    display.apply(ConfigureAxes((AxisDescription("field", "x", limits=(-2, 2)),)))
    before = display.export_state().axes
    with pytest.raises(ValueError, match="one axis"):
        display.apply(ConfigureAxes((AxisDescription("a", "y"), AxisDescription("b", "y"))))
    assert display.export_state().axes == before


def test_sparse_surface_mesh_leaves_missing_and_nan_cells_open():
    request = SeriesUpdate(
        "grid",
        PlotData({"x": [0, 1, 0, 1, 2], "y": [0, 0, 1, 1, 1], "z": [1, 2, 3, 4, 5]}),
        CoordinateBinding("x", "y", "z"),
        presentation=Presentation.SURFACE,
        surface=SurfaceBinding("grid"),
    )
    assert surface_triangles(request).shape == (2, 3)
    broken = replace(
        request,
        data=PlotData({"x": [0, 1, 0, 1, 2], "y": [0, 0, 1, 1, 1], "z": [1, 2, np.nan, 4, 5]}),
    )
    assert surface_triangles(broken).shape == (0, 3)
    centres, edges = cell_edges([0, 2, 5])
    np.testing.assert_array_equal(centres, [0, 2, 5])
    np.testing.assert_array_equal(edges, [-1, 1, 3.5, 6.5])


def test_unstructured_xyz_append_and_nan_line_break(display):
    if not display.three_dimensional:
        return
    request = SeriesUpdate(
        "line",
        PlotData({"x": [0, 1, 2], "y": [1, 1, 1], "z": [0, np.nan, 2]}),
        CoordinateBinding("x", "y", "z"),
        presentation=Presentation.LINE,
    )
    display.apply(request)
    display.apply(
        replace(request, data=PlotData({"x": [3], "y": [1], "z": [3]}), mode=UpdateMode.APPEND)
    )
    display.refresh()
    assert len(display.export_state().series[0].update.data.channels["z"]) == 4
    segments = [
        item
        for item in display.canvas.view.items
        if isinstance(item, display.canvas.gl.GLLinePlotItem) and item.mode == "lines"
    ]
    assert len(segments) == 1 and len(segments[0].pos) == 2


def test_point_stream_coalesces_graphics_and_never_snapshots_per_point(display, monkeypatch, qtbot):
    frames = []
    monkeypatch.setattr(display.canvas, "render", lambda *args: frames.append(args))
    display.apply(update(display, xs=(0,), ys=(1,), zs=(0,), kind="cells"))
    grid = display._surfaces["sample"]
    snapshot = grid.snapshot

    def unexpected_snapshot():
        raise AssertionError("An incoming point must not snapshot the full surface.")

    monkeypatch.setattr(grid, "snapshot", unexpected_snapshot)
    for x in range(1, 1001):
        display.apply(update(display, xs=(x,), ys=(1,), zs=(x,), kind="cells"))
    assert frames == []
    monkeypatch.setattr(grid, "snapshot", snapshot)
    qtbot.waitUntil(lambda: len(frames) == 1)
    assert len(frames[0][0][0].data.channels["z"]) == 1001


def test_fixed_colour_limits_are_saved_without_changing_source_values(display):
    display.import_settings({"colour_limits": [0, 100]})
    display.apply(update(display))
    display.refresh()
    assert display.export_settings()["colour_limits"] == (0, 100)
    np.testing.assert_array_equal(
        display.export_state().series[0].update.data.channels["z"], [10, 20]
    )
    display.auto_colour.setChecked(True)
    assert display.export_settings()["colour_limits"] is None
    with pytest.raises(ValueError, match="colour limits"):
        display.import_settings({"colour_limits": [10, 5]})


def test_intensity_paint_and_readout_preserve_gaps_and_nan(display, qtbot):
    if display.three_dimensional:
        return
    display.parentWidget().show()
    display.resize(800, 600)
    display.show()
    qtbot.waitUntil(lambda: display.canvas.plot.vb.width() > 100)
    request = update(display, xs=(0, 0, 2), ys=(0, 2, 2), zs=(0, np.nan, 10), kind="cells")
    display.apply(request)
    display.refresh()
    item = next(item for item in display.canvas.plot.items if isinstance(item, IntensityCellsItem))
    image = QImage(200, 200, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.translate(50, 50)
    painter.scale(50, 50)
    item.paint(painter, None)
    painter.end()
    assert image.pixelColor(50, 50).alpha() == 255  # A measured zero is acquired.
    assert image.pixelColor(150, 50).alpha() == 0  # Missing cell.
    assert image.pixelColor(50, 150).alpha() == 0  # Unknown measurement.
    display.canvas._read_position(display.canvas.plot.vb.mapViewToScene(pg.Point(2, 2)))
    assert "z = 10" in display.canvas.readout.text()
    display.canvas._read_position(display.canvas.plot.vb.mapViewToScene(pg.Point(2, 0)))
    assert display.canvas.readout.text() == "No acquired value at this position."
