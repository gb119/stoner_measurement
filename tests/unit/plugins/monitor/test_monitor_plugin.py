"""Focused tests for MonitorPlugin behavior."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.monitor import MonitorPlugin


class _ConstMonitor(MonitorPlugin):
    """MonitorPlugin that always returns a fixed reading."""

    @property
    def name(self) -> str:
        return "ConstMonitor"

    @property
    def quantity_names(self) -> list[str]:
        return ["temperature", "pressure"]

    @property
    def units(self) -> dict[str, str]:
        return {"temperature": "K", "pressure": "Pa"}

    def read(self) -> dict[str, float]:
        return {"temperature": 300.0, "pressure": 101325.0}


class TestMonitorPlugin:
    def test_plugin_type(self, qapp):
        assert _ConstMonitor().plugin_type == "monitor"

    def test_quantity_names(self, qapp):
        assert _ConstMonitor().quantity_names == ["temperature", "pressure"]

    def test_units(self, qapp):
        assert _ConstMonitor().units == {"temperature": "K", "pressure": "Pa"}

    def test_read_returns_dict(self, qapp):
        m = _ConstMonitor()
        reading = m.read()
        assert reading == {"temperature": 300.0, "pressure": 101325.0}

    def test_monitor_interval_default(self, qapp):
        assert _ConstMonitor().monitor_interval == 1000

    def test_last_reading_initially_empty(self, qapp):
        assert _ConstMonitor().last_reading == {}

    def test_last_reading_is_a_copy(self, qapp):
        m = _ConstMonitor()
        m._last_reading = {"temperature": 100.0}
        r1 = m.last_reading
        r1["temperature"] = 999.0
        assert m._last_reading["temperature"] == 100.0

    def test_start_monitoring_activates_timer(self, qapp):
        m = _ConstMonitor()
        m.start_monitoring(200)
        assert m._timer.isActive()
        m.stop_monitoring()

    def test_stop_monitoring_deactivates_timer(self, qapp):
        m = _ConstMonitor()
        m.start_monitoring()
        m.stop_monitoring()
        assert not m._timer.isActive()

    def test_poll_emits_data_available(self, qapp):
        m = _ConstMonitor()
        received = []
        m.data_available.connect(received.append)
        m._poll()
        assert received == [{"temperature": 300.0, "pressure": 101325.0}]

    def test_poll_caches_last_reading(self, qapp):
        m = _ConstMonitor()
        m._poll()
        assert m.last_reading == {"temperature": 300.0, "pressure": 101325.0}

    def test_poll_emits_read_error_on_exception(self, qapp):
        class _ErrorMonitor(MonitorPlugin):
            @property
            def name(self):
                return "Err"

            @property
            def quantity_names(self):
                return []

            @property
            def units(self):
                return {}

            def read(self):
                raise RuntimeError("hardware fault")

        m = _ErrorMonitor()
        errors = []
        m.read_error.connect(errors.append)
        m._poll()
        assert errors == ["hardware fault"]

    def test_data_available_signal(self, qapp):
        m = _ConstMonitor()
        received = []
        m.data_available.connect(received.append)
        m.data_available.emit({"x": 1.0})
        assert received == [{"x": 1.0}]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
