"""Custom headers across state collection, schemas and configuration."""

import pytest
from qtpy.QtWidgets import QLineEdit

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.state.output_selection import OutputSelectionTable
from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.plugins.state_sweep import SweepTimePlugin
from stoner_measurement.plugins.trace_catalog_ui import trace_channel_items, trace_channel_roles


@pytest.mark.parametrize("plugin_class", [CounterPlugin, SweepTimePlugin])
@pytest.mark.parametrize("role", ["x", "y", "z", "d", "e", "f", "p", "q", "r", "-"])
def test_labels_match_schema_collection_and_catalogue(engine, plugin_class, role):
    plugin = plugin_class()
    plugin.instance_name = "axis"
    source = CounterPlugin()
    source.instance_name = "readback"
    engine.add_plugin("axis", plugin)
    engine.add_plugin("readback", source)
    key = f"{source.instance_name}:Value"
    plugin.collect_data = True
    plugin.collect_outputs = [key]
    plugin.collect_output_roles = {key: role} if role != "-" else {}
    plugin.collect_output_labels = {key: "Measured value"}
    plugin.collect_filter = "True"
    plugin.meas_flag = True
    engine.update_step_plugin_catalog([plugin, source])
    schema = plugin._configured_collected_trace()
    assert "Measured value" in schema.columns
    expected_role = role if role != "-" else "z"
    assert schema.column_roles["Measured value"] == expected_role
    items = trace_channel_items(plugin, engine.traces_catalog)
    channel = next(expr for label, expr in items.items() if "Measured value" in label)
    assert trace_channel_roles(plugin, engine.traces_catalog)[channel] == expected_role
    for value in [3.0, 5.0]:
        source.value = value
        plugin.collect()
    assert plugin.data.df["Measured value"].tolist() == [3.0, 5.0]
    assert plugin.data.columns == schema.columns
    assert plugin.data.column_roles == schema.column_roles
    assert plugin.data.names == schema.names
    assert plugin.data.units == schema.units
    saved = plugin.to_json()
    assert saved.get("collect_output_roles", {}) == plugin.collect_output_roles
    restored = BasePlugin.from_json(saved)
    assert restored.collect_output_labels == plugin.collect_output_labels
    assert restored.collect_output_roles == plugin.collect_output_roles
    legacy = plugin.to_json()
    legacy.pop("collect_output_labels")
    assert BasePlugin.from_json(legacy).collect_output_labels == {}
    plugin.collect_output_labels = {key: "  "}
    assert ("x" if role == "x" else key) in plugin._configured_collected_trace().columns


@pytest.mark.parametrize("label", ["iteration", "stage", "state", "x", "other:Value"])
def test_labels_cannot_overwrite_columns(engine, label):
    plugin = CounterPlugin()
    engine.add_plugin("axis", plugin)
    plugin.engine_namespace["_values"] = {"one:Value": "1", "other:Value": "2"}
    plugin.collect_output_labels = {"one:Value": label}
    with pytest.raises(ValueError, match="duplicate or reserved"):
        plugin._configured_collected_trace()


@pytest.mark.parametrize("plugin_class", [CounterPlugin, SweepTimePlugin])
def test_label_editor_survives_refresh_and_selection(
    engine, plugin_class, managed_plugin_config_tabs
):
    plugin = plugin_class()
    engine.add_plugin("axis", plugin)
    engine.update_step_plugin_catalog([plugin])
    pages = managed_plugin_config_tabs(plugin)
    table = next(
        page.findChild(OutputSelectionTable)
        for _, page in pages
        if page.findChild(OutputSelectionTable)
    )
    key = table.item(0, 1).text()
    role_combo = table.cellWidget(0, 3)
    assert {"z", "f", "p", "q", "r"} <= {
        role_combo.itemText(index) for index in range(role_combo.count())
    }
    role_combo.setCurrentText("f")
    assert plugin.to_json()["collect_output_roles"] == {key: "f"}
    editor = table.cellWidget(0, 2)
    assert isinstance(editor, QLineEdit)
    editor.setText("Custom reading")
    table._checks[key].setChecked(False)
    table.refresh()
    table.select_all_with_heuristics()
    assert table.cellWidget(0, 2).text() == "Custom reading"
    assert plugin.collect_output_labels[key] == "Custom reading"
    table.cellWidget(0, 2).setText("")
    assert key not in plugin.collect_output_labels


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
