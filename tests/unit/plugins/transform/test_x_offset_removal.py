"""Tests for the x-offset removal transform."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from qtpy.QtWidgets import QComboBox, QWidget

from stoner_measurement.core.trace_data import (
    COLUMN_ROLE_D,
    COLUMN_ROLE_E,
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
)
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.transform.voltage_offset import (
    METHOD_MEAN,
    METHOD_NEAR_ZERO_Y,
    METHOD_RANGE_MIDPOINT,
    XOffsetRemovalPlugin,
)
from stoner_measurement.ui.widgets import SISpinBox


def _selected_data(x, y):
    x_arr = np.asarray(x)
    y_arr = np.asarray(y)
    source = TraceData(
        df=pd.DataFrame({"x": x_arr, "voltage": y_arr}),
        column_roles={"voltage": COLUMN_ROLE_Y},
        names={"x": "Field", "voltage": "Voltage"},
        units={"x": "T", "voltage": "V"},
    )
    return (
        x_arr,
        y_arr,
        "x",
        dict(source.names),
        dict(source.units),
        source,
    )


class TestXOffsetRemovalPlugin:
    def test_defaults_and_outputs(self, qapp):
        plugin = XOffsetRemovalPlugin()
        assert plugin.name == "X Offset Removal"
        assert plugin.column_key == "x"
        assert plugin.method == METHOD_MEAN
        assert plugin.factor == 0.05
        assert plugin.output_trace_names == ["offset_removed"]
        assert plugin.output_value_names == ["dx"]

    @pytest.mark.parametrize(
        ("method", "expected"),
        [
            (METHOD_MEAN, 2.5),
            (METHOD_RANGE_MIDPOINT, 2.5),
        ],
    )
    def test_mean_and_range_midpoint_methods(self, qapp, method, expected):
        plugin = XOffsetRemovalPlugin()
        plugin.advanced_mode = True
        plugin.method = method
        with patch.object(
            plugin,
            "_get_selected_data_arrays",
            return_value=_selected_data([1.0, 2.0, 3.0, 4.0], [-2.0, -1.0, 1.0, 2.0]),
        ):
            result = plugin.transform({})

        assert result["dx"] == pytest.approx(expected)
        assert result["offset_removed"].x.tolist() == pytest.approx(
            [-1.5, -0.5, 0.5, 1.5]
        )
        assert result["offset_removed"].y.tolist() == pytest.approx([-2.0, -1.0, 1.0, 2.0])
        assert result["offset_removed"].units == {"x": "T", "voltage": "V"}

    def test_near_zero_y_method_uses_factor(self, qapp):
        plugin = XOffsetRemovalPlugin()
        plugin.advanced_mode = True
        plugin.method = METHOD_NEAR_ZERO_Y
        plugin.factor = 0.05
        with patch.object(
            plugin,
            "_get_selected_data_arrays",
            return_value=_selected_data(
                [8.0, 9.0, 10.0, 11.0, 12.0], [-10.0, -0.2, 0.0, 0.2, 10.0]
            ),
        ):
            result = plugin.transform({})

        assert result["dx"] == pytest.approx(10.0)
        assert result["offset_removed"].x.tolist() == pytest.approx(
            [-2.0, -1.0, 0.0, 1.0, 2.0]
        )

    def test_near_zero_y_returns_empty_when_mask_has_no_points(self, qapp):
        plugin = XOffsetRemovalPlugin()
        plugin.advanced_mode = True
        plugin.method = METHOD_NEAR_ZERO_Y
        plugin.factor = 0.0
        with patch.object(
            plugin,
            "_get_selected_data_arrays",
            return_value=_selected_data([1.0, 2.0], [-1.0, 1.0]),
        ):
            assert plugin.transform({}) == {}

    def test_simple_mode_copies_complete_trace_and_only_replaces_x(self, engine):
        source = TraceData(
            df=pd.DataFrame(
                {
                    "x": [1.0, 2.0, 3.0, 4.0],
                    "voltage": [-2.0, -1.0, 1.0, 2.0],
                    "resistance": [10.0, 11.0, 12.0, 13.0],
                    "x_error": [0.1, 0.1, 0.2, 0.2],
                    "y_error": [0.3, 0.4, 0.5, 0.6],
                }
            ),
            column_roles={
                "voltage": COLUMN_ROLE_Y,
                "resistance": COLUMN_ROLE_Z,
                "x_error": COLUMN_ROLE_D,
                "y_error": COLUMN_ROLE_E,
            },
            names={
                "x": "Field",
                "voltage": "Voltage",
                "resistance": "Resistance",
                "x_error": "Field uncertainty",
                "y_error": "Voltage uncertainty",
            },
            units={
                "x": "T",
                "voltage": "V",
                "resistance": "ohm",
                "x_error": "T",
                "y_error": "V",
            },
        )
        original_df = source.df.copy(deep=True)
        plugin = XOffsetRemovalPlugin()
        engine.add_plugin("x_offset_removal", plugin)
        engine._namespace["source_trace"] = source
        engine._namespace["_traces"] = {"measurement": "source_trace"}
        plugin.trace_key = "measurement"
        plugin.column_key = "x"

        result = plugin.transform({})
        corrected = result["offset_removed"]

        assert result["dx"] == pytest.approx(2.5)
        np.testing.assert_allclose(corrected.x, [-1.5, -0.5, 0.5, 1.5])
        pd.testing.assert_frame_equal(
            corrected.df.drop(columns="x"), source.df.drop(columns="x")
        )
        assert isinstance(corrected.df.index, pd.RangeIndex)
        assert corrected.column_roles == source.column_roles
        assert corrected.names == source.names
        assert corrected.units == source.units
        assert corrected is not source
        assert corrected.df is not source.df
        assert corrected.column_roles is not source.column_roles
        assert corrected.names is not source.names
        assert corrected.units is not source.units
        pd.testing.assert_frame_equal(source.df, original_df)

        corrected.df.loc[corrected.df.index[0], "resistance"] = -999.0
        corrected.names["resistance"] = "Changed"
        corrected.units["resistance"] = "changed"
        corrected.column_roles["resistance"] = COLUMN_ROLE_Y
        assert source.df.iloc[0]["resistance"] == pytest.approx(10.0)
        assert source.names["resistance"] == "Resistance"
        assert source.units["resistance"] == "ohm"
        assert source.column_roles["resistance"] == COLUMN_ROLE_Z

    def test_selected_data_column_is_offset_without_changing_x_or_other_columns(self, engine):
        source = TraceData(
            df=pd.DataFrame(
                {
                    "x": [1.0, 2.0, 3.0, 4.0],
                    "voltage": [-2.0, -1.0, 1.0, 2.0],
                    "resistance": [10.0, 11.0, 12.0, 13.0],
                }
            ),
            column_roles={"voltage": COLUMN_ROLE_Y, "resistance": COLUMN_ROLE_Z},
        )
        original_df = source.df.copy(deep=True)
        plugin = XOffsetRemovalPlugin()
        engine.add_plugin("x_offset_removal", plugin)
        engine._namespace["source_trace"] = source
        engine._namespace["_traces"] = {"measurement": "source_trace"}
        plugin.trace_key = "measurement"
        plugin.column_key = "resistance"

        corrected = plugin.transform({})["offset_removed"]

        np.testing.assert_allclose(corrected.x, source.x)
        np.testing.assert_allclose(corrected.df["resistance"], [-1.5, -0.5, 0.5, 1.5])
        np.testing.assert_allclose(corrected.df["voltage"], source.df["voltage"])
        pd.testing.assert_frame_equal(source.df, original_df)

    def test_advanced_mode_calculates_on_one_trace_and_applies_to_another(self, engine):
        calibration = TraceData.from_xy(
            np.array([1.0, 2.0, 3.0]), np.array([-1.0, 0.0, 1.0])
        )
        target = TraceData.from_xy(
            np.array([10.0, 11.0, 12.0, 13.0, 14.0]),
            np.array([5.0, 4.0, 3.0, 2.0, 1.0]),
        )
        plugin = XOffsetRemovalPlugin()
        engine.add_plugin("x_offset_removal", plugin)
        engine._namespace["calibration"] = calibration
        engine._namespace["target"] = target
        engine._namespace["_traces"] = {"target": "target"}
        plugin.trace_key = "target"
        plugin.column_key = "x"
        plugin.advanced_mode = True
        plugin.x_expr = "calibration.x"
        plugin.y_expr = "calibration.y"

        result = plugin.transform({})

        assert result["dx"] == pytest.approx(2.0)
        np.testing.assert_allclose(result["offset_removed"].x, [8.0, 9.0, 10.0, 11.0, 12.0])
        np.testing.assert_array_equal(result["offset_removed"].y, target.y)

    def test_6221_2182_x_noise_is_shifted_without_being_smoothed(self, engine):
        source_x = np.array([-2.02, -0.97, -0.04, 1.03, 1.98])
        source = TraceData(
            pd.DataFrame(
                {
                    "x": source_x,
                    "V": [-2.1, -1.2, 0.05, 0.9, 2.2],
                    "R": [1.04, 1.24, -1.25, 0.87, 1.11],
                    "P": [4.24, 1.16, -0.002, 0.93, 4.36],
                }
            ),
            column_roles={"V": COLUMN_ROLE_Y, "R": COLUMN_ROLE_Z, "P": COLUMN_ROLE_Z},
        )
        plugin = XOffsetRemovalPlugin()
        engine.add_plugin("x_offset_removal", plugin)
        engine._namespace["source_trace"] = source
        engine._namespace["_traces"] = {"6221-2182:IV": "source_trace"}
        plugin.trace_key = "6221-2182:IV"
        plugin.column_key = "x"

        corrected = plugin.transform({})["offset_removed"]

        expected_x = source_x - np.mean(source_x)
        np.testing.assert_array_equal(corrected.x, expected_x)
        np.testing.assert_array_equal(np.diff(corrected.x), np.diff(source_x))
        pd.testing.assert_frame_equal(
            corrected.df[["V", "R", "P"]], source.df[["V", "R", "P"]]
        )

    def test_column_selector_defaults_to_x_and_lists_all_trace_columns(
        self, engine, managed_qt_widget
    ):
        source = TraceData(
            df=pd.DataFrame({"x": [0.0], "voltage": [1.0], "resistance": [2.0]}),
            names={"x": "Field", "voltage": "Voltage", "resistance": "Resistance"},
            units={"x": "T", "voltage": "V", "resistance": "ohm"},
        )
        plugin = XOffsetRemovalPlugin()
        engine.add_plugin("x_offset_removal", plugin)
        engine._namespace["source_trace"] = source
        engine._namespace["_traces"] = {"measurement": "source_trace"}
        plugin.trace_key = "measurement"
        widget = managed_qt_widget(QWidget())
        ws = plugin._create_data_source_widgets(widget, engine._namespace["_traces"])
        column_combo = ws["column_combo"]

        assert plugin.column_key == "x"
        assert column_combo.currentText() == "measurement:Field (T)"
        assert [column_combo.itemText(i) for i in range(column_combo.count())] == [
            "measurement:Field (T)",
            "measurement:Voltage (V)",
            "measurement:Resistance (ohm)",
        ]

    def test_dummy_target_selector_matches_advanced_channel_labels_before_acquisition(
        self, engine, managed_qt_widget
    ):
        from stoner_measurement.plugins.trace import DummyPlugin

        dummy = DummyPlugin()
        engine.add_plugin("dummy", dummy)
        engine.update_step_plugin_catalog([dummy])
        plugin = XOffsetRemovalPlugin()
        engine.add_plugin("x_offset_removal", plugin)
        plugin.trace_key = "dummy:Dummy"
        widget = managed_qt_widget(QWidget())
        ws = plugin._create_data_source_widgets(widget, engine.traces_catalog)
        target_combo = ws["column_combo"]

        assert [target_combo.itemText(i) for i in range(target_combo.count())] == [
            "dummy:Dummy:I (A)",
            "dummy:Dummy:V (V)",
        ]
        assert list(ws["channel_items"]) == [
            "dummy:Dummy:I (A)",
            "dummy:Dummy:V (V)",
        ]
        assert target_combo.currentText() == "dummy:Dummy:I (A)"
        assert target_combo.currentData() == "x"

    def test_serialisation_round_trip(self, qapp):
        plugin = XOffsetRemovalPlugin()
        plugin.trace_key = "source:trace"
        plugin.column_key = "voltage"
        plugin.advanced_mode = True
        plugin.x_expr = "source.data.x"
        plugin.y_expr = "source.data.y"
        plugin.method = METHOD_NEAR_ZERO_Y
        plugin.factor = "offset_factor"

        restored = BasePlugin.from_json(plugin.to_json())

        assert isinstance(restored, XOffsetRemovalPlugin)
        assert restored.trace_key == "source:trace"
        assert restored.column_key == "voltage"
        assert restored.advanced_mode is True
        assert restored.x_expr == "source.data.x"
        assert restored.y_expr == "source.data.y"
        assert restored.method == METHOD_NEAR_ZERO_Y
        assert restored.factor == "offset_factor"

    def test_config_tabs_use_shared_trace_selection_and_factor_control(self, qapp):
        plugin = XOffsetRemovalPlugin()
        tabs = plugin.config_tabs()
        assert [title for title, _widget in tabs][:2] == ["Data", "Offset"]
        combos = tabs[0][1].findChildren(QComboBox)
        assert len(combos) >= 4
        factor_spin = tabs[1][1].findChild(SISpinBox)
        assert factor_spin is not None
        assert factor_spin.isEnabled() is False

        method_combo = tabs[1][1].findChild(QComboBox)
        method_combo.setCurrentIndex(method_combo.findData(METHOD_NEAR_ZERO_Y))
        assert factor_spin.isEnabled() is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
