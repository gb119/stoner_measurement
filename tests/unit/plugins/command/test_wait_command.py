"""Tests for WaitCommand."""

from __future__ import annotations

import time

import pytest

from stoner_measurement.plugins.command import WaitCommand


class TestWaitCommand:
    def test_name(self, qapp):
        assert WaitCommand().name == "Wait"

    def test_plugin_type(self, qapp):
        assert WaitCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert WaitCommand().has_lifecycle is False

    def test_default_delay_expr(self, qapp):
        assert WaitCommand().delay_expr == "1.0"

    def test_to_json_includes_delay_expr(self, qapp):
        command = WaitCommand()
        command.delay_expr = "0.5"
        data = command.to_json()
        assert data["delay_expr"] == "0.5"

    def test_restore_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        command = WaitCommand()
        command.delay_expr = "2.5"
        restored = BasePlugin.from_json(command.to_json())
        assert isinstance(restored, WaitCommand)
        assert restored.delay_expr == "2.5"

    def test_config_widget_returns_widget(self, qapp):
        from qtpy.QtWidgets import QWidget

        assert isinstance(WaitCommand().config_widget(), QWidget)

    def test_config_widget_has_lineedit(self, qapp):
        from stoner_measurement.ui.widgets import SISpinBox

        widget = WaitCommand().config_widget()
        assert len(widget.findChildren(SISpinBox)) == 1

    def test_config_widget_updates_delay_expr(self, qapp):
        from stoner_measurement.ui.widgets import SISpinBox

        command = WaitCommand()
        widget = command.config_widget()
        spin = widget.findChild(SISpinBox)
        spin.lineEdit().setText("settling_time * 2")
        spin.editingFinished.emit()
        assert command.delay_expr == "settling_time * 2"

    def test_execute_with_explicit_delay_sleeps(self, qapp):
        command = WaitCommand()
        started = time.monotonic()
        command.execute(delay=0.1)
        elapsed = time.monotonic() - started
        assert elapsed >= 0.08

    def test_call_with_explicit_delay_sleeps(self, qapp):
        command = WaitCommand()
        started = time.monotonic()
        command(delay=0.1)
        elapsed = time.monotonic() - started
        assert elapsed >= 0.08

    def test_execute_uses_delay_expr_when_attached(self, qapp, engine):
        command = WaitCommand()
        command.delay_expr = "settling_time * 2"
        engine.add_plugin("wait", command)
        command.engine_namespace["settling_time"] = 0.05
        started = time.monotonic()
        command.execute()
        elapsed = time.monotonic() - started
        assert elapsed >= 0.08

    def test_execute_raises_when_detached_and_no_kwarg(self, qapp):
        command = WaitCommand()
        with pytest.raises(RuntimeError):
            command.execute()

    def test_generate_action_code(self, qapp):
        command = WaitCommand()
        lines = command.generate_action_code(1, [], lambda source, indent: [])
        assert lines[0] == "    wait()"

    def test_reported_traces_empty(self, qapp):
        assert WaitCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert WaitCommand().reported_values() == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
