"""Singleton magnet controller engine.

Provides :class:`MagnetControllerEngine`, a singleton
:class:`~PyQt6.QtCore.QObject` that owns all hardware communication with a
:class:`~stoner_measurement.instruments.magnet_controller.MagnetController`
driver.  The engine runs a polling :class:`~PyQt6.QtCore.QTimer`, calculates
derived quantities (field rate of change, at-target stability), and publishes
results via a :class:`~stoner_measurement.magnet_control.pubsub.MagnetPublisher`.

UI panels and sequence plugins interact with the engine through its public
command API; they never talk to instrument drivers directly.
"""

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
from stoner_measurement.instruments.magnet_controller import MagnetLimits, MagnetState
from stoner_measurement.instruments.protocol import LakeshoreProtocol, OxfordProtocol
from stoner_measurement.instruments.transport import (
    EthernetTransport,
    GpibTransport,
    NullTransport,
    SerialTransport,
)
from stoner_measurement.magnet_control.config import (
    load_magnet_controller_config,
    save_magnet_controller_config,
)
from stoner_measurement.magnet_control.pubsub import MagnetPublisher
from stoner_measurement.magnet_control.types import (
    MagnetEngineState,
    MagnetEngineStatus,
    MagnetReading,
    MagnetStabilityConfig,
)
from stoner_measurement.qt_compat import pyqtSlot

if TYPE_CHECKING:
    from stoner_measurement.instruments.magnet_controller import (
        MagnetController,
    )
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport

logger = logging.getLogger(__name__)

#: Number of timestamped field readings kept for rate-of-change estimation.
_HISTORY_SIZE = 60

#: Default polling interval in milliseconds.
_DEFAULT_POLL_INTERVAL_MS = 1000


class MagnetControllerEngine(QObject):
    """Singleton engine that mediates all communication with a magnet controller.

    The engine owns the hardware driver reference and a polling
    :class:`~PyQt6.QtCore.QTimer` that queries the instrument, computes
    derived quantities, and publishes results via its :attr:`publisher`.  It
    persists for the lifetime of the application and continues polling when
    the UI panel is closed.

    Obtain the singleton instance via :meth:`instance`.  Destroy it by calling
    :meth:`shutdown` (also called automatically on
    :attr:`~PyQt6.QtWidgets.QApplication.aboutToQuit`).

    Attributes:
        publisher (MagnetPublisher):
            The pub/sub bus; connect to its signals to receive live data.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.magnet_control.engine import MagnetControllerEngine
        >>> engine = MagnetControllerEngine.instance()
        >>> engine is MagnetControllerEngine.instance()
        True
        >>> from stoner_measurement.magnet_control.types import MagnetEngineStatus
        >>> engine.status
        <MagnetEngineStatus.DISCONNECTED: 'disconnected'>
        >>> engine.shutdown()
        >>> engine.status
        <MagnetEngineStatus.STOPPED: 'stopped'>
    """

    _singleton: MagnetControllerEngine | None = None

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the engine.

        Args:
            parent (QObject | None):
                Optional Qt parent.
        """
        super().__init__(parent)

        self.publisher: MagnetPublisher = MagnetPublisher(self)

        self._driver = None  # MagnetController | None
        self._connected_driver_name: str | None = None
        self._connected_transport_name: str | None = None
        self._connected_address: str | None = None

        self._preferred_driver_name: str = ""
        self._preferred_transport_name: str = "Null (test)"
        self._preferred_address: str = ""
        self._status: MagnetEngineStatus = MagnetEngineStatus.DISCONNECTED
        self._stability_config: MagnetStabilityConfig = MagnetStabilityConfig()

        # Rolling field history: deque of (datetime, float) pairs.
        self._history: deque[tuple[datetime, float]] = deque(maxlen=_HISTORY_SIZE)

        # Stability tracking.
        self._is_at_target: bool = False
        self._at_target_since: datetime | None = None
        self._unstable_since: datetime | None = None
        self._stable: bool = False

        # Cached target/ramp settings (updated when commands are issued).
        self._target_field: float | None = None
        self._target_current: float | None = None
        self._ramp_rate_field: float | None = None
        self._ramp_rate_current: float | None = None
        self._magnet_constant: float | None = None
        self._limits: MagnetLimits | None = None
        self._quench_active: bool = False
        self._latest_state: MagnetEngineState = MagnetEngineState(engine_status=self._status)

        self._timer = QTimer(self)
        self._engine_lock = threading.RLock()
        self._timer.setInterval(_DEFAULT_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._apply_configuration(load_magnet_controller_config())

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
                MagnetStabilityConfig(
                    tolerance_t=float(
                        stability.get("tolerance_t", self._stability_config.tolerance_t)
                    ),
                    window_s=float(
                        stability.get("window_s", self._stability_config.window_s)
                    ),
                    min_rate=float(
                        stability.get("min_rate", self._stability_config.min_rate)
                    ),
                    unstable_holdoff_s=float(
                        stability.get(
                            "unstable_holdoff_s",
                            self._stability_config.unstable_holdoff_s,
                        )
                    ),
                )
            )

        targets = config.get("targets")
        if isinstance(targets, dict):
            target_field = targets.get("field")
            target_current = targets.get("current")
            self._target_field = None if target_field is None else float(target_field)
            self._target_current = None if target_current is None else float(target_current)

        ramp = config.get("ramp")
        if isinstance(ramp, dict):
            ramp_rate_field = ramp.get("field_rate")
            ramp_rate_current = ramp.get("current_rate")
            self._ramp_rate_field = None if ramp_rate_field is None else float(ramp_rate_field)
            self._ramp_rate_current = None if ramp_rate_current is None else float(ramp_rate_current)

        limits = config.get("limits")
        if isinstance(limits, dict):
            magnet_constant = limits.get("magnet_constant")
            self._magnet_constant = None if magnet_constant is None else float(magnet_constant)
            max_current = limits.get("max_current")
            if max_current is not None:
                max_field = limits.get("max_field")
                max_ramp_rate = limits.get("max_ramp_rate")
                self._limits = MagnetLimits(
                    max_current=float(max_current),
                    max_field=None if max_field is None else float(max_field),
                    max_ramp_rate=None if max_ramp_rate is None else float(max_ramp_rate),
                )

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> MagnetControllerEngine:
        """Return the singleton engine, creating it on first call.

        Returns:
            (MagnetControllerEngine):
                The singleton engine instance.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.magnet_control.engine import MagnetControllerEngine
            >>> e1 = MagnetControllerEngine.instance()
            >>> e2 = MagnetControllerEngine.instance()
            >>> e1 is e2
            True
            >>> e1.shutdown()
        """
        if cls._singleton is None:
            cls._singleton = cls()
            app = _qapp()
            if app is not None:
                app.aboutToQuit.connect(cls._singleton.shutdown)
        return cls._singleton

    # ------------------------------------------------------------------
    # Status property
    # ------------------------------------------------------------------

    @property
    def status(self) -> MagnetEngineStatus:
        """The current operational status of the engine.

        Returns:
            (MagnetEngineStatus):
                Current :class:`~stoner_measurement.magnet_control.types.MagnetEngineStatus`.
        """
        return self._status

    # ------------------------------------------------------------------
    # Public command API
    # ------------------------------------------------------------------

    def connect_instrument(self, driver: MagnetController) -> None:
        """Connect to a magnet controller driver and start polling.

        Args:
            driver (MagnetController):
                A fully constructed
                :class:`~stoner_measurement.instruments.magnet_controller.MagnetController`
                instance. The engine opens it (if needed), verifies identity,
                and takes ownership of its lifecycle.

        Raises:
            RuntimeError:
                If the engine has been shut down.
        """
        with self._engine_lock:
            if self._status == MagnetEngineStatus.STOPPED:
                raise RuntimeError("Engine has been shut down and cannot accept new connections.")
            self._timer.stop()
            if self._driver is not None:
                self._disconnect_driver(self._driver, log_context="before replacing magnet controller")
            try:
                if not driver.is_connected:
                    driver.connect()
                else:
                    driver.confirm_identity()
            except Exception:
                self._driver = None
                self._set_status(MagnetEngineStatus.DISCONNECTED)
                raise
            self._driver = driver
            self._connected_driver_name = type(driver).__name__
            self._history.clear()
            self._is_at_target = False
            self._at_target_since = None
            self._unstable_since = None
            self._stable = False
            try:
                self._magnet_constant = driver.refresh_magnet_constant()
            except Exception:
                logger.debug(
                    "MagnetControllerEngine: failed to refresh magnet constant on connect",
                    exc_info=True,
                )
            self._set_status(MagnetEngineStatus.CONNECTED)
            self._timer.start()
        logger.info("MagnetControllerEngine: connected to %s", type(driver).__name__)

    def connect_driver(self, driver_name: str, transport_name: str, address: str) -> None:
        """Instantiate and connect a magnet controller from identifiers.

        Args:
            driver_name (str):
                Registered instrument driver name.
            transport_name (str):
                Transport type name (``"Serial"``, ``"GPIB"``,
                ``"Ethernet"``, or ``"Null"``).
            address (str):
                Transport address string. Serial format is
                ``"port=<device>;baud=<rate>"``.

        Raises:
            RuntimeError:
                If the engine has been shut down.
            Exception:
                Any exception raised while resolving or connecting the driver.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = MagnetControllerEngine()
            >>> engine.connect_driver("OxfordIPS120", "Null", "")  # doctest: +SKIP
            >>> engine.shutdown()
        """
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
            raise RuntimeError("No persisted magnet-controller driver is configured.")
        self.connect_driver(
            driver_name,
            self.preferred_transport_name,
            self.preferred_address,
        )

    def _resolve_driver_class(self, driver_name: str) -> type[MagnetController]:
        """Resolve a magnet-controller driver class by name.

        Args:
            driver_name (str):
                Registered driver name.

        Returns:
            (type[MagnetController]):
                Resolved driver class.

        Raises:
            ValueError:
                If no driver is registered with the requested name.
        """
        from stoner_measurement.instruments.magnet_controller import MagnetController

        manager = InstrumentDriverManager()
        manager.discover()
        driver_cls = manager.get(driver_name)
        if driver_cls is None:
            raise ValueError(f"Unknown magnet driver: {driver_name!r}")
        if not issubclass(driver_cls, MagnetController):
            raise ValueError(f"Driver {driver_name!r} is not a magnet-controller driver")
        return driver_cls

    def _build_transport(self, transport_name: str, address: str) -> BaseTransport:
        """Instantiate a transport from a transport type and address string.

        Args:
            transport_name (str):
                Transport type name.
            address (str):
                Transport address string.

        Returns:
            (BaseTransport):
                Instantiated transport object.

        Raises:
            ValueError:
                If the transport name is unsupported.
        """
        kind = transport_name.strip().lower()
        if kind == "serial":
            port, baud = self._parse_serial_address(address)
            return SerialTransport(port=port, baud_rate=baud)
        if kind == "gpib":
            resource = address.strip() or "GPIB0::2::INSTR"
            return GpibTransport.from_resource_string(resource)
        if kind == "ethernet":
            host, port = self._parse_ethernet_address(address)
            return EthernetTransport(host=host, port=port)
        if kind in {"null", "null (test)"}:
            return NullTransport()
        raise ValueError(f"Unsupported transport type: {transport_name!r}")

    def _build_protocol(self, driver_name: str) -> BaseProtocol:
        """Instantiate the default protocol for a driver name.

        Args:
            driver_name (str):
                Registered driver name.

        Returns:
            (BaseProtocol):
                Protocol instance selected for the driver family.
        """
        name = driver_name.lower()
        if "oxford" in name or "ips" in name:
            return OxfordProtocol()
        return LakeshoreProtocol()

    def _parse_serial_address(self, address: str) -> tuple[str, int]:
        """Parse serial address strings in ``port=<device>;baud=<rate>`` format.

        Args:
            address (str):
                Serial address string (for example
                ``"port=/dev/ttyUSB0;baud=9600"``).

        Returns:
            (tuple[str, int]):
                Parsed ``(port, baud_rate)`` tuple.

        Raises:
            ValueError:
                If a baud value is supplied but cannot be parsed as an integer.
        """
        return parse_serial_address(address)

    def _parse_ethernet_address(self, address: str) -> tuple[str, int]:
        """Parse Ethernet address strings in ``<host>:<port>`` format.

        Args:
            address (str):
                Ethernet address string (for example ``"localhost:5025"``).

        Returns:
            (tuple[str, int]):
                Parsed ``(host, port)`` tuple.

        Raises:
            ValueError:
                If a port is supplied but is not a valid integer.
        """
        return parse_ethernet_address(address)

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
            self._set_status(MagnetEngineStatus.DISCONNECTED)
            self._latest_state = MagnetEngineState(
                target_field=self._target_field,
                target_current=self._target_current,
                ramp_rate_field=self._ramp_rate_field,
                ramp_rate_current=self._ramp_rate_current,
                engine_status=self._status,
            )
        self.publisher.connection_changed.emit()
        logger.info("MagnetControllerEngine: disconnected.")

    @property
    def connected_driver(self) -> MagnetController | None:
        """Return the currently connected driver instance.

        Returns:
            (MagnetController | None):
                Connected driver instance, or ``None`` when disconnected.
        """
        return self._driver

    @property
    def connected_driver_name(self) -> str | None:
        """Return the connected driver name when known."""
        return self._connected_driver_name

    @property
    def connected_transport_name(self) -> str | None:
        """Return the active transport type when known."""
        return self._connected_transport_name

    @property
    def connected_address(self) -> str | None:
        """Return the active connection address when known."""
        return self._connected_address

    @property
    def preferred_driver_name(self) -> str:
        return self._preferred_driver_name

    @preferred_driver_name.setter
    def preferred_driver_name(self, value: str) -> None:
        self._preferred_driver_name = value

    @property
    def preferred_transport_name(self) -> str:
        return self._preferred_transport_name

    @preferred_transport_name.setter
    def preferred_transport_name(self, value: str) -> None:
        self._preferred_transport_name = value

    @property
    def preferred_address(self) -> str:
        return self._preferred_address

    @preferred_address.setter
    def preferred_address(self, value: str) -> None:
        self._preferred_address = value

    def configuration_dict(self) -> dict:
        return {
            "poll_interval_ms": self._timer.interval(),
            "connection": {
                "driver": self._preferred_driver_name,
                "transport": self._preferred_transport_name,
                "address": self._preferred_address,
            },
            "targets": {
                "field": self._target_field,
                "current": self._target_current,
            },
            "ramp": {
                "field_rate": self._ramp_rate_field,
                "current_rate": self._ramp_rate_current,
            },
            "limits": {
                "magnet_constant": self._magnet_constant,
                "max_current": None if self._limits is None else self._limits.max_current,
                "max_field": None if self._limits is None else self._limits.max_field,
                "max_ramp_rate": None if self._limits is None else self._limits.max_ramp_rate,
            },
            "stability": {
                "tolerance_t": self._stability_config.tolerance_t,
                "window_s": self._stability_config.window_s,
                "min_rate": self._stability_config.min_rate,
                "unstable_holdoff_s": self._stability_config.unstable_holdoff_s,
            },
        }

    def save_configuration(self):
        return save_magnet_controller_config(self.configuration_dict())

    def set_target_field(self, field: float) -> None:
        """Set the target magnetic field.

        Args:
            field (float):
                Desired target field in tesla.
        """
        with self._engine_lock:
            self._target_field = field
            if self._driver is None:
                return
            try:
                self._driver.set_target_field(field)
                self._mark_target_pending()
            except Exception:
                logger.exception("Failed to set target field to %s T", field)

    def set_target_current(self, current: float) -> None:
        """Set the target output current.

        Args:
            current (float):
                Desired target current in amps.
        """
        with self._engine_lock:
            self._target_current = current
            if self._driver is None:
                return
            try:
                self._driver.set_target_current(current)
                self._mark_target_pending()
            except Exception:
                logger.exception("Failed to set target current to %s A", current)

    def set_ramp_rate_field(self, rate: float) -> None:
        """Set the field ramp rate.

        Args:
            rate (float):
                Ramp rate in tesla per minute.
        """
        with self._engine_lock:
            self._ramp_rate_field = rate
            if self._driver is None:
                return
            try:
                self._driver.set_ramp_rate_field(rate)
            except Exception:
                logger.exception("Failed to set field ramp rate to %s T/min", rate)

    def set_ramp_rate_current(self, rate: float) -> None:
        """Set the current ramp rate.

        Args:
            rate (float):
                Ramp rate in amps per minute.
        """
        with self._engine_lock:
            self._ramp_rate_current = rate
            if self._driver is None:
                return
            try:
                self._driver.set_ramp_rate_current(rate)
            except Exception:
                logger.exception("Failed to set current ramp rate to %s A/min", rate)

    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        """Set the magnet constant used for field/current conversion.

        Args:
            tesla_per_amp (float):
                Magnet constant in tesla per amp.
        """
        with self._engine_lock:
            self._magnet_constant = tesla_per_amp
            if self._driver is None:
                return
            try:
                self._driver.set_magnet_constant(tesla_per_amp)
            except Exception:
                logger.exception("Failed to set magnet constant to %s T/A", tesla_per_amp)

    def set_limits(self, limits: MagnetLimits) -> None:
        """Set operating limits for the connected magnet supply.

        Args:
            limits (MagnetLimits):
                Maximum current, field, and ramp rate limits.
        """
        with self._engine_lock:
            self._limits = limits
            if self._driver is None:
                return
            try:
                self._driver.set_limits(limits)
            except Exception:
                logger.exception("Failed to set magnet limits")

    def ramp_to_target(self) -> None:
        """Start ramping to the currently programmed target."""
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                self._validate_ramp_allowed()
                self._mark_target_pending()
                self._driver.ramp_to_target()
            except Exception:
                logger.exception("Failed to start ramp to target")

    def ramp_to_field(self, field: float) -> None:
        """Set a new target field and begin ramping.

        Args:
            field (float):
                Desired target field in tesla.
        """
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                self._validate_ramp_allowed()
                self._driver.set_target_field(field)
                self._target_field = field
                self._mark_target_pending()
                self._driver.ramp_to_target()
            except Exception:
                logger.exception("Failed to ramp to field %s T", field)

    def pause_ramp(self) -> None:
        """Pause an active ramp, holding the output at its current value."""
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                self._driver.pause_ramp()
            except Exception:
                logger.exception("Failed to pause ramp")

    def hold(self) -> None:
        """Hold the present output without changing field."""
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                self._driver.hold()
            except Exception:
                logger.exception("Failed to hold present field/current")

    def go_to_zero(self) -> None:
        """Ramp the supply output to zero using the controller zero action."""
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                self._validate_ramp_allowed()
                self._driver.go_to_zero()
                self._target_field = 0.0
                try:
                    self._target_current = 0.0
                except Exception:
                    logger.debug("Failed to cache zero target current after go-to-zero command", exc_info=True)
            except Exception:
                logger.exception("Failed to go to zero")

    def abort_ramp(self) -> None:
        """Abort an active ramp immediately."""
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                self._driver.abort_ramp()
            except Exception:
                logger.exception("Failed to abort ramp")

    def heater_on(self) -> None:
        """Energise the persistent switch heater."""
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                self._validate_heater_on_allowed()
                self._driver.heater_on()
            except Exception:
                logger.exception("Failed to turn heater on")

    def heater_off(self) -> None:
        """De-energise the persistent switch heater."""
        with self._engine_lock:
            if self._driver is None:
                return
            try:
                self._driver.heater_off()
            except Exception:
                logger.exception("Failed to turn heater off")

    def set_stability_config(self, config: MagnetStabilityConfig) -> None:
        """Replace the stability-evaluation configuration.

        Args:
            config (MagnetStabilityConfig):
                New stability configuration to apply immediately.
        """
        self._stability_config = config
        self._at_target_since = None
        self._unstable_since = None
        self._stable = False

    def set_poll_interval(self, ms: int) -> None:
        """Set the polling interval.

        Args:
            ms (int):
                Polling interval in milliseconds (minimum 100 ms).
        """
        ms = max(100, ms)
        self._timer.setInterval(ms)

    def read_controller_state(self) -> MagnetEngineState | None:
        """Read the current controller state immediately and publish it.

        Returns:
            (MagnetEngineState | None):
                Freshly read engine state, or ``None`` when no controller is
                connected or the read fails.
        """
        with self._engine_lock:
            if self._driver is None:
                return None
            try:
                state = self._build_state()
            except Exception:
                logger.exception("MagnetControllerEngine: read-state error")
                self._set_status(MagnetEngineStatus.ERROR)
                return None

            self._set_status(MagnetEngineStatus.POLLING)
            self._latest_state = state
            self._handle_quench_state(state)
            self.publisher.reading_updated.emit(state.reading)
            self.publisher.state_updated.emit(state)
            self.publisher.poll_activity.emit()
        return state

    def refresh_magnet_constant(self) -> float | None:
        """Refresh the cached magnet constant from the connected driver."""
        with self._engine_lock:
            if self._driver is None:
                return self._magnet_constant
            try:
                self._magnet_constant = self._driver.refresh_magnet_constant()
            except Exception:
                logger.exception("MagnetControllerEngine: failed to refresh magnet constant")
            return self._magnet_constant

    def get_limits(self) -> MagnetLimits | None:
        """Return the controller limits from the connected driver.

        Returns:
            (MagnetLimits | None):
                Active limits, or ``None`` when disconnected or unavailable.
        """
        with self._engine_lock:
            if self._driver is None:
                return self._limits
            try:
                self._magnet_constant = self._driver.refresh_magnet_constant()
            except Exception:
                logger.exception("MagnetControllerEngine: failed to refresh magnet constant")
            try:
                limits = self._driver.limits
                self._limits = limits
                return limits
            except Exception:
                logger.exception("MagnetControllerEngine: failed to read limits")
                return self._limits

    def get_engine_state(self) -> MagnetEngineState:
        """Return a snapshot of the current engine state without polling.

        Returns:
            (MagnetEngineState):
                Current engine state snapshot.  The ``reading`` field is
                ``None`` when no instrument is connected.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.magnet_control.engine import MagnetControllerEngine
            >>> engine = MagnetControllerEngine.instance()
            >>> state = engine.get_engine_state()
            >>> state.reading is None
            True
            >>> engine.shutdown()
        """
        return replace(
            self._latest_state,
            target_field=self._target_field,
            target_current=self._target_current,
            ramp_rate_field=self._ramp_rate_field,
            ramp_rate_current=self._ramp_rate_current,
            at_target=self._is_at_target,
            stable=self._stable,
            engine_status=self._status,
        )

    @pyqtSlot()
    def shutdown(self) -> None:
        """Stop polling, release the driver, and mark the engine as stopped.

        After calling this method the engine can no longer be used.  The
        singleton reference is also cleared so :meth:`instance` will create a
        fresh instance if called again.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.magnet_control.engine import MagnetControllerEngine
            >>> e = MagnetControllerEngine()
            >>> e.shutdown()
            >>> e.status
            <MagnetEngineStatus.STOPPED: 'stopped'>
        """
        self._timer.stop()
        with self._engine_lock:
            if self._driver is not None:
                self._disconnect_driver(self._driver, log_context="on shutdown")
            self._driver = None
            self._connected_driver_name = None
            self._connected_transport_name = None
            self._connected_address = None
            self._set_status(MagnetEngineStatus.STOPPED)
            self._latest_state = MagnetEngineState(
                target_field=self._target_field,
                target_current=self._target_current,
                ramp_rate_field=self._ramp_rate_field,
                ramp_rate_current=self._ramp_rate_current,
                engine_status=self._status,
            )
        if MagnetControllerEngine._singleton is self:
            MagnetControllerEngine._singleton = None
        logger.info("MagnetControllerEngine: shut down.")

    def _disconnect_driver(self, driver: MagnetController, *, log_context: str) -> None:
        """Disconnect *driver*, logging exceptions.

        Args:
            driver (MagnetController):
                Driver instance to disconnect.

        Keyword Parameters:
            log_context (str):
                Context string included in disconnect failure logs.
        """
        try:
            if driver.is_connected:
                try:
                    driver.return_to_local()
                except Exception:
                    logger.exception(
                        "Failed to return magnet controller to local mode %s",
                        log_context,
                    )
                if not driver.is_connected:
                    return
                driver.disconnect()
        except Exception:
            logger.exception("Error while disconnecting magnet controller %s", log_context)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _poll(self) -> None:
        """Query the instrument, compute derived quantities, and publish results."""
        self.read_controller_state()

    def _build_state(self) -> MagnetEngineState:
        """Query the driver and return a full :class:`MagnetEngineState`.

        Returns:
            (MagnetEngineState):
                Snapshot incorporating instrument readings and derived
                stability flags.
        """
        driver = self._driver
        status = driver.status
        now = datetime.now(tz=UTC)

        target_field = self._read_driver_float_attr("target_field", self._target_field)
        target_current = self._read_driver_float_attr("target_current", self._target_current)
        ramp_rate_field = self._read_driver_float_attr("ramp_rate_field", self._ramp_rate_field)
        ramp_rate_current = self._read_driver_float_attr("ramp_rate_current", self._ramp_rate_current)

        self._target_field = target_field
        self._target_current = target_current
        self._ramp_rate_field = ramp_rate_field
        self._ramp_rate_current = ramp_rate_current

        field_val: float | None = status.field
        if field_val is not None:
            self._history.append((now, field_val))

        field_rate = _compute_rate(self._history)

        # Evaluate stability.
        self._evaluate_stability(field_val, now)

        magnet_constant = self._magnet_constant

        persistent_current: float | None = None
        if status.persistent_field is not None and magnet_constant not in {None, 0.0}:
            persistent_current = status.persistent_field / magnet_constant

        reading = MagnetReading(
            timestamp=now,
            field=field_val,
            current=status.current,
            voltage=status.voltage,
            heater_on=status.heater_on,
            heater_state=status.heater_state,
            state=status.state,
            persistent_current=persistent_current,
            persistent_field=status.persistent_field,
            at_target=status.at_target,
            quench_detected=status.state is MagnetState.QUENCH,
            field_rate=field_rate,
        )

        return MagnetEngineState(
            reading=reading,
            target_field=target_field,
            target_current=target_current,
            ramp_rate_field=ramp_rate_field,
            ramp_rate_current=ramp_rate_current,
            magnet_constant=magnet_constant,
            at_target=self._is_at_target,
            stable=self._stable,
            engine_status=MagnetEngineStatus.POLLING,
        )

    def _read_driver_float_attr(self, attr_name: str, fallback: float | None) -> float | None:
        """Read a float-like driver attribute, falling back quietly on errors."""
        driver = self._driver
        if driver is None:
            return fallback
        try:
            value = getattr(driver, attr_name)
        except Exception:
            logger.debug("Failed to read magnet driver attribute %s", attr_name, exc_info=True)
            return fallback
        if value is None:
            return fallback
        return float(value)

    def _evaluate_stability(self, field: float | None, now: datetime) -> None:
        """Update the stability flag based on the current field reading.

        Args:
            field (float | None):
                Current field in tesla, or ``None`` if unavailable.
            now (datetime):
                Current UTC timestamp.
        """
        cfg = self._stability_config
        if field is None or self._target_field is None:
            self._is_at_target = False
            self._at_target_since = None
            self._try_clear_stable(now, cfg)
            return

        currently_at = abs(field - self._target_field) < cfg.tolerance_t
        self._is_at_target = currently_at
        field_rate = _compute_rate(self._history)

        if currently_at:
            if self._at_target_since is None:
                self._at_target_since = now
            elapsed = (now - self._at_target_since).total_seconds()
            rate_ok = abs(field_rate) < cfg.min_rate
            if elapsed >= cfg.window_s and rate_ok:
                self._unstable_since = None
                self._stable = True
            else:
                self._try_clear_stable(now, cfg)
        else:
            self._at_target_since = None
            self._try_clear_stable(now, cfg)

    def _validate_ramp_allowed(self) -> None:
        """Raise if a field change should be blocked for heater-safety reasons."""
        status = self._driver.status
        heater_state = getattr(status.heater_state, "value", str(status.heater_state)).lower()
        if heater_state in {"warming", "cooling"}:
            raise RuntimeError("Cannot change magnetic field while the switch heater is transitioning.")

    def _validate_heater_on_allowed(self) -> None:
        """Raise if turning the heater on would be unsafe in persistent mode."""
        status = self._driver.status
        heater_state = getattr(status.heater_state, "value", str(status.heater_state)).lower()
        if heater_state in {"warming", "cooling"}:
            raise RuntimeError("Cannot turn switch heater on while it is already transitioning.")
        if not status.persistent:
            return
        persistent_field = status.persistent_field
        supply_field = status.field
        if persistent_field is None or supply_field is None:
            raise RuntimeError(
                "Cannot safely turn the switch heater on in persistent mode because the trapped and supply fields cannot be verified."
            )
        cfg = self._stability_config
        if abs(supply_field - persistent_field) > cfg.tolerance_t:
            raise RuntimeError(
                "Cannot turn the switch heater on in persistent mode until the power-supply field matches the trapped persistent field."
            )

    def _mark_target_pending(self) -> None:
        """Invalidate cached target/stability flags after a new target command."""
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
            at_target=False,
            stable=False,
        )

    def _try_clear_stable(self, now: datetime, cfg: MagnetStabilityConfig) -> None:
        """Clear the stable flag after the holdoff period has elapsed.

        Args:
            now (datetime):
                Current UTC timestamp.
            cfg (MagnetStabilityConfig):
                Active stability configuration.
        """
        if not self._stable:
            return
        if self._unstable_since is None:
            self._unstable_since = now
        holdoff_elapsed = (now - self._unstable_since).total_seconds() >= cfg.unstable_holdoff_s
        if holdoff_elapsed:
            self._stable = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_status(self, status: MagnetEngineStatus) -> None:
        """Update the engine status and emit the change signal if it changed.

        Args:
            status (MagnetEngineStatus):
                New status to apply.
        """
        if status != self._status:
            self._status = status
            self._latest_state = replace(self._latest_state, engine_status=status)
            self.publisher.engine_status_changed.emit(status)

    def _handle_quench_state(self, state: MagnetEngineState) -> None:
        """Emit a critical log when a quench is newly detected."""
        quench_detected = bool(state.reading is not None and state.reading.quench_detected)
        if quench_detected and not self._quench_active:
            logger.critical("MagnetControllerEngine: quench detected by magnet controller.")
            driver = self._driver
            if driver is not None and driver.is_connected:
                try:
                    driver.return_to_local()
                except Exception:
                    logger.exception(
                        "MagnetControllerEngine: failed to return magnet controller to local mode after quench."
                    )
            self._quench_active = True
        elif not quench_detected:
            self._quench_active = False


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _qapp():
    """Return the running QApplication instance, or None."""
    try:
        from qtpy.QtWidgets import QApplication

        return QApplication.instance()
    except (ImportError, RuntimeError):
        return None


def _compute_rate(history: deque[tuple[datetime, float]]) -> float:
    """Compute the rate of field change in tesla per minute.

    Uses a simple linear fit (least-squares slope) over the available
    timestamped history.  Returns ``0.0`` when fewer than two readings are
    available.

    Args:
        history (deque[tuple[datetime, float]]):
            Ordered sequence of ``(timestamp, value)`` pairs; oldest first.

    Returns:
        (float):
            Estimated rate of change in tesla per minute.
    """
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
    return slope_per_second * 60.0  # convert T/s → T/min
