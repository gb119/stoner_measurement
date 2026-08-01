"""Tests for concise scan and sweep generator representations."""

from __future__ import annotations

import pytest

from stoner_measurement.scan import (
    ArbitraryFunctionScanGenerator,
    FunctionScanGenerator,
    ListScanGenerator,
    RampMode,
    RampScanGenerator,
    SteppedScanGenerator,
    WaveformType,
)
from stoner_measurement.sweep import (
    MonitorAndFilterSweepGenerator,
    MultiSegmentRampSweepGenerator,
)


def test_list_scan_representation_reports_point_count(qapp):
    generator = ListScanGenerator(stages=[(1.0, True), (2.0, False)])

    assert str(generator) == "List Scan Generator (2 points)"
    assert repr(generator) == str(generator)


def test_stepped_scan_representation_reports_segment_and_point_counts(qapp):
    generator = SteppedScanGenerator(
        start=0.0,
        stages=[(1.0, 0.5, True), (2.0, 0.25, False)],
    )

    assert str(generator) == "Stepped Scan Generator (2 segments, 7 points)"


def test_ramp_scan_representation_reports_shape_range_and_point_count(qapp):
    generator = RampScanGenerator(
        start=-1.0,
        end=2.0,
        num_points=25,
        mode=RampMode.POWER,
    )

    assert str(generator) == "Ramp Scan Generator (Power, -1 to 2, 25 points)"


def test_function_scan_representation_reports_parameters(qapp):
    generator = FunctionScanGenerator(
        waveform=WaveformType.TRIANGLE,
        amplitude=2.5,
        offset=1.0,
        phase=90.0,
        periods=3.0,
        exponent=2.0,
        num_points=40,
    )

    assert str(generator) == (
        "Function Scan Generator (Triangle, amplitude=2.5, offset=1, "
        "phase=90 degrees, periods=3, exponent=2, 40 points)"
    )


def test_arbitrary_function_representation_reports_validity_and_point_count(qapp):
    generator = ArbitraryFunctionScanGenerator(
        code="def scan(ix, omega):\n    return ix * omega\n",
        num_points=12,
    )

    assert str(generator) == (
        "Arbitrary Function Scan Generator (scan(ix, omega), valid, 12 points)"
    )


def test_multisegment_sweep_representation_reports_segment_count(qapp):
    generator = MultiSegmentRampSweepGenerator(
        start=-2.0,
        segments=[(0.0, 0.5, True), (1.0, 0.25, False)],
    )

    assert str(generator) == (
        "Multi Segment Ramp Sweep Generator (start=-2, 2 segments)"
    )
    assert repr(generator) == str(generator)


def test_monitor_sweep_representation_reports_monitors_and_timeout(qapp):
    generator = MonitorAndFilterSweepGenerator(
        rows=[("temperature", False, 0.1), ("field", True, 2.0)],
        timeout=1.5,
    )

    assert str(generator) == (
        "Monitor And Filter Sweep Generator (2 monitors, timeout=1.5 seconds)"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
