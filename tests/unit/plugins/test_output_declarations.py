"""Unified declarations, legacy adapters and built-in plugin compatibility."""

from importlib.metadata import entry_points
from unittest.mock import Mock

import numpy as np
import pytest

from stoner_measurement.core.plugin_outputs import (
    PluginOutputs,
    ScalarOutput,
    TraceOutput,
    resolve_outputs,
    trace_outputs,
    transform_outputs,
)
from stoner_measurement.core.trace_data import TraceData
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.monitor.magnet_controller import MagneticFieldMonitorPlugin
from stoner_measurement.plugins.monitor.motor_controller import MotorAngleMonitorPlugin
from stoner_measurement.plugins.monitor.temperature_controller import TemperatureMonitorPlugin
from stoner_measurement.plugins.trace.base import TracePlugin
from stoner_measurement.plugins.trace.keithley_2400 import Keithley2400SweepPlugin
from stoner_measurement.plugins.trace.network_analyser import NetworkAnalyserTracePlugin
from stoner_measurement.plugins.transform.base import TransformPlugin


def _schema():
    return TraceData.from_xy(np.array([]), np.array([]), units={"x": "A", "y": "V"})


class _Unified(BasePlugin):
    calls = 0

    @property
    def name(self):
        return "unified"

    def declared_outputs(self):
        self.calls += 1
        return PluginOutputs(
            traces={"arbitrary.table": TraceOutput("unified.payload", schema_factory=_schema)},
            values={"gain": ScalarOutput("unified.gain", "Ω")},
        )


class _Legacy(BasePlugin):
    @property
    def name(self):
        return "legacy"

    def reported_traces(self):
        return {"old:Trace": "legacy.data['Trace']"}

    def reported_values(self):
        return {"old:Value": "legacy.value"}

    def reported_value_units(self):
        return {"old:Value": "K", "not_published": "A"}

    def configured_trace_data(self):
        return {"old:Trace": _schema()}


def test_new_plugin_supports_existing_dictionary_views_without_evaluating_results():
    plugin = _Unified()
    plugin.eval = Mock(side_effect=AssertionError("Declarations must not evaluate results"))
    assert plugin.reported_traces() == {"arbitrary.table": "unified.payload"}
    assert plugin.reported_values() == {"gain": "unified.gain"}
    assert plugin.reported_value_units() == {"gain": "Ω"}
    assert plugin.configured_trace_data()["arbitrary.table"].units == {"x": "A", "y": "V"}
    plugin.eval.assert_not_called()


def test_legacy_outputs_are_adapted_without_changing_the_existing_methods():
    plugin = _Legacy()
    outputs = resolve_outputs(plugin)
    assert outputs.traces["old:Trace"].expression == plugin.reported_traces()["old:Trace"]
    assert outputs.values["old:Value"] == ScalarOutput("legacy.value", "K")
    assert outputs.configured_traces()["old:Trace"].columns == ["x", "y"]
    assert "not_published" not in outputs.values
    assert plugin.reported_value_units()["not_published"] == "A"


def test_more_specific_legacy_overrides_and_super_calls_are_preserved():
    class _Child(_Unified):
        def reported_traces(self):
            return {**super().reported_traces(), "extra": "unified.other"}

        def reported_values(self):
            return {**super().reported_values(), "extra": "unified.extra"}

        def reported_value_units(self):
            return {**super().reported_value_units(), "extra": "A"}

        def configured_trace_data(self):
            return {**super().configured_trace_data(), "extra": _schema()}

    plugin = _Child()
    outputs = resolve_outputs(plugin)
    assert plugin.calls == 1
    assert list(outputs.traces) == ["arbitrary.table", "extra"]
    assert list(outputs.values) == ["gain", "extra"]
    assert outputs.values["extra"].units == "A"
    assert list(outputs.configured_traces()) == ["arbitrary.table", "extra"]
    assert plugin.calls == 1
    assert plugin.reported_value_units() == {"gain": "Ω", "extra": "A"}


def test_partial_unit_override_preserves_legacy_replacement_semantics():
    class _Child(_Unified):
        def reported_value_units(self):
            return {}

    assert resolve_outputs(_Child()).values["gain"].units == ""


def test_direct_legacy_super_mutations_are_applied_once_across_inheritance():
    class _Remove(_Unified):
        def reported_values(self):
            values = super().reported_values()
            values.pop("gain")
            values["first"] = "unified.first"
            return values

    class _Extend(_Remove):
        def reported_values(self):
            values = super().reported_values()
            values["second"] = "unified.second"
            return values

    plugin = _Extend()
    expected = {"first": "unified.first", "second": "unified.second"}
    assert plugin.reported_values() == expected
    assert {
        key: item.expression for key, item in resolve_outputs(plugin).values.items()
    } == expected


def test_legacy_schema_override_can_remove_inherited_schema():
    class _Remove(_Unified):
        def configured_trace_data(self):
            schemas = super().configured_trace_data()
            schemas.pop("arbitrary.table")
            return schemas

    plugin = _Remove()
    assert plugin.configured_trace_data() == {}
    assert resolve_outputs(plugin).configured_traces() == {}


def test_explicit_empty_declarations_are_authoritative_and_diagnose_conflicts(caplog):
    class _Empty(_Legacy):
        def declared_outputs(self):
            return PluginOutputs()

        def reported_values(self):
            return {"ignored": "legacy.value"}

    outputs = resolve_outputs(_Empty())
    assert outputs.traces == outputs.values == {}
    assert "unified declaration takes precedence" in caplog.text


def test_none_selects_legacy_adaptation():
    assert _Legacy().declared_outputs() is None
    assert resolve_outputs(_Legacy()).values["old:Value"].units == "K"


def test_unified_child_of_legacy_parent_has_consistent_old_caller_views():
    class _Migrated(_Legacy):
        def declared_outputs(self):
            return PluginOutputs(values={"new": ScalarOutput("legacy.new", "V")})

    plugin = _Migrated()
    assert plugin.reported_traces() == {}
    assert plugin.reported_values() == {"new": "legacy.new"}
    assert plugin.reported_value_units() == {"new": "V"}
    assert plugin.configured_trace_data() == {}


def test_legacy_grandchild_extends_unified_parent_of_legacy_ancestor():
    class _Migrated(_Legacy):
        def declared_outputs(self):
            return PluginOutputs(values={"new": ScalarOutput("legacy.new", "V")})

    class _Extension(_Migrated):
        def reported_values(self):
            return {**super().reported_values(), "extra": "legacy.extra"}

    plugin = _Extension()
    expected = {"new": "legacy.new", "extra": "legacy.extra"}
    assert plugin.reported_values() == expected
    assert {
        key: item.expression for key, item in resolve_outputs(plugin).values.items()
    } == expected


def test_explicit_none_on_child_keeps_legacy_ancestor_methods():
    class _Adapter(_Legacy):
        def declared_outputs(self):
            return None

    plugin = _Adapter()
    assert plugin.reported_values() == {"old:Value": "legacy.value"}
    assert resolve_outputs(plugin).values["old:Value"].units == "K"


def test_engine_resolves_once_and_defers_schemas_until_values_are_published(engine):
    schemas = []

    class _Dependent(_Unified):
        def declared_outputs(self):
            outputs = super().declared_outputs()

            def factory():
                schemas.append(engine.values_catalog["gain"].units)
                return _schema()

            outputs.traces["arbitrary.table"] = TraceOutput(
                "unified.payload", schema_factory=factory
            )
            return outputs

    plugin = _Dependent()
    engine.add_plugin("unified", plugin)
    engine.update_step_plugin_catalog([plugin])
    assert plugin.calls == 1
    assert schemas == ["Ω"]
    assert isinstance(engine.values_catalog["gain"], str)
    assert engine.values_catalog["gain"].units == "Ω"
    assert engine.traces_catalog == {"arbitrary.table": "unified.payload"}
    assert "arbitrary.table" in engine.namespace["_trace_schemas"]


def test_empty_and_missing_schema_remain_distinct():
    outputs = PluginOutputs(
        traces={
            "unknown": TraceOutput("missing"),
            "empty": TraceOutput("also_missing", schema=_schema()),
        }
    )
    assert list(outputs.configured_traces()) == ["empty"]


def test_schema_snapshots_are_independent():
    descriptor = TraceOutput("data", schema=_schema())
    first = descriptor.configured_data()
    first.units["y"] = "changed"
    assert descriptor.configured_data().units["y"] == "V"


@pytest.mark.parametrize(
    "descriptor",
    [
        TraceOutput("data", schema=_schema(), schema_factory=_schema),
        TraceOutput("data", schema_factory=lambda: TraceData.from_xy(np.array([1]), np.array([2]))),
    ],
)
def test_invalid_schema_declarations_are_rejected(descriptor):
    with pytest.raises(ValueError):
        descriptor.configured_data()


def test_trace_and_scalar_can_share_a_legacy_catalogue_identifier():
    outputs = PluginOutputs(
        traces={"same": TraceOutput("table")}, values={"same": ScalarOutput("value", "V")}
    )
    assert outputs.traces["same"].expression == "table"
    assert outputs.values["same"].expression == "value"


def test_result_names_preserve_explicit_order_and_new_subclass_results():
    outputs = PluginOutputs(
        traces={"table": TraceOutput("table", result_key="table")},
        values={"gain": ScalarOutput("gain", result_key="gain"), "mean": ScalarOutput("mean")},
        result_order=("table", "gain"),
    )
    outputs.values["extra"] = ScalarOutput("extra", result_key="extra")
    assert outputs.result_keys() == ["table", "gain", "extra"]
    assert outputs.result_keys("trace") == ["table"]
    assert outputs.result_keys("value") == ["gain", "extra"]


def test_statistics_configuration_refreshes_unified_scalar_catalogue(engine):
    plugin = Keithley2400SweepPlugin()
    engine.add_plugin("source", plugin)
    engine.update_step_plugin_catalog([plugin])
    assert engine.values_catalog == {}
    plugin._set_report_channel_statistics(True)
    key = f"{plugin.instance_name}:IV Resistance mean"
    assert engine.values_catalog[key].units == "Ω"
    plugin._set_report_channel_statistics(False)
    assert engine.values_catalog == {}


def test_network_analyser_statistics_retain_the_reported_trace_identity(qapp):
    plugin = NetworkAnalyserTracePlugin()
    plugin._report_channel_statistics = True
    var = plugin.instance_name
    assert plugin.reported_values() == {
        f"{var}:S parameters mean": f"{var}.get_channel_statistic('S parameters', 'mean')",
        f"{var}:S parameters std": f"{var}.get_channel_statistic('S parameters', 'std')",
    }


@pytest.mark.parametrize(
    "plugin_class, flag, label, unit",
    [
        (MagneticFieldMonitorPlugin, "report_field", "Field", "T"),
        (MotorAngleMonitorPlugin, "report_angle", "Angle", "deg"),
        (TemperatureMonitorPlugin, "report_setpoints", "Setpoint loop 1", "K"),
    ],
)
def test_controller_monitor_units_match_published_identifiers(
    qapp, plugin_class, flag, label, unit
):
    plugin = plugin_class()
    setattr(plugin, flag, True)
    if isinstance(plugin, TemperatureMonitorPlugin):
        plugin.control_loops = [1]
    key = f"{plugin.instance_name}:{label}"
    assert plugin.reported_value_units()[key] == unit
    assert resolve_outputs(plugin).values[key].units == unit


class _UnifiedTrace(TracePlugin):
    @property
    def name(self):
        return "trace"

    def declared_outputs(self):
        return trace_outputs(self, ["native"])

    def _measure(self, parameters):
        raise NotImplementedError


def test_legacy_trace_name_override_can_extend_inherited_names(qapp):
    class _Child(_UnifiedTrace):
        @property
        def trace_names(self):
            return [*super().trace_names, "extra"]

    plugin = _Child()
    assert list(plugin.reported_traces()) == ["trace:native", "trace:extra"]
    assert plugin.reported_traces()["trace:extra"] == "trace.data['extra']"


class _UnifiedTransform(TransformPlugin):
    @property
    def name(self):
        return "transform"

    @property
    def required_inputs(self):
        return []

    def declared_outputs(self):
        return transform_outputs(self, [], ["gain"])

    def transform(self, data):
        return {"gain": 1}


def test_unified_transform_needs_no_separate_output_names(qapp):
    plugin = _UnifiedTransform()
    assert plugin.output_names == plugin.output_value_names == ["gain"]
    assert plugin.output_trace_names == []


def test_legacy_transform_name_override_can_extend_inherited_names(qapp):
    class _Child(_UnifiedTransform):
        @property
        def output_names(self):
            return [*super().output_names, "extra"]

    plugin = _Child()
    assert list(plugin.reported_values()) == ["transform:gain", "transform:extra"]


def test_legacy_transform_classification_is_preserved(qapp):
    class _Old(_UnifiedTransform):
        def declared_outputs(self):
            return TransformPlugin.declared_outputs(self)

        @property
        def output_names(self):
            return ["table", "value"]

        @property
        def output_trace_names(self):
            return ["table"]

    outputs = resolve_outputs(_Old())
    assert list(outputs.traces) == ["transform:table"]
    # Old defaults treated every output as a scalar, even a declared trace.
    assert list(outputs.values) == ["transform:table", "transform:value"]


@pytest.mark.parametrize(
    "entry",
    sorted(entry_points(group="stoner_measurement.plugins"), key=lambda entry: entry.name),
    ids=lambda entry: entry.name,
)
def test_registered_builtins_use_unified_declarations_and_compatible_views(qapp, entry):
    plugin = entry.load()()
    assert isinstance(plugin.declared_outputs(), PluginOutputs)
    outputs = resolve_outputs(plugin)
    assert plugin.reported_traces() == {
        key: item.expression for key, item in outputs.traces.items()
    }
    assert plugin.reported_values() == {
        key: item.expression for key, item in outputs.values.items()
    }
    assert plugin.reported_value_units() == {
        key: item.units for key, item in outputs.values.items()
    }


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
