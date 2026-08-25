"""Contract tests for the generic network-analyser hierarchy."""

from __future__ import annotations

import inspect

import pytest

from stoner_measurement.instruments import (
    AgilentE5062A,
    AgilentN5222A,
    InstrumentDriverManager,
    NetworkAnalyser,
    SweepConfiguration,
    SweepType,
)
from stoner_measurement.instruments.transport import NullTransport


def test_network_analyser_is_abstract_and_concrete_drivers_conform():
    assert inspect.isabstract(NetworkAnalyser)
    assert issubclass(AgilentE5062A, NetworkAnalyser)
    assert issubclass(AgilentN5222A, NetworkAnalyser)
    assert not inspect.isabstract(AgilentE5062A)
    assert not inspect.isabstract(AgilentN5222A)


def test_common_validation_rejects_invalid_indices_and_sweep():
    driver = AgilentE5062A(NullTransport(), auto_check_errors=False)

    with pytest.raises(ValueError, match="channel"):
        driver.get_sweep_configuration(0)
    with pytest.raises(ValueError, match="trace"):
        driver.read_complex(trace=0)
    with pytest.raises(ValueError, match="stop"):
        driver.set_sweep_configuration(
            SweepConfiguration(
                sweep_type=SweepType.LINEAR,
                start_hz=2.0,
                stop_hz=1.0,
                points=11,
            )
        )


def test_driver_manager_discovers_both_network_analysers():
    manager = InstrumentDriverManager()

    manager.discover()

    drivers = manager.drivers_by_type(NetworkAnalyser)
    assert drivers["AgilentE5062A"] is AgilentE5062A
    assert drivers["AgilentN5222A"] is AgilentN5222A


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
