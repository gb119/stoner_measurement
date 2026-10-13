"""Discoverable Cartesian axis removal and compatibility before replacement."""

import numpy as np
from qtpy.QtCore import QPointF

from stoner_measurement.ui.plot_widget import PlotWidget
from stoner_measurement.ui.plotting.host import PlotDisplayHost
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry


def removal_menu(widget):
    menu = widget._build_plot_context_menu(QPointF())
    return next(action.menu() for action in menu.actions() if action.text() == "Remove Axis")


def test_removing_one_axis_reassigns_traces_and_removes_anchored_markers(managed_qt_widget):
    widget = managed_qt_widget(PlotWidget())
    widget.add_y_axis("temperature", "Temperature")
    widget.add_x_axis("field", "Field")
    widget.append_point("signal", 1, 2)
    widget.assign_trace_axes("signal", x_axis="field", y_axis="temperature")
    widget.add_data_marker(1, 2, x_axis="field", y_axis="temperature")
    menu = removal_menu(widget)
    next(action for action in menu.actions() if action.text() == "temperature").trigger()
    assert widget._trace_axes["signal"] == ("field", "left")
    assert "temperature" not in widget._axis_items
    assert widget._data_markers == []
    np.testing.assert_array_equal(widget.y_data("signal"), [2])
    assert not {"bottom", "left"} & {action.text() for action in menu.actions()}
    next(
        action
        for action in removal_menu(widget).actions()
        if action.text() == "Remove All Extra Axes"
    ).trigger()
    assert widget._trace_axes["signal"] == ("bottom", "left")
    np.testing.assert_array_equal(widget.x_data("signal"), [1])


def test_remove_all_extra_axes_updates_public_state_and_allows_empty_display_switch(
    managed_qt_widget,
):
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry()))
    widget = host.display_widget
    widget.add_y_axis("temperature", "Temperature")
    widget.add_x_axis("field", "Field")
    assert not host.switch_display("intensity")
    menu = removal_menu(widget)
    next(action for action in menu.actions() if action.text() == "Remove All Extra Axes").trigger()
    assert {axis.name for axis in host.service.axes()} == {"bottom", "left"}
    assert {axis.name for axis in host.export_state().axes} == {"bottom", "left"}
    assert not removal_menu(widget).isEnabled()
    assert host.switch_display("intensity")
    assert host.switch_display("cartesian_3d")
