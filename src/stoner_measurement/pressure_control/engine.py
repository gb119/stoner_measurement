"""Singleton pressure controller engine."""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from qtpy.QtCore import QObject, QTimer

from stoner_measurement.instruments.addressing import parse_ethernet_address, parse_serial_address
from stoner_measurement.instruments.driver_manager import InstrumentDriverManager
from stoner_measurement.instruments.pressure_controller import PressureGaugeController
from stoner_measurement.instruments.protocol import LeyboldCenterProtocol, ScpiProtocol
from stoner_measurement.instruments.transport import (
    EthernetTransport,
    GpibTransport,
    NullTransport,
    SerialTransport,
)
from stoner_measurement.pressure_control.config import (
    load_pressure_controller_config,
    save_pressure_controller_config,
)
from stoner_measurement.pressure_control.pubsub import PressurePublisher
from stoner_measurement.pressure_control.types import (
    PressureEngineReading,
    PressureEngineState,
    PressureEngineStatus,
)
from stoner_measurement.qt_compat import pyqtSlot

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_MS = 1000


class PressureControllerEngine(QObject):
    """Singleton engine that mediates pressure-controller communication."""

    _singleton: PressureControllerEngine | None = None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.publisher: PressurePublisher = PressurePublisher(self)
        self._driver: PressureGaugeController | None = None
        self._connected_driver_name: str | None = None
        self._connected_transport_name: str | None = None
        self._connected_address: str | None = None
        self._preferred_driver_name: str = ""
        self._preferred_transport_name: str = "Null (test)"
        self._preferred_address: str = ""
        self._status: PressureEngineStatus = PressureEngineStatus.DISCONNECTED
        self._latest_state: PressureEngineState = PressureEngineState(engine_status=self._status)
        self._engine_lock = threading.RLock()
        self._timer = QTimer(self)
        self._timer.setInterval(_DEFAULT_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._apply_configuration(load_pressure_controller_config())

    @classmethod
    def instance(cls) -> PressureControllerEngine:
        """Return the singleton engine, creating it on first call."""
        if cls._singleton is None:
            cls._singleton = cls()
            app = _qapp()
            if app is not None:
                app.aboutToQuit.connect(cls._singleton.shutdown)
        return cls._singleton

    @property
    def status(self) -> PressureEngineStatus:
        """The current operational status of the engine."""
        return self._status

    def connect_instrument(self, driver: PressureGaugeController) -> None:
        """Connect to a pressure controller driver and start polling."""
        with self._engine_lock:
            if self._status == PressureEngineStatus.STOPPED:
                raise RuntimeError("Engine has been shut down and cannot accept new connections.")
            self._timer.stop()
            if self._driver is not None:
                self._disconnect_driver(self._driver, log_context="before replacing pressure controller")
            try:
                if not driver.is_connected:
                    driver.connect()
            except Exception:
                self._driver = None
                self._set_status(PressureEngineStatus.DISCONNECTED)
                raise
            self._driver = driver
            self._connected_driver_name = type(driver).__name__
            self._set_status(PressureEngineStatus.CONNECTED)
            self._latest_state = PressureEngineState(engine_status=self._status, driver_name=self._connected_driver_name)
            self._timer.start()
        logger.info("PressureControllerEngine: connected to %s", type(driver).__name__)

    def connect_driver(self, driver_name: str, transport_name: str, address: str) -> None:
        """Instantiate and connect a pressure controller from identifiers."""
        driver_cls = self._resolve_driver_class(driver_name)
        capabilities = driver_cls._CAPABILITIES  # noqa: SLF001
        if capabilities.analogue_only:
            raise ValueError(
                f"Driver {driver_name!r} requires external analogue I/O callbacks and cannot be built from the panel."
            )
        transport = self._build_transport(transport_name, address)
        protocol = self._build_protocol(driver_name)
        driver = driver_cls(transport=transport, protocol=protocol)
        self.connect_instrument(driver)
        self._connected_driver_name = driver_name
        self._connected_transport_name = transport_name
        self._connected_address = address
        self.publisher.connection_changed.emit()

    def connect_preferred_driver(self) -> None:
        """Connect using persisted preferred driver and transport settings."""
        if self.connected_driver is not None:
            return
        driver_name = self.preferred_driver_name.strip()
        if not driver_name:
            raise RuntimeError("No persisted pressure-controller driver is configured.")
        self.connect_driver(driver_name, self.preferred_transport_name, self.preferred_address)

    def disconnect_instrument(self) -> None:
        """Stop polling and release the pressure-controller driver reference."""
        self._timer.stop()
        with self._engine_lock:
            if self._driver is not None:
                self._disconnect_driver(self._driver, log_context="on disconnect")
            self._driver = None
            self._connected_driver_name = None
            self._connected_transport_name = None
            self._connected_address = None
            self._set_status(PressureEngineStatus.DISCONNECTED)
            self._latest_state = PressureEngineState(engine_status=self._status)
        self.publisher.connection_changed.emit()
        logger.info("PressureControllerEngine: disconnected.")

    @property
    def connected_driver(self) -> PressureGaugeController | None:
        """Return the connected pressure-controller driver, if any."""
        return self._driver

    @property
    def connected_driver_name(self) -> str | None:
        """Return the connected driver class name, if any."""
        return self._connected_driver_name

    @property
    def connected_transport_name(self) -> str | None:
        """Return the connected transport name, if known."""
        return self._connected_transport_name

    @property
    def connected_address(self) -> str | None:
        """Return the connected instrument address, if known."""
        return self._connected_address

    @property
    def preferred_driver_name(self) -> str:
        """Return the saved preferred driver name."""
        return self._preferred_driver_name

    @preferred_driver_name.setter
    def preferred_driver_name(self, value: str) -> None:
        self._preferred_driver_name = value

    @property
    def preferred_transport_name(self) -> str:
        """Return the saved preferred transport name."""
        return self._preferred_transport_name

    @preferred_transport_name.setter
    def preferred_transport_name(self, value: str) -> None:
        self._preferred_transport_name = value

    @property
    def preferred_address(self) -> str:
        """Return the saved preferred address."""
        return self._preferred_address

    @preferred_address.setter
    def preferred_address(self, value: str) -> None:
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
        }

    def save_configuration(self):
        """Persist the current engine configuration to the user config file."""
        return save_pressure_controller_config(self.configuration_dict())

    def set_poll_interval(self, ms: int) -> None:
        """Set the polling interval in milliseconds."""
        self._timer.setInterval(max(100, ms))

    def read_controller_state(self) -> PressureEngineState | None:
        """Poll the controller once and publish the resulting engine state."""
        with self._engine_lock:
            if self._driver is None:
                return None
            try:
                state = self._build_state()
            except Exception:
                logger.exception("PressureControllerEngine: read-state error")
                self._set_status(PressureEngineStatus.ERROR)
                return None
            self._set_status(PressureEngineStatus.POLLING)
            state.engine_status = self._status
            self._latest_state = state
            if state.reading is not None:
                self.publisher.reading_updated.emit(state.reading)
            self.publisher.state_updated.emit(state)
            self.publisher.poll_activity.emit()
        return state

    def get_engine_state(self) -> PressureEngineState:
        """Return the latest cached pressure-engine state."""
        return replace(self._latest_state, engine_status=self._status, driver_name=self._connected_driver_name)

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
            self._set_status(PressureEngineStatus.STOPPED)
            self._latest_state = PressureEngineState(engine_status=self._status)
        if PressureControllerEngine._singleton is self:
            PressureControllerEngine._singleton = None
        logger.info("PressureControllerEngine: shut down.")

    def _apply_configuration(self, config: dict) -> None:
        connection = config.get("connection")
        if isinstance(connection, dict):
            self._preferred_driver_name = str(connection.get("driver", ""))
            self._preferred_transport_name = str(connection.get("transport", "Null (test)"))
            self._preferred_address = str(connection.get("address", ""))
        poll_interval = config.get("poll_interval_ms")
        if isinstance(poll_interval, int):
            self.set_poll_interval(poll_interval)

    def _resolve_driver_class(self, driver_name: str) -> type[PressureGaugeController]:
        manager = InstrumentDriverManager()
        manager.discover()
        driver_cls = manager.get(driver_name)
        if driver_cls is None:
            raise ValueError(f"Unknown pressure driver: {driver_name!r}")
        if not issubclass(driver_cls, PressureGaugeController):
            raise ValueError(f"Driver {driver_name!r} is not a pressure-controller driver")
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
        if "leyboldcenter" in driver_name.replace("_", "").lower() or "center" in driver_name.lower():
            return LeyboldCenterProtocol()
        return ScpiProtocol()

def _disconnect_driver(self, driver: PressureGaugeController, *, log_context: str) -> None:
        try:
            if driver.is_connected:
                driver.disconnect()
        except Exception:
            logger.exception(
                "Error while disconnecting pressure controller %s", log_context
            )
    @pyqtSlot()
    def _poll(self) -> None:
        self.read_controller_state()

    def _build_state(self) -> PressureEngineState:
        driver = self._driver
        if driver is None:
            return PressureEngineState(engine_status=self._status)
        now = datetime.now(tz=UTC)
        readings = driver.read_all_pressures()
        unit = next((reading.unit for reading in readings.values()), None)
        reading = PressureEngineReading(timestamp=now, readings=readings, unit=unit)
        return PressureEngineState(
            reading=reading,
            readings=readings,
            engine_status=PressureEngineStatus.POLLING,
            driver_name=self._connected_driver_name,
            unit=unit,
        )

    def _set_status(self, status: PressureEngineStatus) -> None:
        if status == self._status:
            return
        self._status = status
        self.publisher.engine_status_changed.emit(status)


def _qapp():
    from qtpy.QtWidgets import QApplication

    return QApplication.instance()
