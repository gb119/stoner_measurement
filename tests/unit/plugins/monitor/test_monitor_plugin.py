"""Focused tests for MonitorPlugin behavior."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

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


@pytest.mark.parametrize("path", ["direct", "poll", "generated"])
def test_all_read_paths_cache_and_emit_once(qapp, path):
    monitor = _ConstMonitor()
    received = []
    monitor.data_available.connect(received.append)
    if path == "direct":
        reading = monitor.read()
    elif path == "poll":
        monitor._poll()
        reading = received[0]
    else:
        namespace = {monitor.instance_name: monitor}
        source = "\n".join(monitor.generate_action_code(0, [], lambda *_: []))
        exec(compile(source, "<monitor action>", "exec"), namespace)
        reading = namespace["data"]
    assert received == [reading]
    assert monitor.last_reading == reading
    reading["temperature"] = -1
    received[0]["pressure"] = -1
    assert monitor.last_reading == {"temperature": 300.0, "pressure": 101325.0}


def test_inherited_read_caches_outer_result_and_preserves_keyword_arguments(qapp):
    class _AdjustedMonitor(_ConstMonitor):
        def read(self, *, offset=0):
            reading = super().read()
            reading["temperature"] += offset
            return reading

    monitor = _AdjustedMonitor()
    received = []
    monitor.data_available.connect(received.append)
    assert monitor.read(offset=2)["temperature"] == 302
    assert monitor.last_reading["temperature"] == 302
    assert len(received) == 1


@pytest.mark.parametrize("path", ["direct", "poll", "generated"])
def test_failed_read_keeps_last_success_and_does_not_publish(qapp, path):
    class _FailingMonitor(_ConstMonitor):
        failed = False

        def read(self):
            reading = super().read()
            if self.failed:
                raise RuntimeError("read failed")
            return reading

    monitor = _FailingMonitor()
    expected = monitor.read()
    monitor.failed = True
    received = []
    errors = []
    monitor.data_available.connect(received.append)
    monitor.read_error.connect(errors.append)
    if path == "poll":
        monitor._poll()
        assert errors == ["read failed"]
    else:
        with pytest.raises(RuntimeError, match="read failed"):
            if path == "direct":
                monitor.read()
            else:
                source = "\n".join(monitor.generate_action_code(0, [], lambda *_: []))
                exec(compile(source, "<monitor action>", "exec"), {monitor.instance_name: monitor})
        assert errors == []
    assert monitor.last_reading == expected
    assert received == []
    monitor.failed = False
    monitor.read()
    assert len(received) == 1


def test_read_inherited_from_mixin_updates_the_cache(qapp):
    class _ReadMixin:
        def read(self):
            return {"temperature": 12.0}

    class _MixinMonitor(_ReadMixin, _ConstMonitor):
        pass

    monitor = _MixinMonitor()
    received = []
    monitor.data_available.connect(received.append)
    monitor.read()
    assert monitor.last_reading == {"temperature": 12.0}
    assert received == [{"temperature": 12.0}]


def test_concurrent_reads_each_publish_their_completed_result(qapp, qtbot):
    entered = Event()
    release = Event()

    class _ConcurrentMonitor(_ConstMonitor):
        def read(self, *, delayed=False):
            if delayed:
                entered.set()
                assert release.wait(timeout=5)
                return {"temperature": 1.0}
            return {"temperature": 2.0}

    monitor = _ConcurrentMonitor()
    received = []
    monitor.data_available.connect(received.append)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(monitor.read, delayed=True)
        try:
            assert entered.wait(timeout=5)
            assert executor.submit(monitor.read).result(timeout=5) == {"temperature": 2.0}
        finally:
            release.set()
        assert first.result(timeout=5) == {"temperature": 1.0}
    qtbot.waitUntil(lambda: len(received) == 2)
    assert monitor.last_reading == {"temperature": 1.0}
    assert received == [{"temperature": 2.0}, {"temperature": 1.0}]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
