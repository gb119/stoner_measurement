"""Focused tests for plugin reported output contracts."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from stoner_measurement.plugins.monitor import MonitorPlugin
from stoner_measurement.plugins.state_control import StateControlPlugin
from stoner_measurement.plugins.trace import TracePlugin
from stoner_measurement.plugins.transform import TransformPlugin


class _SimpleTrace(TracePlugin):
    @property
    def name(self) -> str:
        return "SimpleTrace"

    def execute(
        self, parameters: dict[str, Any]
    ) -> Generator[tuple[float, float]]:
        n = int(parameters.get("n", 5))
        for i in range(n):
            yield float(i), float(i * i)


class _InstantState(StateControlPlugin):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._value: float = 0.0

    @property
    def name(self) -> str:
        return "InstantState"

    @property
    def state_name(self) -> str:
        return "Voltage"

    @property
    def units(self) -> str:
        return "V"

    def set_state(self, value: float) -> None:
        self._value = value

    def get_state(self) -> float:
        return self._value

    def is_at_target(self) -> bool:
        return True


class _ConstMonitor(MonitorPlugin):
    @property
    def name(self) -> str:
        return "ConstMonitor"

    @property
    def quantity_names(self) -> list[str]:
        return ["temperature", "pressure"]

    @property
    def units(self) -> dict[str, str]:
        return {"temperature": "K", "pressure": "Pa"}

    def read(self) -> dict[str, float]:
        return {"temperature": 300.0, "pressure": 101325.0}


class _ScaleTransform(TransformPlugin):
    @property
    def name(self) -> str:
        return "Scale"

    @property
    def required_inputs(self) -> list[str]:
        return ["y"]

    @property
    def output_names(self) -> list[str]:
        return ["y_scaled"]

    def transform(self, data: dict[str, object]) -> dict[str, object]:
        return {"y_scaled": [v * 3 for v in data["y"]]}


class TestReportedTraces:
    def test_base_plugin_reported_traces_empty(self):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        class _M(BasePlugin):
            @property
            def name(self):
                return "Minimal"

        assert _M().reported_traces() == {}

    def test_base_plugin_reported_values_empty(self):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        class _M(BasePlugin):
            @property
            def name(self):
                return "Minimal"

        assert _M().reported_values() == {}

    def test_trace_plugin_reported_traces_single_channel(self, qapp):
        p = _SimpleTrace()
        traces = p.reported_traces()
        assert "simpletrace:SimpleTrace" in traces
        assert traces["simpletrace:SimpleTrace"] == "simpletrace.data['SimpleTrace']"

    def test_trace_plugin_reported_traces_multi_channel(self, qapp):
        class _TwoChannel(_SimpleTrace):
            @property
            def channel_names(self):
                return ["ch1", "ch2"]

        p = _TwoChannel()
        traces = p.reported_traces()
        assert "simpletrace:ch1" in traces
        assert "simpletrace:ch2" in traces
        assert traces["simpletrace:ch1"] == "simpletrace.data['ch1']"

    def test_trace_plugin_reported_values_empty(self, qapp):
        assert _SimpleTrace().reported_values() == {}

    def test_trace_plugin_custom_instance_name(self, qapp):
        p = _SimpleTrace()
        p.instance_name = "my_trace"
        traces = p.reported_traces()
        assert "my_trace:SimpleTrace" in traces
        assert traces["my_trace:SimpleTrace"] == "my_trace.data['SimpleTrace']"

    def test_monitor_plugin_reported_values(self, qapp):
        p = _ConstMonitor()
        vals = p.reported_values()
        assert "constmonitor:temperature" in vals
        assert "constmonitor:pressure" in vals
        assert vals["constmonitor:temperature"] == "constmonitor.last_reading['temperature']"
        assert vals["constmonitor:pressure"] == "constmonitor.last_reading['pressure']"

    def test_monitor_plugin_reported_traces_empty(self, qapp):
        assert _ConstMonitor().reported_traces() == {}

    def test_state_control_plugin_reported_values(self, qapp):
        p = _InstantState()
        vals = p.reported_values()
        assert "instantstate:Voltage" in vals
        assert "instantstate:Index" in vals
        assert vals["instantstate:Voltage"] == "instantstate.value"
        assert vals["instantstate:Index"] == "instantstate.index"

    def test_state_control_plugin_reported_traces_empty(self, qapp):
        assert _InstantState().reported_traces() == {}

    def test_transform_plugin_reported_values_default_all_outputs(self, qapp):
        p = _ScaleTransform()
        vals = p.reported_values()
        assert "scale:y_scaled" in vals
        assert vals["scale:y_scaled"] == "scale.data['y_scaled']"

    def test_transform_plugin_reported_traces_empty_by_default(self, qapp):
        assert _ScaleTransform().reported_traces() == {}

    def test_transform_plugin_output_trace_names_override(self, qapp):
        class _MixedTransform(TransformPlugin):
            @property
            def name(self):
                return "Mixed"

            @property
            def required_inputs(self):
                return []

            @property
            def output_names(self):
                return ["curve", "rms"]

            @property
            def output_trace_names(self):
                return ["curve"]

            @property
            def output_value_names(self):
                return ["rms"]

            def transform(self, data):
                return {}

        p = _MixedTransform()
        traces = p.reported_traces()
        vals = p.reported_values()
        assert "mixed:curve" in traces
        assert traces["mixed:curve"] == "mixed.data['curve']"
        assert "mixed:rms" in vals
        assert vals["mixed:rms"] == "mixed.data['rms']"
        assert "mixed:curve" not in vals

    def test_transform_plugin_run_stores_data(self, qapp):
        p = _ScaleTransform()
        p.run({"y": [1.0, 2.0]})
        assert p.data == {"y_scaled": [3.0, 6.0]}

    def test_transform_plugin_data_empty_before_run(self, qapp):
        assert _ScaleTransform().data == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
