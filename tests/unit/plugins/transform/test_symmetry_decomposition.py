"""Focused tests for symmetric and antisymmetric trace decomposition."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QComboBox, QLineEdit, QListWidget, QSpinBox

from stoner_measurement.core import COLUMN_ROLE_Y, COLUMN_ROLE_Z, TraceData
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.transform.symmetry_decomposition import (
    CHANNELS_SELECTED,
    DEFAULT_INTERPOLATION,
    DEFAULT_MINIMUM_BRANCH_LENGTH,
    DEFAULT_OUT_OF_RANGE,
    DEFAULT_SMOOTHING_POLYORDER,
    DEFAULT_SMOOTHING_WINDOW,
    DEFAULT_TURNING_PROMINENCE,
    INTERPOLATION_LINEAR,
    MODE_HYSTERETIC,
    MODE_NON_HYSTERETIC,
    OUT_OF_RANGE_NEAREST,
    SymmetryDecompositionPlugin,
    _consolidate_duplicate_x,
)
from stoner_measurement.ui.widgets import SISpinBox


def _attach_source(engine, plugin, x, **channels) -> TraceData:
    frame = pd.DataFrame({"field": np.asarray(x, dtype=float), **channels})
    roles = {"field": "x"}
    for index, column in enumerate(channels):
        roles[column] = COLUMN_ROLE_Y if index == 0 else COLUMN_ROLE_Z
    trace = TraceData(frame, column_roles=roles)
    engine.add_plugin("symmetry_decomposition", plugin)
    engine._namespace["source_trace"] = trace  # noqa: SLF001
    engine._namespace["_traces"] = {"measurement": "source_trace"}  # noqa: SLF001
    plugin.trace_key = "measurement"
    return trace


def test_non_hysteretic_irregular_x_decomposes_without_exact_mirror_points(engine):
    x = np.array([-3.0, -1.7, -0.4, 0.2, 1.1, 2.4, 3.0])
    y = 3.0 + 2.0 * x
    plugin = SymmetryDecompositionPlugin()
    plugin.mode = MODE_NON_HYSTERETIC
    _attach_source(engine, plugin, x, signal=y)

    result = plugin.transform({})

    np.testing.assert_allclose(result["symmetric"].df["signal"], 3.0)
    np.testing.assert_allclose(result["antisymmetric"].df["signal"], 2.0 * x)
    np.testing.assert_array_equal(result["symmetric"].x, x)


def test_auto_mode_falls_back_to_global_interpolation_for_monotonic_x(engine):
    x = np.array([-3.0, -1.2, -0.1, 0.5, 1.8, 3.0])
    plugin = SymmetryDecompositionPlugin()
    _attach_source(engine, plugin, x, signal=4.0 - 3.0 * x)

    result = plugin.transform({})

    np.testing.assert_allclose(result["symmetric"].df["signal"], 4.0)
    np.testing.assert_allclose(result["antisymmetric"].df["signal"], -3.0 * x)
    assert plugin.turning_points == []
    assert plugin.branch_directions == []


def test_default_nan_and_nearest_out_of_range_policies(engine):
    x = np.array([-2.0, -1.0, 0.0, 1.0])
    y = 1.0 + x
    plugin = SymmetryDecompositionPlugin()
    plugin.mode = MODE_NON_HYSTERETIC
    _attach_source(engine, plugin, x, signal=y)

    default_result = plugin.transform({})
    assert np.isnan(default_result["symmetric"].df["signal"].iloc[0])
    assert np.isnan(default_result["antisymmetric"].df["signal"].iloc[0])

    plugin.out_of_range = OUT_OF_RANGE_NEAREST
    nearest_result = plugin.transform({})
    assert nearest_result["symmetric"].df["signal"].iloc[0] == pytest.approx(0.5)
    assert nearest_result["antisymmetric"].df["signal"].iloc[0] == pytest.approx(-1.5)


def test_hysteretic_mode_pairs_noisy_rising_and_falling_branches(engine):
    rising = np.linspace(-2.0, 2.0, 41)
    falling = np.linspace(2.0, -2.0, 41)[1:]
    x = np.concatenate((rising, falling))
    x += 0.012 * np.sin(np.arange(len(x)) * 2.1)
    direction_offset = np.concatenate((np.ones(len(rising)), -np.ones(len(falling))))
    y = 5.0 + 2.0 * x + direction_offset
    plugin = SymmetryDecompositionPlugin()
    plugin.mode = MODE_HYSTERETIC
    plugin.smoothing_window = 9
    plugin.turning_point_prominence = 0.05
    plugin.minimum_branch_length = 10
    _attach_source(engine, plugin, x, signal=y)

    result = plugin.transform({})

    symmetric = result["symmetric"].df["signal"].to_numpy()
    antisymmetric = result["antisymmetric"].df["signal"].to_numpy()
    finite = np.isfinite(symmetric)
    np.testing.assert_allclose(symmetric[finite], 5.0, atol=0.03)
    np.testing.assert_allclose(
        antisymmetric[finite], (2.0 * x + direction_offset)[finite], atol=0.03
    )
    assert plugin.branch_directions == [1, -1]
    assert len(plugin.turning_points) == 1
    assert plugin.turning_points[0] == pytest.approx(40, abs=3)


def test_multiple_cycles_pair_consecutive_opposite_direction_branches(engine):
    branch_x = [
        np.linspace(-2.0, 2.0, 31),
        np.linspace(2.0, -2.0, 31)[1:],
        np.linspace(-2.0, 2.0, 31)[1:],
        np.linspace(2.0, -2.0, 31)[1:],
    ]
    offsets = [1.0, -1.0, 3.0, -3.0]
    x = np.concatenate(branch_x)
    y = np.concatenate([5.0 + 2.0 * values + offset for values, offset in zip(branch_x, offsets)])
    plugin = SymmetryDecompositionPlugin()
    plugin.mode = MODE_HYSTERETIC
    plugin.smoothing_window = 3
    plugin.smoothing_polyorder = 2
    plugin.turning_point_prominence = 0.05
    plugin.minimum_branch_length = 10
    _attach_source(engine, plugin, x, signal=y)

    symmetric = plugin.transform({})["symmetric"].df["signal"].to_numpy()

    np.testing.assert_allclose(symmetric[np.isfinite(symmetric)], 5.0)
    assert plugin.branch_directions == [1, -1, 1, -1]


def test_selected_channel_scope_omits_unselected_columns(engine):
    x = np.array([-2.0, -0.7, 0.1, 1.3, 2.0])
    voltage = 3.0 + 2.0 * x
    resistance = 10.0 - 4.0 * x
    plugin = SymmetryDecompositionPlugin()
    plugin.mode = MODE_NON_HYSTERETIC
    plugin.channel_mode = CHANNELS_SELECTED
    plugin.channel_keys = ["voltage"]
    _attach_source(engine, plugin, x, voltage=voltage, resistance=resistance)

    result = plugin.transform({})

    assert result["symmetric"].columns == ["field", "voltage"]
    assert result["antisymmetric"].columns == ["field", "voltage"]
    np.testing.assert_allclose(result["symmetric"].df["voltage"], 3.0)
    np.testing.assert_allclose(result["antisymmetric"].df["voltage"], 2.0 * x)
    assert result["symmetric"].names["voltage"] == "Symmetric voltage"
    assert result["antisymmetric"].names["voltage"] == "Antisymmetric voltage"


def test_decomposed_traces_preserve_source_channel_units(engine):
    x = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    plugin = SymmetryDecompositionPlugin()
    plugin.mode = MODE_NON_HYSTERETIC
    source = _attach_source(
        engine,
        plugin,
        x,
        voltage=3.0 + 2.0 * x,
        resistance=10.0 - 4.0 * x,
    )
    source.units.update({"field": "T", "voltage": "V", "resistance": "Ω"})

    result = plugin.transform({})

    expected_units = {"field": "T", "voltage": "V", "resistance": "Ω"}
    assert result["symmetric"].units == expected_units
    assert result["antisymmetric"].units == expected_units


def test_selected_channel_scope_can_use_data_column_as_x(engine):
    field = np.array([-3.0, -2.0, -1.0, 0.0, 1.0])
    voltage = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    resistance = 5.0 + 3.0 * voltage
    plugin = SymmetryDecompositionPlugin()
    plugin.mode = MODE_NON_HYSTERETIC
    plugin.channel_mode = CHANNELS_SELECTED
    plugin.x_channel_key = ""
    plugin.channel_keys = ["resistance"]
    _attach_source(engine, plugin, field, voltage=voltage, resistance=resistance)

    result = plugin.transform({})

    assert result["symmetric"].columns == ["voltage", "resistance"]
    assert result["symmetric"].column_roles == {"voltage": "x", "resistance": "z"}
    np.testing.assert_array_equal(result["symmetric"].x, voltage)
    np.testing.assert_allclose(result["symmetric"].df["resistance"], 5.0)
    np.testing.assert_allclose(result["antisymmetric"].df["resistance"], 3.0 * voltage)


def test_duplicate_x_values_are_consolidated_with_median_y():
    x, y = _consolidate_duplicate_x(
        np.array([1.0, 0.0, 1.0, -1.0]),
        np.array([10.0, 2.0, 14.0, -3.0]),
    )

    np.testing.assert_array_equal(x, [-1.0, 0.0, 1.0])
    np.testing.assert_array_equal(y, [-3.0, 2.0, 12.0])


def test_custom_output_names_are_catalogue_names_and_round_trip(qapp):
    plugin = SymmetryDecompositionPlugin()
    plugin.mode = MODE_HYSTERETIC
    plugin.channel_mode = CHANNELS_SELECTED
    plugin.x_channel_key = "voltage"
    plugin.channel_keys = ["voltage", "resistance"]
    plugin.symmetric_trace_name = "even"
    plugin.antisymmetric_trace_name = "odd"

    restored = BasePlugin.from_json(plugin.to_json())

    assert isinstance(restored, SymmetryDecompositionPlugin)
    assert restored.mode == MODE_HYSTERETIC
    assert restored.channel_mode == CHANNELS_SELECTED
    assert restored.x_channel_key == "voltage"
    assert restored.channel_keys == ["voltage", "resistance"]
    assert restored.output_trace_names == ["even", "odd"]
    assert restored.reported_traces() == {
        "symmetry_decomposition:even": "symmetry_decomposition.data['even']",
        "symmetry_decomposition:odd": "symmetry_decomposition.data['odd']",
    }


def test_default_advanced_settings_are_omitted_from_json(qapp):
    plugin = SymmetryDecompositionPlugin()

    data = plugin.to_json()

    assert "smoothing_window" not in data
    assert "smoothing_polyorder" not in data
    assert "turning_point_prominence" not in data
    assert "minimum_branch_length" not in data
    assert "interpolation" not in data
    assert "out_of_range" not in data

    plugin.smoothing_window = 21
    plugin.smoothing_polyorder = 3
    plugin.turning_point_prominence = 0.02
    plugin.minimum_branch_length = 20
    plugin.interpolation = INTERPOLATION_LINEAR
    plugin.out_of_range = OUT_OF_RANGE_NEAREST
    restored = BasePlugin.from_json(plugin.to_json())

    assert restored.smoothing_window == 21
    assert restored.smoothing_polyorder == 3
    assert restored.turning_point_prominence == pytest.approx(0.02)
    assert restored.minimum_branch_length == 20
    assert restored.interpolation == INTERPOLATION_LINEAR
    assert restored.out_of_range == OUT_OF_RANGE_NEAREST


def test_missing_advanced_json_uses_documented_defaults(qapp):
    plugin = BasePlugin.from_json(SymmetryDecompositionPlugin().to_json())

    assert plugin.smoothing_window == DEFAULT_SMOOTHING_WINDOW
    assert plugin.smoothing_polyorder == DEFAULT_SMOOTHING_POLYORDER
    assert plugin.turning_point_prominence == DEFAULT_TURNING_PROMINENCE
    assert plugin.minimum_branch_length == DEFAULT_MINIMUM_BRANCH_LENGTH
    assert plugin.interpolation == DEFAULT_INTERPOLATION
    assert plugin.out_of_range == DEFAULT_OUT_OF_RANGE


def test_general_and_advanced_tabs_follow_layout_conventions(engine, managed_qt_widget):
    plugin = SymmetryDecompositionPlugin()
    _attach_source(
        engine,
        plugin,
        [-1.0, 0.0, 1.0],
        voltage=[-1.0, 0.0, 1.0],
        resistance=[1.0, 2.0, 3.0],
    )

    tabs = plugin.config_tabs()
    assert [title for title, _widget in tabs][:2] == ["General", "Advanced"]
    general = managed_qt_widget(tabs[0][1])
    advanced = managed_qt_widget(tabs[1][1])

    line_edits = general.findChildren(QLineEdit)
    assert line_edits[0].text() == "symmetry_decomposition"
    assert line_edits[1].text() == ""
    assert general.findChild(QComboBox, "symmetry_mode") is not None
    assert general.findChild(QComboBox, "symmetry_channel_mode") is not None
    assert general.findChild(QComboBox, "symmetry_x_channel") is not None
    assert general.findChild(QListWidget, "symmetry_channels").count() == 2
    assert general.findChild(QLineEdit, "symmetric_trace_name").text() == "symmetric"
    assert general.findChild(QLineEdit, "antisymmetric_trace_name").text() == "antisymmetric"
    assert advanced.findChild(QSpinBox, "symmetry_smoothing_window").value() == 11
    assert advanced.findChild(SISpinBox, "symmetry_turning_prominence") is not None
    assert advanced.findChild(QComboBox, "symmetry_interpolation") is not None
    assert advanced.findChild(QComboBox, "symmetry_out_of_range") is not None


def test_output_name_edit_remaps_catalogue_data_and_downstream_references(
    engine, managed_qt_widget
):
    from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
    from stoner_measurement.plugins.command.save import SaveCommand

    plugin = SymmetryDecompositionPlugin()
    plot = PlotTraceCommand()
    save = SaveCommand()
    plot.trace_key = "symmetry_decomposition:symmetric"
    plot.x_expr = "symmetry_decomposition.data['symmetric'].x"
    save.trace_selection = {"symmetry_decomposition:symmetric": False}
    output = object()
    plugin.data["symmetric"] = output
    plugin.sequence_engine = engine
    engine.update_step_plugin_catalog([plugin, plot, save])
    general = managed_qt_widget(plugin.config_tabs()[0][1])
    name_edit = general.findChild(QLineEdit, "symmetric_trace_name")

    name_edit.setText("even")
    name_edit.editingFinished.emit()

    assert plugin.output_trace_names == ["even", "antisymmetric"]
    assert plugin.data == {"even": output}
    assert "symmetry_decomposition:even" in engine.traces_catalog
    assert "symmetry_decomposition:symmetric" not in engine.traces_catalog
    assert plot.trace_key == "symmetry_decomposition:even"
    assert plot.x_expr == "symmetry_decomposition.data['even'].x"
    assert save.trace_selection == {"symmetry_decomposition:even": False}


def test_channel_list_uses_configured_scan_outputs_before_collection(
    engine, managed_qt_widget
):
    from stoner_measurement.core.value_catalog import ValueCatalogEntry
    from stoner_measurement.plugins.state_scan.counter import CounterPlugin

    counter = CounterPlugin()
    counter.collect_data = True
    counter.collect_output_roles = {
        "counter:Value": "y",
        "curve_fit:Ic": "y",
        "curve_fit:Rn": "y",
    }
    plugin = SymmetryDecompositionPlugin()
    engine.add_plugin("counter", counter)
    engine.add_plugin("symmetry_decomposition", plugin)
    engine._namespace["_values"] = {  # noqa: SLF001
        "counter:Value": ValueCatalogEntry("0.0", ""),
        "curve_fit:Ic": ValueCatalogEntry("0.0", "A"),
        "curve_fit:Rn": ValueCatalogEntry("0.0", "ohm"),
    }
    engine._namespace["_traces"] = {"counter.data": "counter.data"}  # noqa: SLF001
    plugin.trace_key = "counter.data"

    general = managed_qt_widget(plugin.config_tabs()[0][1])
    channels = general.findChild(QListWidget, "symmetry_channels")

    labels = {channels.item(row).text() for row in range(channels.count())}
    assert {
        "counter.data:counter:Value ()",
        "counter.data:curve_fit:Ic (A)",
        "counter.data:curve_fit:Rn (ohm)",
    } <= labels


def test_channel_list_refreshes_when_magnet_sweep_expected_outputs_change(
    engine, managed_qt_widget, qapp
):
    from stoner_measurement.core.value_catalog import ValueCatalogEntry
    from stoner_measurement.plugins.state_sweep import MagnetControllerSweepPlugin

    sweep = MagnetControllerSweepPlugin()
    sweep.collect_data = True
    sweep.collect_outputs = [f"{sweep.instance_name}:Field"]
    plugin = SymmetryDecompositionPlugin()
    engine.add_plugin(sweep.instance_name, sweep)
    engine.add_plugin("symmetry_decomposition", plugin)
    engine._namespace["_values"] = {  # noqa: SLF001
        f"{sweep.instance_name}:Field": ValueCatalogEntry("0.0", "T"),
    }
    engine._namespace["_traces"] = {  # noqa: SLF001
        f"{sweep.instance_name}.data": f"{sweep.instance_name}.data"
    }
    plugin.trace_key = f"{sweep.instance_name}.data"
    general = managed_qt_widget(plugin.config_tabs()[0][1])
    channels = general.findChild(QListWidget, "symmetry_channels")

    sweep.collect_outputs = [
        f"{sweep.instance_name}:Field",
        f"{sweep.instance_name}:Current",
        f"{sweep.instance_name}:Voltage",
    ]
    updated_values = {
        f"{sweep.instance_name}:Field": ValueCatalogEntry("0.0", "T"),
        f"{sweep.instance_name}:Current": ValueCatalogEntry("0.0", "A"),
        f"{sweep.instance_name}:Voltage": ValueCatalogEntry("0.0", "V"),
    }
    engine._namespace["_values"] = updated_values  # noqa: SLF001
    engine.values_catalog_changed.emit(updated_values)
    qapp.processEvents()

    labels = {channels.item(row).text() for row in range(channels.count())}
    assert {
        f"{sweep.instance_name}.data:{sweep.instance_name}:Field (T)",
        f"{sweep.instance_name}.data:{sweep.instance_name}:Current (A)",
        f"{sweep.instance_name}.data:{sweep.instance_name}:Voltage (V)",
    } <= labels


def test_channel_list_uses_themed_item_checkboxes(engine, managed_qt_widget):
    plugin = SymmetryDecompositionPlugin()
    _attach_source(
        engine,
        plugin,
        [-1.0, 0.0, 1.0],
        voltage=[-1.0, 0.0, 1.0],
        resistance=[1.0, 2.0, 3.0],
    )
    plugin.channel_mode = CHANNELS_SELECTED
    plugin.channel_keys = ["", "resistance"]

    general = managed_qt_widget(plugin.config_tabs()[0][1])
    channels = general.findChild(QListWidget, "symmetry_channels")
    assert [channels.item(row).text() for row in range(channels.count())] == [
        "measurement:voltage ()",
        "measurement:resistance ()",
    ]
    assert all(
        channels.item(row).flags() & Qt.ItemFlag.ItemIsUserCheckable
        for row in range(channels.count())
    )
    channels.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert plugin.channel_keys == ["resistance"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
