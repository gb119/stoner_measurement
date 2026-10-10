"""Polar projection, raw-state replay and native canvas operations."""

from dataclasses import replace

import numpy as np
import pytest
from qtpy.QtCore import QPointF

from stoner_measurement.core.plotting.contracts import (
    AngularUnit,
    ChannelMetadata,
    ClearPlot,
    CoordinateBinding,
    CoordinateDescriptor,
    CoordinateSystem,
    ModifySeries,
    PlotData,
    RemoveSeries,
    SeriesUpdate,
    UpdateMode,
)
from stoner_measurement.ui.plotting.polar import PolarDisplayFactory


def update(angles=(0, 90, 180, 270), radii=(1, 2, 3, 4), **kwargs):
    return SeriesUpdate(
        "response",
        PlotData(
            {"angle": angles, "radius": radii},
            {
                "angle": ChannelMetadata("Motor", "deg"),
                "radius": ChannelMetadata("Resistance", "ohm"),
            },
        ),
        CoordinateBinding("angle", "radius"),
        CoordinateDescriptor(CoordinateSystem.POLAR, AngularUnit.DEGREES),
        **kwargs,
    )


@pytest.fixture
def canvas(managed_qt_widget):
    return managed_qt_widget(PolarDisplayFactory().create(None))


def test_angle_first_cardinal_projection_and_raw_snapshot(canvas):
    source = update()
    canvas.apply(source)
    x, y = canvas._curves["response"].getData()
    np.testing.assert_allclose(x, [1, 0, -3, 0], atol=1e-14)
    np.testing.assert_allclose(y, [0, 2, 0, -4], atol=1e-14)
    state = canvas.export_state()
    assert state.series[0].update is source
    assert [axis.name for axis in state.axes] == ["angle", "radius"]
    assert canvas.plot.getViewBox().state["aspectLocked"] == 1
    assert canvas.angle_units.currentText() == "degrees"


def test_radians_clockwise_origin_signed_radii_and_nan_gap(canvas):
    source = replace(
        update(),
        data=PlotData({"angle": [0, np.pi / 2, np.nan], "radius": [2, -3, 1]}),
        coordinates=CoordinateDescriptor(
            CoordinateSystem.POLAR, angular_origin=np.pi / 2, clockwise=True
        ),
    )
    canvas.apply(source)
    x, y = canvas._curves["response"].getData()
    np.testing.assert_allclose(x[:2], [0, -3], atol=1e-14)
    np.testing.assert_allclose(y[:2], [2, 0], atol=1e-14)
    assert np.isnan(x[2]) and np.isnan(y[2])
    assert canvas.export_state().series[0].update.data.channels["radius"][1] == -3


def test_append_visibility_title_style_and_removal(canvas):
    canvas.apply(update([0], [1]))
    canvas.apply(update([90], [2], mode=UpdateMode.APPEND))
    canvas.apply(
        ModifySeries(
            "response",
            title="Measured",
            visible=False,
            style={"colour": "red", "line_style": "dash-dot", "point_style": "plus"},
        )
    )
    state = canvas.export_state().series[0]
    np.testing.assert_array_equal(state.update.data.channels["angle"], [0, 90])
    assert not state.visible and not canvas._curves["response"].isVisible()
    assert state.update.title == "Measured"
    canvas.apply(RemoveSeries("response"))
    assert not canvas.export_state().series
    canvas.apply(ClearPlot())


def test_uncertainty_endpoints_and_angular_arc(canvas):
    source = replace(
        update([90], [2]),
        data=PlotData(
            {"angle": [90], "radius": [2]}, uncertainties={"radius": [0.5], "angle": [10]}
        ),
    )
    canvas.apply(source)
    x, y = canvas._errors["response"].getData()
    np.testing.assert_allclose(x[:2], [0, 0], atol=1e-14)
    np.testing.assert_allclose(y[:2], [1.5, 2.5])
    np.testing.assert_allclose(np.hypot(x[3:-1], y[3:-1]), 2)
    assert source.data.uncertainties["angle"][0] == 10


@pytest.mark.parametrize(
    "style",
    [
        {"colour": "bad colour"},
        {"line_style": "wrong"},
        {"point_style": "wrong"},
        {"line_width": 0},
        {"point_size": np.inf},
    ],
)
def test_invalid_style_leaves_existing_state_unchanged(canvas, style):
    canvas.apply(update())
    before = canvas.export_state().series[0]
    with pytest.raises(ValueError):
        canvas.apply(update(style=style))
    assert canvas.export_state().series[0] == before


def test_settings_replay_pointer_and_idempotent_close(canvas, managed_qt_widget, qapp):
    source = update([90], [2])
    canvas.apply(source)
    canvas.angle_units.setCurrentText("radians")
    clone = managed_qt_widget(PolarDisplayFactory().create(None))
    clone.import_state(canvas.export_state())
    assert clone.export_settings() == {"version": 1, "angle_units": "radians", "auto_range": True}
    clone.resize(800, 600)
    clone.show()
    qapp.processEvents()
    scene_position = clone.plot.getViewBox().mapViewToScene(QPointF(0, 2))
    clone._pointer_moved(scene_position)
    assert "angle 90 degrees, radius 2" in clone.pointer.text()
    clone.close()
    clone.close()


def test_descriptor_change_rejected_for_append_and_other_series(canvas):
    canvas.apply(update())
    wrong = replace(
        update([0], [1], mode=UpdateMode.APPEND),
        coordinates=CoordinateDescriptor(
            CoordinateSystem.POLAR, AngularUnit.DEGREES, clockwise=True
        ),
    )
    with pytest.raises(ValueError, match="binding"):
        canvas.apply(wrong)
    with pytest.raises(ValueError, match="origin"):
        canvas.apply(replace(wrong, series_id="other", mode=UpdateMode.REPLACE))


def test_empty_and_all_missing_data_keep_a_finite_view(canvas):
    canvas.apply(update([], []))
    canvas.apply(update([np.nan], [np.nan], mode=UpdateMode.APPEND))
    assert np.all(np.isfinite(canvas.plot.getViewBox().viewRange()))
    assert np.isnan(canvas.export_state().series[0].update.data.channels["angle"][0])


def test_manual_view_survives_updates_and_reset_restores_auto_range(canvas):
    canvas.apply(update())
    canvas.plot.getViewBox().sigRangeChangedManually.emit([True, True])
    assert not canvas.auto_range.isChecked()
    canvas.plot.setRange(xRange=(-1, 1), yRange=(-1, 1), padding=0)
    before = canvas.plot.getViewBox().viewRange()
    canvas.apply(update([0], [10], mode=UpdateMode.APPEND))
    np.testing.assert_allclose(canvas.plot.getViewBox().viewRange(), before)
    settings = canvas.export_settings()
    assert settings["auto_range"] is False and "view_range" in settings
    canvas._reset_view()
    assert canvas.auto_range.isChecked()
    assert canvas.plot.getViewBox().viewRange()[0][1] > 10


@pytest.mark.parametrize(
    "settings",
    [
        {"version": 2},
        {"angle_units": "gradians"},
        {"auto_range": "yes"},
        {"view_range": [[2, 1], [0, 1]]},
    ],
)
def test_bad_saved_settings_do_not_change_angle_labels(canvas, settings):
    before = canvas.export_settings()
    with pytest.raises(ValueError):
        canvas.import_settings(settings)
    assert canvas.export_settings() == before


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
