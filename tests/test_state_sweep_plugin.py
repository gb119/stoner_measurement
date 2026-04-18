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
