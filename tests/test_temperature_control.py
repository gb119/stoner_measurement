"""Tests for the temperature control engine and UI panel.

Covers:
* Data model type construction.
* Rate-of-change computation.
* Engine singleton lifecycle.
* Engine stability flag evaluation.
* TemperatureControlPanel widget smoke tests.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta

import pytest

from stoner_measurement.temperature_control.engine import (
    TemperatureControllerEngine,
    _compute_rate,
)
from stoner_measurement.temperature_control.types import (
    EngineStatus,
    StabilityConfig,
    TemperatureChannelReading,
    TemperatureEngineState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_history(
    values: list[float],
    start: datetime | None = None,
    step_s: float = 2.0,
) -> deque[tuple[datetime, float]]:
    """Build a deque of (timestamp, value) pairs for rate-of-change tests.

    Args:
        values (list[float]):
            Ordered sequence of temperature values.

    Keyword Parameters:
        start (datetime | None):
            Starting timestamp.  Defaults to a fixed UTC time.
        step_s (float):
            Interval between readings in seconds.  Defaults to ``2.0``.

    Returns:
        (deque[tuple[datetime, float]]):
            History deque suitable for passing to ``_compute_rate``.
    """
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
    return deque(
        [(start + timedelta(seconds=i * step_s), v) for i, v in enumerate(values)]
    )


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class TestTemperatureChannelReading:
    def test_default_units_and_rate(self):
        from stoner_measurement.instruments.temperature_controller import SensorStatus

        r = TemperatureChannelReading(
            channel="A",
            value=300.0,
            timestamp=datetime.now(tz=UTC),
            status=SensorStatus.OK,
        )
        assert r.units == "K"
        assert r.rate_of_change == 0.0

    def test_custom_units(self):
        from stoner_measurement.instruments.temperature_controller import SensorStatus

        r = TemperatureChannelReading(
            channel="B",
            value=27.0,
            timestamp=datetime.now(tz=UTC),
            status=SensorStatus.OK,
            units="C",
        )
        assert r.units == "C"


class TestTemperatureEngineState:
    def test_defaults(self):
        state = TemperatureEngineState(engine_status=EngineStatus.DISCONNECTED)
        assert state.readings == {}
        assert state.setpoints == {}
        assert state.at_setpoint == {}
        assert state.stable == {}
        assert state.needle_valve is None

    def test_with_data(self):
        from stoner_measurement.instruments.temperature_controller import SensorStatus

        reading = TemperatureChannelReading(
            channel="A",
            value=300.0,
            timestamp=datetime.now(tz=UTC),
            status=SensorStatus.OK,
        )
        state = TemperatureEngineState(
            readings={"A": reading},
            setpoints={1: 300.0},
            heater_outputs={1: 25.0},
            at_setpoint={1: True},
            stable={1: False},
            engine_status=EngineStatus.POLLING,
        )
        assert state.readings["A"].value == 300.0
        assert state.at_setpoint[1] is True


class TestStabilityConfig:
    def test_defaults(self):
        cfg = StabilityConfig()
        assert cfg.tolerance_k == pytest.approx(0.1)
        assert cfg.window_s == pytest.approx(60.0)
        assert cfg.min_rate == pytest.approx(0.005)
        assert cfg.unstable_holdoff_s == pytest.approx(5.0)

    def test_custom(self):
        cfg = StabilityConfig(tolerance_k=0.5, window_s=120.0, min_rate=0.01)
        assert cfg.tolerance_k == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Rate-of-change computation
# ---------------------------------------------------------------------------


class TestComputeRate:
    def test_empty_history_returns_zero(self):
        assert _compute_rate(deque()) == pytest.approx(0.0)

    def test_single_point_returns_zero(self):
        history = _make_history([300.0])
        assert _compute_rate(history) == pytest.approx(0.0)

    def test_constant_temperature_returns_zero(self):
        history = _make_history([300.0] * 10)
        assert _compute_rate(history) == pytest.approx(0.0, abs=1e-9)

    def test_linear_rise_1_k_per_minute(self):
        # 1 K/min = 1/60 K/s; with 2 s steps: step = 1/30 K
        step = 1.0 / 30.0
        values = [300.0 + i * step for i in range(20)]
        history = _make_history(values, step_s=2.0)
        rate = _compute_rate(history)
        assert rate == pytest.approx(1.0, rel=1e-4)

    def test_linear_fall_2_k_per_minute(self):
        step = 2.0 / 30.0  # 2 K/min in 2 s steps
        values = [300.0 - i * step for i in range(20)]
        history = _make_history(values, step_s=2.0)
        rate = _compute_rate(history)
        assert rate == pytest.approx(-2.0, rel=1e-4)

    def test_two_points_gives_slope(self):
        # Two points 60 s apart with 1 K difference → 1 K/min
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        history = deque([
            (t0, 300.0),
            (t0 + timedelta(seconds=60), 301.0),
        ])
        assert _compute_rate(history) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Engine singleton lifecycle
# ---------------------------------------------------------------------------


class TestEngineLifecycle:
    def test_instance_returns_same_object(self, qapp):
        e1 = TemperatureControllerEngine.instance()
        e2 = TemperatureControllerEngine.instance()
        assert e1 is e2
        e1.shutdown()

    def test_initial_status_disconnected(self, qapp):
        engine = TemperatureControllerEngine()
        assert engine.status == EngineStatus.DISCONNECTED
        engine.shutdown()

    def test_shutdown_sets_stopped(self, qapp):
        engine = TemperatureControllerEngine()
        engine.shutdown()
        assert engine.status == EngineStatus.STOPPED

    def test_shutdown_clears_singleton(self, qapp):
        engine = TemperatureControllerEngine.instance()
        engine.shutdown()
        # A fresh instance should be created on next call.
        new_engine = TemperatureControllerEngine.instance()
        assert new_engine is not engine
        new_engine.shutdown()

    def test_connect_then_disconnect(self, qapp):
        from stoner_measurement.instruments.protocol.lakeshore import LakeshoreProtocol
        from stoner_measurement.instruments.temperature_controller import (
            ControllerCapabilities,
            ControlMode,
            PIDParameters,
            SensorStatus,
            TemperatureController,
        )
        from stoner_measurement.instruments.transport import NullTransport

        class _FakeTC(TemperatureController):
            def get_temperature(self, channel):
                return 300.0

            def get_sensor_status(self, channel):
                return SensorStatus.OK

            def get_input_channel(self, loop):
                return "A"

            def set_input_channel(self, loop, channel):
                pass

            def get_setpoint(self, loop):
                return 300.0

            def set_setpoint(self, loop, value):
                pass

            def get_loop_mode(self, loop):
                return ControlMode.CLOSED_LOOP

            def set_loop_mode(self, loop, mode):
                pass

            def get_heater_output(self, loop):
                return 10.0

            def set_heater_range(self, loop, range_):
                pass

            def get_pid(self, loop):
                return PIDParameters(50.0, 1.0, 0.0)

            def set_pid(self, loop, p, i, d):
                pass

            def get_ramp_rate(self, loop):
                return 5.0

            def set_ramp_rate(self, loop, rate):
                pass

            def get_ramp_enabled(self, loop):
                return False

            def set_ramp_enabled(self, loop, enabled):
                pass

            def get_capabilities(self):
                return ControllerCapabilities(
                    num_inputs=1,
                    num_loops=1,
                    input_channels=("A",),
                    loop_numbers=(1,),
                )

        engine = TemperatureControllerEngine()
        driver = _FakeTC(NullTransport(), LakeshoreProtocol())
        engine.connect_instrument(driver)
        assert engine.status == EngineStatus.CONNECTED
        engine.disconnect_instrument()
        assert engine.status == EngineStatus.DISCONNECTED
        engine.shutdown()

    def test_set_poll_interval_minimum_enforced(self, qapp):
        engine = TemperatureControllerEngine()
        engine.set_poll_interval(50)  # Below minimum of 100
        assert engine._timer.interval() == 100
        engine.shutdown()

    def test_set_stability_config(self, qapp):
        engine = TemperatureControllerEngine()
        cfg = StabilityConfig(tolerance_k=0.5, window_s=30.0)
        engine.set_stability_config(cfg)
        assert engine._stability_config.tolerance_k == pytest.approx(0.5)
        engine.shutdown()


# ---------------------------------------------------------------------------
# Engine stability evaluation
# ---------------------------------------------------------------------------


class TestEngineStabilityEvaluation:
    """Tests for _evaluate_stability using a synthetic engine instance."""

    def _make_reading(self, ch, value, rate=0.0):
        from stoner_measurement.instruments.temperature_controller import SensorStatus

        return TemperatureChannelReading(
            channel=ch,
            value=value,
            timestamp=datetime.now(tz=UTC),
            status=SensorStatus.OK,
            rate_of_change=rate,
        )

    def test_at_setpoint_flag_true_when_within_tolerance(self, qapp):
        engine = TemperatureControllerEngine()
        engine._stability_config = StabilityConfig(tolerance_k=0.1)
        readings = {"A": self._make_reading("A", 300.05)}
        setpoints = {1: 300.0}
        now = datetime.now(tz=UTC)
        at_sp, _ = engine._evaluate_stability(readings, setpoints, (1,), now)
        assert at_sp[1] is True
        engine.shutdown()

    def test_at_setpoint_flag_false_when_outside_tolerance(self, qapp):
        engine = TemperatureControllerEngine()
        engine._stability_config = StabilityConfig(tolerance_k=0.1)
        readings = {"A": self._make_reading("A", 301.0)}
        setpoints = {1: 300.0}
        now = datetime.now(tz=UTC)
        at_sp, _ = engine._evaluate_stability(readings, setpoints, (1,), now)
        assert at_sp[1] is False
        engine.shutdown()

    def test_stable_declared_after_window(self, qapp):
        engine = TemperatureControllerEngine()
        engine._stability_config = StabilityConfig(
            tolerance_k=0.1, window_s=10.0, min_rate=0.01
        )
        readings = {"A": self._make_reading("A", 300.0, rate=0.0)}
        setpoints = {1: 300.0}
        # Simulate first poll setting at_setpoint_since
        t0 = datetime.now(tz=UTC)
        engine._evaluate_stability(readings, setpoints, (1,), t0)
        # Advance time beyond window
        t1 = t0 + timedelta(seconds=15)
        _, stable = engine._evaluate_stability(readings, setpoints, (1,), t1)
        assert stable[1] is True
        engine.shutdown()

    def test_stable_not_declared_before_window(self, qapp):
        engine = TemperatureControllerEngine()
        engine._stability_config = StabilityConfig(
            tolerance_k=0.1, window_s=60.0, min_rate=0.01
        )
        readings = {"A": self._make_reading("A", 300.0, rate=0.0)}
        setpoints = {1: 300.0}
        t0 = datetime.now(tz=UTC)
        engine._evaluate_stability(readings, setpoints, (1,), t0)
        t1 = t0 + timedelta(seconds=5)
        _, stable = engine._evaluate_stability(readings, setpoints, (1,), t1)
        assert stable[1] is False
        engine.shutdown()

    def test_stable_requires_low_rate(self, qapp):
        engine = TemperatureControllerEngine()
        engine._stability_config = StabilityConfig(
            tolerance_k=0.1, window_s=10.0, min_rate=0.01
        )
        readings = {"A": self._make_reading("A", 300.0, rate=0.5)}  # rate too high
        setpoints = {1: 300.0}
        t0 = datetime.now(tz=UTC)
        engine._evaluate_stability(readings, setpoints, (1,), t0)
        t1 = t0 + timedelta(seconds=15)
        _, stable = engine._evaluate_stability(readings, setpoints, (1,), t1)
        assert stable[1] is False
        engine.shutdown()

    def test_stable_cleared_after_leaving_setpoint(self, qapp):
        engine = TemperatureControllerEngine()
        engine._stability_config = StabilityConfig(
            tolerance_k=0.1, window_s=1.0, min_rate=0.01, unstable_holdoff_s=0.0
        )
        t0 = datetime.now(tz=UTC)
        # First establish stability
        readings_ok = {"A": self._make_reading("A", 300.0, rate=0.0)}
        engine._evaluate_stability(readings_ok, {1: 300.0}, (1,), t0)
        t1 = t0 + timedelta(seconds=5)
        _, stable = engine._evaluate_stability(readings_ok, {1: 300.0}, (1,), t1)
        assert stable[1] is True, "Should be stable after window"
        # Now move away from setpoint
        readings_off = {"A": self._make_reading("A", 301.0)}
        t2 = t1 + timedelta(seconds=1)
        _, stable2 = engine._evaluate_stability(readings_off, {1: 300.0}, (1,), t2)
        assert stable2[1] is False, "Should lose stability when outside tolerance"
        engine.shutdown()


# ---------------------------------------------------------------------------
# Engine publisher signals
# ---------------------------------------------------------------------------


class TestEnginePublisher:
    def test_status_changed_signal_emitted(self, qapp):
        from stoner_measurement.instruments.protocol.lakeshore import LakeshoreProtocol
        from stoner_measurement.instruments.temperature_controller import (
            ControllerCapabilities,
            ControlMode,
            PIDParameters,
            SensorStatus,
            TemperatureController,
        )
        from stoner_measurement.instruments.transport import NullTransport

        class _FakeTC(TemperatureController):
            def get_temperature(self, channel):
                return 300.0

            def get_sensor_status(self, channel):
                return SensorStatus.OK

            def get_input_channel(self, loop):
                return "A"

            def set_input_channel(self, loop, channel):
                pass

            def get_setpoint(self, loop):
                return 300.0

            def set_setpoint(self, loop, value):
                pass

            def get_loop_mode(self, loop):
                return ControlMode.CLOSED_LOOP

            def set_loop_mode(self, loop, mode):
                pass

            def get_heater_output(self, loop):
                return 5.0

            def set_heater_range(self, loop, range_):
                pass

            def get_pid(self, loop):
                return PIDParameters(50.0, 1.0, 0.0)

            def set_pid(self, loop, p, i, d):
                pass

            def get_ramp_rate(self, loop):
                return 0.0

            def set_ramp_rate(self, loop, rate):
                pass

            def get_ramp_enabled(self, loop):
                return False

            def set_ramp_enabled(self, loop, enabled):
                pass

            def get_capabilities(self):
                return ControllerCapabilities(
                    num_inputs=1,
                    num_loops=1,
                    input_channels=("A",),
                    loop_numbers=(1,),
                )

        received: list[EngineStatus] = []
        engine = TemperatureControllerEngine()
        engine.publisher.engine_status_changed.connect(received.append)

        driver = _FakeTC(NullTransport(), LakeshoreProtocol())
        engine.connect_instrument(driver)
        engine.disconnect_instrument()
        engine.shutdown()

        assert EngineStatus.CONNECTED in received
        assert EngineStatus.DISCONNECTED in received
        assert EngineStatus.STOPPED in received


# ---------------------------------------------------------------------------
# TemperatureControlPanel widget smoke tests
# ---------------------------------------------------------------------------


class TestTemperatureControlPanel:
    def test_creates_widget(self, qapp):
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        panel = TemperatureControlPanel()
        assert panel is not None
        assert panel.windowTitle() == "Temperature Control"

    def test_show_and_raise(self, qapp):
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        panel = TemperatureControlPanel()
        panel.show_and_raise()
        assert panel.isVisible()
        panel.hide()

    def test_close_hides_not_destroys(self, qapp):
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        panel = TemperatureControlPanel()
        panel.show()
        assert panel.isVisible()
        panel.close()
        assert not panel.isVisible()

    def test_has_all_tabs(self, qapp):
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        panel = TemperatureControlPanel()
        tabs = panel._tabs
        tab_titles = [tabs.tabText(i) for i in range(tabs.count())]
        assert "Connection" in tab_titles
        assert "Control" in tab_titles
        assert "Stability" in tab_titles
        assert "Zone Table" in tab_titles
        assert "Chart" in tab_titles

    def test_stability_apply(self, qapp):
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        panel = TemperatureControlPanel()
        panel._stab_tolerance_spin.setValue(0.5)
        panel._stab_window_spin.setValue(30.0)
        panel._on_apply_stability()
        engine = TemperatureControllerEngine.instance()
        assert engine._stability_config.tolerance_k == pytest.approx(0.5)
        assert engine._stability_config.window_s == pytest.approx(30.0)

    def test_driver_combo_contains_temperature_controllers(self, qapp):
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        panel = TemperatureControlPanel()
        count = panel._driver_combo.count()
        # At least one concrete TC driver should be discovered.
        assert count >= 1
        # Ensure none are abstract base classes.
        for i in range(count):
            cls = panel._driver_combo.itemData(i)
            if cls is not None:
                import inspect

                assert not inspect.isabstract(cls)

    def test_has_input_settings_tab(self, qapp):
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        panel = TemperatureControlPanel()
        tabs = panel._tabs
        tab_titles = [tabs.tabText(i) for i in range(tabs.count())]
        assert "Input Settings" in tab_titles

    def test_input_settings_tab_disabled_on_startup(self, qapp):
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        panel = TemperatureControlPanel()
        assert not panel._tabs.isTabEnabled(panel._input_settings_tab_index)

    def test_needle_read_btn_exists(self, qapp):
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        panel = TemperatureControlPanel()
        assert hasattr(panel, "_needle_read_btn")

    def test_needle_read_btn_remains_enabled_when_gas_auto_active(self, qapp):
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        panel = TemperatureControlPanel()
        panel._needle_group.show()
        # Simulate enabling gas-auto mode.
        panel._on_gas_auto_changed(2)  # Qt.CheckState.Checked == 2
        # Apply button should be disabled, but Read button must stay enabled.
        assert not panel._needle_apply_btn.isEnabled()
        assert panel._needle_read_btn.isEnabled()
        # Reset.
        panel._on_gas_auto_changed(0)


# ---------------------------------------------------------------------------
# Engine zone table methods
# ---------------------------------------------------------------------------


def _make_fake_tc():
    """Return a minimal fake TemperatureController for zone tests."""
    from stoner_measurement.instruments.protocol.lakeshore import LakeshoreProtocol
    from stoner_measurement.instruments.temperature_controller import (
        ControllerCapabilities,
        ControlMode,
        PIDParameters,
        SensorStatus,
        TemperatureController,
        ZoneEntry,
    )
    from stoner_measurement.instruments.transport import NullTransport

    class _FakeTC(TemperatureController):
        def get_temperature(self, channel):
            return 300.0

        def get_sensor_status(self, channel):
            return SensorStatus.OK

        def get_input_channel(self, loop):
            return "A"

        def set_input_channel(self, loop, channel):
            pass

        def get_setpoint(self, loop):
            return 300.0

        def set_setpoint(self, loop, value):
            pass

        def get_loop_mode(self, loop):
            return ControlMode.CLOSED_LOOP

        def set_loop_mode(self, loop, mode):
            pass

        def get_heater_output(self, loop):
            return 10.0

        def set_heater_range(self, loop, range_):
            pass

        def get_pid(self, loop):
            return PIDParameters(50.0, 1.0, 0.0)

        def set_pid(self, loop, p, i, d):
            pass

        def get_ramp_rate(self, loop):
            return 5.0

        def set_ramp_rate(self, loop, rate):
            pass

        def get_ramp_enabled(self, loop):
            return False

        def set_ramp_enabled(self, loop, enabled):
            pass

        def get_capabilities(self):
            return ControllerCapabilities(
                num_inputs=1,
                num_loops=1,
                input_channels=("A",),
                loop_numbers=(1,),
                has_zone=True,
            )

        def get_num_zones(self, loop):
            return 3

        def get_zone(self, loop, zone_index):
            return ZoneEntry(
                upper_bound=float(zone_index * 50),
                p=10.0 * zone_index,
                i=1.0,
                d=0.0,
                ramp_rate=5.0,
                heater_range=1,
                heater_output=0.0,
            )

        def set_zone(self, loop, zone_index, entry):
            pass

    driver = _FakeTC(NullTransport(), LakeshoreProtocol())
    return driver


class TestEngineZoneTable:
    def test_get_zone_table_disconnected(self, qapp):
        engine = TemperatureControllerEngine()
        result = engine.get_zone_table(1)
        assert result is None
        engine.shutdown()

    def test_get_zone_table_reads_all_entries(self, qapp):
        from stoner_measurement.instruments.temperature_controller import ZoneEntry

        engine = TemperatureControllerEngine()
        driver = _make_fake_tc()
        engine.connect_instrument(driver)
        entries = engine.get_zone_table(1)
        assert entries is not None
        assert len(entries) == 3
        assert all(isinstance(e, ZoneEntry) for e in entries)
        # Zone 1 (entries[0]) upper_bound should be 50.0, zone 2 (entries[1]) should be 100.0
        assert entries[0].upper_bound == pytest.approx(50.0)
        assert entries[0].p == pytest.approx(10.0)
        assert entries[1].upper_bound == pytest.approx(100.0)
        assert entries[2].upper_bound == pytest.approx(150.0)
        engine.shutdown()

    def test_set_zone_table_calls_driver(self, qapp):
        from unittest.mock import MagicMock

        from stoner_measurement.instruments.temperature_controller import ZoneEntry

        engine = TemperatureControllerEngine()
        driver = _make_fake_tc()
        driver.set_zone = MagicMock()
        engine.connect_instrument(driver)
        entries = [
            ZoneEntry(upper_bound=50.0, p=10.0, i=1.0, d=0.0, ramp_rate=5.0, heater_range=1, heater_output=0.0),
            ZoneEntry(upper_bound=100.0, p=20.0, i=2.0, d=0.0, ramp_rate=5.0, heater_range=2, heater_output=0.0),
        ]
        engine.set_zone_table(1, entries)
        assert driver.set_zone.call_count == 2
        # First call should be zone index 1
        call_args = driver.set_zone.call_args_list
        assert call_args[0][0][1] == 1  # zone_index=1
        assert call_args[1][0][1] == 2  # zone_index=2
        engine.shutdown()

    def test_get_zone_table_handles_partial_failure(self, qapp):
        from stoner_measurement.instruments.temperature_controller import ZoneEntry

        engine = TemperatureControllerEngine()
        driver = _make_fake_tc()

        call_count = [0]
        original_get_zone = driver.get_zone

        def _patched_get_zone(loop, zone_index):
            call_count[0] += 1
            if zone_index == 2:
                raise RuntimeError("simulated read failure")
            return original_get_zone(loop, zone_index)

        driver.get_zone = _patched_get_zone
        engine.connect_instrument(driver)
        entries = engine.get_zone_table(1)
        # Zone 2 failed; zones 1 and 3 were read successfully and are returned
        # at list indices 0 and 1 respectively.
        assert entries is not None
        assert len(entries) == 2
        assert entries[0].upper_bound == pytest.approx(50.0)
        assert entries[1].upper_bound == pytest.approx(150.0)
        engine.shutdown()

    def test_set_zone_table_disconnected(self, qapp):
        engine = TemperatureControllerEngine()
        # Should silently do nothing when disconnected.
        from stoner_measurement.instruments.temperature_controller import ZoneEntry

        entries = [
            ZoneEntry(upper_bound=50.0, p=10.0, i=1.0, d=0.0, ramp_rate=5.0, heater_range=1, heater_output=0.0)
        ]
        engine.set_zone_table(1, entries)  # no exception expected
        engine.shutdown()
