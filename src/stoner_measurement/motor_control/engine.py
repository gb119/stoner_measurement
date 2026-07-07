"""Singleton motor controller engine."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from qtpy.QtCore import QObject, QTimer

from stoner_measurement.instruments.addressing import (
    parse_ethernet_address,
    parse_serial_address,
)
from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.motor_controller import (
    MotorMoveDirection,
    resolve_relative_motor_move,
    wrap_angle_360,
)
from stoner_measurement.instruments.protocol import LakeshoreProtocol, OxfordProtocol, ScpiProtocol
from stoner_measurement.instruments.transport import (
    EthernetTransport,
    GpibTransport,
    NullTransport,
    SerialTransport,
)
from stoner_measurement.motor_control.config import (
    load_motor_controller_config,
    save_motor_controller_config,
)
from stoner_measurement.motor_control.pubsub import MotorPublisher
from stoner_measurement.motor_control.types import (
    MotorEngineState,
    MotorEngineStatus,
    MotorReading,
    MotorStabilityConfig,
)
from stoner_measurement.qt_compat import pyqtSlot

if TYPE_CHECKING:
    from stoner_measurement.instruments.motor_controller import MotorController
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport

logger = logging.getLogger(__name__)

_HISTORY_SIZE = 60
_DEFAULT_POLL_INTERVAL_MS = 250


class MotorControllerEngine(QObject):
    """Singleton engine that mediates all communication with a motor controller."""

    _singleton: MotorControllerEngine | None = None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.publisher: MotorPublisher = MotorPublisher(self)

        self._driver = None
        self._connected_driver_name: str | None = None
        self._connected_transport_name: str | None = None
        self._connected_address: str | None = None

        self._preferred_driver_name: str = ""
        self._preferred_transport_name: str = "Null (test)"
        self._preferred_address: str = ""
        self._status: MotorEngineStatus = MotorEngineStatus.DISCONNECTED
        self._stability_config: MotorStabilityConfig = MotorStabilityConfig()
        self._soft_limit: float = 190.0

        self._history: deque[tuple[datetime, float]] = deque(maxlen=_HISTORY_SIZE)
        self._is_at_target: bool = False
        self._at_target_since: datetime | None = None
        self._unstable_since: datetime | None = None
        self._stable: bool = False

        self._target_angle: float | None = None
        self._velocity: float | None = None
        self._move_direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE
        self._display_target_angle: float | None = None
        self._acceleration: float | None = None
        self._latest_state: MotorEngineState = MotorEngineState(engine_status=self._status)

        self._timer = QTimer(self)
        self._engine_lock = threading.RLock()
        self._timer.setInterval(_DEFAULT_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._apply_configuration(load_motor_controller_config())

    def _apply_configuration(self, config: dict) -> None:
        connection = config.get("connection")
        if isinstance(connection, dict):
            self._preferred_driver_name = str(connection.get("driver", ""))
            self._preferred_transport_name = str(connection.get("transport", "Null (test)"))
            self._preferred_address = str(connection.get("address", ""))

        poll_interval = config.get("poll_interval_ms")
        if isinstance(poll_interval, int):
            self.set_poll_interval(poll_interval)

        stability = config.get("stability")
        if isinstance(stability, dict):
            self.set_stability_config(
                MotorStabilityConfig(
                    tolerance_deg=float(
                        stability.get("tolerance_deg", self._stability_config.tolerance_deg)
                    ),
                    window_s=float(stability.get("window_s", self._stability_config.window_s)),
                    min_rate=float(stability.get("min_rate", self._stability_config.min_rate)),
                    unstable_holdoff_s=float(
                        stability.get(
                            "unstable_holdoff_s",
                            self._stability_config.unstable_holdoff_s,
                        )
                    ),
                )
            )

        motion = config.get("motion")
        if isinstance(motion, dict):
            velocity = motion.get("velocity_deg_s")
            if isinstance(velocity, (int, float)):
                self._velocity = float(velocity)
            acceleration = motion.get("acceleration_deg_s2")
            if isinstance(acceleration, (int, float)):
                self._acceleration = float(acceleration)
            direction_name = str(motion.get("direction", self._move_direction.value))
            try:
                self._move_direction = MotorMoveDirection(direction_name)
                if self._move_direction is MotorMoveDirection.TOWARDS_ZERO:
                    self._move_direction = MotorMoveDirection.SHORTEST
            except ValueError:
                logger.warning("Unknown saved motor move direction %r; keeping default.", direction_name)

        limits = config.get("limits")
        if isinstance(limits, dict):
            soft_limit = limits.get("soft_limit_deg")
            if isinstance(soft_limit, (int, float)):
                self._soft_limit = abs(float(soft_limit))
            else:
                clockwise_limit = limits.get("clockwise_deg", self._soft_limit)
                counterclockwise_limit = limits.get("counterclockwise_deg", self._soft_limit)
                self._soft_limit = max(abs(float(clockwise_limit)), abs(float(counterclockwise_limit)))

    @classmethod
    def instance(cls) -> MotorControllerEngine:
        """Return the singleton engine, creating it on first call."""
        if cls._singleton is None:
            cls._singleton = cls()
            app = _qapp()
            if app is not None:
                app.aboutToQuit.connect(cls._singleton.shutdown)
        return cls._singleton

    @property
    def status(self) -> MotorEngineStatus:
        """The current operational status of the engine."""
        return self._status

    def connect_instrument(self, driver: MotorController) -> None:
        """Connect to a motor controller driver and start polling."""
        with self._engine_lock:
            if self._status == MotorEngineStatus.STOPPED:
                raise RuntimeError("Engine has been shut down and cannot accept new connections.")
            self._timer.stop()
            if self._driver is not None:
                self._disconnect_driver(self._driver, log_context="before replacing motor controller")
            try:
                if not driver.is_connected:
                    driver.connect()
                else:
                    driver.confirm_identity()
            except Exception:
                self._driver = None
                self._set_status(MotorEngineStatus.DISCONNECTED)
                raise
            self._driver = driver
            self._connected_driver_name = type(driver).__name__
            self._history.clear()
            self._is_at_target = False
            self._at_target_since = None
            self._unstable_since = None
            self._stable = False
            self._set_status(MotorEngineStatus.CONNECTED)
            self._timer.start()
        logger.info("MotorControllerEngine: connected to %s", type(driver).__name__)

    def connect_driver(self, driver_name: str, transport_name: str, address: str) -> None:
        """Instantiate and connect a motor controller from identifiers."""
        driver_cls = self._resolve_driver_class(driver_name)
        transport = self._build_transport(transport_name, address)
        protocol = self._build_protocol(driver_name)
        driver = driver_cls(transport=transport, protocol=protocol)
        self.connect_instrument(driver)
        self._connected_driver_name = driver_name
        self._connected_transport_name = transport_name
        self._connected_address = address
        self.publisher.connection_changed.emit()

    def connect_preferred_driver(self) -> None:
        """Connect using the persisted preferred driver and transport settings.

        Returns immediately when a controller is already connected.

        Raises:
            RuntimeError:
                If no preferred driver has been configured.
            Exception:
                Any exception raised while constructing or connecting the
                preferred driver.
        """
        if self.connected_driver is not None:
            return
        driver_name = self.preferred_driver_name.strip()
        if not driver_name:
            raise RuntimeError("No persisted motor-controller driver is configured.")
        self.connect_driver(
            driver_name,
            self.preferred_transport_name,
            self.preferred_address,
        )

    def _resolve_driver_class(self, driver_name: str) -> type[MotorController]:
        from stoner_measurement.instruments.base_instrument import BaseInstrument

        manager = InstrumentDriverManager()
        manager.discover()
        driver_cls = manager.get(driver_name)
        if driver_cls is None:
            raise ValueError(f"Unknown motor driver: {driver_name!r}")
        if not issubclass(driver_cls, BaseInstrument):
            raise ValueError(f"Driver {driver_name!r} is not an instrument driver")
        required_methods = (
            "set_velocity",
            "set_acceleration",
            "move_to_angle",
            "move_home",
            "set_home",
        )
        if any(not hasattr(driver_cls, method_name) for method_name in required_methods):
            raise ValueError(f"Driver {driver_name!r} is not a motor-controller driver")
        return driver_cls

    def _build_transport(self, transport_name: str, address: str) -> BaseTransport:
        kind = transport_name.strip().lower()
        if kind == "serial":
            port, baud = parse_serial_address(address)
            return SerialTransport(port=port, baud_rate=baud)
        if kind == "gpib":
            resource = address.strip() or "GPIB0::1::INSTR"
            return GpibTransport.from_resource_string(resource)
        if kind == "ethernet":
            host, port = parse_ethernet_address(address)
            return EthernetTransport(host=host, port=port)
        if kind in {"null", "null (test)"}:
            return NullTransport()
        raise ValueError(f"Unsupported transport type: {transport_name!r}")

    def _build_protocol(self, driver_name: str) -> BaseProtocol:
        name = driver_name.lower()
        if "oxford" in name:
            return OxfordProtocol()
        if "lakeshore" in name:
            return LakeshoreProtocol()
        return ScpiProtocol()

    def disconnect_instrument(self) -> None:
        """Stop polling and release the driver reference."""
        self._timer.stop()
        with self._engine_lock:
            if self._driver is not None:
                self._disconnect_driver(self._driver, log_context="on disconnect")
            self._driver = None
            self._connected_driver_name = None
            self._connected_transport_name = None
            self._connected_address = None
            self._history.clear()
            self._is_at_target = False
            self._at_target_since = None
            self._unstable_since = None
            self._stable = False
            self._set_status(MotorEngineStatus.DISCONNECTED)
            self._latest_state = MotorEngineState(
                target_angle=self._target_angle,
                displayed_angle=wrap_angle_360(self._target_angle) if self._target_angle is not None else None,
                move_direction=self._move_direction.value,
                velocity=self._velocity,
                acceleration=self._acceleration,
                engine_status=self._status,
            )
        self.publisher.connection_changed.emit()
        logger.info("MotorControllerEngine: disconnected.")

    @property
    def connected_driver(self) -> MotorController | None:
        """Return the currently connected motor-controller driver, if any."""
        return self._driver

    @property
    def connected_driver_name(self) -> str | None:
        """Return the name of the connected driver class, if any."""
        return self._connected_driver_name

    @property
    def connected_transport_name(self) -> str | None:
        """Return the name of the connected transport, if known."""
        return self._connected_transport_name

    @property
    def connected_address(self) -> str | None:
        """Return the connected instrument address string, if known."""
        return self._connected_address

    @property
    def preferred_driver_name(self) -> str:
        """Return the saved preferred driver name."""
        return self._preferred_driver_name

    @preferred_driver_name.setter
    def preferred_driver_name(self, value: str) -> None:
        """Set the preferred driver name to persist in configuration."""
        self._preferred_driver_name = value

    @property
    def preferred_transport_name(self) -> str:
        """Return the saved preferred transport name."""
        return self._preferred_transport_name

    @preferred_transport_name.setter
    def preferred_transport_name(self, value: str) -> None:
        """Set the preferred transport name to persist in configuration."""
        self._preferred_transport_name = value

    @property
    def preferred_address(self) -> str:
        """Return the saved preferred address string."""
        return self._preferred_address

    @preferred_address.setter
    def preferred_address(self, value: str) -> None:
        """Set the preferred address string to persist in configuration."""
        self._preferred_address = value

    def configuration_dict(self) -> dict:
        """Return the current engine configuration as a serialisable mapping."""
        return {
            "poll_interval_ms": self._timer.interval(),
            "connection": {
                "driver": self._preferred_driver_name,
                "transport": self._preferred_transport_name,
                "address": self._preferred_address,
            },
            "motion": {
                "velocity_deg_s": self._velocity,
                "acceleration_deg_s2": self._acceleration,
                "direction": self._move_direction.value,
            },
            "limits": {
                "soft_limit_deg": self._soft_limit,
            },
            "stability": {
                "tolerance_deg": self._stability_config.tolerance_deg,
                "window_s": self._stability_config.window_s,
                "min_rate": self._stability_config.min_rate,
                "unstable_holdoff_s": self._stability_config.unstable_holdoff_s,
            },
        }

    def save_configuration(self):
        """Persist the current engine configuration to the user config file."""
        return save_motor_controller_config(self.configuration_dict())

    def set_velocity(self, velocity: float) -> None:
        """Apply a travel velocity to the connected controller, if any."""
        with self._engine_lock:
            if self._driver is None:
                return
            self._velocity = float(velocity)
            value = self._velocity
            try:
                self._driver.set_velocity(value)
            except Exception:
                logger.exception("Failed to set motor velocity to %s deg/s", velocity)

    def set_acceleration(self, acceleration: float) -> None:
        """Apply a travel acceleration to the connected controller, if any."""
        with self._engine_lock:
            if self._driver is None:
                return
            self._acceleration = float(acceleration)
            value = self._acceleration
            try:
                self._driver.set_acceleration(value)
            except Exception:
                logger.exception("Failed to set motor acceleration to %s deg/s²", acceleration)

    def move_to_angle(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
        *,
        force: bool = False,
    ) -> None:
        """Command the connected controller to move to an angle via a relative move."""
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                current_angle = float(self._driver.get_position())
                plan = resolve_relative_motor_move(
                    current_angle,
                    float(angle),
                    direction,
                    soft_limit=self._soft_limit,
                    force=force,
                )
                self._driver.move_relative(plan.relative_angle, direction=plan.direction)
                self._target_angle = plan.target_angle
                self._display_target_angle = wrap_angle_360(plan.target_angle)
                self._move_direction = plan.direction
                self._mark_target_pending()
            except Exception:
                logger.exception("Failed to move motor to %s deg with direction %s", angle, direction.value)
                raise

    def set_home(self, angle: float = 0.0) -> None:
        """Set the current position reference as the motor home angle."""
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                self._driver.set_home(float(angle))
            except Exception:
                logger.exception("Failed to set motor home to %s deg", angle)

    def move_home(self) -> None:
        """Command the connected controller to move to its home position."""
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                self._driver.move_home()
                self._target_angle = 0.0
                self._display_target_angle = 0.0
                self._mark_target_pending()
            except Exception:
                logger.exception("Failed to move motor home")

    def set_stability_config(self, config: MotorStabilityConfig) -> None:
        """Replace the current at-target stability configuration."""
        self._stability_config = config
        self._at_target_since = None
        self._unstable_since = None
        self._stable = False

    def set_poll_interval(self, ms: int) -> None:
        """Set the polling interval in milliseconds."""
        ms = max(50, ms)
        self._timer.setInterval(ms)

    def read_controller_state(self) -> MotorEngineState | None:
        """Poll the controller once and publish the resulting engine state."""
        with self._engine_lock:
            if self._driver is None:
                return None
            try:
                state = self._build_state()
            except Exception:
                logger.exception("MotorControllerEngine: read-state error")
                self._set_status(MotorEngineStatus.ERROR)
                return None

            self._set_status(MotorEngineStatus.POLLING)
            self._latest_state = state
            self.publisher.reading_updated.emit(state.reading)
            self.publisher.state_updated.emit(state)
            self.publisher.poll_activity.emit()
        return state

    def get_engine_state(self) -> MotorEngineState:
        """Return the latest cached engine state snapshot."""
        return replace(
            self._latest_state,
            target_angle=self._target_angle,
            displayed_angle=wrap_angle_360(self._target_angle) if self._target_angle is not None else None,
            move_direction=self._move_direction.value,
            velocity=self._velocity,
            acceleration=self._acceleration,
            at_target=self._is_at_target,
            stable=self._stable,
            engine_status=self._status,
        )

    @pyqtSlot()
    def shutdown(self) -> None:
        """Stop polling, disconnect the controller, and release the singleton."""
        self._timer.stop()
        with self._engine_lock:
            if self._driver is not None:
                self._disconnect_driver(self._driver, log_context="on shutdown")
            self._driver = None
            self._connected_driver_name = None
            self._connected_transport_name = None
            self._connected_address = None
            self._set_status(MotorEngineStatus.STOPPED)
            self._latest_state = MotorEngineState(
                target_angle=self._target_angle,
                displayed_angle=wrap_angle_360(self._target_angle) if self._target_angle is not None else None,
                move_direction=self._move_direction.value,
                velocity=self._velocity,
                acceleration=self._acceleration,
                engine_status=self._status,
            )
        if MotorControllerEngine._singleton is self:
            MotorControllerEngine._singleton = None
        logger.info("MotorControllerEngine: shut down.")

    def _disconnect_driver(self, driver: MotorController, *, log_context: str) -> None:
        try:
            if driver.is_connected:
                try:
                    driver.return_to_local()
                except Exception:
                    logger.debug("Motor controller did not support return_to_local %s", log_context)
                if driver.is_connected:
                    driver.disconnect()
        except Exception:
            logger.exception("Error while disconnecting motor controller %s", log_context)

    @pyqtSlot()
    def _poll(self) -> None:
        self.read_controller_state()

    def _build_state(self) -> MotorEngineState:
        driver = self._driver
        status = driver.status
        now = datetime.now(tz=UTC)

        angle_val = float(status.current_angle)
        displayed_angle = wrap_angle_360(angle_val)
        self._history.append((now, angle_val))
        angular_rate = _compute_rate(self._history)

        target_angle = status.target_angle if status.target_angle is not None else self._target_angle
        displayed_target = (
            wrap_angle_360(target_angle)
            if target_angle is not None
            else self._display_target_angle
        )
        self._evaluate_stability(angle_val, target_angle, bool(status.moving), now)

        reading = MotorReading(
            timestamp=now,
            angle=angle_val,
            target_angle=displayed_target,
            moving=bool(status.moving),
            homed=status.homed,
            displayed_angle=displayed_angle,
            angular_rate=angular_rate,
            at_target=self._is_at_target,
            revolutions=int(angle_val // 360.0),
            target_revolutions=int(target_angle // 360.0) if target_angle is not None else None,
            move_direction=self._move_direction.value,
        )

        return MotorEngineState(
            reading=reading,
            target_angle=target_angle,
            displayed_angle=displayed_angle,
            velocity=self._velocity,
            acceleration=self._acceleration,
            at_target=self._is_at_target,
            stable=self._stable,
            engine_status=MotorEngineStatus.POLLING,
            revolutions=int(angle_val // 360.0),
            move_direction=self._move_direction.value,
        )

    def _evaluate_stability(
        self,
        angle: float,
        target_angle: float | None,
        moving: bool,
        now: datetime,
    ) -> None:
        cfg = self._stability_config
        if target_angle is None:
            self._is_at_target = False
            self._at_target_since = None
            self._try_clear_stable(now, cfg)
            return

        currently_at = (not moving) and abs(angle - target_angle) < cfg.tolerance_deg
        self._is_at_target = currently_at
        angular_rate = _compute_rate(self._history)

        if currently_at:
            if self._at_target_since is None:
                self._at_target_since = now
            elapsed = (now - self._at_target_since).total_seconds()
            rate_ok = abs(angular_rate) < cfg.min_rate
            if elapsed >= cfg.window_s and rate_ok:
                self._unstable_since = None
                self._stable = True
            else:
                self._try_clear_stable(now, cfg)
        else:
            self._at_target_since = None
            self._try_clear_stable(now, cfg)

    def _try_clear_stable(self, now: datetime, cfg: MotorStabilityConfig) -> None:
        if not self._stable:
            return
        if self._unstable_since is None:
            self._unstable_since = now
        holdoff_elapsed = (now - self._unstable_since).total_seconds() >= cfg.unstable_holdoff_s
        if holdoff_elapsed:
            self._stable = False

    def _mark_target_pending(self) -> None:
        """Invalidate cached target/stability flags after a move command."""
        self._is_at_target = False
        self._at_target_since = None
        self._unstable_since = None
        self._stable = False
        reading = self._latest_state.reading
        if reading is not None:
            reading = replace(reading, at_target=False)
        self._latest_state = replace(
            self._latest_state,
            reading=reading,
            target_angle=self._target_angle,
            displayed_angle=wrap_angle_360(self._target_angle) if self._target_angle is not None else None,
            at_target=False,
            stable=False,
        )

    def _set_status(self, status: MotorEngineStatus) -> None:
        if status != self._status:
            self._status = status
            self._latest_state = replace(self._latest_state, engine_status=status)
            self.publisher.engine_status_changed.emit(status)


def _qapp():
    try:
        from qtpy.QtWidgets import QApplication

        return QApplication.instance()
    except (ImportError, RuntimeError):
        return None


def _compute_rate(history: deque[tuple[datetime, float]]) -> float:
    if len(history) < 2:
        return 0.0

    t0, _ = history[0]
    xs = []
    ys = []
    for ts, val in history:
        dt = (ts - t0).total_seconds()
        xs.append(dt)
        ys.append(val)

    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0.0:
        return 0.0
    slope_per_second = (n * sum_xy - sum_x * sum_y) / denom
    return slope_per_second
