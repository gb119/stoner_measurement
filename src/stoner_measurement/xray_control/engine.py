"""Singleton process/controller for the legacy X-ray diffractometer."""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from qtpy.QtCore import QObject, QTimer

from stoner_measurement.instruments.transport import FtdiD2xxTransport
from stoner_measurement.instruments.xray import (
    AxisMechanics,
    DiffractometerMechanics,
    LegacyXrayDiffractometer,
    LegacyXrayProtocol,
    SimulatedXrayDiffractometer,
    XrayOperationCancelled,
)
from stoner_measurement.instruments.xray_diffractometer import XrayDiffractometer
from stoner_measurement.qt_compat import pyqtSlot
from stoner_measurement.xray_control.config import (
    load_xray_controller_config,
    save_xray_controller_config,
)
from stoner_measurement.xray_control.pubsub import XrayPublisher
from stoner_measurement.xray_control.types import (
    XrayConnectionInfo,
    XrayEngineState,
    XrayEngineStatus,
    XrayMotionMode,
)

if TYPE_CHECKING:
    from stoner_measurement.instruments.xray import XraySnapshot

logger = logging.getLogger(__name__)


class XrayControllerEngine(QObject):
    """Own the driver, polling timer and cancellable background operations."""

    _singleton: XrayControllerEngine | None = None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.publisher = XrayPublisher(self)
        self._driver: XrayDiffractometer | None = None
        self._status = XrayEngineStatus.DISCONNECTED
        self._connection = XrayConnectionInfo()
        self._engine_lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._operation_thread: threading.Thread | None = None
        self._polling_rate_hz = 1.0
        self._preferred_instrument_name = "Wharfdale"
        self._preferred_address = "index:0"
        self._timeout_s = 2.0
        self._motion_mode = XrayMotionMode.COUPLED
        self._speed_deg_per_min = 1.0
        self._two_theta_offset_deg = 0.0
        self._count_duration_s = 1.0
        self._mechanics = DiffractometerMechanics.recovered_site_defaults()
        self._latest_state = XrayEngineState()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._apply_configuration(load_xray_controller_config())

    @classmethod
    def instance(cls) -> XrayControllerEngine:
        if cls._singleton is None:
            cls._singleton = cls()
            app = _qapp()
            if app is not None:
                app.aboutToQuit.connect(cls._singleton.shutdown)
        return cls._singleton

    @property
    def status(self) -> XrayEngineStatus:
        return self._status

    @property
    def connected_driver(self) -> XrayDiffractometer | None:
        return self._driver

    @property
    def connection_info(self) -> XrayConnectionInfo:
        return self._connection

    @property
    def preferred_transport_name(self) -> str:
        """Compatibility alias for the selected instrument name."""
        return self._preferred_instrument_name

    @property
    def preferred_instrument_name(self) -> str:
        return self._preferred_instrument_name

    @property
    def preferred_address(self) -> str:
        return self._preferred_address

    @property
    def mechanics(self) -> DiffractometerMechanics:
        return self._mechanics

    @property
    def polling_rate_hz(self) -> float:
        """Polling rate in hertz; zero disables automatic polling."""
        return self._polling_rate_hz

    @property
    def count_duration_s(self) -> float:
        """Configured detector acquisition time in seconds."""
        return self._count_duration_s

    @pyqtSlot(float)
    def set_count_duration(self, duration_s: float) -> None:
        """Set the detector acquisition time used by :meth:`count`."""
        duration_s = float(duration_s)
        if not math.isfinite(duration_s) or duration_s <= 0.0:
            raise ValueError("Count duration must be a positive finite value.")
        if math.isclose(duration_s, self._count_duration_s, rel_tol=0.0, abs_tol=1e-12):
            return
        self._count_duration_s = duration_s
        self.publisher.count_duration_changed.emit(duration_s)

    def set_poll_interval(self, ms: int) -> None:
        """Set the polling interval in milliseconds."""
        ms = max(100, int(ms))
        self.set_polling_rate(min(10.0, 1000.0 / ms))

    def set_polling_rate(self, rate_hz: float) -> None:
        """Set automatic polling from 0 to 10 Hz."""
        rate_hz = min(10.0, max(0.0, float(rate_hz)))
        self._polling_rate_hz = rate_hz
        if rate_hz == 0.0:
            self._timer.stop()
            if self._driver is not None and self._status not in {
                XrayEngineStatus.MOVING,
                XrayEngineStatus.COUNTING,
            }:
                self._set_status(XrayEngineStatus.CONNECTED)
            return
        self._timer.setInterval(round(1000.0 / rate_hz))
        if self._driver is not None and self._status is not XrayEngineStatus.STOPPED:
            self._timer.start()

    def connect_driver(self, instrument_name: str, address: str) -> None:
        """Construct the selected instrument and verify a snapshot."""
        instrument_name = _normalise_instrument_name(instrument_name)
        kind = instrument_name.casefold()
        if kind in {"simulated", "simulation"}:
            driver = SimulatedXrayDiffractometer(mechanics=self._mechanics, realtime=True)
            self.connect_instrument(driver)
            self._connection = XrayConnectionInfo(instrument_name, "")
            self._preferred_instrument_name = instrument_name
            self._preferred_address = ""
            self.publisher.connection_changed.emit()
            return
        if kind == "wharfdale":
            selector = _parse_d2xx_selector(address)
            transport = FtdiD2xxTransport(selector, timeout=self._timeout_s)
        else:
            raise ValueError(f"Unsupported X-ray instrument {instrument_name!r}.")
        driver = LegacyXrayDiffractometer(
            transport=transport,
            protocol=LegacyXrayProtocol(),
            mechanics=self._mechanics,
        )
        self.connect_instrument(driver)
        self._connection = XrayConnectionInfo(instrument_name, address)
        self._preferred_instrument_name = instrument_name
        self._preferred_address = address
        self.publisher.connection_changed.emit()

    def connect_preferred_driver(self) -> None:
        """Connect using the persisted FTDI or simulated transport selection."""
        if self._driver is not None:
            return
        self.connect_driver(self._preferred_instrument_name, self._preferred_address)

    def connect_instrument(self, driver: XrayDiffractometer) -> None:
        """Connect an injected driver and begin periodic snapshot polling."""
        with self._engine_lock:
            if self._status is XrayEngineStatus.STOPPED:
                raise RuntimeError("The X-ray engine has been shut down.")
            self.disconnect_instrument()
            try:
                if not driver.is_connected:
                    driver.connect()
                snapshot = driver.read_snapshot()
            except Exception:
                if driver.is_connected:
                    driver.disconnect()
                self._set_status(XrayEngineStatus.ERROR)
                raise
            self._driver = driver
            driver.set_progress_callback(self._on_driver_progress)
            self._mechanics = driver.mechanics
            self._latest_state = self._state_from_snapshot(snapshot)
            self._set_status(XrayEngineStatus.CONNECTED)
            self._start_timer()
        self.publisher.state_updated.emit(self._latest_state)

    def disconnect_instrument(self) -> None:
        self.cancel_operation()
        thread = self._operation_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(2.0, self._timeout_s + 0.5))
        self._timer.stop()
        with self._engine_lock:
            driver = self._driver
            self._driver = None
            if driver is not None:
                driver.set_progress_callback(None)
            if driver is not None and driver.is_connected:
                driver.disconnect()
            self._connection = XrayConnectionInfo()
            if self._status is not XrayEngineStatus.STOPPED:
                self._set_status(XrayEngineStatus.DISCONNECTED)
            self._latest_state = replace(self._latest_state, engine_status=self._status)
        self.publisher.connection_changed.emit()

    def read_controller_state(self) -> XrayEngineState | None:
        driver = self._driver
        if driver is None or self._operation_active():
            return None
        try:
            snapshot = driver.read_snapshot()
        except Exception as exc:
            self._set_status(XrayEngineStatus.ERROR)
            self.publisher.operation_failed.emit(str(exc))
            logger.exception("Unable to poll the X-ray controller")
            return None
        self._latest_state = self._state_from_snapshot(snapshot)
        self._set_status(XrayEngineStatus.POLLING)
        self.publisher.poll_activity.emit()
        self.publisher.state_updated.emit(self._latest_state)
        return self._latest_state

    def get_engine_state(self) -> XrayEngineState:
        return self._latest_state

    def move_to(
        self,
        target_deg: float,
        mode: XrayMotionMode | None = None,
        *,
        speed_deg_per_min: float | None = None,
    ) -> XrayEngineState:
        """Synchronously execute one of the three supported motion modes."""
        driver = self._require_driver()
        selected = mode or self._motion_mode
        speed = speed_deg_per_min or self._speed_deg_per_min
        self._cancel_event.clear()
        self._set_status(XrayEngineStatus.MOVING)
        self._latest_state = replace(
            self._latest_state,
            target_deg=float(target_deg),
            theta_target_deg=(
                float(target_deg)
                if selected is not XrayMotionMode.TWO_THETA
                else self._snapshot_angle("theta")
            ),
            two_theta_target_deg=(
                float(target_deg)
                if selected is XrayMotionMode.TWO_THETA
                else (
                    2.0 * float(target_deg) + self._two_theta_offset_deg
                    if selected is XrayMotionMode.COUPLED
                    else self._snapshot_angle("two_theta")
                )
            ),
            theta_speed_deg_per_min=(speed if selected is not XrayMotionMode.TWO_THETA else 0.0),
            two_theta_speed_deg_per_min=(
                2.0 * speed
                if selected is XrayMotionMode.COUPLED
                else (speed if selected is XrayMotionMode.TWO_THETA else 0.0)
            ),
            moving=True,
            at_target=False,
            motion_mode=selected,
            engine_status=self._status,
        )
        self.publisher.state_updated.emit(self._latest_state)
        try:
            if selected is XrayMotionMode.THETA:
                snapshot = driver.move_theta(target_deg, speed, cancel=self._cancel_event)
            elif selected is XrayMotionMode.TWO_THETA:
                snapshot = driver.move_two_theta(target_deg, speed, cancel=self._cancel_event)
            else:
                snapshot = driver.move_coupled(
                    target_deg,
                    speed,
                    two_theta_offset_deg=self._two_theta_offset_deg,
                    cancel=self._cancel_event,
                )
        except XrayOperationCancelled:
            self._latest_state = replace(self._latest_state, moving=False, at_target=False)
            self._set_status(XrayEngineStatus.POLLING)
            raise
        except Exception:
            self._latest_state = replace(self._latest_state, moving=False, at_target=False)
            self._set_status(XrayEngineStatus.ERROR)
            raise
        self._latest_state = replace(
            self._state_from_snapshot(snapshot), moving=False, at_target=True
        )
        self._set_status(XrayEngineStatus.POLLING)
        self.publisher.state_updated.emit(self._latest_state)
        return self._latest_state

    def count(self, duration_s: float | None = None) -> XrayEngineState:
        """Synchronously acquire detector counts for a host-timed interval."""
        driver = self._require_driver()
        self._cancel_event.clear()
        self._set_status(XrayEngineStatus.COUNTING)
        try:
            result = driver.count(
                self._count_duration_s if duration_s is None else duration_s,
                cancel=self._cancel_event,
            )
        except XrayOperationCancelled:
            self._set_status(XrayEngineStatus.POLLING)
            raise
        except Exception:
            self._set_status(XrayEngineStatus.ERROR)
            raise
        self._latest_state = replace(
            self._state_from_snapshot(result.snapshot),
            count_rate_hz=result.count_rate_hz,
            count_elapsed_s=result.elapsed_s,
        )
        self._set_status(XrayEngineStatus.POLLING)
        self.publisher.state_updated.emit(self._latest_state)
        return self._latest_state

    def start_move(
        self,
        target_deg: float,
        mode: XrayMotionMode | None = None,
        *,
        speed_deg_per_min: float | None = None,
    ) -> None:
        self._start_operation(
            lambda: self.move_to(target_deg, mode, speed_deg_per_min=speed_deg_per_min),
            "X-ray motion",
        )

    def start_count(self, duration_s: float | None = None) -> None:
        self._start_operation(lambda: self.count(duration_s), "X-ray count")

    def cancel_operation(self) -> None:
        self._cancel_event.set()

    def zero_theta(self) -> None:
        self._require_driver().zero_theta()
        self.read_controller_state()

    def zero_two_theta(self) -> None:
        self._require_driver().zero_two_theta()
        self.read_controller_state()

    def reset_limit_latch(self) -> None:
        self._require_driver().reset_limit_latch()

    def disable_motors(self) -> None:
        driver = self._require_driver()
        driver.disable_theta()
        driver.disable_two_theta()

    def configure_motion(
        self,
        *,
        enabled: bool,
        mode: XrayMotionMode,
        speed_deg_per_min: float,
        two_theta_offset_deg: float,
    ) -> None:
        if speed_deg_per_min <= 0.0:
            raise ValueError("Motion speed must be positive.")
        self._motion_mode = mode
        self._speed_deg_per_min = float(speed_deg_per_min)
        self._two_theta_offset_deg = float(two_theta_offset_deg)
        self._mechanics = replace(self._mechanics, motion_enabled=bool(enabled))
        if self._driver is not None:
            self._driver.mechanics = self._mechanics
        self._latest_state = replace(
            self._latest_state,
            motion_mode=mode,
            speed_deg_per_min=self._speed_deg_per_min,
            two_theta_offset_deg=self._two_theta_offset_deg,
            motion_enabled=bool(enabled),
        )

    def configuration_dict(self) -> dict:
        return {
            "connection": {
                "instrument": self._preferred_instrument_name,
                "address": self._preferred_address,
                "timeout_s": self._timeout_s,
            },
            "polling_rate_hz": self._polling_rate_hz,
            "motion": {
                "enabled": self._mechanics.motion_enabled,
                "mode": self._motion_mode.value,
                "speed_deg_per_min": self._speed_deg_per_min,
                "two_theta_offset_deg": self._two_theta_offset_deg,
                "theta": _axis_config(self._mechanics.theta),
                "two_theta": _axis_config(self._mechanics.two_theta),
            },
            "count": {"duration_s": self._count_duration_s},
        }

    def save_configuration(self):
        return save_xray_controller_config(self.configuration_dict())

    @pyqtSlot()
    def shutdown(self) -> None:
        if self._status is XrayEngineStatus.STOPPED:
            return
        self.cancel_operation()
        thread = self._operation_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self.disconnect_instrument()
        self._set_status(XrayEngineStatus.STOPPED)

    @pyqtSlot()
    def _poll(self) -> None:
        self.read_controller_state()

    def _start_operation(self, operation, label: str) -> None:
        if self._operation_active():
            raise RuntimeError("An X-ray operation is already running.")

        def run() -> None:
            try:
                operation()
            except XrayOperationCancelled:
                logger.info("%s cancelled.", label)
            except Exception as exc:  # noqa: BLE001 - delivered to the Qt UI
                logger.exception("%s failed", label)
                self.publisher.operation_failed.emit(str(exc))
            finally:
                self.publisher.operation_finished.emit()

        self._cancel_event.clear()
        self._operation_thread = threading.Thread(target=run, name=label, daemon=True)
        self._operation_thread.start()

    def _operation_active(self) -> bool:
        return self._operation_thread is not None and self._operation_thread.is_alive()

    def _require_driver(self) -> XrayDiffractometer:
        if self._driver is None:
            raise RuntimeError("No X-ray diffractometer is connected.")
        return self._driver

    def _state_from_snapshot(self, snapshot: XraySnapshot) -> XrayEngineState:
        return replace(
            self._latest_state,
            snapshot=snapshot,
            updated_at=datetime.now(tz=UTC),
            motion_mode=self._motion_mode,
            two_theta_offset_deg=self._two_theta_offset_deg,
            speed_deg_per_min=self._speed_deg_per_min,
            motion_enabled=self._mechanics.motion_enabled,
            engine_status=self._status,
        )

    def _on_driver_progress(self, snapshot: XraySnapshot) -> None:
        """Publish intermediate positions supplied by a moving driver."""
        self._latest_state = replace(
            self._state_from_snapshot(snapshot), moving=True, at_target=False
        )
        self.publisher.state_updated.emit(self._latest_state)

    def _snapshot_angle(self, axis: str) -> float | None:
        snapshot = self._latest_state.snapshot
        if snapshot is None:
            return None
        return snapshot.theta_deg if axis == "theta" else snapshot.two_theta_deg

    def _set_status(self, status: XrayEngineStatus) -> None:
        if status is self._status:
            return
        self._status = status
        self._latest_state = replace(self._latest_state, engine_status=status)
        self.publisher.engine_status_changed.emit(status)

    def _start_timer(self) -> None:
        if self._polling_rate_hz > 0.0:
            self._timer.start(max(1, round(1000.0 / self._polling_rate_hz)))

    def _apply_configuration(self, config: dict) -> None:
        connection = config.get("connection", {})
        selected = connection.get("instrument", connection.get("transport", "Wharfdale"))
        self._preferred_instrument_name = _normalise_instrument_name(str(selected))
        self._preferred_address = str(connection.get("address", "index:0"))
        self._timeout_s = float(connection.get("timeout_s", 2.0))
        self._polling_rate_hz = max(0.0, float(config.get("polling_rate_hz", 1.0)))
        motion = config.get("motion", {})
        theta = motion.get("theta", {})
        two_theta = motion.get("two_theta", {})
        self._mechanics = DiffractometerMechanics(
            theta=AxisMechanics(
                400,
                float(theta.get("minimum_deg", -90.0)),
                float(theta.get("maximum_deg", 90.0)),
                int(theta.get("backlash_steps", 100)),
            ),
            two_theta=AxisMechanics(
                200,
                float(two_theta.get("minimum_deg", -30.0)),
                float(two_theta.get("maximum_deg", 90.0)),
                int(two_theta.get("backlash_steps", 50)),
            ),
            motion_enabled=bool(motion.get("enabled", False)),
        )
        try:
            self._motion_mode = XrayMotionMode(str(motion.get("mode", "theta-2theta")))
        except ValueError:
            self._motion_mode = XrayMotionMode.COUPLED
        self._speed_deg_per_min = float(motion.get("speed_deg_per_min", 1.0))
        self._two_theta_offset_deg = float(motion.get("two_theta_offset_deg", 0.0))
        self._count_duration_s = float(config.get("count", {}).get("duration_s", 1.0))
        self._latest_state = XrayEngineState(
            motion_mode=self._motion_mode,
            two_theta_offset_deg=self._two_theta_offset_deg,
            speed_deg_per_min=self._speed_deg_per_min,
            motion_enabled=self._mechanics.motion_enabled,
            engine_status=self._status,
        )


def _parse_d2xx_selector(address: str) -> int | str:
    value = address.strip()
    if value.casefold().startswith("index:"):
        return int(value.split(":", 1)[1])
    if value.casefold().startswith("serial:"):
        serial = value.split(":", 1)[1].strip()
        if not serial:
            raise ValueError("An FTDI serial number is required after 'serial:'.")
        return serial
    if value.isdigit() or not value:
        return int(value or "0")
    return value


def _normalise_instrument_name(name: str) -> str:
    """Map legacy transport labels onto the two user-facing instruments."""
    kind = name.strip().casefold()
    if kind in {"simulated", "simulation"}:
        return "Simulated"
    if kind in {"wharfdale", "ftdi d2xx", "d2xx"}:
        return "Wharfdale"
    return name.strip()


def _axis_config(axis: AxisMechanics) -> dict:
    return {
        "minimum_deg": axis.minimum_deg,
        "maximum_deg": axis.maximum_deg,
        "backlash_steps": axis.backlash_steps,
    }


def _qapp():
    try:
        from qtpy.QtWidgets import QApplication

        return QApplication.instance()
    except (ImportError, RuntimeError):
        return None
