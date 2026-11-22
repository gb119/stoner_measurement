"""Configuration-time trace declarations and their selection controls."""

from unittest.mock import MagicMock

import numpy as np
import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QLineEdit

from stoner_measurement.core.trace_data import TraceData
from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
from stoner_measurement.plugins.state_scan import CounterPlugin
from stoner_measurement.plugins.state_sweep import SweepTimePlugin
from stoner_measurement.plugins.trace.dummy import DummyPlugin
from stoner_measurement.plugins.trace.k6221_2182a import Keithley6221_2182APlugin
from stoner_measurement.plugins.trace.k6221_multi_sr830 import (
    Keithley6221_MultiSR830Plugin,
    LockInEntry,
    LockInOutput,
)
from stoner_measurement.plugins.trace.k6221_pulse_delta import Keithley6221PulseDeltaPlugin
from stoner_measurement.plugins.trace.keithley_2400 import Keithley2400SweepPlugin, SweepSourceMode
from stoner_measurement.plugins.trace_catalog_ui import (
    TraceChannelComboBox,
    trace_channel_items,
    trace_channel_roles,
    trace_target_column_items,
)
from stoner_measurement.plugins.transform.curve_fit import CurveFitPlugin


class _DeclaredTrace(DummyPlugin):
    """Publish two differently shaped outputs without acquiring either."""

    @property
    def trace_names(self):
        return ["First", "Second"]

    def configured_trace_data(self):
        return {
            f"{self.instance_name}:{name}": TraceData.from_xy(
                np.array([]), np.array([]), units={"x": "A", "y": unit}
            )
            for name, unit in (("First", "V"), ("Second", "Ω"))
        }


def _attach(engine, producer, consumer):
    engine.add_plugin("producer", producer)
    engine.add_plugin("consumer", consumer)
    engine.update_step_plugin_catalog([producer, consumer])


def test_multiple_configured_traces_resolve_without_evaluating_results(engine):
    producer = _DeclaredTrace()
    consumer = PlotTraceCommand()
    _attach(engine, producer, consumer)
    consumer.eval = MagicMock(side_effect=AssertionError("Results must not be evaluated"))

    items = trace_channel_items(consumer, engine.traces_catalog)
    roles = trace_channel_roles(consumer, engine.traces_catalog)

    assert len(items) == 4
    assert f"{producer.instance_name}:Second:y (Ω)" in items
    assert sorted(roles.values()) == ["x", "x", "y", "y"]
    assert producer.data == {}
    consumer.eval.assert_not_called()


def test_undeclared_schema_retains_configured_and_live_fallbacks(engine):
    producer = DummyPlugin()
    consumer = PlotTraceCommand()
    _attach(engine, producer, consumer)
    key = next(iter(engine.traces_catalog))
    assert producer.configured_trace_data() == {}
    assert len(trace_channel_items(consumer, engine.traces_catalog)) == 2

    producer.data[producer.trace_names[0]] = TraceData.from_xy(np.array([1]), np.array([2]))
    items = trace_channel_items(consumer, engine.traces_catalog)
    assert items[f"{key}:y ()"].endswith(".df['y'].to_numpy()")


@pytest.mark.parametrize("plugin_class", [CounterPlugin, SweepTimePlugin])
def test_collected_trace_schema_uses_complete_value_catalogue(engine, plugin_class):
    producer = plugin_class()
    producer.collect_data = True
    source = CounterPlugin()
    source.instance_name = "readback"
    producer.collect_outputs = ["readback:Value"]
    _attach(engine, producer, source)

    schemas = producer.configured_trace_data()
    assert schemas.keys() == producer.reported_traces().keys()
    schema = schemas[f"{producer.instance_name}.data"]
    assert schema.df.empty
    assert "readback:Value" in schema.columns
    assert producer.data.df.empty
    producer.collect_data = False
    assert producer.configured_trace_data() == {}


@pytest.mark.parametrize("plugin_class", [Keithley6221_2182APlugin, Keithley6221PulseDeltaPlugin])
@pytest.mark.parametrize("conductance", [False, True])
def test_6221_schema_declares_differential_channels(qapp, plugin_class, conductance):
    plugin = plugin_class()
    plugin._differential_mode = True
    plugin._differential_conductance = conductance
    plugin._delta_current = "not_defined_until_runtime"
    response = "G" if conductance else "R"
    expected = ["x", "V", response, "P"]
    if plugin_class is Keithley6221_2182APlugin:
        plugin._secondary_enabled = True
        plugin._secondary_prefix = "hall"
        expected += ["hall V", f"hall {response}", "hall P"]

    schemas = plugin.configured_trace_data()
    assert schemas.keys() == plugin.reported_traces().keys()
    schema = next(iter(schemas.values()))
    assert schema.df.empty
    assert schema.columns == expected
    assert schema.units[response] == ("S" if conductance else "Ω")
    assert plugin.data == {}


@pytest.mark.parametrize("mode", list(SweepSourceMode))
@pytest.mark.parametrize(
    "function,unit", [("CURR", "A"), ("VOLT", "V"), ("RES", "Ω"), ("CHAR", "C")]
)
def test_2400_schema_includes_electrometer_and_nanovoltmeter(qapp, mode, function, unit):
    plugin = Keithley2400SweepPlugin()
    plugin._source_mode = mode
    plugin._secondary_enabled = True
    plugin._electrometer.settings.enabled = True
    plugin._electrometer.settings.function = function
    plugin._electrometer.settings.nplc = "runtime_nplc"
    schema = next(iter(plugin.configured_trace_data().values()))
    column, _ = plugin._electrometer.settings.channel

    assert schema.df.empty
    assert schema.columns == [
        "x",
        "Current",
        "Voltage",
        "Resistance",
        "Power",
        "Timestamp",
        "secondary V",
        "secondary R",
        "secondary P",
        column,
    ]
    assert schema.units[column] == unit
    assert schema.column_roles[column] == "y"
    assert schema.column_roles["Voltage" if mode is SweepSourceMode.CURRENT else "Current"] == "y"
    assert schema.units["x"] == ("A" if mode is SweepSourceMode.CURRENT else "V")
    assert plugin._electrometer.readings is None


def test_2400_differential_conductance_and_transpose_schema(qapp):
    plugin = Keithley2400SweepPlugin()
    plugin._source_mode = SweepSourceMode.CURRENT
    plugin._differential_mode = True
    plugin._differential_conductance = True
    plugin._transpose = True
    schema = next(iter(plugin.configured_trace_data().values()))
    assert "Conductance" in schema.columns
    assert "Resistance" not in schema.columns
    assert schema.units["Conductance"] == "S"
    assert schema.get_columns_by_role("x") == ["Voltage"]
    assert schema.expected_column_roles == schema.column_roles
    assert schema.units[schema.get_columns_by_role("x")[0]] == "V"


def test_lockin_schema_declares_selected_outputs_and_derived_resistance(qapp):
    plugin = Keithley6221_MultiSR830Plugin()
    plugin._lockin_entries = [
        LockInEntry(label="sample", outputs=(LockInOutput.X, LockInOutput.THETA))
    ]
    plugin._resistance_enabled = True
    plugin._waveform_amplitude = "runtime_amplitude"
    schema = next(iter(plugin.configured_trace_data().values()))
    assert schema.columns == ["x", "sample X", "sample X resistance", "sample THETA"]
    assert schema.units["sample X resistance"] == "Ω"
    assert schema.df.empty


def test_current_schema_overrides_previous_result_and_populates_all_selectors(engine):
    producer = Keithley6221_2182APlugin()
    consumer = PlotTraceCommand()
    producer.data["IV"] = TraceData.from_xy(np.array([1]), np.array([2]))
    producer._secondary_enabled = True
    producer._secondary_prefix = "hall"
    _attach(engine, producer, consumer)
    key = next(iter(engine.traces_catalog))

    items = trace_channel_items(consumer, engine.traces_catalog)
    targets = trace_target_column_items(consumer, engine.traces_catalog, key)
    assert items[f"{key}:hall V (V)"].endswith(".df['hall V'].to_numpy()")
    assert targets[f"{key}:R (Ω)"] == "R"
    assert consumer._get_trace_columns(key) == ["x", "V", "R", "P", "hall V", "hall R", "hall P"]
    fit = CurveFitPlugin()
    engine.add_plugin("fit", fit)
    assert fit._get_trace_columns(key) == consumer._get_trace_columns(key)
    assert producer.data["IV"].columns == ["x", "y"]


def test_keithley_controls_refresh_open_channel_selectors(
    engine, managed_plugin_config_tabs, managed_qt_widget
):
    producer = Keithley6221_2182APlugin()
    consumer = PlotTraceCommand()
    _attach(engine, producer, consumer)
    consumer.x_expr = f"{producer.instance_name}.data['IV'].x"
    widget = managed_qt_widget(consumer.config_widget())
    tabs = dict(managed_plugin_config_tabs(producer))
    checkboxes = [child for page in tabs.values() for child in page.findChildren(QCheckBox)]
    secondary = next(child for child in checkboxes if child.objectName() == "secondary_enabled")
    secondary.setChecked(True)
    producer._differential_mode = True
    conductance = next(
        child for child in checkboxes if child.objectName() == "differential_conductance"
    )
    conductance.setChecked(True)

    combos = widget.findChildren(TraceChannelComboBox)
    assert all(
        any("secondary G (S)" in combo.itemText(i) for i in range(combo.count()))
        for combo in combos
    )
    assert consumer.x_expr in (
        f"{producer.instance_name}.data['IV'].x",
        f"{producer.instance_name}.data['IV'].df['x'].to_numpy()",
    )

    secondary.setChecked(False)
    assert all(
        not any("secondary" in combo.itemText(i) for i in range(combo.count())) for combo in combos
    )


@pytest.mark.parametrize(
    "plugin_class",
    [
        Keithley6221_2182APlugin,
        Keithley6221PulseDeltaPlugin,
        Keithley2400SweepPlugin,
    ],
)
@pytest.mark.parametrize("conductance", [False, True])
def test_configured_iv_metadata_matches_acquisition(qapp, monkeypatch, plugin_class, conductance):
    plugin = plugin_class()
    plugin._differential_mode = True
    plugin._differential_conductance = conductance
    plugin._delta_current = 0.1
    plugin._sweep_values = (1.1, 1.9, 3.1)
    plugin._nominal_sweep_values = np.array([1, 2, 3])
    if plugin_class is Keithley2400SweepPlugin:
        monkeypatch.setattr(plugin, "_acquire_buffer_records", lambda _parameters: ())
        monkeypatch.setattr(
            plugin,
            "_records_to_arrays",
            lambda *_args: (
                np.array([1, 2, 3]),
                np.array([2, 4, 6]),
                np.array([2, 2, 2]),
                np.array([2, 8, 18]),
                np.array([0, 1, 2]),
            ),
        )
        plugin._electrometer.settings.enabled = True
        plugin._electrometer.readings = [1e-9, 2e-9, 3e-9]
    else:
        monkeypatch.setattr(plugin, "_acquire_pairs", lambda _parameters: [(1, 2), (2, 4), (3, 6)])
    if plugin_class is not Keithley6221PulseDeltaPlugin:
        plugin._secondary_enabled = True
        plugin._secondary_voltages = [0.2, 0.4, 0.6]

    configured = next(iter(plugin.configured_trace_data().values()))
    acquired = plugin._measure({})["IV"]
    assert acquired.df.shape[0] == 3
    assert configured.columns == acquired.columns
    assert configured.column_roles == acquired.column_roles
    assert configured.names == acquired.names
    assert configured.units == acquired.units


def test_removed_producer_clears_configured_schemas(engine):
    producer = _DeclaredTrace()
    _attach(engine, producer, PlotTraceCommand())
    assert engine.namespace["_trace_schemas"]
    engine.update_step_plugin_catalog([])
    assert engine.namespace["_trace_schemas"] == {}


@pytest.mark.parametrize("refresh_method", ["refresh", "full_refresh"])
def test_programmatic_refresh_updates_open_selectors(engine, managed_qt_widget, refresh_method):
    producer = Keithley6221_2182APlugin()
    consumer = PlotTraceCommand()
    _attach(engine, producer, consumer)
    widget = managed_qt_widget(consumer.config_widget())
    producer._secondary_enabled = True
    producer._secondary_prefix = "hall"
    producer._differential_mode = True
    producer._differential_conductance = True
    getattr(producer, refresh_method)()

    key = next(iter(producer.reported_traces()))
    assert engine.namespace["_trace_schemas"][key].columns == [
        "x",
        "V",
        "G",
        "P",
        "hall V",
        "hall G",
        "hall P",
    ]
    for combo in widget.findChildren(TraceChannelComboBox):
        assert any("hall G (S)" in combo.itemText(i) for i in range(combo.count()))


def test_2400_electrometer_controls_refresh_configured_channels(
    engine, managed_plugin_config_tabs, managed_qt_widget
):
    producer = Keithley2400SweepPlugin()
    consumer = PlotTraceCommand()
    _attach(engine, producer, consumer)
    widget = managed_qt_widget(consumer.config_widget())
    pages = [page for _title, page in managed_plugin_config_tabs(producer)]

    def control(widget_class, name):
        return next(
            child for page in pages if (child := page.findChild(widget_class, name)) is not None
        )

    control(QCheckBox, "electrometer_enabled").setChecked(True)
    driver = control(QComboBox, "electrometer_driver")
    driver.setCurrentIndex(driver.findData("keithley_6517"))
    function = control(QComboBox, "electrometer_function")
    function.setCurrentIndex(function.findData("VOLT"))
    control(QLineEdit, "electrometer_prefix").setText("gate")

    for combo in widget.findChildren(TraceChannelComboBox):
        assert any("gate Voltage (V)" in combo.itemText(i) for i in range(combo.count()))
        assert not any("electrometer Current" in combo.itemText(i) for i in range(combo.count()))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
