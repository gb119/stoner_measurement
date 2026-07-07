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

from stoner_measurement.instruments.magnet_controller import MagnetLimits
from stoner_measurement.magnet_control import engine as engine_module
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
from stoner_measurement.ui.widgets.visa_resource_widget import VisaResourceStatus

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
        HeaterState,
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
            self._target_current_val = init_current
            self._ramp_rate_current_val = 5.0

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
                heater_state=HeaterState.ON,
                at_target=True,
                persistent_field=None,
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

        @property
        def target_current(self):
            return self._target_current_val

        @property
        def target_field(self):
            return self._target_current_val * self._magnet_constant_val

        @property
        def ramp_rate_current(self):
            return self._ramp_rate_current_val

        @property
        def ramp_rate_field(self):
            return self._ramp_rate_current_val * self._magnet_constant_val

        def set_target_current(self, current_):
            self._target_current_val = current_

        def set_target_field(self, field_):
            self._field_val = field_
            self._target_current_val = field_ / self._magnet_constant_val

        def set_ramp_rate_current(self, rate):
            self._ramp_rate_current_val = rate

        def set_ramp_rate_field(self, rate):
            self._ramp_rate_current_val = rate / self._magnet_constant_val

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

        def return_to_local(self):
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
        from stoner_measurement.instruments.magnet_controller import HeaterState, MagnetState

        r = MagnetReading(
            timestamp=datetime.now(tz=UTC),
            field=1.0,
            current=10.0,
            voltage=0.05,
            heater_on=True,
            heater_state=HeaterState.ON,
            state=MagnetState.AT_TARGET,
            persistent_field=None,
            at_target=True,
        )
        assert r.field_rate == pytest.approx(0.0)

    def test_none_field(self):
        from stoner_measurement.instruments.magnet_controller import HeaterState, MagnetState

        r = MagnetReading(
            timestamp=datetime.now(tz=UTC),
            field=None,
            current=0.0,
            voltage=None,
            heater_on=None,
            heater_state=HeaterState.UNKNOWN,
            state=MagnetState.UNKNOWN,
            persistent_field=None,
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
        from stoner_measurement.instruments.magnet_controller import HeaterState, MagnetState

        reading = MagnetReading(
            timestamp=datetime.now(tz=UTC),
            field=2.0,
            current=20.0,
            voltage=0.1,
            heater_on=True,
            heater_state=HeaterState.ON,
            state=MagnetState.RAMPING,
            persistent_field=None,
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
    def test_constructor_applies_configuration(self, monkeypatch, qapp):
        monkeypatch.setattr(
            engine_module,
            "load_magnet_controller_config",
            lambda: {
                "connection": {
                    "driver": "TestDriver",
                    "transport": "Ethernet",
                    "address": "testhost:1234",
                },
                "poll_interval_ms": 1234,
                "stability": {
                    "tolerance_t": 0.25,
                    "window_s": 12.0,
                    "min_rate": 0.02,
                    "unstable_holdoff_s": 3.0,
                },
                "targets": {
                    "field": 1.5,
                    "current": 15.0,
                },
                "ramp": {
                    "field_rate": 0.4,
                    "current_rate": 4.0,
                },
                "limits": {
                    "magnet_constant": 0.1,
                    "max_current": 60.0,
                    "max_field": 6.0,
                    "max_ramp_rate": 0.8,
                },
            },
        )
        engine = MagnetControllerEngine()
        assert engine._timer.interval() == 1234  # noqa: SLF001
        assert engine.preferred_driver_name == "TestDriver"
        assert engine.preferred_transport_name == "Ethernet"
        assert engine.preferred_address == "testhost:1234"
        assert engine._stability_config.tolerance_t == pytest.approx(0.25)  # noqa: SLF001
        assert engine._stability_config.window_s == pytest.approx(12.0)  # noqa: SLF001
        assert engine._stability_config.min_rate == pytest.approx(0.02)  # noqa: SLF001
        assert engine._stability_config.unstable_holdoff_s == pytest.approx(3.0)  # noqa: SLF001
        assert engine._target_field == pytest.approx(1.5)  # noqa: SLF001
        assert engine._target_current == pytest.approx(15.0)  # noqa: SLF001
        assert engine._ramp_rate_field == pytest.approx(0.4)  # noqa: SLF001
        assert engine._ramp_rate_current == pytest.approx(4.0)  # noqa: SLF001
        assert engine._magnet_constant == pytest.approx(0.1)  # noqa: SLF001
        assert engine._limits is not None  # noqa: SLF001
        assert engine._limits.max_current == pytest.approx(60.0)  # noqa: SLF001
        assert engine._limits.max_field == pytest.approx(6.0)  # noqa: SLF001
        assert engine._limits.max_ramp_rate == pytest.approx(0.8)  # noqa: SLF001
        engine.shutdown()

    def test_preferred_connection_properties_are_mutable(self, qapp):
        engine = MagnetControllerEngine()

        engine.preferred_driver_name = "DriverA"
        engine.preferred_transport_name = "Serial"
        engine.preferred_address = "port=COM3;baud=115200"

        assert engine.preferred_driver_name == "DriverA"
        assert engine.preferred_transport_name == "Serial"
        assert engine.preferred_address == "port=COM3;baud=115200"

        engine.shutdown()

    def test_configuration_dict_exports_current_settings(self, qapp):
        engine = MagnetControllerEngine()

        engine.preferred_driver_name = "DriverA"
        engine.preferred_transport_name = "Ethernet"
        engine.preferred_address = "host:1234"
        engine.set_poll_interval(1500)
        engine.set_target_field(2.5)
        engine.set_target_current(25.0)
        engine.set_ramp_rate_field(0.75)
        engine.set_ramp_rate_current(7.5)
        engine.set_magnet_constant(0.1)
        engine.set_limits(MagnetLimits(max_current=80.0, max_field=8.0, max_ramp_rate=0.9))
        engine.set_stability_config(
            MagnetStabilityConfig(
                tolerance_t=0.2,
                window_s=30.0,
                min_rate=0.01,
                unstable_holdoff_s=2.0,
            )
        )

        config = engine.configuration_dict()

        assert config["poll_interval_ms"] == 1500
        assert config["connection"] == {
            "driver": "DriverA",
            "transport": "Ethernet",
            "address": "host:1234",
        }
        assert config["targets"] == {"field": pytest.approx(2.5), "current": pytest.approx(25.0)}
        assert config["ramp"] == {
            "field_rate": pytest.approx(0.75),
            "current_rate": pytest.approx(7.5),
        }
        assert config["limits"] == {
            "magnet_constant": pytest.approx(0.1),
            "max_current": pytest.approx(80.0),
            "max_field": pytest.approx(8.0),
            "max_ramp_rate": pytest.approx(0.9),
        }
        assert config["stability"]["tolerance_t"] == pytest.approx(0.2)
        assert config["stability"]["window_s"] == pytest.approx(30.0)
        assert config["stability"]["min_rate"] == pytest.approx(0.01)
        assert config["stability"]["unstable_holdoff_s"] == pytest.approx(2.0)

        engine.shutdown()

    def test_save_configuration_writes_machine_config(self, monkeypatch, tmp_path, qapp):
        from stoner_measurement.magnet_control import config as config_module

        config_path = tmp_path / "magnet_controller.yaml"

        monkeypatch.setattr(
            config_module,
            "machine_config_path",
            lambda: config_path,
        )

        engine = MagnetControllerEngine()
        engine.preferred_driver_name = "DriverA"

        path = engine.save_configuration()

        assert path == config_path
        assert path.exists()
        assert "DriverA" in path.read_text(encoding="utf-8")

        engine.shutdown()

    def test_save_configuration_creates_timestamped_backup(
        self, monkeypatch, tmp_path, qapp
    ):
        from stoner_measurement.magnet_control import config as config_module

        config_path = tmp_path / "magnet_controller.yaml"
        config_path.write_text("original: true\n", encoding="utf-8")

        monkeypatch.setattr(
            config_module,
            "machine_config_path",
            lambda: config_path,
        )

        engine = MagnetControllerEngine()
        engine.preferred_driver_name = "DriverB"

        engine.save_configuration()

        backups = list(
            tmp_path.glob("magnet_controller.*.yaml")
        )

        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "original: true\n"
        assert "DriverB" in config_path.read_text(encoding="utf-8")

        engine.shutdown()

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
        assert driver.is_connected
        engine.disconnect_instrument()
        assert engine.status == MagnetEngineStatus.DISCONNECTED
        assert not driver.is_connected
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

    def test_reconnect_disconnects_previous_driver(self, qapp):
        engine = MagnetControllerEngine()
        first = _make_fake_driver()
        second = _make_fake_driver()
        engine.connect_instrument(first)
        assert first.is_connected
        engine.connect_instrument(second)
        assert not first.is_connected
        assert second.is_connected
        engine.shutdown()

    def test_connect_preferred_driver_uses_persisted_connection_settings(self, qapp):
        from stoner_measurement.instruments.magnet_controller import MagnetController
        from stoner_measurement.instruments.protocol.oxford import OxfordProtocol
        from stoner_measurement.instruments.transport import NullTransport

        class _PreferredMagnetDriver(MagnetController):
            def get_model(self):
                return "PreferredMagnet"

            def get_firmware_version(self):
                return "0.0"

            @property
            def current(self):
                return 10.0

            @property
            def field(self):
                return 1.0

            @property
            def voltage(self):
                return 0.05

            @property
            def status(self):
                return _make_fake_driver().status

            @property
            def magnet_constant(self):
                return 0.1

            @property
            def limits(self):
                return MagnetLimits(max_current=100.0, max_field=10.0, max_ramp_rate=1.0)

            @property
            def heater(self):
                return True

            @property
            def target_current(self):
                return 10.0

            @property
            def target_field(self):
                return 1.0

            @property
            def ramp_rate_current(self):
                return 5.0

            @property
            def ramp_rate_field(self):
                return 0.5

            def set_target_current(self, current_):
                pass

            def set_target_field(self, field_):
                pass

            def set_ramp_rate_current(self, rate):
                pass

            def set_ramp_rate_field(self, rate):
                pass

            def set_magnet_constant(self, tesla_per_amp):
                pass

            def set_limits(self, limits):
                pass

            def ramp_to_target(self):
                pass

            def ramp_to_current(self, current_, *, wait=False):
                pass

            def ramp_to_field(self, field_, *, wait=False):
                pass

            def pause_ramp(self):
                pass

            def abort_ramp(self):
                pass

            def heater_on(self):
                pass

            def heater_off(self):
                pass

            def return_to_local(self):
                pass

        engine = MagnetControllerEngine()
        engine._resolve_driver_class = lambda _name: _PreferredMagnetDriver
        engine._build_transport = lambda _transport, _address: NullTransport()
        engine._build_protocol = lambda _driver: OxfordProtocol()
        engine.preferred_driver_name = "PersistedMagnet"
        engine.preferred_transport_name = "Ethernet"
        engine.preferred_address = "magnet-host:7020"

        engine.connect_preferred_driver()

        assert isinstance(engine.connected_driver, _PreferredMagnetDriver)
        assert engine.connected_driver_name == "PersistedMagnet"
        assert engine.connected_transport_name == "Ethernet"
        assert engine.connected_address == "magnet-host:7020"
        engine.shutdown()

    def test_connect_preferred_driver_requires_persisted_driver_name(self, qapp):
        engine = MagnetControllerEngine()
        engine.preferred_driver_name = ""
        engine.preferred_transport_name = "Null (test)"
        engine.preferred_address = ""

        with pytest.raises(RuntimeError, match="No persisted magnet-controller driver"):
            engine.connect_preferred_driver()

        engine.shutdown()

    def test_reconnect_failure_clears_engine_state(self, qapp):
        engine = MagnetControllerEngine()
        first = _make_fake_driver()
        engine.connect_instrument(first)

        def _make_broken_driver():
            class _BrokenDriver:
                is_connected = False

                def connect(self):
                    raise RuntimeError("boom")

            return _BrokenDriver()

        with pytest.raises(RuntimeError, match="boom"):
            engine.connect_instrument(_make_broken_driver())
        assert not first.is_connected
        assert engine._driver is None
        assert engine.status == MagnetEngineStatus.DISCONNECTED
        engine.shutdown()

    def test_connect_driver_instantiates_driver_class(self, qapp):
        from stoner_measurement.instruments.oxford import OxfordIPS120
        from stoner_measurement.instruments.protocol.oxford import OxfordProtocol
        from stoner_measurement.instruments.transport import NullTransport

        engine = MagnetControllerEngine()
        engine._resolve_driver_class = lambda _name: OxfordIPS120
        engine._build_transport = (
            lambda _transport, _address: NullTransport(responses=[b"VIPS120-10 3.07\r"])
        )
        engine._build_protocol = lambda _driver: OxfordProtocol()
        engine.connect_driver("OxfordIPS120", "Null", "")
        assert engine._driver is not None
        assert isinstance(engine._driver, OxfordIPS120)
        engine.disconnect_instrument()
        engine.shutdown()

    def test_connect_driver_propagates_construction_errors(self, qapp):
        class _BrokenDriver:
            def __init__(self, transport, protocol):
                raise RuntimeError("boom")

        engine = MagnetControllerEngine()
        engine._resolve_driver_class = lambda _name: _BrokenDriver
        engine._build_transport = lambda _transport, _address: object()
        engine._build_protocol = lambda _driver: object()
        with pytest.raises(RuntimeError, match="boom"):
            engine.connect_driver("BrokenDriver", "Null", "")
        assert engine._driver is None
        engine.shutdown()

    def test_connect_driver_unknown_driver_name_raises(self, qapp):
        engine = MagnetControllerEngine()
        with pytest.raises(ValueError, match="Unknown magnet driver"):
            engine.connect_driver("NotADriver", "Null", "")
        engine.shutdown()

    def test_connect_driver_unsupported_transport_raises(self, qapp):
        from stoner_measurement.instruments.protocol.oxford import OxfordProtocol

        engine = MagnetControllerEngine()
        engine._resolve_driver_class = lambda _name: _make_fake_driver().__class__
        engine._build_protocol = lambda _driver: OxfordProtocol()
        with pytest.raises(ValueError, match="Unsupported transport type"):
            engine.connect_driver("FakeDriver", "InvalidTransport", "")
        engine.shutdown()

    def test_resolve_driver_class_rejects_non_magnet_driver(self, monkeypatch, qapp):
        from stoner_measurement.instruments.driver_manager import InstrumentDriverManager

        monkeypatch.setattr(InstrumentDriverManager, "discover", lambda self: None)
        monkeypatch.setattr(InstrumentDriverManager, "get", lambda self, _name: object)

        engine = MagnetControllerEngine()
        with pytest.raises(ValueError, match="not a magnet-controller driver"):
            engine._resolve_driver_class("object")
        engine.shutdown()

    def test_parse_serial_address_invalid_baud_message(self, qapp):
        engine = MagnetControllerEngine()
        with pytest.raises(ValueError, match="Invalid serial baud in address"):
            engine._parse_serial_address("port=/dev/ttyUSB5;baud=bad")
        engine.shutdown()

    def test_parse_ethernet_address_missing_host_uses_default(self, qapp):
        engine = MagnetControllerEngine()
        assert engine._parse_ethernet_address(":4000") == ("localhost", 4000)
        engine.shutdown()

    def test_parse_ethernet_address_port_only_uses_default_host(self, qapp):
        engine = MagnetControllerEngine()
        assert engine._parse_ethernet_address("4000") == ("localhost", 4000)
        engine.shutdown()

    def test_parse_ethernet_address_invalid_port_message(self, qapp):
        engine = MagnetControllerEngine()
        with pytest.raises(ValueError, match="Invalid Ethernet port in address"):
            engine._parse_ethernet_address("10.0.0.1:not-a-port")
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
    def test_engine_state_reports_at_target_before_stable(self, qapp):
        engine = MagnetControllerEngine()
        engine._stability_config = MagnetStabilityConfig(
            tolerance_t=0.001, window_s=60.0, min_rate=0.001
        )
        engine._target_field = 1.0

        t0 = datetime.now(tz=UTC)
        engine._history.append((t0, 1.0))
        engine._evaluate_stability(1.0, t0)

        state = engine.get_engine_state()

        assert state.at_target is True
        assert state.stable is False
        engine.shutdown()

    def test_engine_state_reports_stable_after_window(self, qapp):
        engine = MagnetControllerEngine()
        engine._stability_config = MagnetStabilityConfig(
            tolerance_t=0.001, window_s=1.0, min_rate=0.001
        )
        engine._target_field = 1.0

        t0 = datetime.now(tz=UTC)
        for i in range(5):
            engine._history.append((t0 + timedelta(seconds=i * 0.25), 1.0))

        engine._evaluate_stability(1.0, t0)
        engine._evaluate_stability(1.0, t0 + timedelta(seconds=5))

        state = engine.get_engine_state()

        assert state.at_target is True
        assert state.stable is True
        engine.shutdown()

    def test_engine_state_reports_not_at_target_when_outside_tolerance(self, qapp):
        engine = MagnetControllerEngine()
        engine._stability_config = MagnetStabilityConfig(tolerance_t=0.001)
        engine._target_field = 1.0

        t0 = datetime.now(tz=UTC)
        engine._evaluate_stability(2.0, t0)

        state = engine.get_engine_state()

        assert state.at_target is False
        assert state.stable is False
        engine.shutdown()

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

    def test_read_controller_state_returns_fresh_snapshot(self, qapp):
        engine = MagnetControllerEngine()
        driver = _make_fake_driver(field=1.5, current=12.0)
        engine.connect_instrument(driver)

        state = engine.read_controller_state()

        assert state is not None
        assert state.reading is not None
        assert state.reading.field == pytest.approx(1.5)
        assert state.reading.current == pytest.approx(12.0)
        assert state.target_field == pytest.approx(1.2)
        assert state.target_current == pytest.approx(12.0)
        assert state.ramp_rate_field == pytest.approx(0.5)
        assert state.ramp_rate_current == pytest.approx(5.0)
        engine.shutdown()

    def test_set_target_field_invalidates_cached_target_state(self, qapp):
        from stoner_measurement.instruments.magnet_controller import HeaterState, MagnetState

        engine = MagnetControllerEngine()
        driver = _make_fake_driver(field=1.0, current=10.0)
        engine.connect_instrument(driver)
        engine._is_at_target = True
        engine._stable = True
        engine._latest_state = MagnetEngineState(
            reading=MagnetReading(
                timestamp=datetime.now(tz=UTC),
                field=1.0,
                current=10.0,
                voltage=0.05,
                heater_on=True,
                heater_state=HeaterState.ON,
                state=MagnetState.AT_TARGET,
                at_target=True,
            ),
            target_field=1.0,
            at_target=True,
            stable=True,
            engine_status=MagnetEngineStatus.POLLING,
        )

        engine.set_target_field(2.0)
        state = engine.get_engine_state()

        assert state.target_field == pytest.approx(2.0)
        assert state.at_target is False
        assert state.stable is False
        assert state.reading is not None
        assert state.reading.at_target is False
        engine.shutdown()

    def test_get_limits_returns_driver_limits(self, qapp):
        engine = MagnetControllerEngine()
        driver = _make_fake_driver()
        engine.connect_instrument(driver)

        limits = engine.get_limits()

        assert limits is not None
        assert limits.max_current == pytest.approx(100.0)
        assert limits.max_field == pytest.approx(10.0)
        assert limits.max_ramp_rate == pytest.approx(1.0)
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

    def test_hide_button_hides_panel(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        panel.show()
        assert panel._btn_hide.text() == "Hide"
        assert panel.isVisible()
        panel._btn_hide.click()
        qapp.processEvents()
        assert not panel.isVisible()

    def test_has_all_tabs(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        tabs = panel._tabs
        tab_titles = [tabs.tabText(i) for i in range(tabs.count())]
        assert "Connection" in tab_titles
        assert "Configuration" in tab_titles
        assert "Chart" in tab_titles

    def test_save_button_is_on_connection_tab(self, qapp):
        from qtpy.QtWidgets import QPushButton

        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        connection_tab = panel._tabs.widget(0)
        config_tab = panel._tabs.widget(1)

        connection_labels = [btn.text() for btn in connection_tab.findChildren(QPushButton)]
        config_labels = [btn.text() for btn in config_tab.findChildren(QPushButton)]

        assert "Save Settings to YAML" in connection_labels
        assert "Save Settings to YAML" not in config_labels

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

    def test_driver_combo_filters_out_underscore_prefixed_magnet_drivers(
        self, qapp, monkeypatch
    ):
        from stoner_measurement.instruments.magnet_controller import MagnetController
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        class _VisibleMagnetDriver:
            @classmethod
            def display_name(cls):
                return "Visible Magnet Driver"

        panel = MagnetControlPanel()
        monkeypatch.setattr(
            panel._driver_manager,
            "drivers_by_type",
            lambda _cls: {
                "_HiddenMagnetDriver": MagnetController,
                "VisibleMagnetDriver": _VisibleMagnetDriver,
            },
        )

        panel._populate_driver_combo()

        items = [panel._driver_combo.itemText(i) for i in range(panel._driver_combo.count())]
        assert "Visible Magnet Driver" in items
        assert "_HiddenMagnetDriver" not in items

    def test_null_transport_connect_sets_address_status_connected(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        panel._transport_combo.setCurrentText("Null (test)")
        panel._on_connect()

        assert "background-color" in panel._null_form_widget.styleSheet()

    def test_disconnect_clears_null_transport_address_status(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        panel._set_address_widget_status(3, VisaResourceStatus.CONNECTED)
        panel._on_disconnect()
        assert panel._null_form_widget.styleSheet() == ""

    def test_apply_limits_updates_magnet_constant(self, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        panel._magnet_const_spin.setValue(0.05)
        # Engine has no driver connected — set_magnet_constant should be a no-op.
        panel._on_apply_limits()
        assert panel._magnet_constant == pytest.approx(0.05)

    def test_read_ramp_updates_ramp_rate_spin_boxes(self, monkeypatch, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        monkeypatch.setattr(
            panel._engine,
            "read_controller_state",
            lambda: MagnetEngineState(
                ramp_rate_field=0.8,
                ramp_rate_current=12.5,
            ),
        )

        panel._on_read_ramp()

        assert panel._ramp_field_spin.value() == pytest.approx(0.8)
        assert panel._ramp_current_spin.value() == pytest.approx(12.5)

    def test_state_update_shows_ramp_rate_labels_and_chart_traces(self, qapp):
        from stoner_measurement.instruments.magnet_controller import HeaterState, MagnetState
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        state = MagnetEngineState(
            reading=MagnetReading(
                timestamp=datetime.now(tz=UTC),
                field=1.0,
                current=10.0,
                voltage=0.2,
                heater_on=True,
                heater_state=HeaterState.ON,
                state=MagnetState.RAMPING,
                at_target=False,
                field_rate=0.35,
            ),
            target_field=1.5,
            target_current=15.0,
            ramp_rate_field=0.8,
            ramp_rate_current=8.0,
            magnet_constant=0.1,
            at_target=False,
            stable=False,
            engine_status=MagnetEngineStatus.POLLING,
        )

        panel._on_state_updated(state)

        assert panel._ramp_target_rate_label.text() == "0.8000 T/min (8.000 A/min)"
        assert panel._ramp_actual_rate_label.text() == "0.3500 T/min"
        assert "Field Rate" in panel._legend_items
        assert "Target Rate" in panel._legend_items
        assert panel._legend_items["Field Rate"].text(1) == "0.3500 T/min"
        assert panel._legend_items["Target Rate"].text(1) == "0.8000 T/min"

    def test_read_target_updates_target_field_spin_box(self, monkeypatch, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        monkeypatch.setattr(
            panel._engine,
            "read_controller_state",
            lambda: MagnetEngineState(
                target_field=1.75,
                magnet_constant=0.1,
            ),
        )

        panel._on_read_target()

        assert panel._target_field_spin.value() == pytest.approx(1.75)

    def test_read_heater_updates_heater_state_label(self, monkeypatch, qapp):
        from stoner_measurement.instruments.magnet_controller import HeaterState, MagnetState
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        monkeypatch.setattr(
            panel._engine,
            "read_controller_state",
            lambda: MagnetEngineState(
                reading=MagnetReading(
                    timestamp=datetime.now(tz=UTC),
                    field=1.0,
                    current=10.0,
                    voltage=0.1,
                    heater_on=False,
                    heater_state=HeaterState.OFF,
                    state=MagnetState.STANDBY,
                    at_target=False,
                ),
            ),
        )

        panel._on_read_heater()

        assert panel._heater_state_label.text() == "Off"

    def test_read_ramp_warns_when_state_unavailable(self, monkeypatch, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        monkeypatch.setattr(panel._engine, "read_controller_state", lambda: None)
        calls: list[tuple[str, str]] = []

        def _fake_warning(_parent, title, text):
            calls.append((title, text))
            return 0

        monkeypatch.setattr("stoner_measurement.ui.magnet_panel.QMessageBox.warning", _fake_warning)

        panel._on_read_ramp()

        assert calls == [("Ramp Rate", "No instrument connected or read failed.")]

    def test_read_limits_updates_limit_widgets(self, monkeypatch, qapp):
        from stoner_measurement.instruments.magnet_controller import MagnetLimits
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        panel = MagnetControlPanel()
        monkeypatch.setattr(
            panel._engine,
            "read_controller_state",
            lambda: MagnetEngineState(
                magnet_constant=0.075,
            ),
        )
        monkeypatch.setattr(
            panel._engine,
            "get_limits",
            lambda: MagnetLimits(
                max_current=88.0,
                max_field=7.5,
                max_ramp_rate=0.9,
            ),
        )

        panel._on_read_limits()

        assert panel._magnet_const_spin.value() == pytest.approx(0.075)
        assert panel._max_current_spin.value() == pytest.approx(88.0)
        assert panel._max_field_spin.value() == pytest.approx(7.5)
        assert panel._max_ramp_spin.value() == pytest.approx(0.9)

    def test_panel_restores_cached_config_settings_from_engine(self, qapp):
        from stoner_measurement.instruments.magnet_controller import MagnetLimits
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        engine = MagnetControllerEngine.instance()
        engine._target_field = 1.8  # noqa: SLF001
        engine._target_current = 18.0  # noqa: SLF001
        engine._ramp_rate_field = 0.6  # noqa: SLF001
        engine._ramp_rate_current = 6.0  # noqa: SLF001
        engine._magnet_constant = 0.1  # noqa: SLF001
        engine._limits = MagnetLimits(max_current=70.0, max_field=7.0, max_ramp_rate=0.7)  # noqa: SLF001

        panel = MagnetControlPanel()

        assert panel._target_field_spin.value() == pytest.approx(1.8)
        assert panel._target_current_spin.value() == pytest.approx(18.0)
        assert panel._ramp_field_spin.value() == pytest.approx(0.6)
        assert panel._ramp_current_spin.value() == pytest.approx(6.0)
        assert panel._magnet_const_spin.value() == pytest.approx(0.1)
        assert panel._max_current_spin.value() == pytest.approx(70.0)
        assert panel._max_field_spin.value() == pytest.approx(7.0)
        assert panel._max_ramp_spin.value() == pytest.approx(0.7)
        engine.shutdown()

    def test_save_configuration_persists_config_tab_values(self, monkeypatch, qapp):
        from stoner_measurement.ui.magnet_panel import MagnetControlPanel

        engine = MagnetControllerEngine.instance()
        panel = MagnetControlPanel()
        panel._target_field_spin.setValue(2.2)
        panel._ramp_field_spin.setValue(0.9)
        panel._magnet_constant = 0.11  # noqa: SLF001
        panel._magnet_const_spin.setValue(0.11)
        panel._max_current_spin.setValue(55.0)
        panel._max_field_spin.setValue(5.5)
        panel._max_ramp_spin.setValue(0.95)

        monkeypatch.setattr(
            "stoner_measurement.ui.magnet_panel.selected_transport",
            lambda *_args, **_kwargs: ("Ethernet", "host:1234"),
        )
        monkeypatch.setattr(
            "stoner_measurement.ui.magnet_panel.QMessageBox.information",
            lambda *_args, **_kwargs: 0,
        )

        panel._on_save_configuration()

        assert engine._target_field == pytest.approx(2.2)  # noqa: SLF001
        assert engine._target_current == pytest.approx(20.0)  # noqa: SLF001
        assert engine._ramp_rate_field == pytest.approx(0.9)  # noqa: SLF001
        assert engine._ramp_rate_current == pytest.approx(8.1818181818)  # noqa: SLF001
        assert engine._magnet_constant == pytest.approx(0.11)  # noqa: SLF001
        assert engine._limits is not None  # noqa: SLF001
        assert engine._limits.max_current == pytest.approx(55.0)  # noqa: SLF001
        assert engine._limits.max_field == pytest.approx(5.5)  # noqa: SLF001
        assert engine._limits.max_ramp_rate == pytest.approx(0.95)  # noqa: SLF001
        engine.shutdown()


class TestSimulatedMagnetControllerIntegration:
    def test_engine_reads_simulated_magnet_controller(self, qapp):
        from stoner_measurement.instruments.simulated import (
            SimulatedMagnetController,
        )

        engine = MagnetControllerEngine()
        driver = SimulatedMagnetController()

        engine.connect_instrument(driver)

        state = engine.read_controller_state()

        assert state is not None
        assert state.reading is not None
        assert state.reading.field == pytest.approx(0.0)

        engine.shutdown()

    def test_engine_observes_simulated_field_ramp(self, qapp):
        from stoner_measurement.instruments.simulated import (
            SimulatedMagnetController,
        )

        engine = MagnetControllerEngine()
        driver = SimulatedMagnetController()

        engine.connect_instrument(driver)

        engine.set_target_field(1.0)
        driver._last_update -= 20.0  # pylint: disable=protected-access

        state = engine.read_controller_state()

        assert state is not None
        assert state.reading is not None
        assert state.reading.field is not None
        assert state.reading.field > 0.0

        engine.shutdown()


if __name__ == "__main__":

    raise SystemExit(pytest.main([__file__, "--pdb"]))
