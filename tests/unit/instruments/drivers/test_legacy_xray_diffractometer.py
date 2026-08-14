"""Driver and simulator behaviour tests for X-ray diffractometers."""

from __future__ import annotations

from abc import ABC
from collections import Counter

import pytest

from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.transport import NullTransport
from stoner_measurement.instruments.xray import (
    DiffractometerMechanics,
    LegacyXrayDiffractometer,
    SimulatedXrayDiffractometer,
    XrayDiffractometer,
    XrayMotionDisabledError,
    XrayTravelLimitError,
)


def _bcd(value: int, width: int) -> bytes:
    result = bytearray()
    for _ in range(width):
        pair = value % 100
        result.append((pair // 10) << 4 | pair % 10)
        value //= 100
    return bytes(result)


def _frame(theta: float = 0.0, two_theta: float = 0.0, counts: int = 0) -> bytes:
    theta_raw = round(theta * 400) % 1_000_000
    two_raw = round(two_theta * 200) % 1_000_000
    return b"\x00\x04" + _bcd(counts, 4) + _bcd(two_raw, 3) + _bcd(theta_raw, 3)


def _driver(responses, *, enabled=True):
    transport = NullTransport(responses=list(responses))
    driver = LegacyXrayDiffractometer(
        transport,
        mechanics=DiffractometerMechanics.recovered_site_defaults(motion_enabled=enabled),
        pre_read_delay_s=0.0,
        sleep=lambda _seconds: None,
    )
    driver.connect()
    return driver, transport


def test_abstract_contract_separates_both_concrete_drivers():
    assert issubclass(XrayDiffractometer, ABC)
    assert issubclass(LegacyXrayDiffractometer, XrayDiffractometer)
    assert issubclass(SimulatedXrayDiffractometer, XrayDiffractometer)
    assert LegacyXrayDiffractometer not in SimulatedXrayDiffractometer.__mro__


def test_driver_manager_discovers_both_concrete_xray_drivers():
    manager = InstrumentDriverManager()
    manager.discover()

    drivers = manager.drivers_by_type(XrayDiffractometer)

    assert drivers["LegacyXrayDiffractometer"] is LegacyXrayDiffractometer
    assert drivers["SimulatedXrayDiffractometer"] is SimulatedXrayDiffractometer


def test_snapshot_writes_only_binary_f0_and_requests_fixed_frame():
    driver, transport = _driver([_frame(theta=1.0, two_theta=2.0, counts=123)])

    snapshot = driver.read_snapshot()

    assert snapshot.theta_deg == 1.0
    assert snapshot.two_theta_deg == 2.0
    assert snapshot.counts == 123
    assert transport.write_log == [b"\xF0"]


def test_increasing_reflection_step_moves_theta_and_detector_clockwise():
    driver, transport = _driver([_frame(), _frame(theta=0.0025, two_theta=0.005)])

    driver.move_coupled(0.0025, 1.0)

    assert transport.write_log == [b"\xF0", b"\x93", b"\x83", b"\xF0"]


def test_decreasing_coupled_move_takes_up_each_axis_backlash_clockwise():
    driver, transport = _driver(
        [_frame(), _frame(theta=-0.0025, two_theta=-0.005)]
    )

    driver.move_coupled(-0.0025, 1.0)

    writes = Counter(transport.write_log)
    assert writes[b"\x92"] == 101  # one theta step plus 100-step overshoot
    assert writes[b"\x82"] == 51  # one 2-theta step plus 50-step overshoot
    assert writes[b"\x93"] == 100
    assert writes[b"\x83"] == 50
    assert transport.write_log[0] == b"\xF0"
    assert transport.write_log[-1] == b"\xF0"


def test_motion_stays_disabled_until_mechanics_are_confirmed():
    driver, transport = _driver([], enabled=False)

    with pytest.raises(XrayMotionDisabledError):
        driver.move_theta(1.0, 1.0)

    assert transport.write_log == []


def test_soft_limit_rejection_performs_no_io():
    driver, transport = _driver([])

    with pytest.raises(XrayTravelLimitError):
        driver.move_two_theta(90.005, 1.0)

    assert transport.write_log == []


def test_zero_duration_count_still_guarantees_stop_then_reads():
    driver, transport = _driver([_frame(counts=42)])

    result = driver.count(0.0)

    assert result.snapshot.counts == 42
    assert transport.write_log == [b"\xD0", b"\xE0", b"\xF0"]


def test_simulator_enforces_coupling_and_generates_diffraction_peaks():
    simulator = SimulatedXrayDiffractometer()
    simulator.connect()

    snapshot = simulator.move_coupled(18.6, 1.0, two_theta_offset_deg=0.0)
    peak = simulator.count(1.0)
    simulator.move_two_theta(40.0, 1.0)
    background = simulator.count(1.0)

    assert snapshot.theta_deg == pytest.approx(18.6)
    assert snapshot.two_theta_deg == pytest.approx(37.2)
    assert peak.snapshot.counts > background.snapshot.counts * 100
    assert len(peak.snapshot.raw_frame) == 12


def test_simulator_motion_duration_tracks_speed_and_coupled_detector_rate():
    sleeps: list[float] = []
    snapshots = []
    simulator = SimulatedXrayDiffractometer(
        realtime=True,
        motion_time_scale=1.0,
        sleep=sleeps.append,
    )
    simulator.set_progress_callback(snapshots.append)

    result = simulator.move_coupled(1.0, 60.0)

    assert sum(sleeps) == pytest.approx(1.0)
    assert len(snapshots) == 20
    assert result.theta_deg == pytest.approx(1.0)
    assert result.two_theta_deg == pytest.approx(2.0)


def test_simulator_exposes_counterclockwise_backlash_excursion():
    snapshots = []
    simulator = SimulatedXrayDiffractometer(theta_deg=1.0, two_theta_deg=2.0)
    simulator.set_progress_callback(snapshots.append)

    result = simulator.move_coupled(0.0, 5.0)

    assert min(snapshot.theta_deg for snapshot in snapshots) == pytest.approx(-0.25)
    assert min(snapshot.two_theta_deg for snapshot in snapshots) == pytest.approx(-0.25)
    assert result.theta_deg == pytest.approx(0.0)
    assert result.two_theta_deg == pytest.approx(0.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
