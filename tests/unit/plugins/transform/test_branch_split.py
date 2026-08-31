"""Focused tests for rising/falling trace branch splitting."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QComboBox, QFormLayout, QLineEdit, QListWidget

from stoner_measurement.core import TraceData
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.transform.branch_split import (
    CHANNELS_SELECTED,
    BranchSplitPlugin,
)


def _attach_source(engine, plugin: BranchSplitPlugin, frame: pd.DataFrame, roles: dict[str, str]):
    trace = TraceData(frame, column_roles=roles)
    engine.add_plugin("branch_split", plugin)
    engine._namespace["source_trace"] = trace  # noqa: SLF001
    engine._namespace["_traces"] = {"measurement": "source_trace"}  # noqa: SLF001
    plugin.trace_key = "measurement"
    return trace


def test_splits_noisy_multi_cycle_trace_by_x_direction(engine):
    legs = [
        np.linspace(-2.0, 2.0, 31),
        np.linspace(2.0, -2.0, 31)[1:],
        np.linspace(-2.0, 2.0, 31)[1:],
        np.linspace(2.0, -2.0, 31)[1:],
    ]
    x = np.concatenate(legs)
    x += 0.005 * np.sin(np.arange(len(x)) * 2.3)
    row = np.arange(len(x))
    plugin = BranchSplitPlugin()
    plugin.smoothing_window = 7
    plugin.turning_point_prominence = 0.05
    _attach_source(
        engine,
        plugin,
        pd.DataFrame({"field": x, "signal": 3.0 * x, "row": row}),
        {"field": "x", "signal": "y", "row": "z"},
    )

    result = plugin.transform({})

    assert plugin.branch_directions == [1, -1, 1, -1]
    assert len(plugin.turning_points) == 3
    np.testing.assert_array_equal(result["rising"].df["row"], np.r_[row[:31], row[61:91]])
    np.testing.assert_array_equal(result["falling"].df["row"], np.r_[row[31:61], row[91:]])


def test_selected_data_channel_can_be_independent_variable(engine):
    voltage = np.r_[np.linspace(-1.0, 1.0, 21), np.linspace(1.0, -1.0, 21)[1:]]
    time = np.arange(len(voltage), dtype=float)
    plugin = BranchSplitPlugin()
    plugin.x_channel_key = ""
    plugin.channel_mode = CHANNELS_SELECTED
    plugin.channel_keys = ["resistance"]
    _attach_source(
        engine,
        plugin,
        pd.DataFrame({"time": time, "voltage": voltage, "resistance": 5.0 + voltage}),
        {"time": "x", "voltage": "y", "resistance": "z"},
    )

    result = plugin.transform({})

    assert result["rising"].columns == ["voltage", "resistance"]
    assert result["rising"].column_roles == {"voltage": "x", "resistance": "z"}
    assert np.all(np.diff(result["rising"].x) > 0)
    assert np.all(np.diff(result["falling"].x) < 0)


def test_split_branches_preserve_source_channel_units(engine):
    field = np.r_[np.linspace(-1.0, 1.0, 21), np.linspace(1.0, -1.0, 21)[1:]]
    plugin = BranchSplitPlugin()
    source = _attach_source(
        engine,
        plugin,
        pd.DataFrame(
            {
                "field": field,
                "voltage": 2.0 * field,
                "resistance": 10.0 + field,
            }
        ),
        {"field": "x", "voltage": "y", "resistance": "z"},
    )
    source.units.update({"field": "T", "voltage": "V", "resistance": "Ω"})

    result = plugin.transform({})

    expected_units = {"field": "T", "voltage": "V", "resistance": "Ω"}
    assert result["rising"].units == expected_units
    assert result["falling"].units == expected_units


def test_configuration_and_custom_output_names_round_trip(qapp):
    plugin = BranchSplitPlugin()
    plugin.channel_mode = CHANNELS_SELECTED
    plugin.x_channel_key = "voltage"
    plugin.channel_keys = ["resistance"]
    plugin.rising_trace_name = "up"
    plugin.falling_trace_name = "down"
    plugin.minimum_branch_length = 20

    restored = BasePlugin.from_json(plugin.to_json())

    assert isinstance(restored, BranchSplitPlugin)
    assert restored.x_channel_key == "voltage"
    assert restored.channel_keys == ["resistance"]
    assert restored.output_trace_names == ["up", "down"]
    assert restored.minimum_branch_length == 20


@pytest.mark.parametrize(
    "x",
    [
        np.array([0.0, 1.0]),
        np.array([0.0, np.nan, 1.0]),
        np.linspace(0.0, 1.0, 20),
    ],
)
def test_invalid_or_single_direction_source_returns_no_outputs(engine, x):
    plugin = BranchSplitPlugin()
    _attach_source(
        engine,
        plugin,
        pd.DataFrame({"field": x, "signal": np.arange(len(x), dtype=float)}),
        {"field": "x", "signal": "y"},
    )

    assert plugin.transform({}) == {}


def test_missing_selected_x_channel_returns_no_outputs(engine):
    x = np.r_[np.linspace(-1.0, 1.0, 11), np.linspace(1.0, -1.0, 11)[1:]]
    plugin = BranchSplitPlugin()
    plugin.x_channel_key = "missing"
    _attach_source(
        engine,
        plugin,
        pd.DataFrame({"field": x, "signal": 2 * x}),
        {"field": "x", "signal": "y"},
    )

    assert plugin.transform({}) == {}


def test_missing_selected_output_channels_returns_no_outputs(engine):
    x = np.r_[np.linspace(-1.0, 1.0, 11), np.linspace(1.0, -1.0, 11)[1:]]
    plugin = BranchSplitPlugin()
    plugin.channel_mode = CHANNELS_SELECTED
    plugin.channel_keys = ["missing"]
    _attach_source(
        engine,
        plugin,
        pd.DataFrame({"field": x, "signal": 2 * x}),
        {"field": "x", "signal": "y"},
    )

    assert plugin.transform({}) == {}


@pytest.mark.parametrize(
    ("rising", "falling"),
    [("", "falling"), ("rising", "  "), ("same", "same")],
)
def test_invalid_output_names_return_no_outputs(engine, rising, falling):
    x = np.r_[np.linspace(-1.0, 1.0, 11), np.linspace(1.0, -1.0, 11)[1:]]
    plugin = BranchSplitPlugin()
    plugin.rising_trace_name = rising
    plugin.falling_trace_name = falling
    _attach_source(
        engine,
        plugin,
        pd.DataFrame({"field": x, "signal": 2 * x}),
        {"field": "x", "signal": "y"},
    )

    assert plugin.transform({}) == {}


def test_selected_output_channels_are_deduplicated(engine):
    x = np.r_[np.linspace(-1.0, 1.0, 21), np.linspace(1.0, -1.0, 21)[1:]]
    plugin = BranchSplitPlugin()
    plugin.channel_mode = CHANNELS_SELECTED
    plugin.channel_keys = ["signal", "signal", "auxiliary"]
    _attach_source(
        engine,
        plugin,
        pd.DataFrame({"field": x, "signal": 2 * x, "auxiliary": 3 * x}),
        {"field": "x", "signal": "y", "auxiliary": "z"},
    )

    result = plugin.transform({})

    assert result["rising"].columns == ["field", "signal", "auxiliary"]
    assert result["falling"].columns == ["field", "signal", "auxiliary"]


def test_default_json_omits_advanced_values_and_invalid_mode_restores_to_all(qapp):
    plugin = BranchSplitPlugin()
    data = plugin.to_json()

    assert "smoothing_window" not in data
    assert "smoothing_polyorder" not in data
    assert "turning_point_prominence" not in data
    assert "minimum_branch_length" not in data

    plugin._restore_from_json({"channel_mode": "invalid", "channel_keys": "not a list"})  # noqa: SLF001

    assert plugin.channel_mode == "all"
    assert plugin.channel_keys == []


def test_advanced_configuration_controls_update_branch_settings(qapp, managed_qt_widget):
    plugin = BranchSplitPlugin()
    widget = managed_qt_widget(plugin._build_advanced_tab())  # noqa: SLF001
    controls = [
        widget.layout().itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
        for row in range(4)
    ]

    controls[0].setValue(9)
    controls[1].setValue(3)
    controls[2].setValue(0.25)
    controls[3].setValue(12)

    assert plugin.smoothing_window == 9
    assert plugin.smoothing_polyorder == 3
    assert plugin.turning_point_prominence == pytest.approx(0.25)
    assert plugin.minimum_branch_length == 12


def test_data_configuration_selects_x_outputs_and_trace_names(
    engine, qapp, managed_qt_widget
):
    x = np.r_[np.linspace(-1.0, 1.0, 11), np.linspace(1.0, -1.0, 11)[1:]]
    plugin = BranchSplitPlugin()
    _attach_source(
        engine,
        plugin,
        pd.DataFrame({"field": x, "signal": 2 * x, "auxiliary": 3 * x}),
        {"field": "x", "signal": "y", "auxiliary": "z"},
    )
    widget = managed_qt_widget(plugin._build_data_tab())  # noqa: SLF001
    layout = widget.layout()
    mode = widget.findChild(QComboBox, "branch_split_channel_mode")
    x_channel = widget.findChild(QComboBox, "branch_split_x_channel")
    channels = widget.findChild(QListWidget, "branch_split_channels")
    rising_name = widget.findChild(QLineEdit, "rising_trace_name")
    falling_name = widget.findChild(QLineEdit, "falling_trace_name")

    assert all(layout.indexOf(combo) >= 0 for combo in widget.findChildren(QComboBox))
    assert channels.isEnabled() is False
    mode.setCurrentIndex(mode.findData(CHANNELS_SELECTED))
    x_channel.setCurrentIndex(x_channel.findData(""))

    assert plugin.channel_mode == CHANNELS_SELECTED
    assert plugin.x_channel_key == ""
    assert channels.isEnabled() is True
    assert all(
        channels.item(row).data(Qt.ItemDataRole.UserRole) != ""
        for row in range(channels.count())
    )

    first = channels.item(0)
    first.setCheckState(Qt.CheckState.Unchecked)
    assert str(first.data(Qt.ItemDataRole.UserRole)) not in plugin.channel_keys

    rising_name.setText("up")
    rising_name.editingFinished.emit()
    falling_name.setText("down")
    falling_name.editingFinished.emit()

    assert plugin.output_trace_names == ["up", "down"]


def test_about_documentation_describes_configuration_and_outputs(qapp):
    html = BranchSplitPlugin()._about_html()  # noqa: SLF001

    assert html is not None
    assert "General" in html
    assert "Advanced" in html
    assert "rising" in html
    assert "falling" in html


def test_blank_output_name_in_configuration_uses_default(
    engine, qapp, managed_qt_widget
):
    x = np.r_[np.linspace(-1.0, 1.0, 11), np.linspace(1.0, -1.0, 11)[1:]]
    plugin = BranchSplitPlugin()
    _attach_source(
        engine,
        plugin,
        pd.DataFrame({"field": x, "signal": 2 * x}),
        {"field": "x", "signal": "y"},
    )
    widget = managed_qt_widget(plugin._build_data_tab())  # noqa: SLF001
    rising_name = widget.findChild(QLineEdit, "rising_trace_name")

    rising_name.clear()
    rising_name.editingFinished.emit()

    assert plugin.rising_trace_name == "rising"
    assert rising_name.text() == "rising"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
