"""X-ray engine tests using the concrete simulated instrument."""

from __future__ import annotations

import pytest

from stoner_measurement.instruments.xray import SimulatedXrayDiffractometer
from stoner_measurement.xray_control import (
    XrayControllerEngine,
    XrayEngineStatus,
    XrayMotionMode,
)


def test_engine_moves_all_three_motion_sets_and_reads_detector(qapp):
    engine = XrayControllerEngine()
    simulator = SimulatedXrayDiffractometer()
    engine.connect_instrument(simulator)
    engine._timer.stop()  # noqa: SLF001 - keep this synchronous test deterministic

    theta_state = engine.move_to(10.0, XrayMotionMode.THETA)
    two_theta_state = engine.move_to(25.0, XrayMotionMode.TWO_THETA)
    engine.configure_motion(
        enabled=True,
        mode=XrayMotionMode.COUPLED,
        speed_deg_per_min=1.0,
        two_theta_offset_deg=1.0,
    )
    coupled_state = engine.move_to(20.0)
    counted_state = engine.count(1.0)

    assert theta_state.snapshot.theta_deg == pytest.approx(10.0)
    assert two_theta_state.snapshot.two_theta_deg == pytest.approx(25.0)
    assert coupled_state.snapshot.theta_deg == pytest.approx(20.0)
    assert coupled_state.snapshot.two_theta_deg == pytest.approx(41.0)
    assert counted_state.snapshot.counts >= 0
    assert counted_state.count_rate_hz is not None
    assert engine.status is XrayEngineStatus.POLLING
    engine.shutdown()


def test_engine_can_construct_simulator_from_panel_connection_choice(qapp):
    engine = XrayControllerEngine()

    engine.connect_driver("Simulated", "")

    assert isinstance(engine.connected_driver, SimulatedXrayDiffractometer)
    assert engine.connected_driver.realtime is True
    assert engine.connected_driver.motion_time_scale == pytest.approx(1.0)
    assert engine.connection_info.transport_name == "Simulated"
    engine.shutdown()


def test_polling_rate_can_be_changed_and_disabled(qapp):
    engine = XrayControllerEngine()
    engine.connect_instrument(SimulatedXrayDiffractometer())

    engine.set_polling_rate(4.0)
    assert engine.polling_rate_hz == pytest.approx(4.0)
    assert engine._timer.interval() == 250  # noqa: SLF001
    assert engine._timer.isActive()  # noqa: SLF001

    engine.set_polling_rate(0.0)
    assert engine.polling_rate_hz == pytest.approx(0.0)
    assert not engine._timer.isActive()  # noqa: SLF001
    assert engine.status is XrayEngineStatus.CONNECTED
    engine.shutdown()


def test_count_duration_is_shared_and_published(qapp):
    engine = XrayControllerEngine()
    changes: list[float] = []
    engine.publisher.count_duration_changed.connect(changes.append)

    engine.set_count_duration(2.5)

    assert engine.count_duration_s == pytest.approx(2.5)
    assert changes == pytest.approx([2.5])
    with pytest.raises(ValueError, match="positive finite"):
        engine.set_count_duration(0.0)
    engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
