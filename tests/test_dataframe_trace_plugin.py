"""Tests for DataFrameTracePlugin."""

from __future__ import annotations

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QListWidget

from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.plugins.trace import DataFrameTracePlugin
from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, COLUMN_ROLE_Z


def _make_counter_with_data() -> CounterPlugin:
    plugin = CounterPlugin()
    plugin.collect_data = True
    plugin._data = pd.DataFrame(  # noqa: SLF001
        {
            "value": [0.0, 1.0, 2.0],
            "stage": [0, 0, 0],
            "signal_a": [10.0, 11.0, 12.0],
            "signal_b": [20.0, 21.0, 22.0],
        },
        index=pd.Index([0, 1, 2], name="ix"),
    )
    return plugin


def test_measure_builds_multicolumn_trace_from_state_dataframe(engine):
    source = _make_counter_with_data()
    trace = DataFrameTracePlugin()
    engine.add_plugin("counter", source)
    engine.add_plugin("dataframe_trace", trace)
    engine.update_step_plugin_catalog([source, trace])

    trace.source_plugin = source.instance_name
    trace.x_source = "__index__"
    trace.selected_columns = ["signal_a", "signal_b"]

    result = trace.run({})

    assert list(result.keys()) == [source.instance_name]
    td = result[source.instance_name]
    np.testing.assert_allclose(td.x, np.array([0.0, 1.0, 2.0]))
    np.testing.assert_allclose(td.df["signal_a"].to_numpy(dtype=float), np.array([10.0, 11.0, 12.0]))
    np.testing.assert_allclose(td.df["signal_b"].to_numpy(dtype=float), np.array([20.0, 21.0, 22.0]))
    assert td.column_roles["signal_a"] == COLUMN_ROLE_Y
    assert td.column_roles["signal_b"] == COLUMN_ROLE_Z


def test_measure_uses_selected_column_as_x_axis(engine):
    source = _make_counter_with_data()
    trace = DataFrameTracePlugin()
    engine.add_plugin("counter", source)
    engine.add_plugin("dataframe_trace", trace)
    engine.update_step_plugin_catalog([source, trace])

    trace.source_plugin = source.instance_name
    trace.x_source = "value"
    trace.selected_columns = ["signal_b"]

    result = trace.run({})
    td = result[source.instance_name]

    np.testing.assert_allclose(td.x, np.array([0.0, 1.0, 2.0]))
    np.testing.assert_allclose(td.y, np.array([20.0, 21.0, 22.0]))
    assert td.names["x"] == "value"


def test_measure_deduplicates_selected_output_columns(engine):
    source = _make_counter_with_data()
    trace = DataFrameTracePlugin()
    engine.add_plugin("counter", source)
    engine.add_plugin("dataframe_trace", trace)
    engine.update_step_plugin_catalog([source, trace])

    trace.source_plugin = source.instance_name
    trace.x_source = "__index__"
    trace.selected_columns = ["signal_a", "signal_a", "signal_b"]

    result = trace.run({})
    td = result[source.instance_name]

    assert list(td.df.columns) == ["signal_a", "signal_b"]
    assert td.column_roles["signal_a"] == COLUMN_ROLE_Y
    assert td.column_roles["signal_b"] == COLUMN_ROLE_Z


def test_data_tab_lists_available_columns_from_catalogue(engine):
    source = _make_counter_with_data()
    trace = DataFrameTracePlugin()
    engine.add_plugin("counter", source)
    engine.add_plugin("dataframe_trace", trace)
    engine.update_step_plugin_catalog([source, trace])
    trace.source_plugin = source.instance_name

    settings = trace._build_data_tab()  # noqa: SLF001
    lists = settings.findChildren(QListWidget)
    assert lists, "Expected a QListWidget for column selection."
    assert lists[0].count() >= 2


def test_data_tab_sanitises_stale_selected_columns(engine):
    source = _make_counter_with_data()
    trace = DataFrameTracePlugin()
    engine.add_plugin("counter", source)
    engine.add_plugin("dataframe_trace", trace)
    engine.update_step_plugin_catalog([source, trace])

    trace.source_plugin = source.instance_name
    trace.x_source = "value"
    trace.selected_columns = ["missing_column"]

    settings = trace._build_data_tab()  # noqa: SLF001
    lists = settings.findChildren(QListWidget)
    assert lists, "Expected a QListWidget for column selection."

    assert trace.selected_columns == ["stage", "signal_a", "signal_b"]
    selected_items = [
        lists[0].item(row).text()
        for row in range(lists[0].count())
        if lists[0].item(row).isSelected()
    ]
    assert selected_items == ["stage", "signal_a", "signal_b"]


def test_json_round_trip_preserves_dataframe_selection():
    trace = DataFrameTracePlugin()
    trace.source_plugin = "counter"
    trace.x_source = "value"
    trace.selected_columns = ["signal_a", "signal_b"]

    payload = trace.to_json()
    restored = DataFrameTracePlugin()
    restored._restore_from_json(payload)  # noqa: SLF001

    assert restored.source_plugin == "counter"
    assert restored.x_source == "value"
    assert restored.selected_columns == ["signal_a", "signal_b"]


def test_is_transform_plugin_without_scan_tab():
    trace = DataFrameTracePlugin()
    tabs = trace.config_tabs()
    assert tabs[0][0] == "Data"
    assert all("Scan" not in title for title, _ in tabs)
