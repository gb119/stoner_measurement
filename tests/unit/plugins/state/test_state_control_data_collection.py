"""Focused tests for StateControlPlugin data collection behavior."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.state_control import StateControlPlugin


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


class TestStateControlDataCollection:
    """Tests for the data-collection capabilities of StateControlPlugin."""

    def test_data_initially_empty(self, qapp):
        import pandas as pd

        p = _InstantState()
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
        assert p.data.empty

    def test_collect_noop_when_detached(self, qapp):
        p = _InstantState()
        p.collect_filter = "True"
        p.collect()
        assert p.data.empty

    def test_collect_appends_row(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        p = _InstantState()
        engine.add_plugin("instantstate", p)
        p.collect_filter = "True"
        p.meas_flag = True
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
        p.meas_flag = True
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
        engine.update_step_plugin_catalog([p, counter])
        counter.value = 7.0
        p.collect_filter = "True"
        p.meas_flag = True
        p.ix = 0
        p.value = 2.0
        p.collect(outputs=["counter:Value"])
        assert not p.data.empty
        assert "counter:Value" in p.data.columns
        assert "value" in p.data.columns
        engine.shutdown()

    def test_collect_uses_selected_collect_outputs(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine
        from stoner_measurement.plugins.state_control import CounterPlugin

        engine = SequenceEngine()
        p = _InstantState()
        counter = CounterPlugin()
        engine.add_plugin("instantstate", p)
        engine.add_plugin("counter", counter)
        engine.update_step_plugin_catalog([p, counter])
        counter.value = 11.0
        p.collect_filter = "True"
        p.meas_flag = True
        p.ix = 0
        p.value = 2.0
        p.collect_outputs = ["counter:Value"]
        p.collect()
        assert "counter:Value" in p.data.columns
        assert "instantstate:Voltage" not in p.data.columns
        engine.shutdown()

    def test_to_json_includes_data_collection_settings(self, qapp):
        p = _InstantState()
        p.collect_data = True
        p.clear_on_start = False
        p.collect_filter = "custom_expr"
        p.clear_filter = "another_expr"
        p.collect_outputs = ["a:value", "b:value"]
        d = p.to_json()
        assert d["collect_data"] is True
        assert d["clear_on_start"] is False
        assert d["collect_filter"] == "custom_expr"
        assert d["clear_filter"] == "another_expr"
        assert d["collect_outputs"] == ["a:value", "b:value"]

    def test_from_json_restores_data_collection_settings(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        p = _InstantState()
        p.collect_data = True
        p.clear_on_start = False
        p.collect_filter = "my_filter"
        p.clear_filter = "other"
        p.collect_outputs = ["counter:Value"]
        restored = BasePlugin.from_json(p.to_json())
        assert restored.collect_data is True
        assert restored.clear_on_start is False
        assert restored.collect_filter == "my_filter"
        assert restored.clear_filter == "other"
        assert restored.collect_outputs == ["counter:Value"]

    def test_scan_config_has_output_catalogue_checkboxes(self, qapp):
        from qtpy.QtWidgets import QCheckBox, QScrollArea

        from stoner_measurement.core.sequence_engine import SequenceEngine
        from stoner_measurement.plugins.state_control import CounterPlugin

        engine = SequenceEngine()
        p = _InstantState()
        counter = CounterPlugin()
        engine.add_plugin("instantstate", p)
        engine.add_plugin("counter", counter)
        engine.update_step_plugin_catalog([p, counter])
        tabs = p.config_tabs()
        scan_page = tabs[0][1]
        value_checkbox = next(
            (
                check
                for check in scan_page.findChildren(QCheckBox)
                if check.text() == "counter:Value"
            ),
            None,
        )
        select_all_checkbox = next(
            (
                check
                for check in scan_page.findChildren(QCheckBox)
                if check.text() == "Use all catalogue outputs"
            ),
            None,
        )
        scroll_area = next(iter(scan_page.findChildren(QScrollArea)), None)
        assert value_checkbox is not None
        assert value_checkbox.isChecked()
        assert select_all_checkbox is not None
        assert select_all_checkbox.isChecked()
        assert scroll_area is not None
        value_checkbox.setChecked(False)
        assert not select_all_checkbox.isChecked()
        assert p.collect_outputs is not None
        assert "counter:Value" not in p.collect_outputs
        select_all_checkbox.setChecked(True)
        assert value_checkbox.isChecked()
        assert p.collect_outputs is None
        engine.shutdown()

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
        p = _InstantState()
        p.clear_on_start = False
        p.collect_data = True
        rendered_sub = ["        sub_step_line()"]
        lines = p.generate_action_code(1, ["dummy_step"], lambda s, i: rendered_sub)
        collect_idx = next(i for i, line in enumerate(lines) if "collect()" in line)
        sub_idx = next(i for i, line in enumerate(lines) if "sub_step_line()" in line)
        assert collect_idx > sub_idx

    def test_generate_action_code_does_not_wrap_substeps_in_measure_flag_if(self, qapp):
        p = _InstantState()
        lines = p.generate_action_code(
            1,
            ["dummy_step"],
            lambda s, i: ["        sub_step_line()"],
        )
        assert not any("if instantstate.meas_flag:" in line for line in lines)
        assert "        sub_step_line()" in lines

    def test_generate_action_code_waits_for_plot_ready_before_ramp(self, qapp):
        p = _InstantState()
        lines = p.generate_action_code(1, [], lambda s, i: [])
        wait_idx = next(i for i, line in enumerate(lines) if "wait_for_plot_ready()" in line)
        ramp_idx = next(i for i, line in enumerate(lines) if ".ramp_to(float(" in line)
        assert wait_idx < ramp_idx


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
