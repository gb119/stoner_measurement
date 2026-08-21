"""Shared polling-rate contract tests for controller engines and panels."""

from __future__ import annotations

import time

import pytest

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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
