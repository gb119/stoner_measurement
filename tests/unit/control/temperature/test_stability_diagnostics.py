"""Focused tests for temperature stability diagnostics and active-loop display."""

from datetime import UTC, datetime, timedelta

import pytest

from stoner_measurement.instruments.temperature_controller import ControlMode, SensorStatus
from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
from stoner_measurement.temperature_control.types import (
    StabilityConfig,
    TemperatureChannelReading,
    TemperatureEngineState,
)


def test_engine_reports_current_and_window_stability_values(qapp):
    engine = TemperatureControllerEngine()
    engine.set_stability_config(StabilityConfig(tolerance_k=0.1, window_s=60, min_rate=0.01))
    t0 = datetime.now(tz=UTC)

    for seconds, value, rate in ((0, 300.02, 0.004), (10, 299.97, -0.006)):
        reading = TemperatureChannelReading(
            channel="A",
            value=value,
            timestamp=t0 + timedelta(seconds=seconds),
            status=SensorStatus.OK,
            rate_of_change=rate,
        )
        engine._evaluate_stability(  # noqa: SLF001
            {"A": reading}, {1: 300.0}, (1,), t0 + timedelta(seconds=seconds)
        )

    values = engine._stability_diagnostics[1]  # noqa: SLF001
    assert values.current_difference_k == pytest.approx(-0.03)
    assert values.min_difference_k == pytest.approx(-0.03)
    assert values.max_difference_k == pytest.approx(0.02)
    assert values.current_rate_k_per_min == pytest.approx(-0.006)
    assert values.min_rate_k_per_min == pytest.approx(-0.006)
    assert values.max_rate_k_per_min == pytest.approx(0.004)
    engine.shutdown()


def test_panel_overall_stability_ignores_off_loops(qapp, managed_qt_widget):
    from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

    panel = managed_qt_widget(TemperatureControlPanel())
    state = TemperatureEngineState(
        loop_modes={1: ControlMode.CLOSED_LOOP, 2: ControlMode.OFF},
        at_setpoint={1: True, 2: False},
        stable={1: True, 2: False},
    )

    panel._on_state_updated(state)  # noqa: SLF001

    assert "At setpoint: yes" in panel._at_setpoint_label.text()  # noqa: SLF001
    assert "Stable: yes" in panel._stable_label.text()  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
