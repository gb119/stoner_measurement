"""Shared polling-rate contract tests for controller engines and panels."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from stoner_measurement.core.controller_polling import ControllerTimer
from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.motor_control.engine import MotorControllerEngine
from stoner_measurement.pressure_control.engine import PressureControllerEngine
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.ui.magnet_panel import MagnetControlPanel
from stoner_measurement.ui.motor_panel import MotorControlPanel
from stoner_measurement.ui.pressure_panel import PressureControlPanel
from stoner_measurement.ui.temperature_panel import TemperatureControlPanel


@pytest.mark.parametrize(
    "engine_type",
    [
        MagnetControllerEngine,
        MotorControllerEngine,
        PressureControllerEngine,
        TemperatureControllerEngine,
    ],
)
def test_engine_polling_rate_api_clamps_converts_and_disables(engine_type, qapp):
    engine = engine_type()

    engine.set_polling_rate(2.5)
    assert engine.polling_rate_hz == pytest.approx(2.5)
    assert engine._timer.interval() == 400  # noqa: SLF001
    assert engine.configuration_dict()["polling_rate_hz"] == pytest.approx(2.5)

    engine.set_polling_rate(0.0)
    assert engine.polling_rate_hz == pytest.approx(0.0)
    assert not engine._timer.isActive()  # noqa: SLF001

    engine.set_polling_rate(20.0)
    assert engine.polling_rate_hz == pytest.approx(10.0)
    assert engine._timer.interval() == 100  # noqa: SLF001
    engine.shutdown()


@pytest.mark.parametrize(
    "engine_type",
    [MagnetControllerEngine, MotorControllerEngine, TemperatureControllerEngine],
)
def test_engine_state_cache_records_monotonic_age(engine_type, qapp):
    engine = engine_type()

    assert engine.state_cache_age_seconds == float("inf")
    engine._latest_state_time = time.monotonic() - 2.0  # noqa: SLF001

    assert engine.state_cache_age_seconds == pytest.approx(2.0, abs=0.1)
    engine.shutdown()


@pytest.mark.parametrize(
    "panel_type",
    [
        MagnetControlPanel,
        MotorControlPanel,
        PressureControlPanel,
        TemperatureControlPanel,
    ],
)
def test_panel_polling_control_uses_engine_api(panel_type, qapp):
    panel = panel_type()

    assert panel._polling_rate_spin.minimum() == pytest.approx(0.0)  # noqa: SLF001
    assert panel._polling_rate_spin.maximum() == pytest.approx(10.0)  # noqa: SLF001
    panel._polling_rate_spin.setValue(3.0)  # noqa: SLF001

    assert panel._engine.polling_rate_hz == pytest.approx(3.0)  # noqa: SLF001
    panel._engine.shutdown()  # noqa: SLF001


def test_worker_timer_requests_run_and_latest_stop_wins(qapp, qtbot):
    timer = ControllerTimer()
    ticks = []
    timer.timeout.connect(lambda: ticks.append(True))
    worker = threading.Thread(target=lambda: timer.start(10))
    worker.start()
    worker.join()
    qtbot.waitUntil(lambda: bool(ticks), timeout=1000)
    worker = threading.Thread(target=lambda: (timer.stop(), timer.start(), timer.stop()))
    worker.start()
    worker.join()
    qapp.processEvents()
    assert not timer.isActive()
    timer.stop()


def test_slow_controller_poll_does_not_block_gui_or_queue_reads(qapp, qtbot, monkeypatch):
    engine = MotorControllerEngine()
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls = []

    def read():
        calls.append(True)
        entered.set()
        release.wait(2)
        finished.set()

    monkeypatch.setattr(engine, "read_controller_state", read)
    try:
        engine._poll()  # noqa: SLF001
        assert entered.wait(1)
        heartbeat = []
        timer = ControllerTimer()
        timer.timeout.connect(lambda: heartbeat.append(True))
        timer.start(10)
        for _ in range(20):
            engine._poll()  # noqa: SLF001
        qtbot.waitUntil(lambda: bool(heartbeat), timeout=500)
        assert len(calls) == 1
        timer.stop()
    finally:
        release.set()
        assert finished.wait(1)
        engine.shutdown()


def test_flow_snapshot_does_not_poll_or_publish_gauge_data(qapp, monkeypatch):
    engine = PressureControllerEngine()
    snapshots = []
    engine.publisher.state_updated.connect(snapshots.append)
    monkeypatch.setattr(engine, "_mfc_driver", SimpleNamespace(
        get_capabilities=lambda: SimpleNamespace(channel_count=1),
        read_actual_value=lambda **kwargs: 2.5,
        read_setpoint=lambda **kwargs: 2.5,
        read_unit=lambda **kwargs: "sccm",
    ))
    monkeypatch.setattr(engine, "_read_pressure_values", lambda *_: pytest.fail("Gauge polled"))
    try:
        state = engine.read_flow_state()
        assert state.flow_actual == {1: 2.5}
        assert state.flow_setpoints == {1: 2.5}
        assert not state.readings and not state.interlocks
        assert not snapshots
    finally:
        engine._mfc_driver = None  # noqa: SLF001
        engine.shutdown()


@pytest.mark.parametrize("engine_type", [MotorControllerEngine, MagnetControllerEngine])
def test_failed_poll_invalidates_previous_completion(engine_type, qapp, monkeypatch):
    engine = engine_type()
    engine._latest_state = replace(  # noqa: SLF001
        engine._latest_state, at_target=True, stable=True)  # noqa: SLF001
    engine._is_at_target = engine._stable = True  # noqa: SLF001
    engine._latest_state_time = time.monotonic()  # noqa: SLF001
    engine._driver = object()  # noqa: SLF001

    def fail():
        raise ConnectionError("unplugged")

    monkeypatch.setattr(engine, "_build_state", fail)
    try:
        assert engine.read_controller_state() is None
        assert not engine.get_engine_state().at_target
        assert not engine.get_engine_state().stable
        assert engine.state_cache_age_seconds == float("inf")
    finally:
        engine._driver = None  # noqa: SLF001
        engine.shutdown()


def test_first_singleton_created_by_worker_moves_to_gui_owner(qapp, monkeypatch):
    monkeypatch.setattr(MotorControllerEngine, "_singleton", None)
    engines = []
    worker = threading.Thread(target=lambda: engines.append(MotorControllerEngine.instance()))
    worker.start()
    worker.join(2)
    assert not worker.is_alive()
    engine = engines[0]
    try:
        assert engine.thread() == qapp.thread()
        assert engine._timer.thread() == qapp.thread()  # noqa: SLF001
    finally:
        engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
