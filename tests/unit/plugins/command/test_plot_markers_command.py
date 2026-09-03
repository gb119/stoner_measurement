"""Tests for commands that add and remove plot data markers."""

from __future__ import annotations

import pytest
from qtpy.QtWidgets import QLineEdit, QWidget

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import AddPlotMarkerCommand, RemovePlotMarkersCommand
from stoner_measurement.ui.plot_widget import PlotWidget


def test_add_marker_evaluates_coordinates_and_label(qapp, engine, managed_qt_widget):
    plot = managed_qt_widget(PlotWidget())
    engine.plot_widget = plot
    engine._namespace.update(marker_x=1.25, marker_y=-3.5, sample="A")  # noqa: SLF001
    command = AddPlotMarkerCommand()
    command.x_expr = "marker_x"
    command.y_expr = "marker_y"
    command.label_expr = "'sample {sample}'"
    engine.add_plugin("add_plot_marker", command)
    command.execute()
    marker = plot._data_markers[-1]  # noqa: SLF001
    assert (marker.x, marker.y) == (1.25, -3.5)
    assert marker.item.label().toPlainText() == "sample A"


@pytest.mark.parametrize("label_expr", ["", "   ", "None", "'   '"])
def test_add_marker_blank_label_uses_plot_default(label_expr, qapp, engine, managed_qt_widget):
    plot = managed_qt_widget(PlotWidget())
    engine.plot_widget = plot
    command = AddPlotMarkerCommand()
    command.x_expr = "2"
    command.y_expr = "4"
    command.label_expr = label_expr
    engine.add_plugin("add_plot_marker", command)
    command.execute()
    assert plot._data_markers[-1].item.label().toPlainText() == "(2, 4)"  # noqa: SLF001


def test_add_marker_configuration_and_round_trip(qapp):
    command = AddPlotMarkerCommand()
    widget = command.config_widget()
    assert isinstance(widget, QWidget)
    edits = {edit.objectName(): edit for edit in widget.findChildren(QLineEdit)}
    edits["plot_marker_x"].setText("scan.x")
    edits["plot_marker_y"].setText("scan.y")
    edits["plot_marker_label"].setText("'point'")
    restored = BasePlugin.from_json(command.to_json())
    assert isinstance(restored, AddPlotMarkerCommand)
    assert (restored.x_expr, restored.y_expr, restored.label_expr) == (
        "scan.x", "scan.y", "'point'"
    )


def test_remove_markers_leaves_traces(qapp, engine, managed_qt_widget):
    plot = managed_qt_widget(PlotWidget())
    engine.plot_widget = plot
    plot.append_point("trace", 0.0, 1.0)
    plot.add_data_marker(2.0, 3.0)
    command = RemovePlotMarkersCommand()
    engine.add_plugin("remove_plot_markers", command)
    command.execute()
    assert plot._data_markers == []  # noqa: SLF001
    assert plot.trace_names == ["trace"]


def test_remove_markers_configuration_and_round_trip(qapp):
    command = RemovePlotMarkersCommand()
    assert isinstance(command.config_widget(), QWidget)
    assert command.name == "Remove Plot Markers"
    assert isinstance(BasePlugin.from_json(command.to_json()), RemovePlotMarkersCommand)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
