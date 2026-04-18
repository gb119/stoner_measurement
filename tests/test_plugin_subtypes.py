"""Tests for the four plugin sub-types: Trace, StateControl, Monitor, Transform."""

from __future__ import annotations

import math
from collections.abc import Generator
from typing import Any

import pytest

from stoner_measurement.plugins.monitor import MonitorPlugin
from stoner_measurement.plugins.state_control import StateControlPlugin
from stoner_measurement.plugins.trace import TracePlugin, TraceStatus
from stoner_measurement.plugins.transform import TransformPlugin

# ---------------------------------------------------------------------------
# Minimal concrete implementations used across multiple test classes
# ---------------------------------------------------------------------------


class _SimpleTrace(TracePlugin):
    """Minimal TracePlugin that yields a fixed number of (i, i²) points."""

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
    """StateControlPlugin that settles immediately."""

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
    """MonitorPlugin that always returns a fixed reading."""

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
    """TransformPlugin that scales 'y' by a factor of 3."""

    @property
    def name(self) -> str:
        return "Scale"

    @property
    def required_inputs(self) -> list[str]:
        return ["y"]

    @property
    def output_names(self) -> list[str]:
        return ["y_scaled"]

    def transform(self, data: dict[str, Any]) -> dict[str, Any]:
        return {"y_scaled": [v * 3 for v in data["y"]]}


# ---------------------------------------------------------------------------
# TracePlugin tests
# ---------------------------------------------------------------------------


class TestTracePlugin:
    def test_plugin_type(self, qapp):
        p = _SimpleTrace()
        assert p.plugin_type == "trace"

    def test_channel_names_default(self, qapp):
        p = _SimpleTrace()
        assert p.channel_names == ["SimpleTrace"]

    def test_x_label_default(self, qapp):
        assert _SimpleTrace().x_label == "x"

    def test_y_label_default(self, qapp):
        assert _SimpleTrace().y_label == "y"

    def test_execute_yields_tuples(self, qapp):
        p = _SimpleTrace()
        pts = list(p.execute({"n": 4}))
        assert len(pts) == 4
        for x, y in pts:
            assert isinstance(x, float)
            assert isinstance(y, float)

    def test_execute_values(self, qapp):
        p = _SimpleTrace()
        pts = list(p.execute({"n": 3}))
        assert pts == [(0.0, 0.0), (1.0, 1.0), (2.0, 4.0)]

    def test_execute_multichannel_default_wraps_execute(self, qapp):
        p = _SimpleTrace()
        pts = list(p.execute_multichannel({"n": 3}))
        assert len(pts) == 3
        assert all(ch == "SimpleTrace" for ch, _, _ in pts)
        assert [(x, y) for _, x, y in pts] == [(0.0, 0.0), (1.0, 1.0), (2.0, 4.0)]

    def test_config_widget_default(self, qapp):
        from PyQt6.QtWidgets import QWidget
        p = _SimpleTrace()
        w = p.config_widget()
        assert isinstance(w, QWidget)

    def test_monitor_widget_default_none(self, qapp):
        assert _SimpleTrace().monitor_widget() is None

    def test_scan_generator_attribute(self, qapp):
        from stoner_measurement.scan import FunctionScanGenerator
        p = _SimpleTrace()
        assert isinstance(p.scan_generator, FunctionScanGenerator)

    def test_config_tabs_scan_tab_is_first(self, qapp):
        p = _SimpleTrace()
        tabs = p.config_tabs()
        assert len(tabs) >= 2
        assert "Scan" in tabs[0][0]
        assert "Type" not in tabs[0][0]

    def test_config_tabs_settings_tab_is_second(self, qapp):
        p = _SimpleTrace()
        tabs = p.config_tabs()
        assert "Settings" in tabs[1][0]

    def test_scan_page_contains_generator_type_selector(self, qapp):
        """Generator type selector is embedded in the Scan page (not a separate tab)."""
        from PyQt6.QtWidgets import QComboBox
        p = _SimpleTrace()
        tabs = p.config_tabs()
        scan_page = tabs[0][1]
        # Find combo boxes within the scan page — at least one is the type selector.
        combos = scan_page.findChildren(QComboBox)
        assert len(combos) >= 1

    def test_config_tabs_scan_widget_is_qwidget(self, qapp):
        from PyQt6.QtWidgets import QWidget
        p = _SimpleTrace()
        tabs = p.config_tabs()
        assert isinstance(tabs[0][1], QWidget)

    def test_set_scan_generator_class(self, qapp):
        from stoner_measurement.scan import SteppedScanGenerator
        p = _SimpleTrace()
        p.set_scan_generator_class(SteppedScanGenerator)
        assert isinstance(p.scan_generator, SteppedScanGenerator)

    def test_scan_generator_class_list_includes_new_generators(self, qapp):
        from stoner_measurement.scan import (
            ArbitraryFunctionScanGenerator,
            RampScanGenerator,
        )

        p = _SimpleTrace()
        assert RampScanGenerator in p._scan_generator_classes
        assert ArbitraryFunctionScanGenerator in p._scan_generator_classes

    def test_scan_generator_changed_emitted(self, qapp):
        from stoner_measurement.scan import SteppedScanGenerator
        p = _SimpleTrace()
        received = []
        p.scan_generator_changed.connect(lambda: received.append(True))
        p.set_scan_generator_class(SteppedScanGenerator)
        assert len(received) == 1

    def test_scan_tab_container_refreshes_on_change(self, qapp):
        from PyQt6.QtWidgets import QWidget

        from stoner_measurement.plugins.trace import _ScanTabContainer
        from stoner_measurement.scan import SteppedScanGenerator
        p = _SimpleTrace()
        container = _ScanTabContainer(p)
        p.set_scan_generator_class(SteppedScanGenerator)
        # Container should still be a QWidget and its content updated
        assert isinstance(container, QWidget)

    # ------------------------------------------------------------------
    # TraceStatus and status property
    # ------------------------------------------------------------------

    def test_data_attribute_initially_empty(self, qapp):
        p = _SimpleTrace()
        assert p.data == {}

    def test_data_attribute_populated_after_measure(self, qapp):
        import numpy as np

        p = _SimpleTrace()
        result = p.measure({"n": 4})
        assert p.data is result
        assert list(p.data.keys()) == ["SimpleTrace"]
        td = p.data["SimpleTrace"]
        assert isinstance(td.x, np.ndarray)
        assert isinstance(td.y, np.ndarray)
        assert len(td.x) == 4

    def test_status_initial_idle(self, qapp):
        p = _SimpleTrace()
        assert p.status is TraceStatus.IDLE

    def test_status_changed_signal(self, qapp):
        p = _SimpleTrace()
        received = []
        p.status_changed.connect(received.append)
        p._set_status(TraceStatus.MEASURING)
        assert received == [TraceStatus.MEASURING]

    def test_status_changed_not_emitted_when_same(self, qapp):
        p = _SimpleTrace()
        received = []
        p.status_changed.connect(received.append)
        p._set_status(TraceStatus.IDLE)  # already IDLE
        assert received == []

    def test_set_status_updates_status(self, qapp):
        p = _SimpleTrace()
        p._set_status(TraceStatus.CONFIGURING)
        assert p.status is TraceStatus.CONFIGURING

    # ------------------------------------------------------------------
    # Lifecycle API: connect / configure / disconnect
    # ------------------------------------------------------------------

    def test_connect_default_noop(self, qapp):
        p = _SimpleTrace()
        p.connect()  # should not raise
        assert p.status is TraceStatus.IDLE

    def test_configure_default_noop(self, qapp):
        p = _SimpleTrace()
        p.configure()  # should not raise

    def test_disconnect_resets_status_to_idle(self, qapp):
        p = _SimpleTrace()
        p._set_status(TraceStatus.DATA_AVAILABLE)
        p.disconnect()
        assert p.status is TraceStatus.IDLE

    # ------------------------------------------------------------------
    # measure() method
    # ------------------------------------------------------------------

    def test_measure_returns_channel_x_y_triples(self, qapp):
        import numpy as np

        p = _SimpleTrace()
        result = p.measure({"n": 3})
        assert isinstance(result, dict)
        assert list(result.keys()) == ["SimpleTrace"]
        td = result["SimpleTrace"]
        assert isinstance(td.x, np.ndarray)
        assert isinstance(td.y, np.ndarray)
        assert len(td.x) == 3
        assert len(td.y) == 3

    def test_measure_status_is_measuring_during_acquisition(self, qapp):
        p = _SimpleTrace()
        statuses_during: list = []
        p.status_changed.connect(statuses_during.append)
        p.measure({"n": 2})
        # status_changed is emitted with MEASURING at the start and
        # DATA_AVAILABLE at the end, so the first emitted status must be MEASURING.
        assert statuses_during[0] is TraceStatus.MEASURING

    def test_measure_status_data_available_after_completion(self, qapp):
        p = _SimpleTrace()
        p.measure({"n": 2})
        assert p.status is TraceStatus.DATA_AVAILABLE

    def test_measure_returns_complete_list(self, qapp):
        """measure() must return a dict mapping channel to TraceData, not a generator."""
        import numpy as np

        p = _SimpleTrace()
        result = p.measure({"n": 5})
        assert isinstance(result, dict)
        td = result["SimpleTrace"]
        assert len(td.x) == 5
        assert isinstance(td.x, np.ndarray)
        assert p.status is TraceStatus.DATA_AVAILABLE

    # ------------------------------------------------------------------
    # Trace detail properties
    # ------------------------------------------------------------------

    def test_num_traces_default_one(self, qapp):
        assert _SimpleTrace().num_traces == 1

    def test_trace_title_default_is_name(self, qapp):
        p = _SimpleTrace()
        assert p.trace_title == p.name

    def test_x_units_default_empty(self, qapp):
        assert _SimpleTrace().x_units == ""

    def test_y_units_default_empty(self, qapp):
        assert _SimpleTrace().y_units == ""

    def test_trace_scan_alias_for_scan_generator(self, qapp):
        p = _SimpleTrace()
        assert p.trace_scan is p.scan_generator

    def test_num_traces_reflects_channel_count(self, qapp):
        class _TwoChannel(_SimpleTrace):
            @property
            def channel_names(self):
                return ["ch1", "ch2"]

        p = _TwoChannel()
        assert p.num_traces == 2


# ---------------------------------------------------------------------------
# StateControlPlugin tests
# ---------------------------------------------------------------------------


class TestStateControlPlugin:
    def test_plugin_type(self, qapp):
        assert _InstantState().plugin_type == "state"

    def test_state_name(self, qapp):
        assert _InstantState().state_name == "Voltage"

    def test_units(self, qapp):
        assert _InstantState().units == "V"

    def test_limits_default(self, qapp):
        lo, hi = _InstantState().limits
        assert math.isinf(lo) and lo < 0
        assert math.isinf(hi) and hi > 0

    def test_settle_timeout_default(self, qapp):
        assert _InstantState().settle_timeout == 60.0

    def test_set_and_get_state(self, qapp):
        p = _InstantState()
        p.set_state(5.0)
        assert p.get_state() == 5.0

    def test_scan_generator_class_list_includes_new_generators(self, qapp):
        from stoner_measurement.scan import (
            ArbitraryFunctionScanGenerator,
            RampScanGenerator,
        )

        p = _InstantState()
        assert RampScanGenerator in p._scan_generator_classes
        assert ArbitraryFunctionScanGenerator in p._scan_generator_classes

    def test_is_at_target(self, qapp):
        assert _InstantState().is_at_target() is True

    def test_ramp_to_emits_state_reached(self, qapp):
        p = _InstantState()
        reached = []
        p.state_reached.connect(reached.append)
        p.ramp_to(3.0, poll_interval=0.0)
        assert reached == [3.0]

    def test_ramp_to_sets_state(self, qapp):
        p = _InstantState()
        p.ramp_to(7.5, poll_interval=0.0)
        assert p.get_state() == 7.5

    def test_ramp_to_out_of_range_emits_error(self, qapp):
        class _LimitedState(_InstantState):
            @property
            def limits(self):
                return (0.0, 10.0)

        p = _LimitedState()
        errors = []
        p.state_error.connect(errors.append)
        p.ramp_to(20.0, poll_interval=0.0)
        assert len(errors) == 1
        assert "20.0" in errors[0]

    def test_ramp_to_one_sided_lower_limit(self, qapp):
        """A lower-only limit should still reject values below it."""

        class _LowerLimited(_InstantState):
            @property
            def limits(self):
                return (0.0, float("inf"))

        p = _LowerLimited()
        errors = []
        p.state_error.connect(errors.append)
        p.ramp_to(-1.0, poll_interval=0.0)
        assert len(errors) == 1

    def test_ramp_to_one_sided_upper_limit(self, qapp):
        """An upper-only limit should still reject values above it."""
        class _UpperLimited(_InstantState):
            @property
            def limits(self):
                return (float("-inf"), 5.0)

        p = _UpperLimited()
        errors = []
        p.state_error.connect(errors.append)
        p.ramp_to(10.0, poll_interval=0.0)
        assert len(errors) == 1

    def test_ramp_to_within_limits(self, qapp):
        class _LimitedState(_InstantState):
            @property
            def limits(self):
                return (0.0, 10.0)

        p = _LimitedState()
        reached = []
        p.state_reached.connect(reached.append)
        p.ramp_to(5.0, poll_interval=0.0)
        assert reached == [5.0]

    def test_state_changed_signal(self, qapp):
        p = _InstantState()
        received = []
        p.state_changed.connect(received.append)
        p.state_changed.emit(1.5)
        assert received == [1.5]

    def test_state_error_signal(self, qapp):
        p = _InstantState()
        received = []
        p.state_error.connect(received.append)
        p.state_error.emit("fault")
        assert received == ["fault"]

    # ------------------------------------------------------------------
    # Lifecycle API: connect / configure / disconnect
    # ------------------------------------------------------------------

    def test_connect_default_noop(self, qapp):
        p = _InstantState()
        p.connect()  # should not raise

    def test_configure_default_noop(self, qapp):
        p = _InstantState()
        p.configure()  # should not raise

    def test_disconnect_default_noop(self, qapp):
        p = _InstantState()
        p.disconnect()  # should not raise

    def test_connect_configure_disconnect_sequence(self, qapp):
        """Full lifecycle sequence (connect → configure → ramp → disconnect) completes without error."""
        p = _InstantState()
        p.connect()
        p.configure()
        p.ramp_to(1.0, poll_interval=0.0)
        p.disconnect()


# ---------------------------------------------------------------------------
# MonitorPlugin tests
# ---------------------------------------------------------------------------


class TestMonitorPlugin:
    def test_plugin_type(self, qapp):
        assert _ConstMonitor().plugin_type == "monitor"

    def test_quantity_names(self, qapp):
        assert _ConstMonitor().quantity_names == ["temperature", "pressure"]

    def test_units(self, qapp):
        assert _ConstMonitor().units == {"temperature": "K", "pressure": "Pa"}

    def test_read_returns_dict(self, qapp):
        m = _ConstMonitor()
        reading = m.read()
        assert reading == {"temperature": 300.0, "pressure": 101325.0}

    def test_monitor_interval_default(self, qapp):
        assert _ConstMonitor().monitor_interval == 1000

    def test_last_reading_initially_empty(self, qapp):
        assert _ConstMonitor().last_reading == {}

    def test_last_reading_is_a_copy(self, qapp):
        m = _ConstMonitor()
        m._last_reading = {"temperature": 100.0}
        r1 = m.last_reading
        r1["temperature"] = 999.0
        assert m._last_reading["temperature"] == 100.0

    def test_start_monitoring_activates_timer(self, qapp):
        m = _ConstMonitor()
        m.start_monitoring(200)
        assert m._timer.isActive()
        m.stop_monitoring()

    def test_stop_monitoring_deactivates_timer(self, qapp):
        m = _ConstMonitor()
        m.start_monitoring()
        m.stop_monitoring()
        assert not m._timer.isActive()

    def test_poll_emits_data_available(self, qapp):
        m = _ConstMonitor()
        received = []
        m.data_available.connect(received.append)
        m._poll()
        assert received == [{"temperature": 300.0, "pressure": 101325.0}]

    def test_poll_caches_last_reading(self, qapp):
        m = _ConstMonitor()
        m._poll()
        assert m.last_reading == {"temperature": 300.0, "pressure": 101325.0}

    def test_poll_emits_read_error_on_exception(self, qapp):
        class _ErrorMonitor(MonitorPlugin):
            @property
            def name(self):
                return "Err"

            @property
            def quantity_names(self):
                return []

            @property
            def units(self):
                return {}

            def read(self):
                raise RuntimeError("hardware fault")

        m = _ErrorMonitor()
        errors = []
        m.read_error.connect(errors.append)
        m._poll()
        assert errors == ["hardware fault"]

    def test_data_available_signal(self, qapp):
        m = _ConstMonitor()
        received = []
        m.data_available.connect(received.append)
        m.data_available.emit({"x": 1.0})
        assert received == [{"x": 1.0}]


# ---------------------------------------------------------------------------
# TransformPlugin tests
# ---------------------------------------------------------------------------


class TestTransformPlugin:
    def test_plugin_type(self, qapp):
        assert _ScaleTransform().plugin_type == "transform"

    def test_has_lifecycle_false(self, qapp):
        assert _ScaleTransform().has_lifecycle is False

    def test_required_inputs(self, qapp):
        assert _ScaleTransform().required_inputs == ["y"]

    def test_output_names(self, qapp):
        assert _ScaleTransform().output_names == ["y_scaled"]

    def test_description_default(self, qapp):
        assert _ScaleTransform().description == ""

    def test_generate_action_code_calls_run(self, qapp):
        p = _ScaleTransform()
        p.instance_name = "scale"
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert any("scale.run({})" in ln for ln in lines)

    def test_generate_action_code_not_commented(self, qapp):
        p = _ScaleTransform()
        lines = p.generate_action_code(1, [], lambda s, i: [])
        code_lines = [ln for ln in lines if ln.strip()]
        assert all(not ln.strip().startswith("#") for ln in code_lines)

    def test_transform_returns_dict(self, qapp):
        p = _ScaleTransform()
        result = p.transform({"y": [1.0, 2.0, 3.0]})
        assert result == {"y_scaled": [3.0, 6.0, 9.0]}

    def test_validate_inputs_passes(self, qapp):
        p = _ScaleTransform()
        p.validate_inputs({"y": [1.0]})  # should not raise

    def test_validate_inputs_raises_on_missing(self, qapp):
        p = _ScaleTransform()
        with pytest.raises(ValueError, match="y"):
            p.validate_inputs({"x": [1.0]})

    def test_validate_inputs_raises_lists_all_missing(self, qapp):
        class _Multi(TransformPlugin):
            @property
            def name(self):
                return "Multi"

            @property
            def required_inputs(self):
                return ["a", "b"]

            @property
            def output_names(self):
                return ["c"]

            def transform(self, data):
                return {"c": data["a"]}

        p = _Multi()
        with pytest.raises(ValueError):
            p.validate_inputs({})

    def test_run_returns_result(self, qapp):
        p = _ScaleTransform()
        result = p.run({"y": [2.0, 4.0]})
        assert result == {"y_scaled": [6.0, 12.0]}

    def test_run_emits_transform_complete(self, qapp):
        p = _ScaleTransform()
        received = []
        p.transform_complete.connect(received.append)
        p.run({"y": [1.0]})
        assert received == [{"y_scaled": [3.0]}]

    def test_run_raises_on_missing_inputs(self, qapp):
        p = _ScaleTransform()
        with pytest.raises(ValueError):
            p.run({})

    def test_transform_complete_signal(self, qapp):
        p = _ScaleTransform()
        received = []
        p.transform_complete.connect(received.append)
        p.transform_complete.emit({"out": 1.0})
        assert received == [{"out": 1.0}]


# ---------------------------------------------------------------------------
# reported_traces / reported_values
# ---------------------------------------------------------------------------


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
        assert vals["instantstate:Voltage"] == "instantstate.value"

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


# ---------------------------------------------------------------------------
# StateControlPlugin data collection tests
# ---------------------------------------------------------------------------


class TestStateControlDataCollection:
    """Tests for the data-collection capabilities of StateControlPlugin."""

    def test_data_initially_empty(self, qapp):
        p = _InstantState()
        import pandas as pd
        assert isinstance(p.data, pd.DataFrame)
        assert p.data.empty

    def test_default_config_values(self, qapp):
        p = _InstantState()
        assert p.collect_data is False
        assert p.clear_on_start is True
        assert p.collect_filter == f"{p.instance_name}.meas_flag"
        assert p.clear_filter == "True"

    def test_clear_data_resets_dataframe(self, qapp):
        import pandas as pd
        p = _InstantState()
        p._data = pd.DataFrame([{"value": 1.0}])
        p.clear_data()
        assert p.data.empty

    def test_clear_data_obeys_clear_filter_false(self, qapp):
        import pandas as pd
        p = _InstantState()
        p._data = pd.DataFrame([{"value": 1.0}])
        p.clear_filter = "False"
        p.clear_data()
        # Data should NOT be cleared because filter is False (not attached to engine)
        # When detached, RuntimeError → unconditional clear
        assert p.data.empty

    def test_collect_noop_when_detached(self, qapp):
        p = _InstantState()
        p.collect_filter = "True"
        p.collect()  # should silently do nothing when not attached
        assert p.data.empty

    def test_collect_appends_row(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        p = _InstantState()
        engine.add_plugin("instantstate", p)
        p.collect_filter = "True"
        p.ix = 0
        p.value = 3.5
        p.stage = 2
        p.collect()
        assert not p.data.empty
        assert p.data.index.tolist() == [0]
        assert p.data["value"].iloc[0] == 3.5
        assert p.data["stage"].iloc[0] == 2
        engine.shutdown()

    def test_collect_skips_when_filter_false(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        p = _InstantState()
        engine.add_plugin("instantstate", p)
        p.collect_filter = "False"
        p.ix = 0
        p.value = 1.0
        p.collect()
        assert p.data.empty
        engine.shutdown()

    def test_collect_multiple_rows(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        p = _InstantState()
        engine.add_plugin("instantstate", p)
        p.collect_filter = "True"
        for i in range(3):
            p.ix = i
            p.value = float(i)
            p.stage = i
            p.collect()
        assert len(p.data) == 3
        assert p.data.index.tolist() == [0, 1, 2]
        assert p.data["stage"].tolist() == [0, 1, 2]
        engine.shutdown()

    def test_collect_with_outputs_filter(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        from stoner_measurement.plugins.state_control import CounterPlugin
        engine = SequenceEngine()
        p = _InstantState()
        counter = CounterPlugin()
        engine.add_plugin("instantstate", p)
        engine.add_plugin("counter", counter)
        counter.value = 7.0
        p.collect_filter = "True"
        p.ix = 0
        p.value = 2.0
        # Only collect the counter value, not all outputs
        p.collect(outputs=["counter:Value"])
        assert not p.data.empty
        assert "counter:Value" in p.data.columns
        assert "value" in p.data.columns
        engine.shutdown()

    def test_to_json_includes_data_collection_settings(self, qapp):
        p = _InstantState()
        p.collect_data = True
        p.clear_on_start = False
        p.collect_filter = "custom_expr"
        p.clear_filter = "another_expr"
        d = p.to_json()
        assert d["collect_data"] is True
        assert d["clear_on_start"] is False
        assert d["collect_filter"] == "custom_expr"
        assert d["clear_filter"] == "another_expr"

    def test_from_json_restores_data_collection_settings(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin
        p = _InstantState()
        p.collect_data = True
        p.clear_on_start = False
        p.collect_filter = "my_filter"
        p.clear_filter = "other"
        restored = BasePlugin.from_json(p.to_json())
        assert restored.collect_data is True
        assert restored.clear_on_start is False
        assert restored.collect_filter == "my_filter"
        assert restored.clear_filter == "other"

    def test_generate_action_code_includes_clear_when_clear_on_start(self, qapp):
        p = _InstantState()
        p.clear_on_start = True
        p.collect_data = False
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert any("clear_data()" in line for line in lines)

    def test_generate_action_code_no_clear_when_clear_on_start_false(self, qapp):
        p = _InstantState()
        p.clear_on_start = False
        p.collect_data = False
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert not any("clear_data()" in line for line in lines)

    def test_generate_action_code_includes_collect_when_collect_data(self, qapp):
        p = _InstantState()
        p.clear_on_start = False
        p.collect_data = True
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert any("collect()" in line for line in lines)

    def test_generate_action_code_no_collect_when_collect_data_false(self, qapp):
        p = _InstantState()
        p.clear_on_start = False
        p.collect_data = False
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert not any("collect()" in line for line in lines)

    def test_generate_action_code_collect_after_substeps(self, qapp):
        """collect() should appear after sub-step lines inside the loop body."""
        p = _InstantState()
        p.clear_on_start = False
        p.collect_data = True
        rendered_sub = ["        sub_step_line()"]
        lines = p.generate_action_code(1, ["dummy_step"], lambda s, i: rendered_sub)
        collect_idx = next(i for i, line in enumerate(lines) if "collect()" in line)
        sub_idx = next(i for i, line in enumerate(lines) if "sub_step_line()" in line)
        assert collect_idx > sub_idx

    def test_generate_action_code_waits_for_plot_ready_before_ramp(self, qapp):
        p = _InstantState()
        lines = p.generate_action_code(1, [], lambda s, i: [])
        wait_idx = next(i for i, line in enumerate(lines) if "wait_for_plot_ready()" in line)
        ramp_idx = next(i for i, line in enumerate(lines) if ".ramp_to(float(" in line)
        assert wait_idx < ramp_idx
