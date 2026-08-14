"""Tests for X-ray diffractometer command plugins."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from qtpy.QtWidgets import QComboBox

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import (
    ReadDiffractometerCommand,
    SetDiffractometerCommand,
)
from stoner_measurement.ui.widgets import SISpinBox
from stoner_measurement.xray_control import XrayMotionMode


class _FakeXrayEngine:
    def __init__(self) -> None:
        self.connected_driver = None
        self.connect_calls = 0
        self.move_calls: list[tuple[float, XrayMotionMode]] = []
        self.read_calls = 0
        self.count_calls = 0
        self.state = SimpleNamespace(
            snapshot=SimpleNamespace(theta_deg=4.0, two_theta_deg=9.0, counts=456),
            at_target=True,
            moving=False,
        )

    def connect_preferred_driver(self) -> None:
        self.connect_calls += 1
        self.connected_driver = object()

    def move_to(self, value: float, mode: XrayMotionMode):
        self.move_calls.append((value, mode))
        return self.state

    def read_controller_state(self):
        self.read_calls += 1
        return self.state

    def get_engine_state(self):
        return self.state

    def count(self):
        self.count_calls += 1
        return self.state


def _install_fake(monkeypatch, module: str, engine: _FakeXrayEngine) -> None:
    singleton = type("_XrayEngineSingleton", (), {"instance": staticmethod(lambda: engine)})
    monkeypatch.setattr(f"{module}.XrayControllerEngine", singleton)


def test_set_command_evaluates_angle_reconnects_and_uses_selected_axes(monkeypatch, qapp, engine):
    fake = _FakeXrayEngine()
    _install_fake(monkeypatch, "stoner_measurement.plugins.command.set_diffractometer", fake)
    command = SetDiffractometerCommand()
    command.axes = XrayMotionMode.TWO_THETA
    command.setpoint_expr = "centre + 2"
    engine.add_plugin("set_diffractometer", command)
    engine._namespace["centre"] = 5.0  # noqa: SLF001

    command.execute()

    assert fake.connect_calls == 1
    assert fake.move_calls == [(7.0, XrayMotionMode.TWO_THETA)]
    assert command.output_value("Theta") == pytest.approx(4.0)
    assert command.output_value("2-Theta") == pytest.approx(9.0)
    assert command.output_value("Counts") == pytest.approx(456.0)


def test_set_command_uses_expression_si_spinbox_and_persists_axes(qapp):
    command = SetDiffractometerCommand()
    command.axes = XrayMotionMode.THETA
    command.setpoint_expr = "theta_start + theta_step"

    widget = command.config_widget()
    restored = BasePlugin.from_json(command.to_json())

    assert widget.findChild(SISpinBox, "setpoint_expression") is not None
    assert widget.findChild(QComboBox, "xray_motion_axes").currentData() is XrayMotionMode.THETA
    assert isinstance(restored, SetDiffractometerCommand)
    assert restored.axes is XrayMotionMode.THETA
    assert restored.setpoint_expr == "theta_start + theta_step"


def test_commands_are_filtered_with_the_xray_feature(qapp):
    assert SetDiffractometerCommand().controller_features == frozenset({"xray"})
    assert ReadDiffractometerCommand().controller_features == frozenset({"xray"})


def test_read_command_reconnects_counts_and_exposes_instance_value(monkeypatch, qapp):
    fake = _FakeXrayEngine()
    _install_fake(monkeypatch, "stoner_measurement.plugins.command.read_diffractometer", fake)
    command = ReadDiffractometerCommand()
    command.instance_name = "read_xray"

    command.execute()

    assert fake.connect_calls == 1
    assert fake.count_calls == 1
    assert fake.read_calls == 0
    assert command.value == pytest.approx(456.0)
    assert command.reported_values() == {"read_xray:Counts": "read_xray.value"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
