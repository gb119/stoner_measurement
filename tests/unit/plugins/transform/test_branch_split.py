"""Focused tests for rising/falling trace branch splitting."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
