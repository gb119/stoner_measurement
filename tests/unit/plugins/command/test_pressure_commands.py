"""Tests for pressure-related command plugins."""

from __future__ import annotations

from qtpy.QtWidgets import QLineEdit

from stoner_measurement.plugins.command.pressure_gauge_channel import PressureGaugeChannelCommand
from stoner_measurement.plugins.command.pressure_set_flow import PressureSetFlowCommand


class _FakePressureEngine:
    def __init__(self) -> None:
        self.flow_calls: list[tuple[int, float]] = []
        self.gauge_calls: list[tuple[int, bool]] = []

    def set_flow_rate(self, channel: int, value: float) -> None:
        self.flow_calls.append((channel, value))

    def set_gauge_channel_enabled(self, channel: int, enabled: bool) -> None:
        self.gauge_calls.append((channel, enabled))


def test_pressure_set_flow_executes_runtime_expressions(monkeypatch, qapp, engine):
    fake = _FakePressureEngine()
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.pressure_set_flow.PressureControllerEngine",
        type("_FakePCE", (), {"instance": staticmethod(lambda: fake)}),
    )
    command = PressureSetFlowCommand()
    command.channel_expr = "flow_channel"
    command.flow_expr = "base_flow * 2"
    engine.add_plugin("set_flow", command)
    engine._namespace.update({"flow_channel": 2, "base_flow": 1.25})  # noqa: SLF001
    command.execute()
    assert fake.flow_calls == [(2, 2.5)]


def test_pressure_gauge_channel_executes_runtime_expressions(monkeypatch, qapp, engine):
    fake = _FakePressureEngine()
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.pressure_gauge_channel.PressureControllerEngine",
        type("_FakePCE", (), {"instance": staticmethod(lambda: fake)}),
    )
    command = PressureGaugeChannelCommand()
    command.channel_expr = "selected_channel"
    command.enabled_expr = "not should_disable"
    engine.add_plugin("set_gauge", command)
    engine._namespace.update({"selected_channel": 3, "should_disable": False})  # noqa: SLF001
    command.execute()
    assert fake.gauge_calls == [(3, True)]


def test_pressure_set_flow_config_widget_updates_expressions(qapp):
    command = PressureSetFlowCommand()
    widget = command.config_widget()
    edits = widget.findChildren(QLineEdit)
    edits[0].setText("2")
    edits[1].setText("1.5")
    edits[0].editingFinished.emit()
    edits[1].editingFinished.emit()
    assert command.channel_expr == "2"
    assert command.flow_expr == "1.5"


def test_pressure_gauge_command_has_pressure_feature(qapp):
    command = PressureGaugeChannelCommand()
    assert command.controller_features == frozenset({"pressure"})
