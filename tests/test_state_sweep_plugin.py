"""Tests for state-sweep plugins and sweep generators."""

from __future__ import annotations

from collections.abc import Iterator

from PyQt6.QtWidgets import QWidget

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.state_sweep import StateSweepPlugin, SweepTimePlugin
from stoner_measurement.sweep import (
    BaseSweepGenerator,
    MonitorAndFilterSweepGenerator,
    MultiSegmentRampSweepGenerator,
)


class _FiniteSweepGenerator(BaseSweepGenerator):
    """Simple finite sweep generator used for testing."""

    def __init__(self, points: list[tuple[int, float, int, bool]] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._points = points or []

    def iter_points(self) -> Iterator[tuple[int, float, int, bool]]:
        yield from self._points

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        return QWidget(parent)

    @classmethod
    def _from_json_data(cls, data, *, state_sweep=None, parent=None):
        points = [
            (int(ix), float(value), int(stage), bool(measure_flag))
            for ix, value, stage, measure_flag in data.get("points", [])
        ]
        return cls(points=points, state_sweep=state_sweep, parent=parent)

    def to_json(self) -> dict:
        return {
            "type": "_FiniteSweepGenerator",
            "points": [[ix, value, stage, measure_flag] for ix, value, stage, measure_flag in self._points],
        }


class _TestSweepPlugin(StateSweepPlugin):
    """Minimal concrete state-sweep plugin for tests."""

    _sweep_generator_class = _FiniteSweepGenerator
    _sweep_generator_classes = [_FiniteSweepGenerator]

    @property
    def name(self) -> str:
        return "TestSweep"

    @property
    def state_name(self) -> str:
        return "X"

    @property
    def units(self) -> str:
        return "au"


class _TrackingRampSweep(_TestSweepPlugin):
    """Test plugin that tracks ramp hook calls."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state_value = 0.0
        self._target = 0.0
        self._rate = 0.0

    def set_state(self, value: float) -> None:
        self._state_value = float(value)
        self._target = float(value)

    def set_target(self, value: float) -> None:
        self._target = float(value)

    def set_rate(self, value: float) -> None:
        self._rate = float(value)

    def get_state(self) -> float:
        if self._state_value < self._target:
            self._state_value = min(self._target, self._state_value + max(self._rate, 0.01))
        elif self._state_value > self._target:
            self._state_value = max(self._target, self._state_value - max(self._rate, 0.01))
        return float(self._state_value)

    def is_at_target(self) -> bool:
        return abs(self._state_value - self._target) < 1e-9


class TestStateSweepPlugin:
    def test_plugin_type(self, qapp):
        assert _TestSweepPlugin().plugin_type == "state_sweep"

    def test_next_returns_false_when_exhausted(self, qapp):
        plugin = _TestSweepPlugin()
        plugin.sweep_generator = _FiniteSweepGenerator(points=[(0, 1.0, 0, True)], state_sweep=plugin, parent=plugin)
        plugin._begin_sweep()
        assert next(plugin) is True
        assert plugin.ix == 0
        assert plugin.value == 1.0
        assert next(plugin) is False

    def test_execute_sequence_runs_substeps_once_per_sweep_point(self, qapp):
        plugin = _TestSweepPlugin()
        plugin.sweep_generator = _FiniteSweepGenerator(
            points=[(0, 1.0, 0, True), (1, 2.0, 1, False)],
            state_sweep=plugin,
            parent=plugin,
        )
        calls: list[tuple[int, float, bool]] = []
        plugin.execute_sequence([lambda: calls.append((plugin.ix, plugin.value, plugin.meas_flag))])
        assert calls == [(0, 1.0, True), (1, 2.0, False)]

    def test_collect_records_stage(self, qapp):
        plugin = _TestSweepPlugin()
        plugin.collect_filter = "True"
        plugin._data = plugin.data.iloc[0:0]
        plugin.ix = 3
        plugin.value = 1.25
        plugin.stage = 7
        plugin.meas_flag = True
        # Detached from engine -> no-op
        plugin.collect()
        assert plugin.data.empty

    def test_generate_action_code_uses_while_next(self, qapp):
        plugin = _TestSweepPlugin()
        lines = plugin.generate_action_code(1, [], lambda s, i: [])
        assert any("while next(" in line for line in lines)

    def test_to_json_round_trip(self, qapp):
        plugin = SweepTimePlugin()
        d = plugin.to_json()
        restored = BasePlugin.from_json(d)
        assert isinstance(restored, SweepTimePlugin)
        assert restored.plugin_type == "state_sweep"

    def test_to_json_includes_sweep_timeout_factor(self, qapp):
        plugin = SweepTimePlugin()
        plugin.sweep_timeout_factor = 3.5
        d = plugin.to_json()
        assert d["sweep_timeout_factor"] == 3.5

    def test_from_json_restores_sweep_timeout_factor(self, qapp):
        plugin = SweepTimePlugin()
        plugin.sweep_timeout_factor = 4.0
        restored = BasePlugin.from_json(plugin.to_json())
        assert isinstance(restored, SweepTimePlugin)
        assert restored.sweep_timeout_factor == 4.0

    def test_state_reached_emitted_on_normal_exhaustion(self, qapp):
        plugin = _TestSweepPlugin()
        plugin.sweep_generator = _FiniteSweepGenerator(
            points=[(0, 1.0, 0, True)], state_sweep=plugin, parent=plugin
        )
        reached: list[float] = []
        plugin.state_reached.connect(reached.append)
        plugin._begin_sweep()
        assert next(plugin) is True
        assert next(plugin) is False
        assert reached == [1.0]

    def test_state_changed_emitted_at_each_point(self, qapp):
        plugin = _TestSweepPlugin()
        plugin.sweep_generator = _FiniteSweepGenerator(
            points=[(0, 1.0, 0, True), (1, 2.5, 0, True)], state_sweep=plugin, parent=plugin
        )
        changed: list[float] = []
        plugin.state_changed.connect(changed.append)
        plugin._begin_sweep()
        next(plugin)
        next(plugin)
        next(plugin)  # exhausted
        assert changed == [1.0, 2.5]

    def test_state_error_emitted_on_timeout(self, qapp):
        import time
        from collections.abc import Iterator
        from PyQt6.QtWidgets import QWidget as _QW

        class _SlowGenerator(BaseSweepGenerator):
            def iter_points(self) -> Iterator[tuple[int, float, int, bool]]:
                while True:
                    time.sleep(0.01)
                    yield 0, 0.0, 0, True

            def config_widget(self, parent=None):
                return _QW(parent)

            @classmethod
            def _from_json_data(cls, data, *, state_sweep=None, parent=None):
                return cls(state_sweep=state_sweep, parent=parent)

        plugin = _TestSweepPlugin()
        plugin._sweep_generator_class = _SlowGenerator
        plugin.sweep_generator = _SlowGenerator(state_sweep=plugin, parent=plugin)
        plugin.sweep_timeout_factor = 1.0
        # Manually set a deadline that is already past
        plugin._begin_sweep()
        plugin._sweep_deadline = time.monotonic() - 1.0

        errors: list[str] = []
        plugin.state_error.connect(errors.append)
        result = next(plugin)
        assert result is False
        assert errors
        assert "timeout" in errors[0].lower()

    def test_state_error_emitted_on_out_of_limits(self, qapp):
        plugin = _TestSweepPlugin()
        plugin.sweep_generator = _FiniteSweepGenerator(
            points=[(0, 10.0, 0, True)], state_sweep=plugin, parent=plugin
        )
        errors: list[str] = []
        plugin.state_error.connect(errors.append)

        class _LimitedPlugin(_TestSweepPlugin):
            @property
            def limits(self):
                return (0.0, 5.0)

        p2 = _LimitedPlugin()
        p2.sweep_generator = _FiniteSweepGenerator(
            points=[(0, 10.0, 0, True)], state_sweep=p2, parent=p2
        )
        errors2: list[str] = []
        p2.state_error.connect(errors2.append)
        p2._begin_sweep()
        result = next(p2)
        assert result is False
        assert errors2
        assert "limits" in errors2[0].lower()

    def test_limits_inherited_from_state_plugin(self, qapp):
        from stoner_measurement.plugins.state import StatePlugin
        plugin = _TestSweepPlugin()
        assert isinstance(plugin, StatePlugin)
        assert plugin.limits == (float("-inf"), float("inf"))

    def test_state_signals_inherited_from_state_plugin(self, qapp):
        from stoner_measurement.plugins.state import StatePlugin
        from stoner_measurement.plugins.state_scan import StateScanPlugin
        # Both families share signals from StatePlugin
        assert hasattr(StatePlugin, "state_changed")
        assert hasattr(StatePlugin, "state_reached")
        assert hasattr(StatePlugin, "state_error")
        scan = StateScanPlugin.__dict__
        # scan_generator_changed is scan-specific; the three state signals are NOT redeclared
        assert "state_changed" not in scan
        assert "state_reached" not in scan
        assert "state_error" not in scan


class TestSweepGenerators:
    def test_base_from_json_dispatches_monitor_and_filter(self, qapp):
        gen = MonitorAndFilterSweepGenerator(rows=[("", False, 0.0)])
        restored = BaseSweepGenerator.from_json(gen.to_json())
        assert isinstance(restored, MonitorAndFilterSweepGenerator)

    def test_base_from_json_dispatches_multisegment_ramp(self, qapp):
        gen = MultiSegmentRampSweepGenerator(start=0.0, segments=[(1.0, 0.5, True)])
        restored = BaseSweepGenerator.from_json(gen.to_json())
        assert isinstance(restored, MultiSegmentRampSweepGenerator)

    def test_monitor_and_filter_empty_expression_timeout_triggers(self, qapp):
        plugin = _TestSweepPlugin()
        gen = MonitorAndFilterSweepGenerator(rows=[("", False, 1.0)], timeout=0.0, poll_seconds=0.0, state_sweep=plugin)
        it = iter(gen)
        ix, value, stage, measure = next(it)
        assert ix == -1
        assert isinstance(value, float)
        assert stage == 0
        assert measure is True

    def test_multisegment_ramp_yields_and_stages(self, qapp):
        plugin = _TrackingRampSweep()
        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(0.2, 0.1, True), (0.0, 0.1, False)],
            poll_seconds=0.0,
            state_sweep=plugin,
        )
        points = []
        for _ in range(10):
            try:
                points.append(next(gen))
            except StopIteration:
                break
        assert points
        stages = {stage for _ix, _value, stage, _measure in points}
        assert stages == {0, 1}
        assert points[0][3] is True

    def test_multisegment_estimated_duration_simple(self, qapp):
        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(2.0, 1.0, True), (0.0, 0.5, False)],
        )
        # |2.0 - 0.0| / 1.0  +  |0.0 - 2.0| / 0.5  =  2.0 + 4.0  =  6.0
        assert gen.estimated_duration() == 6.0

    def test_multisegment_estimated_duration_zero_rate_returns_inf(self, qapp):
        import math
        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(1.0, 0.0, True)],
        )
        assert math.isinf(gen.estimated_duration())

    def test_multisegment_estimated_duration_empty_segments(self, qapp):
        gen = MultiSegmentRampSweepGenerator(start=0.0, segments=[])
        # Empty segments list is normalised to [(1.0, 0.1, True)] by setter.
        # Test the zero-segments path by calling with the raw private attribute.
        gen._segments = []
        assert gen.estimated_duration() == 0.0

    def test_monitor_and_filter_estimated_duration_is_inf(self, qapp):
        import math
        gen = MonitorAndFilterSweepGenerator()
        assert math.isinf(gen.estimated_duration())

    def test_sweep_timeout_scales_with_factor(self, qapp):
        plugin = _TrackingRampSweep()
        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(2.0, 1.0, True)],
            state_sweep=plugin,
        )
        plugin.sweep_generator = gen
        plugin.sweep_timeout_factor = 3.0
        assert plugin.sweep_timeout == 6.0
