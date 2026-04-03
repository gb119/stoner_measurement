"""Tests for the four plugin sub-types: Trace, StateControl, Monitor, Transform."""

from __future__ import annotations

import math
from typing import Any, Generator

import pytest

from PyQt6.QtWidgets import QApplication

from stoner_measurement.plugins.monitor import MonitorPlugin
from stoner_measurement.plugins.state_control import StateControlPlugin
from stoner_measurement.plugins.trace import TracePlugin
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
    ) -> Generator[tuple[float, float], None, None]:
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

    def test_trace_started_signal(self, qapp):
        p = _SimpleTrace()
        received = []
        p.trace_started.connect(received.append)
        p.trace_started.emit("SimpleTrace")
        assert received == ["SimpleTrace"]

    def test_trace_point_signal(self, qapp):
        p = _SimpleTrace()
        received = []
        p.trace_point.connect(lambda ch, x, y: received.append((ch, x, y)))
        p.trace_point.emit("ch1", 1.0, 2.0)
        assert received == [("ch1", 1.0, 2.0)]

    def test_trace_complete_signal(self, qapp):
        p = _SimpleTrace()
        received = []
        p.trace_complete.connect(received.append)
        p.trace_complete.emit("SimpleTrace")
        assert received == ["SimpleTrace"]

    def test_config_widget_default(self, qapp):
        from PyQt6.QtWidgets import QWidget
        p = _SimpleTrace()
        w = p.config_widget()
        assert isinstance(w, QWidget)

    def test_monitor_widget_default_none(self, qapp):
        assert _SimpleTrace().monitor_widget() is None


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
        import math

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

    def test_required_inputs(self, qapp):
        assert _ScaleTransform().required_inputs == ["y"]

    def test_output_names(self, qapp):
        assert _ScaleTransform().output_names == ["y_scaled"]

    def test_description_default(self, qapp):
        assert _ScaleTransform().description == ""

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
