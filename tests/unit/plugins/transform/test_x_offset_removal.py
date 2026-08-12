"""Tests for the x-offset removal transform."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from qtpy.QtWidgets import QComboBox

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.transform.voltage_offset import (
    METHOD_MEAN,
    METHOD_NEAR_ZERO_Y,
    METHOD_RANGE_MIDPOINT,
    XOffsetRemovalPlugin,
)
from stoner_measurement.ui.widgets import SISpinBox


def _selected_data(x, y):
    return np.asarray(x), np.asarray(y), "voltage", {"x": "Field", "voltage": "Voltage"}, {
        "x": "T",
        "voltage": "V",
    }


class TestXOffsetRemovalPlugin:
    def test_defaults_and_outputs(self, qapp):
        plugin = XOffsetRemovalPlugin()
        assert plugin.name == "X Offset Removal"
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
        plugin.method = METHOD_NEAR_ZERO_Y
        plugin.factor = 0.0
        with patch.object(
            plugin,
            "_get_selected_data_arrays",
            return_value=_selected_data([1.0, 2.0], [-1.0, 1.0]),
        ):
            assert plugin.transform({}) == {}

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
