"""Tests for the conditional If command."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import IfCommand
from stoner_measurement.plugins.sequence import SequencePlugin


class TestIfCommand:
    def test_plugin_type_is_command(self, qapp):
        assert IfCommand().plugin_type == "command"

    def test_is_sequence_container(self, qapp):
        assert isinstance(IfCommand(), SequencePlugin)

    def test_to_json_round_trip_restores_condition(self, qapp):
        command = IfCommand(condition="counter.meas_flag")
        command.instance_name = "measure_if"
        restored = BasePlugin.from_json(command.to_json())
        assert isinstance(restored, IfCommand)
        assert restored.instance_name == "measure_if"
        assert restored.condition == "counter.meas_flag"

    def test_generate_action_code_renders_if_block(self, qapp):
        command = IfCommand(condition="scan.meas_flag")
        lines = command.generate_action_code(1, ["child"], lambda step, indent: ["        child()"])
        assert lines[0] == "    if scan.meas_flag:"
        assert "        child()" in lines

    def test_generate_action_code_empty_body_uses_pass(self, qapp):
        command = IfCommand(condition="")
        lines = command.generate_action_code(1, [], lambda step, indent: [])
        assert lines == ["    if True:", "        pass", ""]

    def test_execute_sequence_runs_when_condition_truthy(self, qapp, engine):
        command = IfCommand(condition="flag")
        engine.add_plugin("if_command", command)
        engine._namespace["flag"] = True
        calls: list[int] = []
        command.execute_sequence([lambda: calls.append(1)])
        assert calls == [1]

    def test_execute_sequence_skips_when_condition_falsey(self, qapp, engine):
        command = IfCommand(condition="flag")
        engine.add_plugin("if_command", command)
        engine._namespace["flag"] = False
        calls: list[int] = []
        command.execute_sequence([lambda: calls.append(1)])
        assert calls == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
