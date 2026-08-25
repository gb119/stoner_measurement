"""Tests for the restricted network-analyser ramp generator."""

from __future__ import annotations

import numpy as np
import pytest

from stoner_measurement.scan import (
    BaseScanGenerator,
    NetworkAnalyserScanGenerator,
    RampMode,
)


def test_linear_and_exponential_grids_match_analyser_sweep_types(qapp):
    generator = NetworkAnalyserScanGenerator(
        start=1.0,
        end=1000.0,
        num_points=4,
        mode=RampMode.EXPONENTIAL,
    )

    np.testing.assert_allclose(generator.generate(), [1.0, 10.0, 100.0, 1000.0])
    generator.mode = RampMode.LINEAR
    np.testing.assert_allclose(generator.generate(), np.linspace(1.0, 1000.0, 4))


def test_power_mode_rejects_exponential_and_generator_round_trips(qapp):
    generator = NetworkAnalyserScanGenerator(mode=RampMode.EXPONENTIAL)
    generator.set_exponential_available(False)

    assert generator.mode is RampMode.LINEAR
    with pytest.raises(ValueError, match="power sweep"):
        generator.mode = RampMode.EXPONENTIAL

    restored = BaseScanGenerator.from_json(generator.to_json())
    assert isinstance(restored, NetworkAnalyserScanGenerator)
    assert restored.mode is RampMode.LINEAR


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
