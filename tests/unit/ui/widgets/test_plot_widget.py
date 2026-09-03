"""Tests for PlotWidget and axis configuration UI."""

from __future__ import annotations

import numpy as np
import pytest
from qtpy.QtCore import QPointF
from qtpy.QtGui import QColor
from qtpy.QtWidgets import QComboBox, QDialog, QHeaderView, QLabel, QLineEdit

from stoner_measurement.ui.axis_mappings import AxisLabel, inverse_values, transform_values
from stoner_measurement.ui.plot_widget import (
    _MAX_VISIBLE_TRACE_ROWS,
    _POINT_PICTOGRAMS,
    _TRACE_TITLE_COLUMN_WIDTH,
    AxesConfigDialog,
    PlotWidget,
)


class TestPlotWidget:
    @pytest.fixture(autouse=True)
    def _managed_plot_widget_factory(self, managed_qt_widget):
        """Keep every PlotWidget alive through pytest-qt's post-test event pass."""
        self.make_plot_widget = lambda: managed_qt_widget(PlotWidget())

    def test_creates_widget(self, qapp):
        widget = self.make_plot_widget()
        assert widget is not None

    def test_initial_data_empty(self, qapp):
        widget = self.make_plot_widget()
        assert widget.x_data() == []
        assert widget.y_data() == []

    def test_append_point(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 1.0, 2.0)
        assert widget.x_data("sig") == [1.0]
        assert widget.y_data("sig") == [2.0]

    def test_append_point_multiple_traces(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("a", 1.0, 10.0)
        widget.append_point("b", 2.0, 20.0)
        assert widget.x_data("a") == [1.0]
        assert widget.x_data("b") == [2.0]
        assert sorted(widget.trace_names) == ["a", "b"]

    def test_set_trace(self, qapp):
        widget = self.make_plot_widget()
        widget.set_trace("sig", [0.0, 1.0, 2.0], [3.0, 4.0, 5.0])
        assert widget.x_data("sig") == [0.0, 1.0, 2.0]
        assert widget.y_data("sig") == [3.0, 4.0, 5.0]

    def test_set_trace_replaces_data(self, qapp):
        widget = self.make_plot_widget()
        widget.set_trace("sig", [0.0, 1.0], [2.0, 3.0])
        widget.set_trace("sig", [10.0], [20.0])
        assert widget.x_data("sig") == [10.0]
        assert widget.y_data("sig") == [20.0]

    def test_remove_trace(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 1.0, 2.0)
        widget.remove_trace("sig")
        assert "sig" not in widget.trace_names
        assert widget.x_data("sig") == []

    def test_remove_trace_missing_noop(self, qapp):
        widget = self.make_plot_widget()
        widget.remove_trace("nonexistent")  # should not raise

    def test_rename_trace_preserves_data_axes_style_and_visibility(self, qapp):
        widget = self.make_plot_widget()
        widget.add_y_axis("right_data", "Right data")
        widget.append_point("old", 1.0, 2.0)
        widget.assign_trace_axes("old", y_axis="right_data")
        widget.set_trace_style("old", colour="#123456", line_style="dot")
        widget.set_trace_visible("old", False)

        widget.rename_trace("old", "new")

        assert widget.trace_names == ["new"]
        assert widget.x_data("new") == [1.0]
        assert widget.y_data("new") == [2.0]
        assert widget._trace_axes["new"] == ("bottom", "right_data")
        assert widget.trace_style("new")["colour"] == "#123456"
        assert widget._trace_visible["new"] is False
        assert widget._traces["new"].name() == "new"

    def test_rename_trace_rejects_collision_and_empty_name(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("old", 1.0, 2.0)
        widget.append_point("existing", 3.0, 4.0)

        with pytest.raises(ValueError, match="already exists"):
            widget.rename_trace("old", "existing")
        with pytest.raises(ValueError, match="cannot be empty"):
            widget.rename_trace("old", "  ")

    def test_rename_missing_trace_is_noop(self, qapp):
        widget = self.make_plot_widget()
        widget.rename_trace("missing", "new")
        assert widget.trace_names == []

    def test_clear_all(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("a", 1.0, 2.0)
        widget.append_point("b", 3.0, 4.0)
        widget.clear_all()
        assert widget.trace_names == []

    def test_clear_all_resets_auto_colour_cycle(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("trace_a", 0.0, 1.0)
        widget.append_point("trace_b", 1.0, 2.0)
        first_colour = widget._trace_style["trace_a"]["colour"]
        second_colour = widget._trace_style["trace_b"]["colour"]
        widget.clear_all()
        widget.append_point("trace_c", 0.0, 1.0)
        widget.append_point("trace_d", 1.0, 2.0)
        assert widget._trace_style["trace_c"]["colour"] == first_colour
        assert widget._trace_style["trace_d"]["colour"] == second_colour

    def test_clear_all_starts_fresh_axis_label_collection(self, qapp):
        widget = self.make_plot_widget()
        widget.set_default_axis_labels("Time (s)", "Voltage (V)")
        widget.ensure_y_axis("right", "Ic (A)")

        widget.clear_all()
        widget.set_default_axis_labels("Field (T)", "Resistance (ohm)")
        widget.ensure_y_axis("right", "Rn (ohm)")

        assert widget._axis_items["bottom"].axis_label == AxisLabel("Field", "T")
        assert widget._axis_items["left"].axis_label == AxisLabel("Resistance", "ohm")
        assert widget._axis_items["right"].axis_label == AxisLabel("Rn", "ohm")

    def test_pg_widget_exists(self, qapp):
        widget = self.make_plot_widget()
        assert widget.pg_widget is not None

    def test_default_axis_names(self, qapp):
        widget = self.make_plot_widget()
        assert "left" in widget.axis_names
        assert "bottom" in widget.axis_names

    def test_only_configured_default_axes_are_visible(self, qapp):
        widget = self.make_plot_widget()

        assert widget._plot_item.getAxis("left").isVisible()
        assert widget._plot_item.getAxis("bottom").isVisible()
        assert not widget._default_top_axis.isVisible()
        assert not widget._default_right_axis.isVisible()

    def test_configure_axes_button_present(self, qapp):
        widget = self.make_plot_widget()
        assert widget._configure_axes_button.text() == "Configure Axes…"

    def test_plot_control_buttons_use_icons_and_accessible_names(self, qapp):
        widget = self.make_plot_widget()

        assert widget._home_button.text() == ""
        assert not widget._home_button.icon().isNull()
        assert widget._home_button.accessibleName() == "Home"
        assert not widget._autoscale_button.icon().isNull()
        assert widget._autoscale_button.isCheckable()
        assert widget._autoscale_button.isChecked()
        assert "QPushButton:checked" in widget._autoscale_button.styleSheet()
        assert "background-color" in widget._autoscale_button.styleSheet()
        assert not widget._clear_button.icon().isNull()

    def test_pointer_coordinates_are_displayed_at_right_of_controls(self, qapp):
        widget = self.make_plot_widget()
        widget.resize(800, 500)
        widget.show()
        qapp.processEvents()
        widget._plot_item.vb.setRange(xRange=(0.0, 10.0), yRange=(-2.0, 2.0), padding=0.0)
        scene_pos = widget._plot_item.vb.mapViewToScene(QPointF(2.5, 1.25))

        widget._on_scene_mouse_moved((scene_pos,))

        label = widget.findChild(QLabel, "plotCoordinateDisplay")
        assert label is widget._coordinate_label
        assert label.text() == "(2.5, 1.25)"
        assert widget.layout().itemAt(0).layout().itemAt(5).widget() is label

    def test_multiple_axis_coordinates_use_list_format(self, qapp):
        assert PlotWidget._format_pointer_coordinates([1.0, 2.0], [3.0, 4.0]) == (
            "([1, 2], [3, 4])"
        )

    def test_plot_context_menu_adds_and_removes_nearby_marker(self, qapp):
        widget = self.make_plot_widget()
        widget.resize(800, 500)
        widget.show()
        qapp.processEvents()
        widget._plot_item.vb.setRange(xRange=(0.0, 10.0), yRange=(0.0, 10.0), padding=0.0)
        scene_pos = widget._plot_item.vb.mapViewToScene(QPointF(3.0, 4.0))

        menu = widget._build_plot_context_menu(scene_pos)
        actions = {action.text(): action for action in menu.actions()}
        assert set(actions) == {
            "Configure Axes…",
            "Add Data Marker",
            "Remove All Data Markers",
        }
        assert not actions["Remove All Data Markers"].isEnabled()
        actions["Add Data Marker"].trigger()

        assert len(widget._data_markers) == 1
        marker = widget._data_markers[0]
        assert marker.x == pytest.approx(3.0)
        assert marker.y == pytest.approx(4.0)
        assert marker.item in widget._plot_item.vb.addedItems

        nearby_menu = widget._build_plot_context_menu(scene_pos)
        nearby_actions = {action.text(): action for action in nearby_menu.actions()}
        assert "Add Data Marker" not in nearby_actions
        assert nearby_actions["Remove All Data Markers"].isEnabled()
        nearby_actions["Remove Data Marker"].trigger()
        assert widget._data_markers == []

    def test_data_markers_stay_at_data_coordinates_and_clear_with_plot(self, qapp):
        widget = self.make_plot_widget()
        widget.resize(800, 500)
        widget.show()
        qapp.processEvents()
        widget._plot_item.vb.setRange(xRange=(0.0, 10.0), yRange=(0.0, 10.0), padding=0.0)
        widget._add_data_marker_at_scene_position(
            widget._plot_item.vb.mapViewToScene(QPointF(6.0, 7.0))
        )
        marker = widget._data_markers[0]

        widget._plot_item.vb.setRange(xRange=(5.0, 7.0), yRange=(6.0, 8.0), padding=0.0)
        mapped = widget._plot_item.vb.mapSceneToView(
            widget._plot_item.vb.mapViewToScene(marker.item.pos())
        )
        assert mapped.x() == pytest.approx(6.0)
        assert mapped.y() == pytest.approx(7.0)

        widget.clear_all()
        assert widget._data_markers == []
        assert marker.item not in widget._plot_item.vb.addedItems

    def test_public_data_marker_api_adds_removes_and_reports_missing_ids(self, qapp):
        widget = self.make_plot_widget()

        marker_id = widget.add_data_marker(1.5, -2.5, label="Turning point")

        assert marker_id == 1
        assert widget._data_markers[0].marker_id == marker_id
        assert widget._data_markers[0].item.label().toPlainText() == "Turning point"
        assert widget.remove_data_marker(marker_id) is True
        assert widget.remove_data_marker(marker_id) is False
        assert widget._data_markers == []

    def test_autoscale_button_controls_range_updates_for_new_data(self, qapp):
        widget = self.make_plot_widget()
        view_box = widget._plot_item.vb

        widget.append_point("sig", 0.0, 0.0)
        widget._autoscale_button.click()
        assert widget._autoscale_new_data is False
        assert view_box.state["autoRange"] == [False, False]

        widget.append_point("sig", 100.0, 100.0)
        assert view_box.state["autoRange"] == [False, False]

        widget._autoscale_button.click()
        assert widget._autoscale_new_data is True
        assert view_box.viewRange()[0][1] >= 100.0
        assert view_box.viewRange()[1][1] >= 100.0

        widget.append_point("sig", 200.0, 200.0)
        assert view_box.viewRange()[0][1] >= 200.0
        assert view_box.viewRange()[1][1] >= 200.0

    def test_clear_button_removes_all_plotted_data(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 1.0, 2.0)

        widget._clear_button.click()

        assert widget.trace_names == []

    def test_axes_config_dialog_creates_and_collects_changes(self, qapp):
        dialog = AxesConfigDialog(
            x_axes=[
                {
                    "name": "bottom",
                    "label": "Step",
                    "log_scale": False,
                    "grid": True,
                    "side": "bottom",
                    "visible": True,
                    "minimum": 0.0,
                    "maximum": 10.0,
                    "removable": False,
                }
            ],
            y_axes=[
                {
                    "name": "left",
                    "label": "Value",
                    "log_scale": False,
                    "grid": True,
                    "side": "left",
                    "visible": True,
                    "minimum": -1.0,
                    "maximum": 1.0,
                    "removable": False,
                }
            ],
        )
        dialog._add_name_inputs["x"].setText("freq")
        dialog._add_label_inputs["x"].setText("Frequency (Hz)")
        dialog._add_axis_row_from_inputs("x")
        changes = dialog.axis_changes()
        assert changes["visible_axes"]["freq"] is True
        assert changes["labels"]["freq"] == "Frequency (Hz)"
        assert changes["ranges"]["bottom"] == (0.0, 10.0)
        assert changes["ranges"]["left"] == (-1.0, 1.0)
        assert changes["ranges"]["freq"] == (None, None)
        dialog.reject()
        assert dialog.result() == QDialog.DialogCode.Rejected

    def test_axes_config_dialog_rejects_name_used_by_other_axis_kind(self, qapp):
        dialog = AxesConfigDialog(
            x_axes=[
                {
                    "name": "bottom",
                    "label": "Step",
                    "log_scale": False,
                    "grid": True,
                    "side": "bottom",
                    "visible": True,
                    "minimum": None,
                    "maximum": None,
                    "removable": False,
                }
            ],
            y_axes=[
                {
                    "name": "left",
                    "label": "Value",
                    "log_scale": False,
                    "grid": True,
                    "side": "left",
                    "visible": True,
                    "minimum": None,
                    "maximum": None,
                    "removable": False,
                }
            ],
        )
        dialog._add_name_inputs["x"].setText("left")
        dialog._add_label_inputs["x"].setText("Colliding Left")
        dialog._add_axis_row_from_inputs("x")
        changes = dialog.axis_changes()
        assert set(changes["visible_axes"]) == {"bottom", "left"}
        assert changes["labels"]["left"] == "Value"
        dialog.reject()

    def test_axes_config_dialog_collects_mapping_and_parameter(self, qapp):
        """The axes dialog exposes every mapping and its scale parameter."""
        dialog = AxesConfigDialog(
            x_axes=[],
            y_axes=[
                {
                    "name": "left",
                    "label": "Value",
                    "log_scale": False,
                    "grid": True,
                    "side": "left",
                    "visible": True,
                    "minimum": None,
                    "maximum": None,
                    "removable": False,
                }
            ],
        )
        table = dialog._tables["y"]
        scale_combo = table.cellWidget(0, 4)
        parameter_edit = table.cellWidget(0, 5)
        assert isinstance(scale_combo, QComboBox)
        assert isinstance(parameter_edit, QLineEdit)
        assert [scale_combo.itemText(i) for i in range(scale_combo.count())] == [
            "linear",
            "log",
            "symlog",
            "logit",
            "asinh",
        ]

        scale_combo.setCurrentText("asinh")
        parameter_edit.setText("2.5")
        changes = dialog.axis_changes()

        assert changes["scale"]["left"] == "asinh"
        assert changes["scale_parameter"]["left"] == pytest.approx(2.5)

        parameter_edit.setText("not a number")
        minimum_edit = table.cellWidget(0, 7)
        maximum_edit = table.cellWidget(0, 8)
        assert isinstance(minimum_edit, QLineEdit)
        assert isinstance(maximum_edit, QLineEdit)
        minimum_edit.setText("invalid")
        maximum_edit.clear()

        invalid_changes = dialog.axis_changes()

        assert invalid_changes["scale_parameter"]["left"] == pytest.approx(1.0)
        assert invalid_changes["ranges"]["left"] == (None, None)

    def test_open_axes_dialog_applies_additions_and_removals(self, qapp, monkeypatch):
        widget = self.make_plot_widget()
        widget.add_y_axis("temp", "Temperature (K)")
        widget.append_point("sig", 0.0, 1.0)
        widget.assign_trace_axes("sig", y_axis="temp")

        class _FakeDialog:
            def __init__(self, **_kwargs):
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

            def axis_changes(self):
                return {
                    "labels": {"bottom": "Step", "left": "Value", "freq": "Frequency (Hz)"},
                    "log_scale": {"bottom": False, "left": False, "freq": True},
                    "grid": {"bottom": True, "left": True, "freq": False},
                    "side": {"bottom": "bottom", "left": "left", "freq": "top"},
                    "removed": {"x": [], "y": ["temp"]},
                    "ranges": {"bottom": (None, None), "left": (None, None), "freq": (1.0, 2.0)},
                    "visible_axes": {"bottom": True, "left": True, "freq": True},
                }

        monkeypatch.setattr("stoner_measurement.ui.plot_widget.AxesConfigDialog", _FakeDialog)
        widget._open_axes_dialog()
        assert "temp" not in widget.axis_names
        assert widget._trace_axes["sig"] == ("bottom", "left")
        assert "freq" in widget.axis_names
        assert widget._axis_items["freq"].axis_label == AxisLabel("Frequency", "Hz")
        assert widget._axis_log_scale["freq"] is True

    def test_axis_entries_show_blank_bounds_for_auto_axes(self, qapp):
        widget = self.make_plot_widget()
        entry = widget._axis_entries("x")[0]
        assert entry["name"] == "bottom"
        assert entry["minimum"] is None
        assert entry["maximum"] is None

    def test_set_axis_range_supports_partial_auto_bounds(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 0.0, 1.0)
        widget.append_point("sig", 2.0, 3.0)
        widget.set_axis_range("bottom", minimum=0.5, maximum=None)
        assert widget._axis_auto_range["bottom"] == (False, True)
        assert widget._axis_manual_range["bottom"][0] == pytest.approx(0.5)
        entry = widget._axis_entries("x")[0]
        assert entry["minimum"] == pytest.approx(0.5)
        assert entry["maximum"] is None

    def test_reset_all_view_ranges_restores_full_auto_bounds(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 0.0, 1.0)
        widget.append_point("sig", 2.0, 3.0)
        widget.set_axis_range("bottom", minimum=0.5, maximum=None)
        widget.reset_all_view_ranges()
        assert widget._axis_auto_range["bottom"] == (True, True)
        entry = widget._axis_entries("x")[0]
        assert entry["minimum"] is None
        assert entry["maximum"] is None

    def test_axes_config_dialog_live_range_callback(self, qapp):
        calls = []

        def on_range_changed(axis_name, minimum, maximum):
            calls.append((axis_name, minimum, maximum))

        dialog = AxesConfigDialog(
            x_axes=[
                {
                    "name": "bottom",
                    "label": "Step",
                    "log_scale": False,
                    "grid": True,
                    "side": "bottom",
                    "visible": True,
                    "minimum": None,
                    "maximum": None,
                    "removable": False,
                }
            ],
            y_axes=[],
            on_range_changed=on_range_changed,
        )
        table = dialog._tables["x"]
        minimum_edit = table.cellWidget(0, 7)
        maximum_edit = table.cellWidget(0, 8)
        assert isinstance(minimum_edit, QLineEdit)
        assert isinstance(maximum_edit, QLineEdit)
        minimum_edit.setText("1.5")
        maximum_edit.setText("3.5")
        dialog._emit_range_change("x", 0)
        assert calls == [("bottom", 1.5, 3.5)]

    def test_add_y_axis(self, qapp):
        widget = self.make_plot_widget()
        default_right_axis = widget._default_right_axis
        widget.add_y_axis("temperature", "Temperature (K)", side="right")
        widget.resize(800, 600)
        widget.show()
        qapp.processEvents()

        assert "temperature" in widget.axis_names
        assert widget._default_right_axis_removed
        assert widget._default_right_axis is None
        assert default_right_axis.scene() is None
        right_spine_x = widget._axis_items["temperature"].geometry().left()
        plot_right = widget._plot_item.vb.sceneBoundingRect().right()
        assert right_spine_x == pytest.approx(plot_right, abs=1.0)

    def test_moving_axis_to_right_replaces_default_placeholder(self, qapp):
        widget = self.make_plot_widget()
        widget.add_y_axis("temperature", "Temperature (K)", side="left")

        widget.set_axis_side("temperature", "right")

        assert widget._default_right_axis_removed
        assert widget._default_right_axis is None

    def test_add_y_axis_duplicate_noop(self, qapp):
        widget = self.make_plot_widget()
        widget.add_y_axis("temp", "Temp", side="right")
        widget.add_y_axis("temp", "Other", side="right")  # should not raise
        assert widget.axis_names.count("temp") == 1

    def test_add_x_axis(self, qapp):
        widget = self.make_plot_widget()
        widget.add_x_axis("freq", "Frequency (Hz)", position="top")
        assert "freq" in widget.axis_names

    def test_top_axis_reserves_space_above_all_plot_viewboxes(self, qapp):
        """Top-axis labels sit above its spine rather than over plotted data."""
        widget = self.make_plot_widget()
        widget.resize(800, 600)
        widget.add_x_axis("freq", "Frequency (Hz)", position="top")
        widget.add_y_axis("right", "Right axis", side="right")
        widget.append_point("signal", 1.0, 2.0)
        widget.assign_trace_axes("signal", x_axis="freq", y_axis="right")
        widget.show()
        qapp.processEvents()

        top_spine_y = widget._axis_items["freq"].geometry().bottom()
        main_top = widget._plot_item.vb.sceneBoundingRect().top()
        auxiliary_top = widget._pair_view_boxes[("freq", "right")].sceneBoundingRect().top()
        left_top = widget._axis_items["left"].scenePos().y()
        right_top = widget._axis_items["right"].scenePos().y()

        assert main_top == pytest.approx(top_spine_y, abs=1.0)
        assert auxiliary_top == pytest.approx(top_spine_y, abs=1.0)
        assert left_top == pytest.approx(top_spine_y, abs=1.0)
        assert right_top == pytest.approx(top_spine_y, abs=1.0)

    def test_assign_trace_axes(self, qapp):
        widget = self.make_plot_widget()
        widget.add_y_axis("temp", "Temperature (K)")
        widget.append_point("sig", 0.0, 300.0)
        widget.assign_trace_axes("sig", y_axis="temp")
        assert widget._trace_axes["sig"] == ("bottom", "temp")

    def test_assign_trace_axes_unknown_trace_raises(self, qapp):
        widget = self.make_plot_widget()
        with pytest.raises(KeyError, match="unknown"):
            widget.assign_trace_axes("unknown", y_axis="left")

    def test_assign_trace_axes_unknown_axis_raises(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(KeyError, match="no_such"):
            widget.assign_trace_axes("sig", y_axis="no_such")

    def test_assign_trace_axes_unknown_x_axis_raises(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(KeyError, match="no_such_x"):
            widget.assign_trace_axes("sig", x_axis="no_such_x", y_axis="left")

    def test_assign_trace_axes_supports_independent_x_and_y_axes(self, qapp):
        widget = self.make_plot_widget()
        widget.add_x_axis("freq", "Frequency (Hz)")
        widget.add_y_axis("temp", "Temperature (K)")
        widget.append_point("sig", 0.0, 1.0)
        widget.assign_trace_axes("sig", x_axis="freq", y_axis="temp")
        assert widget._trace_axes["sig"] == ("freq", "temp")

    def test_assign_trace_axes_moves_associated_error_bar_item(self, qapp):
        widget = self.make_plot_widget()
        widget.add_y_axis("temp", "Temperature (K)")
        widget.set_trace_with_errors("sig", [0.0, 1.0], [2.0, 3.0], None, [0.1, 0.2])
        ebi = widget._error_bar_items["sig"]
        old_parent = ebi.parentItem()
        widget.assign_trace_axes("sig", y_axis="temp")
        assert widget._trace_axes["sig"] == ("bottom", "temp")
        assert ebi.parentItem() is not None
        assert ebi.parentItem() is not old_parent

    def test_ensure_y_axis_creates_new_axis(self, qapp):
        widget = self.make_plot_widget()
        assert "new_axis" not in widget.axis_names
        widget.ensure_y_axis("new_axis", "New Axis (units)")
        assert "new_axis" in widget.axis_names

    def test_ensure_y_axis_is_idempotent(self, qapp):
        widget = self.make_plot_widget()
        widget.ensure_y_axis("dup", "Duplicate")
        widget.ensure_y_axis("dup", "Duplicate")
        assert widget.axis_names.count("dup") == 1

    def test_ensure_shared_custom_axis_accumulates_distinct_labels(self, qapp):
        widget = self.make_plot_widget()

        widget.ensure_y_axis("right", "Ic (A)")
        widget.ensure_y_axis("right", "Rn (ohm)")
        widget.ensure_y_axis("right", "Ic (A)")

        assert widget._axis_items["right"].axis_label == AxisLabel("Ic (A), Rn (ohm)")

    def test_ensure_y_axis_uses_name_as_label_fallback(self, qapp):
        widget = self.make_plot_widget()
        widget.ensure_y_axis("my_axis")
        assert "my_axis" in widget.axis_names

    def test_ensure_y_axis_noop_for_default_left(self, qapp):
        """ensure_y_axis on the built-in 'left' axis leaves axis count unchanged."""
        widget = self.make_plot_widget()
        initial = sorted(widget.axis_names)
        widget.ensure_y_axis("left")
        assert sorted(widget.axis_names) == initial

    def test_ensure_default_axes_preserves_accumulated_labels(self, qapp):
        """Plot command axis checks must not overwrite combined metadata labels."""
        widget = self.make_plot_widget()

        widget.ensure_x_axis("bottom", "bottom")
        widget.ensure_y_axis("left", "left")
        widget.set_default_axis_labels("Voltage (V)", "Current (A)")
        widget.ensure_x_axis("bottom", "Voltage (V)")
        widget.ensure_y_axis("left", "Current (A)")
        widget.ensure_x_axis("bottom", "bottom")
        widget.ensure_y_axis("left", "left")
        widget.set_default_axis_labels("Resistance (ohm)", "Power (W)")
        widget.ensure_x_axis("bottom", "Resistance (ohm)")
        widget.ensure_y_axis("left", "Power (W)")

        assert widget._axis_items["bottom"].axis_label == AxisLabel("Resistance (ohm), Voltage (V)")
        assert widget._axis_items["left"].axis_label == AxisLabel("Current (A), Power (W)")

    def test_ensure_x_axis_creates_new_axis(self, qapp):
        widget = self.make_plot_widget()
        assert "new_x_axis" not in widget.axis_names
        widget.ensure_x_axis("new_x_axis", "New X Axis (units)")
        assert "new_x_axis" in widget.axis_names

    def test_ensure_x_axis_is_idempotent(self, qapp):
        widget = self.make_plot_widget()
        widget.ensure_x_axis("dup_x", "Duplicate X")
        widget.ensure_x_axis("dup_x", "Duplicate X")
        assert widget.axis_names.count("dup_x") == 1

    def test_ensure_x_axis_noop_for_default_bottom(self, qapp):
        widget = self.make_plot_widget()
        initial = sorted(widget.axis_names)
        widget.ensure_x_axis("bottom")
        assert sorted(widget.axis_names) == initial

    def test_set_axis_label_updates_axis_title(self, qapp):
        widget = self.make_plot_widget()
        widget.add_y_axis("temp", "Temp")
        widget.set_axis_label("temp", "Temperature (K)")
        assert widget._axis_items["temp"].axis_label == AxisLabel("Temperature", "K")

    def test_set_axis_log_scale_updates_axis_state(self, qapp):
        widget = self.make_plot_widget()
        widget.add_x_axis("freq", "Freq")
        widget.set_axis_log_scale("freq", True)
        assert widget._axis_log_scale["freq"] is True

    def test_log_scale_updates_axis_viewbox_and_trace_mapping(self, qapp):
        """Log mode affects tick rendering, view bounds, and plotted values."""
        widget = self.make_plot_widget()
        widget.append_point("pressure", 0.0, 1.0e-6)

        widget.set_axis_log_scale("left", True)

        axis = widget._axis_items["left"]
        view_box = widget._pair_view_boxes[("bottom", "left")]
        trace = widget._traces["pressure"]
        assert axis.logMode is True
        assert view_box.state["logMode"] == [False, True]
        assert trace.opts["logMode"] == [False, False]
        assert trace.getData()[1].tolist() == pytest.approx([-6.0])

    def test_trace_created_after_enabling_log_scale_is_mapped(self, qapp):
        """New traces inherit the current logarithmic axis mode."""
        widget = self.make_plot_widget()
        widget.set_axis_log_scale("left", True)

        widget.append_point("pressure", 0.0, 1.0e-5)

        assert widget._traces["pressure"].opts["logMode"] == [False, False]
        assert widget._traces["pressure"].getData()[1].tolist() == pytest.approx([-5.0])

    def test_reassigned_trace_inherits_destination_axis_log_mode(self, qapp):
        """Moving a trace to a logarithmic axis remaps its displayed values."""
        widget = self.make_plot_widget()
        widget.add_y_axis("pressure", "Pressure")
        widget.set_axis_log_scale("pressure", True)
        widget.append_point("gauge", 0.0, 1.0e-4)

        widget.assign_trace_axes("gauge", y_axis="pressure")

        assert widget._traces["gauge"].opts["logMode"] == [False, False]
        assert widget._traces["gauge"].getData()[1].tolist() == pytest.approx([-4.0])

    @pytest.mark.parametrize(
        ("scale", "parameter", "raw", "mapped"),
        [
            ("symlog", 1.0, [-100.0, -0.5, 0.0, 0.5, 100.0], [-3.0, -0.5, 0.0, 0.5, 3.0]),
            ("logit", 1.0, [0.01, 0.5, 0.99], [-1.995635, 0.0, 1.995635]),
            ("asinh", 2.0, [-7.253721, 0.0, 7.253721], [-2.0, 0.0, 2.0]),
        ],
    )
    def test_axis_mapping_round_trip(self, scale, parameter, raw, mapped):
        """Custom mappings transform display data and preserve raw values."""
        transformed = transform_values(raw, scale, parameter)
        assert transformed.tolist() == pytest.approx(mapped, abs=1.0e-6)
        assert inverse_values(transformed, scale, parameter).tolist() == pytest.approx(raw)

    @pytest.mark.parametrize("scale", ["symlog", "logit", "asinh"])
    def test_custom_axis_scale_maps_trace_and_tick_labels(self, qapp, scale):
        """Custom scales map trace coordinates while retaining meaningful labels."""
        widget = self.make_plot_widget()
        raw = [0.1, 0.5, 0.9] if scale == "logit" else [-10.0, 0.0, 10.0]
        widget.set_trace("signal", [0.0, 1.0, 2.0], raw)

        widget.set_axis_scale("left", scale, 1.0)

        displayed = widget._traces["signal"].getData()[1]
        assert displayed.tolist() == pytest.approx(transform_values(raw, scale, 1.0).tolist())
        assert widget.y_data("signal") == raw
        labels = widget._axis_items["left"].tickStrings(displayed, 1.0, 1.0)
        assert labels == [f"{value:.6g}" for value in raw]

    def test_logit_rejects_values_outside_open_unit_interval(self, qapp):
        """Values outside the logit domain are omitted from rendered data."""
        widget = self.make_plot_widget()
        widget.set_axis_scale("left", "logit")
        widget.set_trace("probability", [0.0, 1.0, 2.0], [0.0, 0.5, 1.0])

        displayed = widget._traces["probability"].getData()[1]
        assert np.isnan(displayed[0])
        assert displayed[1] == pytest.approx(0.0)
        assert np.isnan(displayed[2])

    def test_mapped_axis_manual_range_uses_raw_values(self, qapp):
        """Axis range controls continue to accept untransformed physical values."""
        widget = self.make_plot_widget()
        widget.set_axis_scale("left", "logit")

        widget.set_axis_range("left", 0.01, 0.99)

        assert widget._plot_item.vb.viewRange()[1] == pytest.approx(
            [-1.995635, 1.995635], abs=1.0e-6
        )
        assert widget._axis_range("left") == pytest.approx((0.01, 0.99))

    def test_error_bar_endpoints_follow_custom_mapping(self, qapp):
        """Nonlinear mappings transform each error-bar endpoint independently."""
        widget = self.make_plot_widget()
        widget.set_trace_with_errors("signal", [0.0], [10.0], None, [5.0])

        widget.set_axis_scale("left", "asinh", 2.0)

        item = widget._error_bar_items["signal"]
        centre = transform_values([10.0], "asinh", 2.0)[0]
        lower = transform_values([5.0], "asinh", 2.0)[0]
        upper = transform_values([15.0], "asinh", 2.0)[0]
        assert item.opts["y"].tolist() == pytest.approx([centre])
        assert item.opts["bottom"].tolist() == pytest.approx([centre - lower])
        assert item.opts["top"].tolist() == pytest.approx([upper - centre])

    def test_set_axis_grid_updates_axis_state(self, qapp):
        widget = self.make_plot_widget()
        widget.set_axis_grid("bottom", False)
        assert widget._axis_grid["bottom"] is False

    def test_rolling_time_window_uses_fixed_real_time_axis(self, qapp):
        widget = self.make_plot_widget()

        widget.set_rolling_time_window(3600.0)

        assert widget._axis_range("bottom") == pytest.approx((-3600.0, 0.0))
        assert widget._axis_auto_range["bottom"] == (False, False)

    @pytest.mark.parametrize("duration", [0.0, -1.0, float("inf")])
    def test_rolling_time_window_rejects_invalid_duration(self, qapp, duration):
        widget = self.make_plot_widget()
        with pytest.raises(ValueError, match="positive and finite"):
            widget.set_rolling_time_window(duration)

    def test_remove_axis_rejects_default_axis(self, qapp):
        widget = self.make_plot_widget()
        with pytest.raises(ValueError, match="default axis"):
            widget.remove_axis("left")

    def test_remove_axis_reassigns_trace_to_default(self, qapp):
        widget = self.make_plot_widget()
        widget.add_y_axis("temp", "Temperature (K)")
        widget.append_point("sig", 0.0, 1.0)
        widget.assign_trace_axes("sig", y_axis="temp")
        widget.remove_axis("temp")
        assert widget._trace_axes["sig"] == ("bottom", "left")
        assert "temp" not in widget.axis_names

    def test_set_trace_style_updates_trace_style(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 0.0, 1.0)
        widget.set_trace_style(
            "sig",
            colour="#123456",
            line_style="dash",
            point_style="circle",
            line_width=3.5,
            point_size=11.0,
        )
        assert widget._trace_style["sig"] == {
            "colour": "#123456",
            "line": "dash",
            "point": "circle",
        }
        assert widget._trace_line_width["sig"] == 3.5
        assert widget._trace_point_size["sig"] == 11.0
        curve = widget._traces["sig"]
        assert curve.opts["symbol"] == "o"
        assert curve.opts["pen"].color().name().lower() == "#123456"
        assert curve.opts["pen"].widthF() == pytest.approx(3.5)
        assert curve.opts["symbolSize"] == pytest.approx(11.0)

    def test_set_trace_style_rejects_unknown_line_style(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(ValueError, match="line style"):
            widget.set_trace_style("sig", line_style="wiggly")

    def test_set_trace_style_rejects_unknown_point_style(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(ValueError, match="point style"):
            widget.set_trace_style("sig", point_style="hexagon")

    def test_set_trace_style_rejects_non_positive_line_width(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(ValueError, match="Line width"):
            widget.set_trace_style("sig", line_width=0)

    def test_set_trace_style_rejects_non_positive_point_size(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(ValueError, match="Point size"):
            widget.set_trace_style("sig", point_size=0)

    def test_set_trace_style_rejects_invalid_colour(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(ValueError, match="Invalid colour"):
            widget.set_trace_style("sig", colour="not-a-colour")

    def test_x_data_unknown_trace_returns_empty(self, qapp):
        widget = self.make_plot_widget()
        assert widget.x_data("nonexistent") == []

    def test_y_data_unknown_trace_returns_empty(self, qapp):
        widget = self.make_plot_widget()
        assert widget.y_data("nonexistent") == []

    def test_set_default_axis_labels_updates_bottom_axis(self, qapp):
        widget = self.make_plot_widget()
        widget.set_default_axis_labels("Current (A)", "")
        axis = widget._pg_widget.getPlotItem().getAxis("bottom")
        assert axis.axis_label == AxisLabel("Current", "A")

    def test_set_default_axis_labels_updates_left_axis(self, qapp):
        widget = self.make_plot_widget()
        widget.set_default_axis_labels("", "Voltage (V)")
        axis = widget._pg_widget.getPlotItem().getAxis("left")
        assert axis.axis_label == AxisLabel("Voltage", "V")

    def test_set_default_axis_labels_both(self, qapp):
        widget = self.make_plot_widget()
        widget.set_default_axis_labels("Current (A)", "Voltage (V)")
        assert widget._pg_widget.getPlotItem().getAxis("bottom").axis_label == AxisLabel(
            "Current", "A"
        )
        assert widget._pg_widget.getPlotItem().getAxis("left").axis_label == AxisLabel(
            "Voltage", "V"
        )

    def test_set_default_axis_labels_accumulates_distinct_labels(self, qapp):
        widget = self.make_plot_widget()

        widget.set_default_axis_labels("Time (s)", "Voltage (V)")
        widget.set_default_axis_labels("Frequency (Hz)", "Current (A)")

        assert widget._axis_items["bottom"].axis_label == AxisLabel("Frequency (Hz), Time (s)")
        assert widget._axis_items["left"].axis_label == AxisLabel("Current (A), Voltage (V)")

    def test_set_default_axis_labels_does_not_rewrite_repeated_labels(self, qapp, monkeypatch):
        widget = self.make_plot_widget()
        original_set_axis_label = widget.set_axis_label
        calls = []

        def record_set_axis_label(name, label):
            calls.append((name, label))
            original_set_axis_label(name, label)

        monkeypatch.setattr(widget, "set_axis_label", record_set_axis_label)
        widget.set_default_axis_labels("Time (s)", "Voltage (V)")
        widget.set_default_axis_labels("Time (s)", "Voltage (V)")

        assert calls == [
            ("bottom", AxisLabel("Time", "s")),
            ("left", AxisLabel("Voltage", "V")),
        ]

    def test_axis_uses_si_prefix_on_physical_unit(self, qapp):
        widget = self.make_plot_widget()
        widget.set_axis_label("bottom", AxisLabel("Current", "A"))
        axis = widget._axis_items["bottom"]

        axis.setRange(0.0, 0.003)

        assert axis.labelUnitPrefix == "m"
        assert "(mA)" in axis.labelString()
        assert "x0.001" not in axis.labelString()

    def test_unitless_axis_puts_si_prefix_on_tick_labels(self, qapp):
        widget = self.make_plot_widget()
        widget.set_axis_label("bottom", AxisLabel("Ratio"))
        axis = widget._axis_items["bottom"]
        axis.setRange(0.0, 0.003)

        labels = axis.tickStrings([0.0, 0.001, 0.002], axis.autoSIPrefixScale, 0.001)

        assert labels == ["0", "1m", "2m"]
        assert "x0.001" not in axis.labelString()

        axis.setRange(0.0, 3000.0)
        labels = axis.tickStrings([0.0, 1000.0, 2000.0], axis.autoSIPrefixScale, 1000.0)

        assert labels == ["0", "1k", "2k"]

    def test_set_default_axis_labels_empty_strings_no_change(self, qapp):
        widget = self.make_plot_widget()
        # Default labels set in __init__
        original_bottom = widget._pg_widget.getPlotItem().getAxis("bottom").labelText
        original_left = widget._pg_widget.getPlotItem().getAxis("left").labelText
        widget.set_default_axis_labels("", "")
        # Labels should be unchanged
        assert widget._pg_widget.getPlotItem().getAxis("bottom").labelText == original_bottom
        assert widget._pg_widget.getPlotItem().getAxis("left").labelText == original_left

    def test_trace_table_exists_after_init(self, qapp):
        widget = self.make_plot_widget()
        assert widget._trace_table is not None

    def test_trace_table_has_row_after_trace_created(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("my_trace", 1.0, 2.0)
        assert widget._trace_table.rowCount() == 1
        assert widget._trace_table.item(0, 1).text() == "my_trace"

    def test_trace_table_gives_titles_more_space_and_full_name_tooltip(self, qapp):
        widget = self.make_plot_widget()
        trace_name = "a complete and descriptive trace title"
        widget.append_point(trace_name, 1.0, 2.0)

        assert widget._trace_table.columnWidth(1) == _TRACE_TITLE_COLUMN_WIDTH
        assert widget._trace_table.item(0, 1).toolTip() == trace_name

    def test_trace_table_not_rebuilt_when_axis_assignment_is_unchanged(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("my_trace", 1.0, 2.0)
        original_checkbox = widget._trace_table.cellWidget(0, 0)

        widget.assign_trace_axes("my_trace", "bottom", "left")

        assert widget._trace_table.cellWidget(0, 0) is original_checkbox

    def test_trace_table_not_rebuilt_when_style_is_unchanged(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("my_trace", 1.0, 2.0)
        widget.set_trace_style("my_trace", line_style="dash")
        original_selector = widget._trace_table.cellWidget(0, 3)

        widget.set_trace_style("my_trace", line_style="dash")

        assert widget._trace_table.cellWidget(0, 3) is original_selector
        assert original_selector.currentText() == "dash"

    def test_trace_table_row_removed_on_remove_trace(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("my_trace", 1.0, 2.0)
        widget.remove_trace("my_trace")
        assert widget._trace_table.rowCount() == 0

    def test_trace_table_cleared_on_clear_all(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("a", 1.0, 2.0)
        widget.append_point("b", 3.0, 4.0)
        widget.clear_all()
        assert widget._trace_table.rowCount() == 0

    def test_trace_table_height_shows_three_rows_before_scroll(self, qapp):
        widget = self.make_plot_widget()
        for trace_id in range(4):
            widget.append_point(f"trace_{trace_id}", float(trace_id), float(trace_id))

        expected_height = (
            widget._trace_table.horizontalHeader().height()
            + (_MAX_VISIBLE_TRACE_ROWS * widget._trace_table.verticalHeader().defaultSectionSize())
            + (2 * widget._trace_table.frameWidth())
        )
        assert widget._trace_table.height() == expected_height

    def test_trace_visibility_checkbox_hides_trace(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("my_trace", 1.0, 2.0)
        visible_checkbox = widget._trace_table.cellWidget(0, 0)

        visible_checkbox.setChecked(False)

        assert not widget._traces["my_trace"].isVisible()
        assert widget._trace_visible["my_trace"] is False

    def test_point_selector_uses_pictograms(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("my_trace", 1.0, 2.0)
        point_selector = widget._trace_table.cellWidget(0, 5)

        none_index = point_selector.findData("none")
        circle_index = point_selector.findData("circle")
        assert point_selector.itemText(none_index) == _POINT_PICTOGRAMS["none"]
        assert point_selector.itemText(circle_index) == _POINT_PICTOGRAMS["circle"]

    def test_colour_picker_button_updates_trace_style(self, qapp, monkeypatch):
        widget = self.make_plot_widget()
        widget.append_point("my_trace", 1.0, 2.0)
        colour_button = widget._trace_table.cellWidget(0, 2)

        def _pick_colour(*_args, **_kwargs):
            return QColor("#123456")

        monkeypatch.setattr("stoner_measurement.ui.plot_widget.QColorDialog.getColor", _pick_colour)
        colour_button.click()
        assert widget._trace_style["my_trace"]["colour"] == "#123456"

    def test_axis_columns_have_fixed_width(self, qapp):
        x_axis_column = 7
        y_axis_column = 8
        widget = self.make_plot_widget()
        header = widget._trace_table.horizontalHeader()
        assert header.sectionResizeMode(x_axis_column) == QHeaderView.ResizeMode.Fixed
        assert header.sectionResizeMode(y_axis_column) == QHeaderView.ResizeMode.Fixed

    def test_line_width_and_point_size_controls_update_trace(self, qapp):
        widget = self.make_plot_widget()
        widget.append_point("my_trace", 1.0, 2.0)

        line_width = widget._trace_table.cellWidget(0, 4)
        point_size = widget._trace_table.cellWidget(0, 6)
        line_width.setValue(4.0)
        point_size.setValue(12.0)

        assert widget._trace_line_width["my_trace"] == pytest.approx(4.0)
        assert widget._trace_point_size["my_trace"] == pytest.approx(12.0)
