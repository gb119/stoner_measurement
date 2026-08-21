"""Focused tests for StateControlPlugin data collection behavior."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.base_plugin import BasePlugin
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
        from stoner_measurement.core import TraceData

        p = _InstantState()
        assert isinstance(p.data, TraceData)
        assert p.data.df.empty

    def test_default_config_values(self, qapp):
        p = _InstantState()
        assert p.collect_data is False
        assert p.clear_on_start is True
        assert p.collect_filter == f"{p.instance_name}.meas_flag"
        assert p.clear_filter == "True"

    def test_clear_data_resets_dataframe(self, qapp):
        import pandas as pd

        from stoner_measurement.core import TraceData

        p = _InstantState()
        p._data = TraceData(pd.DataFrame({"x": [0.0], "value": [1.0]}))
        p.clear_data()
        assert p.data.df.empty

    def test_clear_data_obeys_clear_filter_false(self, qapp):
        import pandas as pd

        from stoner_measurement.core import TraceData

        p = _InstantState()
        p._data = TraceData(pd.DataFrame({"x": [0.0], "value": [1.0]}))
        p.clear_filter = "False"
        p.clear_data()
        assert p.data.df.empty

    def test_collect_noop_when_detached(self, qapp):
        p = _InstantState()
        p.collect_filter = "True"
        p.collect()
        assert p.data.df.empty

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
        assert not p.data.df.empty
        assert p.data.x.tolist() == [3.5]
        assert p.data.df["iteration"].iloc[0] == 0
        assert p.data.df["stage"].iloc[0] == 2
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
        assert p.data.df.empty
        engine.shutdown()

    def test_collect_multiple_rows(self, qapp):
        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        p = _InstantState()
        engine.add_plugin("instantstate", p)
        p.collect_filter = "True"
        p.meas_flag = True
        trace_ids: list[int] = []
        for i in range(3):
            p.ix = i
            p.value = float(i)
            p.stage = i
            p.collect()
            trace_ids.append(id(p.data))
        assert len(p.data.df) == 3
        assert p.data.x.tolist() == [0.0, 1.0, 2.0]
        assert p.data.df["iteration"].tolist() == [0, 1, 2]
        assert p.data.df["stage"].tolist() == [0, 1, 2]
        assert len(set(trace_ids)) == 1
        assert len(p.data._df) == 256
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
        assert not p.data.df.empty
        assert "counter:Value" in p.data.columns
        assert "iteration" in p.data.columns
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

    def test_collect_can_use_readback_output_as_x_axis(self, qapp):
        from stoner_measurement.core import COLUMN_ROLE_E, COLUMN_ROLE_Z
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
        p.value = 2.0
        p.collect_outputs = ["counter:Value", "instantstate:Voltage"]
        p.collect_output_roles = {"counter:Value": "x", "instantstate:Voltage": "e"}

        p.collect()

        assert p.data.x.tolist() == [11.0]
        assert p.data.names["x"] == "counter:Value"
        assert p.data.df["state"].tolist() == [2.0]
        assert p.data.names["state"] == "Voltage"
        assert p.data.column_roles["state"] == COLUMN_ROLE_Z
        assert p.data.column_roles["instantstate:Voltage"] == COLUMN_ROLE_E
        engine.shutdown()

    def test_collect_dash_role_leaves_output_auxiliary(self, qapp):
        from stoner_measurement.core import COLUMN_ROLE_Z
        from stoner_measurement.core.sequence_engine import SequenceEngine
        from stoner_measurement.plugins.state_control import CounterPlugin

        engine = SequenceEngine()
        p = _InstantState()
        counter = CounterPlugin()
        engine.add_plugin("instantstate", p)
        engine.add_plugin("counter", counter)
        engine.update_step_plugin_catalog([p, counter])
        p.collect_filter = "True"
        p.meas_flag = True
        p.collect_outputs = ["counter:Value"]
        p.collect_output_roles = {"counter:Value": "-"}

        p.collect()

        assert p.data.column_roles["counter:Value"] == COLUMN_ROLE_Z
        engine.shutdown()

    def test_to_json_includes_data_collection_settings(self, qapp):
        p = _InstantState()
        p.collect_data = True
        p.clear_on_start = False
        p.collect_filter = "custom_expr"
        p.clear_filter = "another_expr"
        p.collect_outputs = ["a:value", "b:value"]
        p.collect_output_roles = {"a:value": "x", "b:value": "-"}
        d = p.to_json()
        assert d["collect_data"] is True
        assert d["clear_on_start"] is False
        assert d["collect_filter"] == "custom_expr"
        assert d["clear_filter"] == "another_expr"
        assert d["collect_outputs"] == ["a:value", "b:value"]
        assert d["collect_output_roles"] == {"a:value": "x", "b:value": "-"}

    def test_from_json_restores_data_collection_settings(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        p = _InstantState()
        p.collect_data = True
        p.clear_on_start = False
        p.collect_filter = "my_filter"
        p.clear_filter = "other"
        p.collect_outputs = ["counter:Value"]
        p.collect_output_roles = {"counter:Value": "x"}
        restored = BasePlugin.from_json(p.to_json())
        assert restored.collect_data is True
        assert restored.clear_on_start is False
        assert restored.collect_filter == "my_filter"
        assert restored.clear_filter == "other"
        assert restored.collect_outputs == ["counter:Value"]
        assert restored.collect_output_roles == {"counter:Value": "x"}

    def test_start_from_current_value_round_trips(self, qapp):
        p = _InstantState()
        p.start_from_current_value = True

        restored = BasePlugin.from_json(p.to_json())

        assert restored.start_from_current_value is True

    def test_scan_config_has_output_catalogue_table(self, qapp):
        from qtpy.QtWidgets import QCheckBox, QComboBox, QPushButton, QTableWidget

        from stoner_measurement.core.sequence_engine import SequenceEngine
        from stoner_measurement.plugins.state_control import CounterPlugin

        engine = SequenceEngine()
        p = _InstantState()
        counter = CounterPlugin()
        engine.add_plugin("instantstate", p)
        engine.add_plugin("counter", counter)
        engine.update_step_plugin_catalog([p, counter])
        tabs = p.config_tabs()
        data_page = tabs[1][1]
        table = data_page.findChild(QTableWidget, "stateOutputSelectionTable")
        assert table is not None
        value_row = next(row for row in range(table.rowCount()) if table.item(row, 1).text() == "counter:Value")
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
        assert p.collect_outputs is not None
        assert "counter:Value" not in p.collect_outputs
        select_all_checkbox.setChecked(True)
        assert value_checkbox.isChecked()
        assert role_combo.currentText() == "y"
        assert p.collect_outputs is None
        role_combo.setCurrentText("x")
        assert p.collect_output_roles["counter:Value"] == "x"
        other_role_combo = next(
            table.cellWidget(row, 2)
            for row in range(table.rowCount())
            if table.item(row, 1).text() == "instantstate:Voltage"
        )
        other_role_combo.setCurrentText("x")
        assert role_combo.currentText() == "-"
        assert p.collect_output_roles["instantstate:Voltage"] == "x"
        role_combo.setCurrentText("-")
        assert p.collect_output_roles["counter:Value"] == "-"
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
