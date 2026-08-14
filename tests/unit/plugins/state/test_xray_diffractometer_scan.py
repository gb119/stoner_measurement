"""Tests for the X-ray diffractometer state-scan plugin."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from qtpy.QtWidgets import QComboBox

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.state_scan import XrayDiffractometerScanPlugin
from stoner_measurement.scan import SteppedScanGenerator
from stoner_measurement.ui.widgets import SISpinBox
from stoner_measurement.xray_control import XrayMotionMode


class _FakeXrayEngine:
    def __init__(self) -> None:
        self.connected_driver = None
        self.connect_calls = 0
        self.move_calls: list[tuple[float, XrayMotionMode]] = []
        self.read_calls = 0
        self.count_duration_s = 2.0
        self.count_calls: list[float] = []
        self.events: list[tuple[str, object]] = []
        self.mechanics = SimpleNamespace(
            theta=SimpleNamespace(minimum_deg=-90.0, maximum_deg=90.0),
            two_theta=SimpleNamespace(minimum_deg=-30.0, maximum_deg=90.0),
        )
        self.state = SimpleNamespace(
            snapshot=SimpleNamespace(theta_deg=3.0, two_theta_deg=7.0, counts=123),
            two_theta_offset_deg=1.0,
            at_target=True,
            moving=False,
        )

    def connect_preferred_driver(self) -> None:
        self.connect_calls += 1
        self.connected_driver = object()

    def get_engine_state(self):
        return self.state

    def read_controller_state(self):
        self.read_calls += 1
        return self.state

    def move_to(self, value: float, mode: XrayMotionMode):
        self.events.append(("move", value))
        self.move_calls.append((value, mode))
        if mode is XrayMotionMode.TWO_THETA:
            self.state.snapshot.two_theta_deg = value
        else:
            self.state.snapshot.theta_deg = value
            if mode is XrayMotionMode.COUPLED:
                self.state.snapshot.two_theta_deg = 2.0 * value + 1.0
        return self.state

    def set_count_duration(self, duration_s: float) -> None:
        self.count_duration_s = float(duration_s)
        self.events.append(("duration", self.count_duration_s))

    def count(self):
        self.count_calls.append(self.count_duration_s)
        self.events.append(("count", self.count_duration_s))
        self.state.snapshot.counts += 1
        return self.state


@pytest.fixture
def fake_engine(monkeypatch):
    engine = _FakeXrayEngine()
    singleton = type("_XrayEngineSingleton", (), {"instance": staticmethod(lambda: engine)})
    monkeypatch.setattr(
        "stoner_measurement.plugins.state._xray_diffractometer_plugin.XrayControllerEngine",
        singleton,
    )
    return engine


def test_scan_reconnects_and_maps_all_three_axis_choices(fake_engine, qapp):
    plugin = XrayDiffractometerScanPlugin()

    assert plugin.controller_features == frozenset({"xray"})
    plugin.connect()
    for mode in XrayMotionMode:
        plugin.axes = mode
        plugin.set_state(5.0)

    assert fake_engine.connect_calls == 1
    assert fake_engine.move_calls == [
        (5.0, XrayMotionMode.THETA),
        (5.0, XrayMotionMode.COUPLED),
        (5.0, XrayMotionMode.TWO_THETA),
    ]


def test_scan_uses_selected_coordinate_limits_and_readback(fake_engine, qapp):
    plugin = XrayDiffractometerScanPlugin()
    fake_engine.connected_driver = object()

    plugin.axes = XrayMotionMode.COUPLED
    assert plugin.limits == pytest.approx((-15.5, 44.5))
    assert plugin.get_state() == pytest.approx(3.0)
    plugin.axes = XrayMotionMode.TWO_THETA
    assert plugin.limits == pytest.approx((-30.0, 90.0))
    assert plugin.get_state() == pytest.approx(7.0)
    assert plugin.is_at_target() is True
    assert fake_engine.read_calls == 1


def test_scan_axis_setting_widget_and_json_round_trip(fake_engine, qapp):
    plugin = XrayDiffractometerScanPlugin()
    plugin.axes = XrayMotionMode.TWO_THETA
    plugin.count_time = "0.25 + abs(xray_scan.value) / 20"

    widget = plugin._plugin_config_tabs()  # noqa: SLF001
    combo = widget.findChild(QComboBox, "xray_motion_axes")
    count_time = widget.findChild(SISpinBox, "xray_count_time")
    restored = BasePlugin.from_json(plugin.to_json())

    assert [combo.itemText(index) for index in range(combo.count())] == [
        "Theta/omega scan",
        "Theta-2theta",
        "Detector/2theta scan",
    ]
    assert combo.currentData() is XrayMotionMode.TWO_THETA
    assert count_time.value() == "0.25 + abs(xray_scan.value) / 20"
    assert isinstance(restored, XrayDiffractometerScanPlugin)
    assert restored.axes is XrayMotionMode.TWO_THETA
    assert restored.count_time == "0.25 + abs(xray_scan.value) / 20"


def test_scan_defaults_to_multi_stage_stepped_generator(fake_engine, qapp):
    plugin = XrayDiffractometerScanPlugin()

    assert isinstance(plugin.scan_generator, SteppedScanGenerator)


def test_scan_moves_then_evaluates_and_counts_measurement_points(fake_engine, qapp, engine):
    fake_engine.connected_driver = object()
    plugin = XrayDiffractometerScanPlugin()
    plugin.instance_name = "xray_scan"
    plugin.count_time = "0.5 + abs(xray_scan.value) / 10"
    plugin.value = 5.0
    plugin.meas_flag = True
    engine.add_plugin("xray_scan", plugin)

    plugin.configure()
    plugin.ramp_to(5.0, poll_interval=0.0)
    plugin.disconnect()

    assert fake_engine.count_calls == pytest.approx([1.0])
    assert fake_engine.events.index(("move", 5.0)) < fake_engine.events.index(("count", 1.0))
    assert fake_engine.count_duration_s == pytest.approx(2.0)
    assert fake_engine.events[-1] == ("duration", 2.0)


def test_scan_does_not_count_positioning_only_points(fake_engine, qapp, engine):
    fake_engine.connected_driver = object()
    plugin = XrayDiffractometerScanPlugin()
    plugin.count_time = "undefined_count_time"
    plugin.meas_flag = False
    engine.add_plugin("xray_scan", plugin)

    plugin.configure()
    plugin.ramp_to(4.0, poll_interval=0.0)
    plugin.disconnect()

    assert fake_engine.move_calls == [(4.0, XrayMotionMode.COUPLED)]
    assert fake_engine.count_calls == []
    assert fake_engine.count_duration_s == pytest.approx(2.0)


def test_scan_lifecycle_counts_only_measure_flags_and_restores_duration(fake_engine, qapp, engine):
    fake_engine.connected_driver = object()
    plugin = XrayDiffractometerScanPlugin()
    plugin.scan_generator = SteppedScanGenerator(
        start=0.0,
        stages=[(1.0, 1.0, False), (2.0, 1.0, True)],
        parent=plugin,
    )
    plugin.count_time = "0.25 + xray_scan.value / 4"
    engine.add_plugin("xray_scan", plugin)

    plugin.execute_sequence([])

    assert fake_engine.move_calls == [
        (0.0, XrayMotionMode.COUPLED),
        (1.0, XrayMotionMode.COUPLED),
        (2.0, XrayMotionMode.COUPLED),
    ]
    assert fake_engine.count_calls == pytest.approx([0.75])
    assert fake_engine.count_duration_s == pytest.approx(2.0)


def test_scan_restores_duration_when_a_nested_step_fails(fake_engine, qapp, engine):
    fake_engine.connected_driver = object()
    plugin = XrayDiffractometerScanPlugin()
    plugin.scan_generator = SteppedScanGenerator(start=1.0, parent=plugin)
    plugin.count_time = 0.5
    engine.add_plugin("xray_scan", plugin)

    def fail() -> None:
        raise RuntimeError("nested failure")

    with pytest.raises(RuntimeError, match="nested failure"):
        plugin.execute_sequence([fail])

    assert fake_engine.count_calls == pytest.approx([0.5])
    assert fake_engine.count_duration_s == pytest.approx(2.0)


def test_scan_reports_positions_and_detector_counts(fake_engine, qapp):
    plugin = XrayDiffractometerScanPlugin()
    plugin.instance_name = "xray_scan"

    assert plugin.reported_values() == {
        "xray_scan:Diffractometer Angle": "xray_scan.value",
        "xray_scan:Index": "xray_scan.index",
        "xray_scan:Theta": "xray_scan.theta",
        "xray_scan:2-Theta": "xray_scan.two_theta",
        "xray_scan:Counts": "xray_scan.counts",
    }


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
