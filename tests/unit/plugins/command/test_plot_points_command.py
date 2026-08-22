"""Tests for PlotPointsCommand."""

from __future__ import annotations

import threading
import time

import pytest
from qtpy.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
)

import stoner_measurement.plugins.command.base as command_base
from stoner_measurement.core import ValueCatalogEntry
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import PlotPointsCommand
from stoner_measurement.ui.axis_mappings import AxisLabel
from stoner_measurement.ui.plot_widget import PlotWidget


class _NeverAckPlotWidget:
    """Test double that tracks queued updates but never acknowledges processing."""

    def __init__(self) -> None:
        self._pending = 0

    def mark_data_update_queued(self) -> None:
        self._pending += 1

    def is_busy_for_data(self) -> bool:
        return self._pending > 0

    def set_trace(self, _trace_name: str, _x_data: object, _y_data: object) -> None:
        pass

    def append_point(self, _trace_name: str, _x: float, _y: float) -> None:
        pass

    def ensure_x_axis(self, _name: str, _label: str) -> None:
        pass

    def ensure_y_axis(self, _name: str, _label: str) -> None:
        pass

    def assign_trace_axes(self, _trace_name: str, _x_axis: str, _y_axis: str) -> None:
        pass


class TestPlotPointsCommand:
    @pytest.fixture(autouse=True)
    def _managed_plot_widget_factory(self, managed_qt_widget):
        self.make_plot_widget = lambda: managed_qt_widget(PlotWidget())

    def test_name(self, qapp):
        assert PlotPointsCommand().name == "Plot Points"

    def test_plugin_type(self, qapp):
        assert PlotPointsCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert PlotPointsCommand().has_lifecycle is False

    def test_default_attributes(self, qapp):
        command = PlotPointsCommand()
        assert command.x_key == ""
        assert command.y_entries == []
        assert command.x_axis_name == "bottom"

    def test_to_json_includes_fields(self, qapp):
        command = PlotPointsCommand()
        command.x_key = "p:x"
        command.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "left"}]
        data = command.to_json()
        assert data["type"] == "command"
        assert data["x_key"] == "p:x"
        assert data["x_axis_name"] == "bottom"
        assert data["y_entries"] == [{"key": "p:y", "label": "My Y", "y_axis": "left"}]

    def test_restore_from_json_round_trip(self, qapp):
        command = PlotPointsCommand()
        command.x_key = "sensor:temp"
        command.y_entries = [{"key": "sensor:voltage", "label": "Voltage (V)", "y_axis": "temp"}]
        command.x_axis_name = "freq"
        restored = BasePlugin.from_json(command.to_json())
        assert isinstance(restored, PlotPointsCommand)
        assert restored.x_key == "sensor:temp"
        assert restored.x_axis_name == "freq"
        assert restored.y_entries == [
            {"key": "sensor:voltage", "label": "Voltage (V)", "y_axis": "temp"}
        ]

    def test_restore_from_json_backward_compat_global_y_axis(self, qapp):
        old_json = {
            "type": "command",
            "class": "stoner_measurement.plugins.command.plot_points:PlotPointsCommand",
            "instance_name": "plot_points",
            "x_key": "p:x",
            "x_axis_name": "bottom",
            "y_axis_name": "temp",
            "y_entries": [{"key": "p:y", "label": "Y"}],
        }
        restored = BasePlugin.from_json(old_json)
        assert isinstance(restored, PlotPointsCommand)
        assert restored.y_entries[0]["y_axis"] == "temp"

    def test_config_widget_returns_widget(self, qapp):
        assert isinstance(PlotPointsCommand().config_widget(), QWidget)

    def test_config_widget_has_x_combo(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        widget = command.config_widget()
        combos = widget.findChildren(QComboBox)
        assert len(combos) >= 1

    def test_config_widget_uses_transposed_y_series_layout(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        command.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "left"}]
        widget = command.config_widget()
        labels = [label.text() for label in widget.findChildren(QLabel)]
        buttons = widget.findChildren(QPushButton)

        assert {
            "<b>Option</b>",
            "<b>Value</b>",
            "<b>Label</b>",
            "<b>Y axis</b>",
            "<b>Colour</b>",
        }.issubset(set(labels))
        assert any(button.text() == "Remove" for button in buttons)
        assert any(button.text() == "(auto)" for button in buttons)

    def test_config_widget_y_series_editors_update_configuration(
        self, qapp, engine, managed_qt_widget
    ):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y", "p:z": "p_z"}
        command.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "left"}]
        widget = managed_qt_widget(command.config_widget())
        scroll_area = widget.findChild(QScrollArea)
        grid = scroll_area.widget().layout()
        assert isinstance(grid, QGridLayout)

        value_combo = grid.itemAtPosition(1, 1).widget()
        label_combo = grid.itemAtPosition(2, 1).widget()
        y_axis_combo = grid.itemAtPosition(3, 1).widget()
        line_style_combo = grid.itemAtPosition(5, 1).widget()
        point_style_combo = grid.itemAtPosition(6, 1).widget()
        line_width_spin = grid.itemAtPosition(7, 1).widget()
        point_size_spin = grid.itemAtPosition(8, 1).widget()
        assert isinstance(value_combo, QComboBox)
        assert isinstance(label_combo, QComboBox)
        assert isinstance(y_axis_combo, QComboBox)
        assert isinstance(line_style_combo, QComboBox)
        assert isinstance(point_style_combo, QComboBox)
        assert isinstance(line_width_spin, QDoubleSpinBox)
        assert isinstance(point_size_spin, QDoubleSpinBox)

        value_combo.setCurrentText("p:z")
        label_combo.lineEdit().setText("Edited label")
        label_combo.lineEdit().editingFinished.emit()
        y_axis_combo.setEditText("custom-axis")
        line_style_combo.setCurrentIndex(line_style_combo.findData("dash"))
        point_style_combo.setCurrentIndex(point_style_combo.findData("circle"))
        line_width_spin.setValue(2.5)
        point_size_spin.setValue(9.0)

        assert command.y_entries == [
            {
                "key": "p:z",
                "label": "Edited label",
                "y_axis": "custom-axis",
                "line_style": "dash",
                "point_style": "circle",
                "line_width": 2.5,
                "point_size": 9.0,
            }
        ]

    def test_editing_series_label_renames_existing_plot_trace(
        self, qapp, engine, managed_qt_widget
    ):
        plot_widget = self.make_plot_widget()
        engine.plot_widget = plot_widget
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        command.y_entries = [{"key": "p:y", "label": "Old label", "y_axis": "left"}]
        plot_widget.append_point("Old label", 1.0, 2.0)
        widget = managed_qt_widget(command.config_widget())
        grid = widget.findChild(QScrollArea).widget().layout()
        label_combo = grid.itemAtPosition(2, 1).widget()

        label_combo.lineEdit().setText("New label")
        label_combo.lineEdit().editingFinished.emit()

        assert plot_widget.trace_names == ["New label"]
        assert plot_widget.x_data("New label") == [1.0]
        assert plot_widget.y_data("New label") == [2.0]

    def test_automatic_label_change_renames_existing_plot_trace(
        self, qapp, engine, managed_qt_widget
    ):
        plot_widget = self.make_plot_widget()
        engine.plot_widget = plot_widget
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y", "p:z": "p_z"}
        command.y_entries = [{"key": "p:y", "label": "y", "y_axis": "left"}]
        plot_widget.append_point("y", 1.0, 2.0)
        widget = managed_qt_widget(command.config_widget())
        grid = widget.findChild(QScrollArea).widget().layout()
        value_combo = grid.itemAtPosition(1, 1).widget()

        value_combo.setCurrentText("p:z")

        assert command.y_entries[0]["label"] == "z"
        assert plot_widget.trace_names == ["z"]

    def test_config_widget_adds_and_removes_y_series(self, qapp, engine, managed_qt_widget):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        widget = managed_qt_widget(command.config_widget())

        add_button = next(
            button for button in widget.findChildren(QPushButton) if button.text() == "Add Y series"
        )
        add_button.click()
        assert command.y_entries == [{"key": "p:x", "label": "x", "y_axis": "left"}]

        remove_button = next(
            button for button in widget.findChildren(QPushButton) if button.text() == "Remove"
        )
        remove_button.click()
        assert command.y_entries == []

    def test_execute_emits_plot_point_for_each_y_series(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x_val", "p:y0": "p_y0_val", "p:y1": "p_y1_val"}
        engine._namespace["p_x_val"] = 3.0
        engine._namespace["p_y0_val"] = 10.0
        engine._namespace["p_y1_val"] = 20.0
        command.x_key = "p:x"
        command.y_entries = [
            {"key": "p:y0", "label": "Series 0"},
            {"key": "p:y1", "label": "Series 1"},
        ]
        received: list[tuple] = []
        command.plot_point.connect(lambda label, x, y: received.append((label, x, y)))
        command.execute()
        assert len(received) == 2
        assert received[0] == ("Series 0", 3.0, 10.0)
        assert received[1] == ("Series 1", 3.0, 20.0)

    def test_execute_emits_axis_signals_for_each_y_series(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x_val", "p:y0": "p_y0_val", "p:y1": "p_y1_val"}
        engine._namespace["p_x_val"] = 3.0
        engine._namespace["p_y0_val"] = 10.0
        engine._namespace["p_y1_val"] = 20.0
        command.x_key = "p:x"
        command.x_axis_name = "freq"
        command.y_entries = [
            {"key": "p:y0", "label": "Series 0", "y_axis": "left"},
            {"key": "p:y1", "label": "Series 1", "y_axis": "temp"},
        ]

        ensured_axes: list[tuple[str, AxisLabel]] = []
        assigned_trace_axes: list[tuple[str, str, str]] = []
        command.plot_ensure_y_axis.connect(lambda axis, label: ensured_axes.append((axis, label)))
        command.plot_trace_axes.connect(
            lambda trace, x_axis, y_axis: assigned_trace_axes.append((trace, x_axis, y_axis))
        )

        command.execute()

        assert ensured_axes == [("left", AxisLabel("y0")), ("temp", AxisLabel("y1"))]
        assert assigned_trace_axes == [("Series 0", "freq", "left"), ("Series 1", "freq", "temp")]

    def test_execute_passes_catalogue_units_to_axis_labels(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {
            "source:Current": ValueCatalogEntry("source_current", "A"),
            "meter:Voltage": ValueCatalogEntry("meter_voltage", "V"),
        }
        engine._namespace.update(source_current=0.001, meter_voltage=0.002)
        command.x_key = "source:Current"
        command.y_entries = [{"key": "meter:Voltage", "label": "Reading"}]
        x_axes = []
        y_axes = []
        command.plot_ensure_x_axis.connect(lambda name, label: x_axes.append((name, label)))
        command.plot_ensure_y_axis.connect(lambda name, label: y_axes.append((name, label)))

        command.execute()

        assert x_axes == [("bottom", AxisLabel("Current", "A"))]
        assert y_axes == [("left", AxisLabel("Voltage", "V"))]

    def test_execute_skips_missing_x_key(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {}
        command.x_key = "missing:x"
        command.y_entries = [{"key": "p:y", "label": "Y"}]
        received: list = []
        command.plot_point.connect(lambda _label, _x, _y: received.append(1))
        command.execute()
        assert received == []

    def test_execute_skips_when_x_key_empty(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "1.0"}
        command.x_key = ""
        received: list = []
        command.plot_point.connect(lambda _label, _x, _y: received.append(1))
        command.execute()
        assert received == []

    def test_execute_skips_when_no_y_entries(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "1.0"}
        engine._namespace["1.0"] = 1.0
        command.x_key = "p:x"
        command.y_entries = []
        received: list = []
        command.plot_point.connect(lambda _label, _x, _y: received.append(1))
        command.execute()
        assert received == []

    def test_execute_waits_when_plot_widget_busy(self, qapp, engine):
        plot_widget = self.make_plot_widget()
        plot_widget.mark_data_update_queued()
        engine.plot_widget = plot_widget

        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        command.x_key = "p:x"
        command.y_entries = [{"key": "p:y", "label": "My Y"}]

        def _release_plot_busy_flag() -> None:
            time.sleep(0.02)
            plot_widget._mark_data_update_processed()

        release_thread = threading.Thread(target=_release_plot_busy_flag, daemon=True)
        release_thread.start()
        started = time.monotonic()
        command.execute()
        elapsed = time.monotonic() - started
        release_thread.join(timeout=1.0)

        assert plot_widget.trace_names == ["My Y"]
        assert plot_widget.x_data("My Y") == [1.0]
        assert plot_widget.y_data("My Y") == [5.0]
        assert elapsed >= 0.01
        assert plot_widget.is_busy_for_data() is False

    def test_execute_raises_when_plot_response_times_out(self, qapp, engine, monkeypatch):
        monkeypatch.setattr(command_base, "_DEFAULT_PLOT_READY_TIMEOUT_SECONDS", 0.01)
        engine.plot_widget = _NeverAckPlotWidget()

        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        command.x_key = "p:x"
        command.y_entries = [{"key": "p:y", "label": "My Y"}]

        with pytest.raises(TimeoutError, match="plot response"):
            command.execute()

    def test_execute_skips_missing_y_key(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x_val"}
        engine._namespace["p_x_val"] = 1.0
        command.x_key = "p:x"
        command.y_entries = [{"key": "p:y_missing", "label": "Y"}]
        received: list = []
        command.plot_point.connect(lambda _label, _x, _y: received.append(1))
        command.execute()
        assert received == []

    def test_execute_skips_when_detached_no_values(self, qapp):
        command = PlotPointsCommand()
        command.x_key = "p:x"
        command.y_entries = [{"key": "p:y", "label": "Y"}]
        received: list = []
        command.plot_point.connect(lambda _label, _x, _y: received.append(1))
        command.execute()
        assert received == []

    def test_generate_action_code(self, qapp):
        command = PlotPointsCommand()
        lines = command.generate_action_code(1, [], lambda source, indent: [])
        assert lines[0] == "    plot_points()"

    def test_reported_traces_empty(self, qapp):
        assert PlotPointsCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert PlotPointsCommand().reported_values() == {}

    def test_sequence_engine_wires_to_plot_widget(self, qapp, engine):
        plot_widget = self.make_plot_widget()
        engine.plot_widget = plot_widget
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        command.x_key = "p:x"
        command.y_entries = [{"key": "p:y", "label": "My Y"}]
        command.execute()
        assert plot_widget.x_data("My Y") == [1.0]
        assert plot_widget.y_data("My Y") == [5.0]
        assert plot_widget.is_busy_for_data() is False

    def test_successive_execute_keeps_existing_trace_table_controls(self, qapp, engine):
        plot_widget = self.make_plot_widget()
        engine.plot_widget = plot_widget
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        command.x_key = "p:x"
        command.y_entries = [{"key": "p:y", "label": "My Y"}]
        command.execute()
        original_checkbox = plot_widget._trace_table.cellWidget(0, 0)

        engine._namespace["p_x"] = 2.0
        engine._namespace["p_y"] = 6.0
        command.execute()

        assert plot_widget._trace_table.cellWidget(0, 0) is original_checkbox
        assert plot_widget.x_data("My Y") == [1.0, 2.0]
        assert plot_widget.y_data("My Y") == [5.0, 6.0]

    def test_sequence_engine_disconnects_on_detach(self, qapp, engine):
        plot_widget = self.make_plot_widget()
        engine.plot_widget = plot_widget
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        command.x_key = "p:x"
        command.y_entries = [{"key": "p:y", "label": "My Y"}]
        command.sequence_engine = None
        command.execute()
        assert plot_widget.trace_names == []

    def test_execute_assigns_points_to_configured_axes(self, qapp, engine):
        plot_widget = self.make_plot_widget()
        plot_widget.add_x_axis("freq", "Frequency (Hz)")
        plot_widget.add_y_axis("temp", "Temperature (K)")
        engine.plot_widget = plot_widget

        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        command.x_key = "p:x"
        command.x_axis_name = "freq"
        command.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "temp"}]

        command.execute()

        assert plot_widget._trace_axes["My Y"] == ("freq", "temp")

    def test_execute_different_series_on_different_y_axes(self, qapp, engine):
        plot_widget = self.make_plot_widget()
        plot_widget.add_y_axis("temp", "Temperature (K)")
        engine.plot_widget = plot_widget

        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:v": "p_v", "p:t": "p_t"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_v"] = 5.0
        engine._namespace["p_t"] = 300.0
        command.x_key = "p:x"
        command.y_entries = [
            {"key": "p:v", "label": "Voltage", "y_axis": "left"},
            {"key": "p:t", "label": "Temp", "y_axis": "temp"},
        ]

        command.execute()

        assert plot_widget._trace_axes["Voltage"] == ("bottom", "left")
        assert plot_widget._trace_axes["Temp"] == ("bottom", "temp")

    def test_execute_auto_creates_missing_y_axis(self, qapp, engine):
        plot_widget = self.make_plot_widget()
        engine.plot_widget = plot_widget

        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        command.x_key = "p:x"
        command.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "brand_new_axis"}]

        assert "brand_new_axis" not in plot_widget.axis_names
        command.execute()
        assert "brand_new_axis" in plot_widget.axis_names
        assert plot_widget._trace_axes["My Y"] == ("bottom", "brand_new_axis")

    def test_execute_auto_creates_missing_x_axis(self, qapp, engine):
        plot_widget = self.make_plot_widget()
        engine.plot_widget = plot_widget

        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        command.x_key = "p:x"
        command.x_axis_name = "brand_new_x_axis"
        command.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "left"}]

        assert "brand_new_x_axis" not in plot_widget.axis_names
        command.execute()
        assert "brand_new_x_axis" in plot_widget.axis_names
        assert plot_widget._trace_axes["My Y"] == ("brand_new_x_axis", "left")

    def test_sequence_engine_attachment_creates_configured_axes(self, qapp, engine):
        plot_widget = self.make_plot_widget()
        engine.plot_widget = plot_widget
        command = PlotPointsCommand()
        command.x_axis_name = "loaded_x"
        command.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "loaded_y"}]

        assert "loaded_x" not in plot_widget.axis_names
        assert "loaded_y" not in plot_widget.axis_names
        engine.add_plugin("plot_points", command)

        assert "loaded_x" in plot_widget.axis_names
        assert "loaded_y" in plot_widget.axis_names

    def test_to_json_preserves_format_fields_in_y_entries(self, qapp):
        command = PlotPointsCommand()
        command.x_key = "p:x"
        command.y_entries = [
            {
                "key": "p:y",
                "label": "My Y",
                "y_axis": "left",
                "colour": "red",
                "line_style": "dash",
                "point_style": "circle",
                "line_width": 2.5,
                "point_size": 9.0,
            }
        ]
        data = command.to_json()
        entry = data["y_entries"][0]
        assert entry["colour"] == "red"
        assert entry["line_style"] == "dash"
        assert entry["point_style"] == "circle"
        assert entry["line_width"] == 2.5
        assert entry["point_size"] == 9.0

    def test_restore_from_json_round_trip_preserves_format(self, qapp):
        command = PlotPointsCommand()
        command.x_key = "p:x"
        command.y_entries = [
            {
                "key": "p:y",
                "label": "My Y",
                "y_axis": "left",
                "colour": "blue",
                "line_style": "dot",
                "point_style": "square",
                "line_width": 1.5,
                "point_size": 6.0,
            }
        ]
        restored = BasePlugin.from_json(command.to_json())
        assert isinstance(restored, PlotPointsCommand)
        entry = restored.y_entries[0]
        assert entry["colour"] == "blue"
        assert entry["line_style"] == "dot"
        assert entry["point_style"] == "square"
        assert entry["line_width"] == 1.5
        assert entry["point_size"] == 6.0

    def test_execute_emits_style_signal_for_y_entry_with_format(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x_val", "p:y": "p_y_val"}
        engine._namespace["p_x_val"] = 1.0
        engine._namespace["p_y_val"] = 2.0
        command.x_key = "p:x"
        command.y_entries = [
            {
                "key": "p:y",
                "label": "Series",
                "y_axis": "left",
                "colour": "red",
                "line_style": "dash",
                "point_style": "circle",
                "line_width": 3.0,
                "point_size": 10.0,
            }
        ]

        style_signals: list[tuple] = []
        command.plot_trace_style.connect(lambda name, style: style_signals.append((name, style)))
        command.execute()

        assert len(style_signals) == 1
        name, style = style_signals[0]
        assert name == "Series"
        assert style["colour"] == "red"
        assert style["line_style"] == "dash"
        assert style["point_style"] == "circle"
        assert style["line_width"] == 3.0
        assert style["point_size"] == 10.0

    def test_execute_no_style_signal_when_entry_has_no_format(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x_val", "p:y": "p_y_val"}
        engine._namespace["p_x_val"] = 1.0
        engine._namespace["p_y_val"] = 2.0
        command.x_key = "p:x"
        command.y_entries = [{"key": "p:y", "label": "Series", "y_axis": "left"}]

        style_signals: list = []
        command.plot_trace_style.connect(lambda name, style: style_signals.append(style))
        command.execute()

        assert style_signals == []

    def test_plot_points_style_signal_wired_to_plot_widget(self, qapp, engine):
        plot_widget = self.make_plot_widget()
        engine.plot_widget = plot_widget

        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x_val", "p:y": "p_y_val"}
        engine._namespace["p_x_val"] = 1.0
        engine._namespace["p_y_val"] = 2.0
        command.x_key = "p:x"
        command.y_entries = [
            {
                "key": "p:y",
                "label": "Styled",
                "y_axis": "left",
                "colour": "green",
                "line_style": "dot",
            }
        ]

        command.execute()

        assert plot_widget._trace_style.get("Styled", {}).get("line") == "dot"

    def test_config_widget_has_format_columns(self, qapp, engine):
        command = PlotPointsCommand()
        engine.add_plugin("plot_points", command)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        command.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "left"}]
        widget = command.config_widget()
        spinboxes = widget.findChildren(QDoubleSpinBox)
        assert len(spinboxes) >= 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
