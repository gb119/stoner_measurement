"""Tests for DataFrameTracePlugin."""

from __future__ import annotations

import numpy as np
import pandas as pd
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QTableWidget

from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.plugins.trace import DataFrameTracePlugin
from stoner_measurement.plugins.trace.base import (
    COLUMN_ROLE_D,
    COLUMN_ROLE_E,
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
)


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


def test_run_builds_multicolumn_trace_from_state_dataframe(engine):
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


def test_run_uses_selected_column_as_x_axis(engine):
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


def test_run_deduplicates_selected_output_columns(engine):
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
    tables = settings.findChildren(QTableWidget)
    assert tables, "Expected a QTableWidget for column selection."
    assert tables[0].rowCount() >= 2


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
    tables = settings.findChildren(QTableWidget)
    assert tables, "Expected a QTableWidget for column selection."

    assert trace.selected_columns == ["stage", "signal_a", "signal_b"]
    selected_items = [
        tables[0].item(row, 1).text()
        for row in range(tables[0].rowCount())
        if tables[0].item(row, 0).checkState() == Qt.CheckState.Checked
    ]
    assert selected_items == ["stage", "signal_a", "signal_b"]


def test_run_applies_configured_column_roles(engine):
    source = _make_counter_with_data()
    trace = DataFrameTracePlugin()
    engine.add_plugin("counter", source)
    engine.add_plugin("dataframe_trace", trace)
    engine.update_step_plugin_catalog([source, trace])

    trace.source_plugin = source.instance_name
    trace.x_source = "__index__"
    trace.selected_columns = ["signal_a", "signal_b"]
    trace.selected_column_roles = {"signal_a": COLUMN_ROLE_E, "signal_b": COLUMN_ROLE_D}

    result = trace.run({})
    td = result[source.instance_name]

    # At least one y-role must exist; first selected column is promoted to y.
    assert td.column_roles["signal_a"] == COLUMN_ROLE_Y
    assert td.column_roles["signal_b"] == COLUMN_ROLE_D


def test_run_maps_error_roles_when_y_column_present(engine):
    source = _make_counter_with_data()
    trace = DataFrameTracePlugin()
    engine.add_plugin("counter", source)
    engine.add_plugin("dataframe_trace", trace)
    engine.update_step_plugin_catalog([source, trace])

    trace.source_plugin = source.instance_name
    trace.x_source = "__index__"
    trace.selected_columns = ["signal_a", "signal_b", "stage"]
    trace.selected_column_roles = {
        "signal_a": COLUMN_ROLE_Y,
        "signal_b": COLUMN_ROLE_E,
        "stage": COLUMN_ROLE_D,
    }

    result = trace.run({})
    td = result[source.instance_name]

    assert td.column_roles["signal_a"] == COLUMN_ROLE_Y
    assert td.column_roles["signal_b"] == COLUMN_ROLE_E
    assert td.column_roles["stage"] == COLUMN_ROLE_D


def test_json_round_trip_preserves_dataframe_selection():
    trace = DataFrameTracePlugin()
    trace.source_plugin = "counter"
    trace.x_source = "value"
    trace.selected_columns = ["signal_a", "signal_b"]
    trace.selected_column_roles = {"signal_a": COLUMN_ROLE_Y, "signal_b": COLUMN_ROLE_E}

    payload = trace.to_json()
    restored = DataFrameTracePlugin()
    restored._restore_from_json(payload)  # noqa: SLF001

    assert restored.source_plugin == "counter"
    assert restored.x_source == "value"
    assert restored.selected_columns == ["signal_a", "signal_b"]
    assert restored.selected_column_roles == {"signal_a": COLUMN_ROLE_Y, "signal_b": COLUMN_ROLE_E}


def test_is_transform_plugin_without_scan_tab():
    trace = DataFrameTracePlugin()
    tabs = trace.config_tabs()
    assert tabs[0][0] == "Data"
    assert all("Scan" not in title for title, _ in tabs)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "--pdb"]))
