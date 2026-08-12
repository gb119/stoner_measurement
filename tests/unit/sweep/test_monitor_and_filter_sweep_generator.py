"""Runtime feedback tests for the monitor-and-filter sweep generator."""

from __future__ import annotations

import pytest

from stoner_measurement.sweep import monitor_and_filter_generator as generator_module
from stoner_measurement.sweep.monitor_and_filter_generator import (
    MonitorAndFilterSweepGenerator,
)


class _FakeStateSweep:
    """Minimal state-sweep owner with deterministic monitored values."""

    def __init__(self, values: list[float]) -> None:
        self._values = iter(values)
        self.engine_namespace = {"_values": {}}

    def get_state(self) -> float:
        return 0.0

    def eval(self, expression: str):
        if expression == "signal":
            return next(self._values)
        return False

    def eval_float(self, expression: str) -> float:
        return float(expression)


def test_progress_resets_and_reports_filter_trigger(qapp, monkeypatch):
    plugin = _FakeStateSweep([0.0, 2.0])
    generator = MonitorAndFilterSweepGenerator(
        rows=[("signal", False, 1.0)],
        timeout=10.0,
        poll_seconds=0.0,
        state_sweep=plugin,
    )
    clock = iter([0.0, 0.5, 1.0, 1.0])
    monkeypatch.setattr(generator_module.time, "monotonic", lambda: next(clock))
    progress: list[tuple[float, float]] = []
    triggers: list[int] = []
    generator.progress_updated.connect(lambda elapsed, timeout: progress.append((elapsed, timeout)))
    generator.measurement_triggered.connect(triggers.append)

    first = next(generator)
    second = next(generator)

    assert first[3] is False
    assert second == (0, 0.0, 0, True)
    assert progress == [(0.5, 10.0), (0.0, 10.0)]
    assert triggers == [0]


def test_timeout_trigger_reports_timeout_source(qapp, monkeypatch):
    plugin = _FakeStateSweep([0.0])
    generator = MonitorAndFilterSweepGenerator(
        rows=[("signal", False, 1.0)],
        timeout=2.0,
        poll_seconds=0.0,
        state_sweep=plugin,
    )
    clock = iter([0.0, 2.5, 2.5])
    monkeypatch.setattr(generator_module.time, "monotonic", lambda: next(clock))
    triggers: list[int] = []
    generator.measurement_triggered.connect(triggers.append)

    assert next(generator)[3] is True
    assert triggers == [-1]


def test_widget_shows_progress_and_trigger_source(qapp, managed_qt_widget):
    generator = MonitorAndFilterSweepGenerator(
        rows=[("first", False, 1.0), ("second", False, 1.0)]
    )
    widget = managed_qt_widget(generator.config_widget())

    generator.progress_updated.emit(2.5, 10.0)
    assert widget._progress.value() == 250  # noqa: SLF001
    assert widget._progress.format() == "2.5 / 10.0 s"  # noqa: SLF001

    generator.measurement_triggered.emit(1)
    assert "palette(highlight)" in widget._table.cellWidget(1, 0).styleSheet()  # noqa: SLF001
    assert widget._timeout_spin.styleSheet() == ""  # noqa: SLF001

    generator.measurement_triggered.emit(-1)
    assert "palette(highlight)" in widget._timeout_spin.styleSheet()  # noqa: SLF001
    assert widget._table.cellWidget(1, 0).styleSheet() == ""  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
