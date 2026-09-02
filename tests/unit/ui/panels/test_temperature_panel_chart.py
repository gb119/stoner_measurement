"""Focused tests for temperature-panel chart chronology."""

from datetime import UTC, datetime, timedelta

import pytest

from stoner_measurement.temperature_control.types import (
    TemperatureChannelReading,
    TemperatureEngineState,
)
from stoner_measurement.ui.temperature_panel import TemperatureControlPanel


def test_heater_samples_scroll_with_temperature_and_setpoint(managed_qt_widget):
    """Heater values stay paired with their poll times as old samples expire."""
    panel = managed_qt_widget(TemperatureControlPanel())
    panel._chart_duration_min = 1  # noqa: SLF001
    start = datetime(2026, 1, 1, tzinfo=UTC)

    for offset, temperature, setpoint, heater in (
        (0, 100.0, 101.0, 10.0),
        (30, 101.0, 102.0, 20.0),
        (60, 102.0, 103.0, 30.0),
        (90, 103.0, 104.0, 40.0),
    ):
        timestamp = start + timedelta(seconds=offset)
        state = TemperatureEngineState(
            readings={
                "A": TemperatureChannelReading(
                    "A", temperature, timestamp, status=None
                )
            },
            setpoints={1: setpoint},
            heater_outputs={1: heater},
        )
        panel._update_chart(state, timestamp.timestamp())  # noqa: SLF001

    expected_xs = [-60.0, -30.0, 0.0]
    assert panel._chart_widget.x_data("T_A") == pytest.approx(expected_xs)  # noqa: SLF001
    assert panel._chart_widget.x_data("SP_1") == pytest.approx(expected_xs)  # noqa: SLF001
    assert panel._chart_widget.x_data("H_1") == pytest.approx(expected_xs)  # noqa: SLF001
    assert panel._chart_widget.y_data("SP_1") == pytest.approx([102.0, 103.0, 104.0])  # noqa: SLF001
    assert panel._chart_widget.y_data("H_1") == pytest.approx([20.0, 30.0, 40.0])  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
