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
        df=pd.DataFrame({"voltage": y_arr}, index=pd.Index(x_arr, name="x")),
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
                    "voltage": [-2.0, -1.0, 1.0, 2.0],
                    "resistance": [10.0, 11.0, 12.0, 13.0],
                    "x_error": [0.1, 0.1, 0.2, 0.2],
                    "y_error": [0.3, 0.4, 0.5, 0.6],
                },
                index=pd.Index([1.0, 2.0, 3.0, 4.0], name="field_setpoint"),
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
        pd.testing.assert_frame_equal(corrected.df.reset_index(drop=True), source.df.reset_index(drop=True))
        assert corrected.df.index.name == "field_setpoint"
        assert corrected.column_roles == source.column_roles
        assert corrected.names == source.names
        assert corrected.units == source.units
        pd.testing.assert_frame_equal(source.df, original_df)

        corrected.df.loc[corrected.df.index[0], "resistance"] = -999.0
        assert source.df.iloc[0]["resistance"] == pytest.approx(10.0)

    def test_selected_data_column_is_offset_without_changing_x_or_other_columns(self, engine):
        source = TraceData(
            df=pd.DataFrame(
                {
                    "voltage": [-2.0, -1.0, 1.0, 2.0],
                    "resistance": [10.0, 11.0, 12.0, 13.0],
                },
                index=pd.Index([1.0, 2.0, 3.0, 4.0], name="field"),
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

    def test_column_selector_defaults_to_x_and_lists_all_trace_columns(
        self, engine, managed_qt_widget
    ):
        source = TraceData(
            df=pd.DataFrame(
                {"voltage": [1.0], "resistance": [2.0]},
                index=pd.Index([0.0], name="field"),
            ),
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
