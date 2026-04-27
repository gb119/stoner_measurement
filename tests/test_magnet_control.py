"""Tests for the magnet controller engine and UI panel.

Covers:
* Data model type construction.
* Rate-of-change computation.
* Engine singleton lifecycle.
* Engine command API no-ops when disconnected.
* Engine stability evaluation.
* Engine publisher signals emitted on connect/disconnect.
* Poll publishes state_updated with correct data when a mock driver is connected.
* MagnetControlPanel widget smoke tests.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta

import pytest

from stoner_measurement.magnet_control.engine import (
    MagnetControllerEngine,
    _compute_rate,
)
from stoner_measurement.magnet_control.types import (
    MagnetEngineState,
    MagnetEngineStatus,
    MagnetReading,
    MagnetStabilityConfig,
)


# ---------------------------------------------------------------------------
# Helpers — fake driver
# ---------------------------------------------------------------------------


def _make_fake_driver(field: float = 1.0, current: float = 10.0):
    """Build a minimal concrete :class:`MagnetController` for tests.

    Args:
        field (float):
            Field value the fake driver will report.  Defaults to ``1.0``.
        current (float):
            Current value the fake driver will report.  Defaults to ``10.0``.

    Returns:
        (MagnetController):
            A concrete :class:`MagnetController` subclass instance.
    """
    from stoner_measurement.instruments.magnet_controller import (
        MagnetController,
        MagnetLimits,
        MagnetState,
        MagnetStatus,
    )
    from stoner_measurement.instruments.protocol.oxford import OxfordProtocol
    from stoner_measurement.instruments.transport import NullTransport

    class _FakeMC(MagnetController):
        def __init__(self, transport, protocol, init_field, init_current):
            super().__init__(transport=transport, protocol=protocol)
            self._field_val = init_field
            self._current_val = init_current
            self._magnet_constant_val = 0.1

        def get_model(self):
            return "FakeMagnet"

        def get_firmware_version(self):
            return "0.0"

        @property
        def current(self):
            return self._current_val

        @property
        def field(self):
            return self._field_val

        @property
        def voltage(self):
            return 0.05

        @property
        def status(self):
            return MagnetStatus(
                state=MagnetState.AT_TARGET,
                current=self._current_val,
                field=self._field_val,
                voltage=0.05,
                persistent=False,
                heater_on=True,
                at_target=True,
            )

        @property
        def magnet_constant(self):
            return self._magnet_constant_val

        @property
        def limits(self):
            return MagnetLimits(max_current=100.0, max_field=10.0, max_ramp_rate=1.0)

        @property
        def heater(self):
            return True

        def set_target_current(self, current_):
            pass

        def set_target_field(self, field_):
            self._field_val = field_

        def set_ramp_rate_current(self, rate):
            pass

        def set_ramp_rate_field(self, rate):
            pass

        def set_magnet_constant(self, tesla_per_amp):
            self._magnet_constant_val = tesla_per_amp

        def set_limits(self, limits):
            pass

        def ramp_to_target(self):
            pass

        def ramp_to_current(self, current_, *, wait=False):
            pass

        def ramp_to_field(self, field_, *, wait=False):
            self._field_val = field_

        def pause_ramp(self):
            pass

        def abort_ramp(self):
            pass

        def heater_on(self):
            pass

        def heater_off(self):
            pass

    return _FakeMC(NullTransport(), OxfordProtocol(), field, current)


def _make_history(
    values: list[float],
    start: datetime | None = None,
    step_s: float = 2.0,
) -> deque[tuple[datetime, float]]:
    """Build a deque of (timestamp, value) pairs for rate-of-change tests.

    Args:
        values (list[float]):
            Ordered sequence of field values.

    Keyword Parameters:
        start (datetime | None):
            Starting timestamp.  Defaults to a fixed UTC time.
        step_s (float):
            Interval between readings in seconds.  Defaults to ``2.0``.

    Returns:
        (deque[tuple[datetime, float]]):
            History deque suitable for passing to :func:`_compute_rate`.
    """
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
    return deque(
        [(start + timedelta(seconds=i * step_s), v) for i, v in enumerate(values)]
    )


# ---------------------------------------------------------------------------
# Data model types
# ---------------------------------------------------------------------------


class TestMagnetReading:
    def test_defaults_field_rate(self):
        from stoner_measurement.instruments.magnet_controller import MagnetState

        r = MagnetReading(
            timestamp=datetime.now(tz=UTC),
            field=1.0,
            current=10.0,
            voltage=0.05,
            heater_on=True,
            state=MagnetState.AT_TARGET,
            at_target=True,
        )
        assert r.field_rate == pytest.approx(0.0)

    def test_none_field(self):
        from stoner_measurement.instruments.magnet_controller import MagnetState

        r = MagnetReading(
            timestamp=datetime.now(tz=UTC),
            field=None,
            current=0.0,
            voltage=None,
            heater_on=None,
            state=MagnetState.UNKNOWN,
            at_target=False,
        )
        assert r.field is None
        assert r.heater_on is None


class TestMagnetEngineState:
    def test_defaults(self):
        state = MagnetEngineState(engine_status=MagnetEngineStatus.DISCONNECTED)
        assert state.reading is None
        assert state.at_target is False
        assert state.target_field is None
        assert state.magnet_constant is None

    def test_with_values(self):
        from stoner_measurement.instruments.magnet_controller import MagnetState

        reading = MagnetReading(
            timestamp=datetime.now(tz=UTC),
            field=2.0,
            current=20.0,
            voltage=0.1,
            heater_on=True,
            state=MagnetState.RAMPING,
            at_target=False,
        )
        state = MagnetEngineState(
            reading=reading,
            target_field=2.0,
            at_target=False,
            engine_status=MagnetEngineStatus.POLLING,
        )
        assert state.reading.field == pytest.approx(2.0)
        assert state.target_field == pytest.approx(2.0)


class TestMagnetStabilityConfig:
    def test_defaults(self):
        cfg = MagnetStabilityConfig()
        assert cfg.tolerance_t == pytest.approx(0.001)
        assert cfg.window_s == pytest.approx(10.0)
        assert cfg.min_rate == pytest.approx(0.0001)
        assert cfg.unstable_holdoff_s == pytest.approx(2.0)

    def test_custom_values(self):
        cfg = MagnetStabilityConfig(tolerance_t=0.005, window_s=30.0)
        assert cfg.tolerance_t == pytest.approx(0.005)
        assert cfg.window_s == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Rate-of-change computation
# ---------------------------------------------------------------------------


class TestComputeRate:
    def test_empty_history_returns_zero(self):
        assert _compute_rate(deque()) == pytest.approx(0.0)

    def test_single_point_returns_zero(self):
        history = _make_history([1.0])
        assert _compute_rate(history) == pytest.approx(0.0)

    def test_constant_field_returns_zero(self):
        history = _make_history([1.0] * 10)
        assert _compute_rate(history) == pytest.approx(0.0, abs=1e-9)

    def test_linear_rise_1_t_per_minute(self):
        # 1 T/min = 1/60 T/s; with 2 s steps: step = 1/30 T
        step = 1.0 / 30.0
        values = [1.0 + i * step for i in range(20)]
        history = _make_history(values, step_s=2.0)
        rate = _compute_rate(history)
        assert rate == pytest.approx(1.0, rel=1e-4)

    def test_linear_fall_2_t_per_minute(self):
        step = 2.0 / 30.0
        values = [2.0 - i * step for i in range(20)]
        history = _make_history(values, step_s=2.0)
        rate = _compute_rate(history)
        assert rate == pytest.approx(-2.0, rel=1e-4)

    def test_two_points_gives_slope(self):
        t0 = datetime(2024, 1, 1, tzinfo=UTC)
        history = deque([
            (t0, 1.0),
            (t0 + timedelta(seconds=60), 2.0),
        ])
        assert _compute_rate(history) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Engine singleton lifecycle
# ---------------------------------------------------------------------------


class TestEngineLifecycle:
    def test_instance_returns_same_object(self, qapp):
        e1 = MagnetControllerEngine.instance()
        e2 = MagnetControllerEngine.instance()
        assert e1 is e2
        e1.shutdown()

    def test_initial_status_disconnected(self, qapp):
        engine = MagnetControllerEngine()
        assert engine.status == MagnetEngineStatus.DISCONNECTED
        engine.shutdown()

    def test_shutdown_sets_stopped(self, qapp):
        engine = MagnetControllerEngine()
        engine.shutdown()
        assert engine.status == MagnetEngineStatus.STOPPED

    def test_shutdown_clears_singleton(self, qapp):
        engine = MagnetControllerEngine.instance()
        engine.shutdown()
        new_engine = MagnetControllerEngine.instance()
        assert new_engine is not engine
        new_engine.shutdown()

    def test_connect_then_disconnect(self, qapp):
        engine = MagnetControllerEngine()
        driver = _make_fake_driver()
        engine.connect_instrument(driver)
        assert engine.status == MagnetEngineStatus.CONNECTED
        engine.disconnect_instrument()
        assert engine.status == MagnetEngineStatus.DISCONNECTED
        engine.shutdown()

    def test_connect_after_shutdown_raises(self, qapp):
        engine = MagnetControllerEngine()
        engine.shutdown()
        driver = _make_fake_driver()
        with pytest.raises(RuntimeError):
            engine.connect_instrument(driver)

    def test_set_poll_interval_minimum_enforced(self, qapp):
        engine = MagnetControllerEngine()
        engine.set_poll_interval(50)  # Below minimum of 100
        assert engine._timer.interval() == 100
        engine.shutdown()

    def test_set_stability_config(self, qapp):
        engine = MagnetControllerEngine()
        cfg = MagnetStabilityConfig(tolerance_t=0.005, window_s=20.0)
        engine.set_stability_config(cfg)
        assert engine._stability_config.tolerance_t == pytest.approx(0.005)
        assert engine._stability_config.window_s == pytest.approx(20.0)
        engine.shutdown()


# ---------------------------------------------------------------------------
# Command API no-ops when disconnected
# ---------------------------------------------------------------------------


class TestCommandApiNoOpsWhenDisconnected:
    """All command methods should be silently ignored when no driver is connected."""

    def test_set_target_field_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.set_target_field(1.0)  # must not raise
        engine.shutdown()

    def test_set_target_current_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.set_target_current(10.0)
        engine.shutdown()

    def test_set_ramp_rate_field_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.set_ramp_rate_field(0.1)
        engine.shutdown()

    def test_set_ramp_rate_current_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.set_ramp_rate_current(1.0)
        engine.shutdown()

    def test_set_magnet_constant_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.set_magnet_constant(0.1)
        engine.shutdown()

    def test_ramp_to_target_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.ramp_to_target()
        engine.shutdown()

    def test_ramp_to_field_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.ramp_to_field(2.0)
        engine.shutdown()

    def test_pause_ramp_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.pause_ramp()
        engine.shutdown()

    def test_abort_ramp_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.abort_ramp()
        engine.shutdown()

    def test_heater_on_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.heater_on()
        engine.shutdown()

    def test_heater_off_no_driver(self, qapp):
        engine = MagnetControllerEngine()
        engine.heater_off()
        engine.shutdown()


# ---------------------------------------------------------------------------
# Engine stability evaluation
# ---------------------------------------------------------------------------


class TestEngineStabilityEvaluation:
    def test_at_target_flag_true_when_within_tolerance(self, qapp):
        engine = MagnetControllerEngine()
        engine._stability_config = MagnetStabilityConfig(tolerance_t=0.001)
        engine._target_field = 1.0
        t0 = datetime.now(tz=UTC)
        engine._history.append((t0, 1.0005))
        engine._evaluate_stability(1.0005, t0)
        # _at_target_since set but window not elapsed → stable is still False
        assert engine._at_target_since is not None
        engine.shutdown()

    def test_at_target_flag_false_when_outside_tolerance(self, qapp):
        engine = MagnetControllerEngine()
        engine._stability_config = MagnetStabilityConfig(tolerance_t=0.001)
        engine._target_field = 1.0
        t0 = datetime.now(tz=UTC)
        engine._evaluate_stability(1.5, t0)
        assert engine._at_target_since is None
        assert engine._stable is False
        engine.shutdown()

    def test_stable_declared_after_window(self, qapp):
        engine = MagnetControllerEngine()
        engine._stability_config = MagnetStabilityConfig(
            tolerance_t=0.001, window_s=5.0, min_rate=0.001
        )
        engine._target_field = 1.0
        t0 = datetime.now(tz=UTC)
        # Populate history with constant values.
        for i in range(10):
            engine._history.append((t0 + timedelta(seconds=i * 0.5), 1.0))
        engine._evaluate_stability(1.0, t0)
        # Simulate time beyond window having elapsed.
        t1 = t0 + timedelta(seconds=10)
        engine._evaluate_stability(1.0, t1)
        assert engine._stable is True
        engine.shutdown()

    def test_stable_cleared_when_field_leaves_target(self, qapp):
        engine = MagnetControllerEngine()
        engine._stability_config = MagnetStabilityConfig(
            tolerance_t=0.001, window_s=1.0, min_rate=0.001, unstable_holdoff_s=0.0
        )
        engine._target_field = 1.0
        t0 = datetime.now(tz=UTC)
        for i in range(5):
            engine._history.append((t0 + timedelta(seconds=i * 0.3), 1.0))
        engine._evaluate_stability(1.0, t0)
        t1 = t0 + timedelta(seconds=5)
        engine._evaluate_stability(1.0, t1)
        assert engine._stable is True
        # Now field drifts away.
        t2 = t1 + timedelta(seconds=1)
        engine._evaluate_stability(2.0, t2)
        assert engine._stable is False
        engine.shutdown()

    def test_stable_not_declared_before_window(self, qapp):
        engine = MagnetControllerEngine()
        engine._stability_config = MagnetStabilityConfig(
            tolerance_t=0.001, window_s=60.0, min_rate=0.001
        )
        engine._target_field = 1.0
        t0 = datetime.now(tz=UTC)
        engine._evaluate_stability(1.0, t0)
        t1 = t0 + timedelta(seconds=5)
        engine._evaluate_stability(1.0, t1)
        assert engine._stable is False
        engine.shutdown()


# ---------------------------------------------------------------------------
# Engine publisher signals
# ---------------------------------------------------------------------------


class TestEnginePublisher:
    def test_status_changed_signal_emitted_on_connect_disconnect(self, qapp):
        received: list[MagnetEngineStatus] = []
        engine = MagnetControllerEngine()
        engine.publisher.engine_status_changed.connect(received.append)

        driver = _make_fake_driver()
        engine.connect_instrument(driver)
        engine.disconnect_instrument()
        engine.shutdown()

        assert MagnetEngineStatus.CONNECTED in received
        assert MagnetEngineStatus.DISCONNECTED in received
        assert MagnetEngineStatus.STOPPED in received

    def test_poll_emits_state_updated(self, qapp):
        """A manual _poll() call should emit state_updated with the reading."""
        states: list[MagnetEngineState] = []
        engine = MagnetControllerEngine()
        engine.publisher.state_updated.connect(states.append)

        driver = _make_fake_driver(field=2.0, current=20.0)
        engine.connect_instrument(driver)
        engine._poll()  # manually trigger one poll cycle
        engine.shutdown()

        assert len(states) == 1
        assert states[0].reading is not None
        assert states[0].reading.field == pytest.approx(2.0)
        assert states[0].reading.current == pytest.approx(20.0)

    def test_get_engine_state_returns_snapshot(self, qapp):
        engine = MagnetControllerEngine()
        engine._target_field = 3.0
        state = engine.get_engine_state()
        assert state.target_field == pytest.approx(3.0)
        assert state.reading is None
        engine.shutdown()


# ---------------------------------------------------------------------------
# MagnetControlPanel widget smoke tests
# ---------------------------------------------------------------------------


class TestMagnetControlPanel:
    def test_creates_widget(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        assert panel is not None
        assert panel.windowTitle() == "Magnet Control"

    def test_show_and_raise(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        panel.show_and_raise()
        assert panel.isVisible()
        panel.hide()

    def test_close_hides_not_destroys(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        panel.show()
        assert panel.isVisible()
        panel.close()
        assert not panel.isVisible()

    def test_has_all_tabs(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        tabs = panel._tabs
        tab_titles = [tabs.tabText(i) for i in range(tabs.count())]
        assert "Connection" in tab_titles
        assert "Configuration" in tab_titles
        assert "Chart" in tab_titles

    def test_target_field_spin_updates_current_label(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        panel._magnet_constant = 0.1
        panel._target_field_spin.setValue(1.0)
        # 1.0 T / 0.1 T/A = 10.0 A
        assert "10.0" in panel._target_current_label.text()

    def test_driver_combo_has_magnet_controllers(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        # Should have at least one entry (possibly "(no drivers found)" if none
        # are registered, but the combo should not be empty).
        assert panel._driver_combo.count() >= 1

    def test_apply_limits_updates_magnet_constant(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        panel._magnet_const_spin.setValue(0.05)
        # Engine has no driver connected — set_magnet_constant should be a no-op.
        panel._on_apply_limits()
        assert panel._magnet_constant == pytest.approx(0.05)
