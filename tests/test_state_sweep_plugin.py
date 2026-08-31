"""Tests for state-sweep plugins and sweep generators."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from qtpy.QtWidgets import QWidget

import stoner_measurement.ui.generator_json as generator_json_module
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.state_scan import CounterPlugin
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
            "points": [
                [ix, value, stage, measure_flag] for ix, value, stage, measure_flag in self._points
            ],
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

    _default_sweep_timeout_factor = 3.0
    _sweep_rate_time_scale_seconds = 60.0

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

    def test_config_tabs_use_concise_role_titles(self, qapp):
        titles = [title for title, _widget in _TestSweepPlugin().config_tabs()]

        assert titles == ["Sweep", "Data", "Settings", "About"]

    def test_next_returns_false_when_exhausted(self, qapp):
        plugin = _TestSweepPlugin()
        plugin.sweep_generator = _FiniteSweepGenerator(
            points=[(0, 1.0, 0, True)], state_sweep=plugin, parent=plugin
        )
        plugin._begin_sweep()
        assert next(plugin) is True
        assert plugin.ix == 0
        assert plugin.index == 0
        assert plugin.segment == 0
        assert plugin.value == 1.0
        assert next(plugin) is False

    def test_reported_values_include_segment_output(self, qapp):
        plugin = _TestSweepPlugin()
        assert plugin.reported_values() == {
            "testsweep:X": "testsweep.value",
            "testsweep:Index": "testsweep.index",
            "testsweep:Segment": "testsweep.segment",
        }

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
        plugin.clear_data()
        plugin.ix = 3
        plugin.value = 1.25
        plugin.stage = 7
        plugin.meas_flag = True
        # Detached from engine -> no-op
        plugin.collect()
        assert plugin.data.df.empty

    def test_sweep_config_has_output_catalogue_table(self, qapp):
        from qtpy.QtWidgets import QCheckBox, QComboBox, QPushButton, QTableWidget

        from stoner_measurement.core.sequence_engine import SequenceEngine
        engine = SequenceEngine()
        plugin = _TestSweepPlugin()
        counter = CounterPlugin()
        engine.add_plugin("testsweep", plugin)
        engine.add_plugin("counter", counter)
        engine.update_step_plugin_catalog([plugin, counter])
        tabs = plugin.config_tabs()
        data_page = tabs[1][1]
        table = data_page.findChild(QTableWidget, "stateOutputSelectionTable")
        assert table is not None
        value_row = next(
            row
            for row in range(table.rowCount())
            if table.item(row, 1).text() == "counter:Value"
        )
        value_checkbox = table.cellWidget(value_row, 0)
        role_combo = table.cellWidget(value_row, 2)
        assert isinstance(value_checkbox, QCheckBox)
        assert isinstance(role_combo, QComboBox)
        select_all_checkbox = next(
            (
                check
                for check in data_page.findChildren(QCheckBox)
                if check.text() == "Use all catalogue outputs"
            ),
            None,
        )
        assert value_checkbox.isChecked()
        assert role_combo.currentText() == "y"
        assert select_all_checkbox is not None
        assert select_all_checkbox.isChecked()
        data_page.resize(900, 1800)
        data_page.show()
        qapp.processEvents()
        refresh_button = next(
            button
            for button in data_page.findChildren(QPushButton)
            if button.text() == "Refresh output list"
        )
        assert table.y() - (refresh_button.y() + refresh_button.height()) < 50
        value_checkbox.setChecked(False)
        assert not select_all_checkbox.isChecked()
        assert plugin.collect_outputs is not None
        assert "counter:Value" not in plugin.collect_outputs
        select_all_checkbox.setChecked(True)
        assert value_checkbox.isChecked()
        assert role_combo.currentText() == "y"
        assert plugin.collect_outputs is None
        role_combo.setCurrentText("x")
        assert plugin.collect_output_roles["counter:Value"] == "x"
        engine.shutdown()

    def test_sweep_config_uses_humanised_generator_names(self, qapp):
        from qtpy.QtWidgets import QComboBox

        plugin = SweepTimePlugin()
        sweep_page = plugin.config_tabs()[0][1]
        combo = next(iter(sweep_page.findChildren(QComboBox)), None)

        assert combo is not None
        labels = [combo.itemText(i) for i in range(combo.count())]
        assert "Monitor And Filter Sweep Generator" in labels
        assert "Multi Segment Ramp Sweep Generator" in labels

    def test_generate_action_code_uses_while_next(self, qapp):
        plugin = _TestSweepPlugin()
        lines = plugin.generate_action_code(1, [], lambda s, i: [])
        assert any("while next(" in line for line in lines)

    def test_generate_action_code_does_not_print_each_sweep_point(self, qapp):
        lines = _TestSweepPlugin().generate_action_code(1, [], lambda s, i: [])

        assert not any("print(" in line for line in lines)

    def test_sweep_config_exposes_comment_field(self, qapp):
        from qtpy.QtWidgets import QLineEdit

        plugin = _TestSweepPlugin()
        tabs = plugin.config_tabs()
        sweep_page = tabs[0][1]
        edits = sweep_page.findChildren(QLineEdit)

        assert any(edit.text() == plugin.comment for edit in edits)

        comment_edit = edits[1]
        comment_edit.setText("collect during motion")
        comment_edit.editingFinished.emit()

        assert plugin.comment == "collect during motion"

    def test_sweep_page_exposes_engine_polling_rate_control(self, qapp):
        from stoner_measurement.ui.widgets import SISpinBox

        plugin = _TestSweepPlugin()
        sweep_page = plugin.config_tabs()[0][1]
        polling_rate = next(
            spin for spin in sweep_page.findChildren(SISpinBox) if spin.opts["suffix"] == "Hz"
        )

        assert polling_rate.value() == pytest.approx(0.0)
        polling_rate.setValue(5.0)
        assert plugin.engine_polling_rate_hz == pytest.approx(5.0)

    def test_scan_config_exposes_comment_field(self, qapp):
        from qtpy.QtWidgets import QLineEdit

        plugin = CounterPlugin()
        tabs = plugin.config_tabs()
        scan_page = tabs[0][1]
        edits = scan_page.findChildren(QLineEdit)

        assert any(edit.text() == plugin.comment for edit in edits)

        comment_edit = edits[1]
        comment_edit.setText("discrete scan")
        comment_edit.editingFinished.emit()

        assert plugin.comment == "discrete scan"

    def test_generate_action_code_does_not_wrap_substeps_in_measure_flag_if(self, qapp):
        plugin = _TestSweepPlugin()
        lines = plugin.generate_action_code(
            1, ["dummy_step"], lambda s, i: ["        sub_step_line()"]
        )
        assert not any("if testsweep.meas_flag:" in line for line in lines)
        assert "        sub_step_line()" in lines

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
        assert d["engine_polling_rate_hz"] == 0.0

    def test_from_json_restores_sweep_timeout_factor(self, qapp):
        plugin = SweepTimePlugin()
        plugin.sweep_timeout_factor = 4.0
        plugin.engine_polling_rate_hz = 8.0
        restored = BasePlugin.from_json(plugin.to_json())
        assert isinstance(restored, SweepTimePlugin)
        assert restored.sweep_timeout_factor == 4.0
        assert restored.engine_polling_rate_hz == 8.0

    def test_zero_sweep_engine_polling_rate_leaves_engine_unchanged(self, qapp):
        engine = type(
            "Engine",
            (),
            {"polling_rate_hz": 1.0, "set_polling_rate": lambda self, rate: calls.append(rate)},
        )()
        calls: list[float] = []
        plugin = _TestSweepPlugin()
        plugin._engine = lambda: engine

        plugin._begin_sweep()
        plugin._end_sweep()

        assert calls == []

    def test_sweep_engine_polling_rate_is_restored_after_substep_error(self, qapp):
        class _Engine:
            polling_rate_hz = 1.0

            def set_polling_rate(self, rate):
                self.polling_rate_hz = float(rate)
                calls.append(float(rate))

        calls: list[float] = []
        engine = _Engine()
        plugin = _TestSweepPlugin()
        plugin._engine = lambda: engine
        plugin.engine_polling_rate_hz = 10.0
        plugin.sweep_generator = _FiniteSweepGenerator(
            points=[(0, 1.0, 0, True)], state_sweep=plugin, parent=plugin
        )

        with pytest.raises(RuntimeError, match="substep failed"):
            plugin.execute_sequence([lambda: (_ for _ in ()).throw(RuntimeError("substep failed"))])

        assert calls == [10.0, 1.0]
        assert engine.polling_rate_hz == 1.0

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

    def test_current_point_changed_emitted_at_each_point(self, qapp):
        plugin = _TestSweepPlugin()
        plugin.sweep_generator = _FiniteSweepGenerator(
            points=[(0, 1.0, 0, True), (1, 2.5, 0, True)], state_sweep=plugin, parent=plugin
        )
        emitted: list[tuple[int, float, int]] = []
        plugin.sweep_generator.current_point_changed.connect(
            lambda index, value, stage: emitted.append((index, value, stage))
        )
        plugin._begin_sweep()
        next(plugin)
        next(plugin)
        next(plugin)  # exhausted
        assert emitted == [(0, 1.0, 0), (1, 2.5, 0)]

    def test_state_error_emitted_on_timeout(self, qapp):
        class _SlowGenerator(BaseSweepGenerator):
            def iter_points(self) -> Iterator[tuple[int, float, int, bool]]:
                while True:
                    time.sleep(0.01)
                    yield 0, 0.0, 0, True

            def config_widget(self, parent=None):
                return QWidget(parent)

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

    def test_sweep_limits_are_cached_at_start(self, qapp):
        class _CountingLimitsPlugin(_TestSweepPlugin):
            limit_reads = 0

            @property
            def limits(self):
                self.limit_reads += 1
                return (0.0, 5.0)

        plugin = _CountingLimitsPlugin()
        plugin.sweep_generator = _FiniteSweepGenerator(
            points=[(0, 1.0, 0, True), (1, 2.0, 0, True)], state_sweep=plugin, parent=plugin
        )

        plugin._begin_sweep()
        assert next(plugin) is True
        assert next(plugin) is True

        assert plugin.limit_reads == 1

    def test_effective_poll_period_uses_engine_update_rate(self, qapp):
        plugin = _TestSweepPlugin()
        plugin._engine = type("Engine", (), {"polling_rate_hz": 1.0})

        assert plugin.effective_poll_period_seconds(0.05) == pytest.approx(1.0)
        assert plugin.effective_poll_period_seconds(1.5) == pytest.approx(1.5)

    def test_iteration_pacing_sleeps_only_for_remaining_period(self, qapp, monkeypatch):
        plugin = _TestSweepPlugin()
        plugin._engine = lambda: type("Engine", (), {"polling_rate_hz": 1.0})()
        generator = _FiniteSweepGenerator(state_sweep=plugin, parent=plugin)
        sleeps: list[float] = []
        monkeypatch.setattr("stoner_measurement.sweep.base.time.monotonic", lambda: 10.5)
        monkeypatch.setattr("stoner_measurement.sweep.base.time.sleep", sleeps.append)

        generator.pace_iteration(10.0, 0.05)

        assert sleeps == pytest.approx([0.5])

    def test_iteration_pacing_does_not_sleep_after_period_elapsed(self, qapp, monkeypatch):
        plugin = _TestSweepPlugin()
        plugin._engine = lambda: type("Engine", (), {"polling_rate_hz": 1.0})()
        generator = _FiniteSweepGenerator(state_sweep=plugin, parent=plugin)
        sleeps: list[float] = []
        monkeypatch.setattr("stoner_measurement.sweep.base.time.monotonic", lambda: 11.1)
        monkeypatch.setattr("stoner_measurement.sweep.base.time.sleep", sleeps.append)

        generator.pace_iteration(10.0, 0.05)

        assert sleeps == []

    def test_generated_loop_restores_engine_polling_rate(self, qapp):
        lines = _TestSweepPlugin().generate_action_code(1, [], lambda s, i: [])

        assert "    try:" in lines
        assert "    finally:" in lines
        assert "        testsweep._end_sweep()" in lines

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

    def test_member_plugins_empty_when_no_sub_steps(self, qapp):
        plugin = _TestSweepPlugin()
        assert plugin.member_plugins() == []

    def test_member_plugins_returns_direct_plugin_instances(self, qapp):
        parent = _TestSweepPlugin()
        child = _TestSweepPlugin()
        parent.sub_steps = [child]
        assert parent.member_plugins() == [child]

    def test_member_plugins_skips_string_descriptors(self, qapp):
        plugin = _TestSweepPlugin()
        plugin.sub_steps = ["some_entry_point"]
        assert plugin.member_plugins() == []

    def test_member_plugins_handles_tuple_descriptors(self, qapp):
        parent = _TestSweepPlugin()
        child = _TestSweepPlugin()
        parent.sub_steps = [(child, [])]
        assert parent.member_plugins() == [child]

    def test_member_plugins_mixed_entries(self, qapp):
        parent = _TestSweepPlugin()
        child1 = _TestSweepPlugin()
        child2 = _TestSweepPlugin()
        parent.sub_steps = [child1, "string_descriptor", (child2, [])]
        result = parent.member_plugins()
        assert result == [child1, child2]


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
        gen = MonitorAndFilterSweepGenerator(
            rows=[("", False, 1.0)], timeout=0.0, poll_seconds=0.0, state_sweep=plugin
        )
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

    def test_multisegment_ramp_can_start_from_current_value(self, qapp):
        plugin = _TrackingRampSweep()
        plugin._state_value = 0.4
        plugin._target = 0.4
        plugin.start_from_current_value = True
        start_commands: list[float] = []
        original_set_state = plugin.set_state

        def _record_set_state(value: float) -> None:
            start_commands.append(value)
            original_set_state(value)

        plugin.set_state = _record_set_state
        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(1.0, 0.2, False)],
            poll_seconds=0.0,
            state_sweep=plugin,
        )

        first_point = next(gen)

        assert start_commands == []
        assert first_point[0] == 0
        assert first_point[1] == pytest.approx(0.6)
        assert first_point[2:] == (0, False)

    def test_multisegment_widget_current_marker_tracks_generator(self, qapp):
        plugin = _TrackingRampSweep()
        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(0.2, 0.1, True)],
            poll_seconds=0.0,
            state_sweep=plugin,
        )
        widget = gen.config_widget()
        _ix, value, _stage, _measure = next(gen)
        x, y = widget._current_marker.getData()  # noqa: SLF001
        assert x is not None and y is not None
        assert widget._current_marker in widget._preview.getPlotItem().items  # noqa: SLF001
        assert x.tolist() == [abs(value - gen.start) / abs(gen.segments[0][1]) * 60.0]
        assert y[0] == value

    def test_multisegment_estimated_duration_simple(self, qapp):
        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(2.0, 1.0, True), (0.0, 0.5, False)],
        )
        # Conservative estimate includes:
        # start timeout (60.0)
        # + travel time: |2.0 - 0.0| / 1.0 + |0.0 - 2.0| / 0.5 = 6.0
        # + polling overhead: 0.05 * (2 segments + 1 startup phase) = 0.15
        assert gen.estimated_duration() == 66.15

    def test_multisegment_estimated_duration_zero_rate_returns_inf(self, qapp):
        import math

        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(1.0, 0.0, True)],
        )
        assert math.isinf(gen.estimated_duration())

    def test_multisegment_estimated_duration_empty_segments(self, qapp):
        gen = MultiSegmentRampSweepGenerator(start=0.0, segments=[])
        assert gen.segments == []
        assert gen.estimated_duration() == 0.0

    def test_multisegment_file_and_row_buttons_have_requested_order_and_icons(self, qapp):
        widget = MultiSegmentRampSweepGenerator().config_widget()
        buttons = [
            widget._new_btn,
            widget._load_btn,
            widget._save_btn,
            widget._add_btn,
            widget._remove_btn,
        ]
        assert [button.text() for button in buttons] == [
            "",
            "",
            "",
            "+ Segment",
            "− Segment",
        ]
        assert all(not button.icon().isNull() for button in buttons[:3])
        assert [button.toolTip() for button in buttons[:3]] == ["New/Clear", "Load", "Save"]

    def test_multisegment_table_shows_eight_rows_before_scrolling(self, qapp):
        segments = [(float(index), 0.1, True) for index in range(9)]
        widget = MultiSegmentRampSweepGenerator(segments=segments).config_widget()
        expected_height = (
            widget._table.horizontalHeader().height()
            + 8 * widget._table.verticalHeader().defaultSectionSize()
            + 2 * widget._table.frameWidth()
        )
        widget.show()
        qapp.processEvents()
        assert widget._table.height() == expected_height
        assert widget._table.verticalScrollBar().isVisible()

    def test_multisegment_tabs_wrap_four_by_three_preview_height(self, qapp):
        widget = MultiSegmentRampSweepGenerator().config_widget()
        widget.resize(800, 1200)
        widget.show()
        widget._tabs.setCurrentIndex(1)
        qapp.processEvents()
        assert widget._tabs.height() < widget.height()
        assert abs(widget._preview.width() / widget._preview.height() - (4.0 / 3.0)) < 0.01

    def test_multisegment_new_clear_removes_all_segments_but_preserves_settings(self, qapp):
        gen = MultiSegmentRampSweepGenerator(
            start=2.0,
            segments=[(3.0, 0.5, True), (1.0, 0.25, False)],
            poll_seconds=0.2,
            start_timeout_seconds=15.0,
        )
        widget = gen.config_widget()
        widget._new_btn.click()
        assert gen.start == 2.0
        assert gen.poll_seconds == 0.2
        assert gen.start_timeout_seconds == 15.0
        assert gen.segments == []
        assert widget._table.rowCount() == 0

    def test_multisegment_save_and_load_round_trip_updates_bound_generator(
        self,
        qapp,
        tmp_path,
        monkeypatch,
    ):
        gen = MultiSegmentRampSweepGenerator(
            start=2.0,
            segments=[(3.0, 0.5, True), (1.0, 0.25, False)],
            poll_seconds=0.2,
            start_timeout_seconds=15.0,
        )
        widget = gen.config_widget()
        saved_path = tmp_path / "multi-segment-sweep.json"
        monkeypatch.setattr(
            generator_json_module.QFileDialog,
            "getSaveFileName",
            lambda *_args: (str(saved_path), "JSON files (*.json)"),
        )
        widget._save_btn.click()
        assert saved_path.is_file()

        gen.start = -4.0
        gen.poll_seconds = 1.0
        gen.start_timeout_seconds = 2.0
        gen.segments = []
        widget._populate_from_generator()
        monkeypatch.setattr(
            generator_json_module.QFileDialog,
            "getOpenFileName",
            lambda *_args: (str(saved_path), "JSON files (*.json)"),
        )
        widget._load_btn.click()
        assert gen.start == 2.0
        assert gen.poll_seconds == 0.2
        assert gen.start_timeout_seconds == 15.0
        assert gen.segments == [(3.0, 0.5, True), (1.0, 0.25, False)]
        assert widget._table.rowCount() == 2

    def test_monitor_and_filter_estimated_duration_is_inf(self, qapp):
        import math

        gen = MonitorAndFilterSweepGenerator()
        assert math.isinf(gen.estimated_duration())

    def test_monitor_and_filter_table_shows_six_rows_before_scrolling(self, qapp):
        from qtpy.QtWidgets import QLabel

        rows = [(f"parameter_{index}", False, 1.0) for index in range(7)]
        widget = MonitorAndFilterSweepGenerator(rows=rows).config_widget()
        expected_height = (
            widget._table.horizontalHeader().height()
            + 6 * widget._table.verticalHeader().defaultSectionSize()
            + 2 * widget._table.frameWidth()
        )

        widget.resize(900, 1200)
        widget.show()
        qapp.processEvents()

        assert widget._table.height() == expected_height
        assert widget._table.verticalScrollBar().isVisible()
        note = next(
            label
            for label in widget.findChildren(QLabel)
            if label.text() == "Measure flag is set by threshold crossing or timeout."
        )
        assert note.y() + note.height() < widget.height() / 2

    def test_sweep_timeout_scales_with_factor(self, qapp):
        plugin = _TrackingRampSweep()
        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(2.0, 1.0, True)],
            state_sweep=plugin,
        )
        plugin.sweep_generator = gen
        # Conservative estimate includes:
        # start timeout (60.0) + travel time (2.0 * 60 = 120.0) + polling overhead
        # 0.05 * (1 segment + 1 startup phase) = 0.1, then scaled by 3.0.
        assert plugin.sweep_timeout == 540.3

    def test_sweep_timeout_factor_expression_is_resolved_at_use(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        plugin = _TrackingRampSweep()
        plugin.sweep_generator = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(1.0, 1.0, True)],
            state_sweep=plugin,
            parent=plugin,
        )
        plugin.sweep_timeout_factor = "timeout_multiplier"
        engine = SequenceEngine()
        engine.add_plugin("tracking", plugin)
        plugin.engine_namespace["timeout_multiplier"] = 2.0
        try:
            assert plugin.sweep_timeout == pytest.approx(
                plugin.sweep_generator.estimated_duration() * 2.0
            )
        finally:
            engine.shutdown()

    def test_state_sweep_plugin_uses_configurable_timeout_default(self, qapp):
        plugin = _TrackingRampSweep()
        assert plugin.default_sweep_timeout_factor == 3.0
        assert plugin.sweep_timeout_factor == 3.0

    def test_multisegment_estimated_duration_uses_plugin_rate_time_scale(self, qapp):
        plugin = _TrackingRampSweep()
        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(2.0, 1.0, True)],
            state_sweep=plugin,
        )
        assert gen.estimated_duration() == 180.1

    def test_multisegment_estimated_duration_defaults_to_rate_per_second_without_plugin(self, qapp):
        gen = MultiSegmentRampSweepGenerator(
            start=0.0,
            segments=[(2.0, 1.0, True)],
        )
        assert gen.estimated_duration() == 62.1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
