"""Tests for PlotWidget and axis configuration UI."""

from __future__ import annotations

import pytest
from qtpy.QtGui import QColor
from qtpy.QtWidgets import QDialog, QHeaderView, QLineEdit

from stoner_measurement.ui.plot_widget import (
    _MAX_VISIBLE_TRACE_ROWS,
    _POINT_PICTOGRAMS,
    AxesConfigDialog,
    PlotWidget,
)

class TestPlotWidget:
    def test_creates_widget(self, qapp):
        widget = PlotWidget()
        assert widget is not None

    def test_initial_data_empty(self, qapp):
        widget = PlotWidget()
        assert widget.x_data() == []
        assert widget.y_data() == []

    def test_append_point(self, qapp):
        widget = PlotWidget()
        widget.append_point("sig", 1.0, 2.0)
        assert widget.x_data("sig") == [1.0]
        assert widget.y_data("sig") == [2.0]

    def test_append_point_multiple_traces(self, qapp):
        widget = PlotWidget()
        widget.append_point("a", 1.0, 10.0)
        widget.append_point("b", 2.0, 20.0)
        assert widget.x_data("a") == [1.0]
        assert widget.x_data("b") == [2.0]
        assert sorted(widget.trace_names) == ["a", "b"]

    def test_set_trace(self, qapp):
        widget = PlotWidget()
        widget.set_trace("sig", [0.0, 1.0, 2.0], [3.0, 4.0, 5.0])
        assert widget.x_data("sig") == [0.0, 1.0, 2.0]
        assert widget.y_data("sig") == [3.0, 4.0, 5.0]

    def test_set_trace_replaces_data(self, qapp):
        widget = PlotWidget()
        widget.set_trace("sig", [0.0, 1.0], [2.0, 3.0])
        widget.set_trace("sig", [10.0], [20.0])
        assert widget.x_data("sig") == [10.0]
        assert widget.y_data("sig") == [20.0]

    def test_remove_trace(self, qapp):
        widget = PlotWidget()
        widget.append_point("sig", 1.0, 2.0)
        widget.remove_trace("sig")
        assert "sig" not in widget.trace_names
        assert widget.x_data("sig") == []

    def test_remove_trace_missing_noop(self, qapp):
        widget = PlotWidget()
        widget.remove_trace("nonexistent")  # should not raise

    def test_clear_all(self, qapp):
        widget = PlotWidget()
        widget.append_point("a", 1.0, 2.0)
        widget.append_point("b", 3.0, 4.0)
        widget.clear_all()
        assert widget.trace_names == []

    def test_clear_all_resets_auto_colour_cycle(self, qapp):
        widget = PlotWidget()
        widget.append_point("trace_a", 0.0, 1.0)
        widget.append_point("trace_b", 1.0, 2.0)
        first_colour = widget._trace_style["trace_a"]["colour"]
        second_colour = widget._trace_style["trace_b"]["colour"]
        widget.clear_all()
        widget.append_point("trace_c", 0.0, 1.0)
        widget.append_point("trace_d", 1.0, 2.0)
        assert widget._trace_style["trace_c"]["colour"] == first_colour
        assert widget._trace_style["trace_d"]["colour"] == second_colour

    def test_pg_widget_exists(self, qapp):
        widget = PlotWidget()
        assert widget.pg_widget is not None

    def test_default_axis_names(self, qapp):
        widget = PlotWidget()
        assert "left" in widget.axis_names
        assert "bottom" in widget.axis_names

    def test_configure_axes_button_present(self, qapp):
        widget = PlotWidget()
        assert widget._configure_axes_button.text() == "Configure Axes…"

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
                {"name": "left", "label": "Value", "log_scale": False, "grid": True, "side": "left", "visible": True, "minimum": None, "maximum": None, "removable": False}
            ],
        )
        dialog._add_name_inputs["x"].setText("left")
        dialog._add_label_inputs["x"].setText("Colliding Left")
        dialog._add_axis_row_from_inputs("x")
        changes = dialog.axis_changes()
        assert set(changes["visible_axes"]) == {"bottom", "left"}
        assert changes["labels"]["left"] == "Value"
        dialog.reject()

    def test_open_axes_dialog_applies_additions_and_removals(self, qapp, monkeypatch):
        widget = PlotWidget()
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
        assert widget._axis_items["freq"].labelText == "Frequency (Hz)"
        assert widget._axis_log_scale["freq"] is True

    def test_axis_entries_show_blank_bounds_for_auto_axes(self, qapp):
        widget = PlotWidget()
        entry = widget._axis_entries("x")[0]
        assert entry["name"] == "bottom"
        assert entry["minimum"] is None
        assert entry["maximum"] is None

    def test_set_axis_range_supports_partial_auto_bounds(self, qapp):
        widget = PlotWidget()
        widget.append_point("sig", 0.0, 1.0)
        widget.append_point("sig", 2.0, 3.0)
        widget.set_axis_range("bottom", minimum=0.5, maximum=None)
        assert widget._axis_auto_range["bottom"] == (False, True)
        assert widget._axis_manual_range["bottom"][0] == pytest.approx(0.5)
        entry = widget._axis_entries("x")[0]
        assert entry["minimum"] == pytest.approx(0.5)
        assert entry["maximum"] is None

    def test_reset_all_view_ranges_restores_full_auto_bounds(self, qapp):
        widget = PlotWidget()
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
        minimum_edit = table.cellWidget(0, 6)
        maximum_edit = table.cellWidget(0, 7)
        assert isinstance(minimum_edit, QLineEdit)
        assert isinstance(maximum_edit, QLineEdit)
        minimum_edit.setText("1.5")
        maximum_edit.setText("3.5")
        dialog._emit_range_change("x", 0)
        assert calls == [("bottom", 1.5, 3.5)]


    def test_add_y_axis(self, qapp):
        widget = PlotWidget()
        widget.add_y_axis("temperature", "Temperature (K)", side="right")
        assert "temperature" in widget.axis_names

    def test_add_y_axis_duplicate_noop(self, qapp):
        widget = PlotWidget()
        widget.add_y_axis("temp", "Temp", side="right")
        widget.add_y_axis("temp", "Other", side="right")  # should not raise
        assert widget.axis_names.count("temp") == 1

    def test_add_x_axis(self, qapp):
        widget = PlotWidget()
        widget.add_x_axis("freq", "Frequency (Hz)", position="top")
        assert "freq" in widget.axis_names

    def test_assign_trace_axes(self, qapp):
        widget = PlotWidget()
        widget.add_y_axis("temp", "Temperature (K)")
        widget.append_point("sig", 0.0, 300.0)
        widget.assign_trace_axes("sig", y_axis="temp")
        assert widget._trace_axes["sig"] == ("bottom", "temp")

    def test_assign_trace_axes_unknown_trace_raises(self, qapp):
        widget = PlotWidget()
        with pytest.raises(KeyError, match="unknown"):
            widget.assign_trace_axes("unknown", y_axis="left")

    def test_assign_trace_axes_unknown_axis_raises(self, qapp):
        widget = PlotWidget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(KeyError, match="no_such"):
            widget.assign_trace_axes("sig", y_axis="no_such")

    def test_assign_trace_axes_unknown_x_axis_raises(self, qapp):
        widget = PlotWidget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(KeyError, match="no_such_x"):
            widget.assign_trace_axes("sig", x_axis="no_such_x", y_axis="left")

    def test_assign_trace_axes_supports_independent_x_and_y_axes(self, qapp):
        widget = PlotWidget()
        widget.add_x_axis("freq", "Frequency (Hz)")
        widget.add_y_axis("temp", "Temperature (K)")
        widget.append_point("sig", 0.0, 1.0)
        widget.assign_trace_axes("sig", x_axis="freq", y_axis="temp")
        assert widget._trace_axes["sig"] == ("freq", "temp")

    def test_assign_trace_axes_moves_associated_error_bar_item(self, qapp):
        widget = PlotWidget()
        widget.add_y_axis("temp", "Temperature (K)")
        widget.set_trace_with_errors("sig", [0.0, 1.0], [2.0, 3.0], None, [0.1, 0.2])
        ebi = widget._error_bar_items["sig"]
        old_parent = ebi.parentItem()
        widget.assign_trace_axes("sig", y_axis="temp")
        assert widget._trace_axes["sig"] == ("bottom", "temp")
        assert ebi.parentItem() is not None
        assert ebi.parentItem() is not old_parent

    def test_ensure_y_axis_creates_new_axis(self, qapp):
        widget = PlotWidget()
        assert "new_axis" not in widget.axis_names
        widget.ensure_y_axis("new_axis", "New Axis (units)")
        assert "new_axis" in widget.axis_names

    def test_ensure_y_axis_is_idempotent(self, qapp):
        widget = PlotWidget()
        widget.ensure_y_axis("dup", "Duplicate")
        widget.ensure_y_axis("dup", "Duplicate")
        assert widget.axis_names.count("dup") == 1

    def test_ensure_y_axis_uses_name_as_label_fallback(self, qapp):
        widget = PlotWidget()
        widget.ensure_y_axis("my_axis")
        assert "my_axis" in widget.axis_names

    def test_ensure_y_axis_noop_for_default_left(self, qapp):
        """ensure_y_axis on the built-in 'left' axis leaves axis count unchanged."""
        widget = PlotWidget()
        initial = sorted(widget.axis_names)
        widget.ensure_y_axis("left")
        assert sorted(widget.axis_names) == initial

    def test_ensure_x_axis_creates_new_axis(self, qapp):
        widget = PlotWidget()
        assert "new_x_axis" not in widget.axis_names
        widget.ensure_x_axis("new_x_axis", "New X Axis (units)")
        assert "new_x_axis" in widget.axis_names

    def test_ensure_x_axis_is_idempotent(self, qapp):
        widget = PlotWidget()
        widget.ensure_x_axis("dup_x", "Duplicate X")
        widget.ensure_x_axis("dup_x", "Duplicate X")
        assert widget.axis_names.count("dup_x") == 1

    def test_ensure_x_axis_noop_for_default_bottom(self, qapp):
        widget = PlotWidget()
        initial = sorted(widget.axis_names)
        widget.ensure_x_axis("bottom")
        assert sorted(widget.axis_names) == initial

    def test_set_axis_label_updates_axis_title(self, qapp):
        widget = PlotWidget()
        widget.add_y_axis("temp", "Temp")
        widget.set_axis_label("temp", "Temperature (K)")
        assert widget._axis_items["temp"].labelText == "Temperature (K)"

    def test_set_axis_log_scale_updates_axis_state(self, qapp):
        widget = PlotWidget()
        widget.add_x_axis("freq", "Freq")
        widget.set_axis_log_scale("freq", True)
        assert widget._axis_log_scale["freq"] is True

    def test_set_axis_grid_updates_axis_state(self, qapp):
        widget = PlotWidget()
        widget.set_axis_grid("bottom", False)
        assert widget._axis_grid["bottom"] is False

    def test_remove_axis_rejects_default_axis(self, qapp):
        widget = PlotWidget()
        with pytest.raises(ValueError, match="default axis"):
            widget.remove_axis("left")

    def test_remove_axis_reassigns_trace_to_default(self, qapp):
        widget = PlotWidget()
        widget.add_y_axis("temp", "Temperature (K)")
        widget.append_point("sig", 0.0, 1.0)
        widget.assign_trace_axes("sig", y_axis="temp")
        widget.remove_axis("temp")
        assert widget._trace_axes["sig"] == ("bottom", "left")
        assert "temp" not in widget.axis_names

    def test_set_trace_style_updates_trace_style(self, qapp):
        widget = PlotWidget()
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
        widget = PlotWidget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(ValueError, match="line style"):
            widget.set_trace_style("sig", line_style="wiggly")

    def test_set_trace_style_rejects_unknown_point_style(self, qapp):
        widget = PlotWidget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(ValueError, match="point style"):
            widget.set_trace_style("sig", point_style="hexagon")

    def test_set_trace_style_rejects_non_positive_line_width(self, qapp):
        widget = PlotWidget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(ValueError, match="Line width"):
            widget.set_trace_style("sig", line_width=0)

    def test_set_trace_style_rejects_non_positive_point_size(self, qapp):
        widget = PlotWidget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(ValueError, match="Point size"):
            widget.set_trace_style("sig", point_size=0)

    def test_set_trace_style_rejects_invalid_colour(self, qapp):
        widget = PlotWidget()
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(ValueError, match="Invalid colour"):
            widget.set_trace_style("sig", colour="not-a-colour")

    def test_x_data_unknown_trace_returns_empty(self, qapp):
        widget = PlotWidget()
        assert widget.x_data("nonexistent") == []

    def test_y_data_unknown_trace_returns_empty(self, qapp):
        widget = PlotWidget()
        assert widget.y_data("nonexistent") == []

    def test_set_default_axis_labels_updates_bottom_axis(self, qapp):
        widget = PlotWidget()
        widget.set_default_axis_labels("Current (A)", "")
        label_text = widget._pg_widget.getPlotItem().getAxis("bottom").labelText
        assert label_text == "Current (A)"

    def test_set_default_axis_labels_updates_left_axis(self, qapp):
        widget = PlotWidget()
        widget.set_default_axis_labels("", "Voltage (V)")
        label_text = widget._pg_widget.getPlotItem().getAxis("left").labelText
        assert label_text == "Voltage (V)"

    def test_set_default_axis_labels_both(self, qapp):
        widget = PlotWidget()
        widget.set_default_axis_labels("Current (A)", "Voltage (V)")
        assert widget._pg_widget.getPlotItem().getAxis("bottom").labelText == "Current (A)"
        assert widget._pg_widget.getPlotItem().getAxis("left").labelText == "Voltage (V)"

    def test_set_default_axis_labels_empty_strings_no_change(self, qapp):
        widget = PlotWidget()
        # Default labels set in __init__
        original_bottom = widget._pg_widget.getPlotItem().getAxis("bottom").labelText
        original_left = widget._pg_widget.getPlotItem().getAxis("left").labelText
        widget.set_default_axis_labels("", "")
        # Labels should be unchanged
        assert widget._pg_widget.getPlotItem().getAxis("bottom").labelText == original_bottom
        assert widget._pg_widget.getPlotItem().getAxis("left").labelText == original_left

    def test_trace_table_exists_after_init(self, qapp):
        widget = PlotWidget()
        assert widget._trace_table is not None

    def test_trace_table_has_row_after_trace_created(self, qapp):
        widget = PlotWidget()
        widget.append_point("my_trace", 1.0, 2.0)
        assert widget._trace_table.rowCount() == 1
        assert widget._trace_table.item(0, 1).text() == "my_trace"

    def test_trace_table_row_removed_on_remove_trace(self, qapp):
        widget = PlotWidget()
        widget.append_point("my_trace", 1.0, 2.0)
        widget.remove_trace("my_trace")
        assert widget._trace_table.rowCount() == 0

    def test_trace_table_cleared_on_clear_all(self, qapp):
        widget = PlotWidget()
        widget.append_point("a", 1.0, 2.0)
        widget.append_point("b", 3.0, 4.0)
        widget.clear_all()
        assert widget._trace_table.rowCount() == 0

    def test_trace_table_height_shows_three_rows_before_scroll(self, qapp):
        widget = PlotWidget()
        for trace_id in range(4):
            widget.append_point(f"trace_{trace_id}", float(trace_id), float(trace_id))

        expected_height = (
            widget._trace_table.horizontalHeader().height()
            + (_MAX_VISIBLE_TRACE_ROWS * widget._trace_table.verticalHeader().defaultSectionSize())
            + (2 * widget._trace_table.frameWidth())
        )
        assert widget._trace_table.height() == expected_height

    def test_trace_visibility_checkbox_hides_trace(self, qapp):
        widget = PlotWidget()
        widget.append_point("my_trace", 1.0, 2.0)
        visible_checkbox = widget._trace_table.cellWidget(0, 0)

        visible_checkbox.setChecked(False)

        assert not widget._traces["my_trace"].isVisible()
        assert widget._trace_visible["my_trace"] is False

    def test_point_selector_uses_pictograms(self, qapp):
        widget = PlotWidget()
        widget.append_point("my_trace", 1.0, 2.0)
        point_selector = widget._trace_table.cellWidget(0, 5)

        none_index = point_selector.findData("none")
        circle_index = point_selector.findData("circle")
        assert point_selector.itemText(none_index) == _POINT_PICTOGRAMS["none"]
        assert point_selector.itemText(circle_index) == _POINT_PICTOGRAMS["circle"]

    def test_colour_picker_button_updates_trace_style(self, qapp, monkeypatch):
        widget = PlotWidget()
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
        widget = PlotWidget()
        header = widget._trace_table.horizontalHeader()
        assert header.sectionResizeMode(x_axis_column) == QHeaderView.ResizeMode.Fixed
        assert header.sectionResizeMode(y_axis_column) == QHeaderView.ResizeMode.Fixed

    def test_line_width_and_point_size_controls_update_trace(self, qapp):
        widget = PlotWidget()
        widget.append_point("my_trace", 1.0, 2.0)

        line_width = widget._trace_table.cellWidget(0, 4)
        point_size = widget._trace_table.cellWidget(0, 6)
        line_width.setValue(4.0)
        point_size.setValue(12.0)

        assert widget._trace_line_width["my_trace"] == pytest.approx(4.0)
        assert widget._trace_point_size["my_trace"] == pytest.approx(12.0)
