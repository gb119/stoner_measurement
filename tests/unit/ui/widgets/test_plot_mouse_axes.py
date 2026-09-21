"""Mouse selection and marker anchoring across independent plot axes."""

import pytest
from qtpy.QtCore import QEvent, QPoint, QPointF, Qt
from qtpy.QtGui import QMouseEvent, QWheelEvent
from qtpy.QtWidgets import QApplication

from stoner_measurement.ui.plot_widget import PlotWidget


@pytest.fixture
def plot(managed_qt_widget, qtbot):
    widget = managed_qt_widget(PlotWidget())
    widget.resize(900, 650)
    widget.add_x_axis("frequency", "Frequency")
    widget.add_y_axis("temperature", "Temperature")
    for name, limits in {
        "bottom": (0, 10),
        "left": (-10, 10),
        "frequency": (100, 200),
        "temperature": (250, 350),
    }.items():
        widget.set_axis_range(name, minimum=limits[0], maximum=limits[1])
    widget.show()
    QApplication.processEvents()
    return widget


def wheel(plot):
    viewport = plot.pg_widget.viewport()
    pos = plot.pg_widget.mapFromScene(plot._plot_item.vb.sceneBoundingRect().center())
    event = QWheelEvent(
        QPointF(pos),
        QPointF(viewport.mapToGlobal(pos)),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(viewport, event)
    QApplication.processEvents()


def drag(plot, qtbot, button):
    viewport = plot.pg_widget.viewport()
    start = plot.pg_widget.mapFromScene(plot._plot_item.vb.sceneBoundingRect().center())
    qtbot.mousePress(viewport, button, pos=start)
    for offset in (QPoint(20, 15), QPoint(60, 40)):
        pos = start + offset
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(pos),
            QPointF(viewport.mapToGlobal(pos)),
            Qt.MouseButton.NoButton,
            button,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(viewport, event)
    qtbot.mouseRelease(viewport, button, pos=start + QPoint(60, 40))
    QApplication.processEvents()


def test_click_axis_toggles_and_survives_theme_refresh(plot, qtbot):
    axis = plot._axis_items["temperature"]
    assert plot._axis_items["left"].mouse_active
    assert plot._axis_items["bottom"].mouse_active
    assert not axis.mouse_active
    pos = plot.pg_widget.mapFromScene(
        axis.mapToScene(QPointF(axis.size().width() / 2, axis.size().height() / 2))
    )
    qtbot.mouseClick(plot.pg_widget.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert axis.mouse_active
    plot.set_axis_label("temperature", "Temperature (K)")
    assert axis.pen().widthF() == 2
    qtbot.mouseClick(plot.pg_widget.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert not axis.mouse_active


@pytest.mark.parametrize("gesture", ["wheel", "pan", "zoom"])
def test_gestures_change_only_selected_independent_axes(plot, qtbot, gesture):
    plot.set_axis_mouse_active("bottom", False)
    plot.set_axis_mouse_active("temperature", True)
    plot.set_axis_mouse_active("frequency", True)
    before = {name: plot._axis_range(name) for name in plot.axis_names}
    if gesture == "wheel":
        wheel(plot)
    else:
        drag(
            plot,
            qtbot,
            Qt.MouseButton.LeftButton if gesture == "pan" else Qt.MouseButton.RightButton,
        )
    assert plot._axis_range("bottom") == pytest.approx(before["bottom"])
    for name in ("left", "temperature", "frequency"):
        assert plot._axis_range(name) != pytest.approx(before[name])
    assert plot._axis_range("left") != pytest.approx(plot._axis_range("temperature"))


def test_all_inactive_freezes_ranges_and_disables_marker_placement(plot):
    for name in plot.axis_names:
        plot.set_axis_mouse_active(name, False)
    before = {name: plot._axis_range(name) for name in plot.axis_names}
    wheel(plot)
    assert {name: plot._axis_range(name) for name in plot.axis_names} == before
    scene_pos = plot._plot_item.vb.sceneBoundingRect().center()
    menu = plot._build_plot_context_menu(scene_pos)
    assert not next(a for a in menu.actions() if a.text() == "Add Data Marker").isEnabled()
    plot._add_data_marker_at_scene_position(scene_pos)
    assert not plot._data_markers


def test_marker_anchors_to_first_active_pair_and_labels_follow_selection(plot):
    for name in plot.axis_names:
        plot.set_axis_mouse_active(name, name in {"frequency", "temperature"})
    scene_pos = plot._plot_item.vb.sceneBoundingRect().center()
    plot._add_data_marker_at_scene_position(scene_pos)
    marker = plot._data_markers[0]
    assert (marker.x_axis, marker.y_axis) == ("frequency", "temperature")
    assert (marker.x, marker.y) == pytest.approx((150, 300), abs=0.3)
    assert marker.item.label().toPlainText() == plot._format_pointer_coordinates(
        [marker.x], [marker.y]
    )
    plot.set_axis_mouse_active("left", True)
    assert "[" in marker.item.label().toPlainText()
    wheel(plot)
    assert (marker.x, marker.y) == pytest.approx((150, 300), abs=0.3)
    assert tuple(marker.item.pos()) == pytest.approx((marker.x, marker.y))
    plot.remove_axis("temperature")
    assert not plot._data_markers


def test_default_selection_leaves_secondary_autorange_untouched(plot):
    plot.set_axis_range("frequency")
    plot.set_axis_range("temperature")
    before = {name: plot._axis_range(name) for name in plot.axis_names}
    wheel(plot)
    for name in ("frequency", "temperature"):
        assert plot._axis_range(name) == pytest.approx(before[name])
        assert plot._axis_auto_range[name] == (True, True)
    assert plot._axis_range("bottom") != pytest.approx(before["bottom"])
    assert plot._axis_range("left") != pytest.approx(before["left"])


def test_mixed_trace_pair_tracks_selected_ranges_once(plot):
    plot.set_trace("mixed", [120, 180], [270, 330])
    plot.assign_trace_axes("mixed", x_axis="frequency", y_axis="temperature")
    for name in plot.axis_names:
        plot.set_axis_mouse_active(name, name in {"frequency", "temperature"})
    wheel(plot)
    view = plot._pair_view_boxes[("frequency", "temperature")]
    assert view.viewRange()[0] == pytest.approx(plot._axis_range("frequency"))
    assert view.viewRange()[1] == pytest.approx(plot._axis_range("temperature"))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
