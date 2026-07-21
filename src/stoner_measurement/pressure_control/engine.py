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
from stoner_measurement.instruments.mass_flow_controller import MassFlowController
from stoner_measurement.instruments.pressure_controller import (
    PressureGaugeController,
    PressureReading,
    PressureStatus,
    PressureUnit,
)
from stoner_measurement.instruments.protocol import (
    LeyboldCenterProtocol,
    MKSPR4000Protocol,
    MKSPSRProtocol,
    ScpiProtocol,
)
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
    """Singleton engine that mediates pressure-controller and MFC communication."""

    _singleton: PressureControllerEngine | None = None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.publisher: PressurePublisher = PressurePublisher(self)
        self._driver: PressureGaugeController | None = None
        self._mfc_driver: MassFlowController | None = None
        self._connected_driver_name: str | None = None
        self._connected_transport_name: str | None = None
        self._connected_address: str | None = None
        self._connected_mfc_driver_name: str | None = None
        self._connected_mfc_transport_name: str | None = None
        self._connected_mfc_address: str | None = None
        self._preferred_driver_name: str = ""
        self._preferred_transport_name: str = "Null (test)"
        self._preferred_address: str = ""
        self._preferred_mfc_driver_name: str = ""
        self._preferred_mfc_transport_name: str = "Null (test)"
        self._preferred_mfc_address: str = ""
        self._status: PressureEngineStatus = PressureEngineStatus.DISCONNECTED
        self._latest_state: PressureEngineState = PressureEngineState(engine_status=self._status)
        self._engine_lock = threading.RLock()
        self._timer = QTimer(self)
        self._timer.setInterval(_DEFAULT_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._gauge_channel_enabled: dict[int, bool | None] = {}
        self._last_flow_setpoints: dict[int, float] = {}
        self._last_target_pressures: dict[int, float] = {}
        self._last_flow_unit: int | str | None = None
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
            self._ensure_running()
            self._timer.stop()
            if self._driver is not None:
                self._disconnect_driver(self._driver, log_context="before replacing pressure controller")
            try:
                if not driver.is_connected:
                    driver.connect()
            except Exception:
                self._driver = None
                self._set_status(self._derive_status())
                raise
            self._driver = driver
            self._connected_driver_name = type(driver).__name__
            self._latest_state = replace(
                self._latest_state,
                driver_name=self._connected_driver_name,
                engine_status=self._derive_status(),
            )
            self._set_status(self._derive_status())
            self._timer.start()
        logger.info("PressureControllerEngine: connected pressure controller %s", type(driver).__name__)
        self.publisher.connection_changed.emit()

    def connect_mfc_instrument(self, driver: MassFlowController) -> None:
        """Connect to a mass-flow controller driver and start polling."""
        with self._engine_lock:
            self._ensure_running()
            self._timer.stop()
            if self._mfc_driver is not None:
                self._disconnect_driver(self._mfc_driver, log_context="before replacing mass flow controller")
            try:
                if not driver.is_connected:
                    driver.connect()
            except Exception:
                self._mfc_driver = None
                self._set_status(self._derive_status())
                raise
            self._mfc_driver = driver
            self._connected_mfc_driver_name = type(driver).__name__
            self._latest_state = replace(
                self._latest_state,
                mfc_driver_name=self._connected_mfc_driver_name,
                engine_status=self._derive_status(),
            )
            self._set_status(self._derive_status())
            self._timer.start()
        logger.info("PressureControllerEngine: connected mass flow controller %s", type(driver).__name__)
        self.publisher.connection_changed.emit()

    def connect_driver(self, driver_name: str, transport_name: str, address: str) -> None:
        """Instantiate and connect a pressure controller from identifiers."""
        driver_cls = self._resolve_pressure_driver_class(driver_name)
        capabilities = driver_cls._CAPABILITIES  # noqa: SLF001
        if capabilities.analogue_only:
            raise ValueError(
                f"Driver {driver_name!r} requires external analogue I/O callbacks and cannot be built from the panel."
            )
        transport = self._build_transport(transport_name, address)
        protocol = self._build_pressure_protocol(driver_name)
        driver = driver_cls(transport=transport, protocol=protocol)
        self.connect_instrument(driver)
        self._connected_driver_name = driver_name
        self._connected_transport_name = transport_name
        self._connected_address = address
        self.publisher.connection_changed.emit()

    def connect_mfc_driver(self, driver_name: str, transport_name: str, address: str) -> None:
        """Instantiate and connect an MFC from identifiers."""
        driver_cls = self._resolve_mfc_driver_class(driver_name)
        transport = self._build_transport(transport_name, address)
        protocol = self._build_mfc_protocol(driver_name)
        driver = driver_cls(transport=transport, protocol=protocol)
        self.connect_mfc_instrument(driver)
        self._connected_mfc_driver_name = driver_name
        self._connected_mfc_transport_name = transport_name
        self._connected_mfc_address = address
        self.publisher.connection_changed.emit()

    def connect_preferred_driver(self) -> None:
        """Connect the preferred pressure gauge driver if one is configured."""
        if self.connected_driver is not None:
            return
        driver_name = self.preferred_driver_name.strip()
        if not driver_name:
            raise RuntimeError("No persisted pressure-controller driver is configured.")
        self.connect_driver(driver_name, self.preferred_transport_name, self.preferred_address)

    def connect_preferred_mfc_driver(self) -> None:
        """Connect the preferred MFC driver if one is configured."""
        if self.connected_mfc_driver is not None:
            return
        driver_name = self.preferred_mfc_driver_name.strip()
        if not driver_name:
            raise RuntimeError("No persisted mass-flow-controller driver is configured.")
        self.connect_mfc_driver(driver_name, self.preferred_mfc_transport_name, self.preferred_mfc_address)

    def disconnect_instrument(self) -> None:
        """Disconnect the pressure controller while leaving any MFC connected."""
        self._timer.stop()
        with self._engine_lock:
            if self._driver is not None:
                self._disconnect_driver(self._driver, log_context="on pressure disconnect")
            self._driver = None
            self._connected_driver_name = None
            self._connected_transport_name = None
            self._connected_address = None
            self._gauge_channel_enabled.clear()
            self._set_status(self._derive_status())
            self._latest_state = replace(
                self._latest_state,
                readings={},
                gauge_channel_enabled={},
                driver_name=None,
                engine_status=self._status,
            )
            if self._driver is not None or self._mfc_driver is not None:
                self._timer.start()
        self.publisher.connection_changed.emit()
        logger.info("PressureControllerEngine: pressure controller disconnected.")

    def disconnect_mfc_instrument(self) -> None:
        """Disconnect the MFC while leaving any pressure controller connected."""
        self._timer.stop()
        with self._engine_lock:
            if self._mfc_driver is not None:
                self._disconnect_driver(self._mfc_driver, log_context="on MFC disconnect")
            self._mfc_driver = None
            self._connected_mfc_driver_name = None
            self._connected_mfc_transport_name = None
            self._connected_mfc_address = None
            self._last_flow_setpoints.clear()
            self._last_target_pressures.clear()
            self._last_flow_unit = None
            self._set_status(self._derive_status())
            self._latest_state = replace(
                self._latest_state,
                flow_actual={},
                flow_setpoints={},
                target_pressures={},
                mfc_driver_name=None,
                flow_unit=None,
                engine_status=self._status,
            )
            if self._driver is not None or self._mfc_driver is not None:
                self._timer.start()
        self.publisher.connection_changed.emit()
        logger.info("PressureControllerEngine: mass flow controller disconnected.")

    @property
    def connected_driver(self) -> PressureGaugeController | None:
        """Return the connected pressure-controller driver, if any."""
        return self._driver

    @property
    def connected_mfc_driver(self) -> MassFlowController | None:
        """Return the connected mass-flow-controller driver, if any."""
        return self._mfc_driver

    @property
    def connected_driver_name(self) -> str | None:
        """Return the connected pressure-controller driver class name, if any."""
        return self._connected_driver_name

    @property
    def connected_mfc_driver_name(self) -> str | None:
        """Return the connected MFC driver class name, if any."""
        return self._connected_mfc_driver_name

    @property
    def connected_transport_name(self) -> str | None:
        """Return the connected pressure-controller transport name, if known."""
        return self._connected_transport_name

    @property
    def connected_mfc_transport_name(self) -> str | None:
        """Return the connected MFC transport name, if known."""
        return self._connected_mfc_transport_name

    @property
    def connected_address(self) -> str | None:
        """Return the connected pressure-controller address, if known."""
        return self._connected_address

    @property
    def connected_mfc_address(self) -> str | None:
        """Return the connected MFC address, if known."""
        return self._connected_mfc_address

    @property
    def preferred_driver_name(self) -> str:
        """Return the saved pressure-controller driver name."""
        return self._preferred_driver_name

    @preferred_driver_name.setter
    def preferred_driver_name(self, value: str) -> None:
        self._preferred_driver_name = value

    @property
    def preferred_transport_name(self) -> str:
        """Return the saved pressure-controller transport name."""
        return self._preferred_transport_name

    @preferred_transport_name.setter
    def preferred_transport_name(self, value: str) -> None:
        self._preferred_transport_name = value

    @property
    def preferred_address(self) -> str:
        """Return the saved pressure-controller address."""
        return self._preferred_address

    @preferred_address.setter
    def preferred_address(self, value: str) -> None:
        self._preferred_address = value

    @property
    def preferred_mfc_driver_name(self) -> str:
        """Return the saved MFC driver name."""
        return self._preferred_mfc_driver_name

    @preferred_mfc_driver_name.setter
    def preferred_mfc_driver_name(self, value: str) -> None:
        self._preferred_mfc_driver_name = value

    @property
    def preferred_mfc_transport_name(self) -> str:
        """Return the saved MFC transport name."""
        return self._preferred_mfc_transport_name

    @preferred_mfc_transport_name.setter
    def preferred_mfc_transport_name(self, value: str) -> None:
        self._preferred_mfc_transport_name = value

    @property
    def preferred_mfc_address(self) -> str:
        """Return the saved MFC address."""
        return self._preferred_mfc_address

    @preferred_mfc_address.setter
    def preferred_mfc_address(self, value: str) -> None:
        self._preferred_mfc_address = value

    def configuration_dict(self) -> dict:
        """Return the current engine configuration as a serialisable mapping."""
        return {
            "poll_interval_ms": self._timer.interval(),
            "connection": {
                "driver": self._preferred_driver_name,
                "transport": self._preferred_transport_name,
                "address": self._preferred_address,
            },
            "mfc_connection": {
                "driver": self._preferred_mfc_driver_name,
                "transport": self._preferred_mfc_transport_name,
                "address": self._preferred_mfc_address,
            },
        }

    def save_configuration(self):
        """Persist the current engine configuration to the user config file."""
        return save_pressure_controller_config(self.configuration_dict())

    def set_poll_interval(self, ms: int) -> None:
        """Set the polling interval in milliseconds."""
        self._timer.setInterval(max(100, ms))

    def set_flow_rate(self, channel: int, value: float) -> None:
        """Program a flow setpoint on the connected MFC."""
        driver = self._require_mfc_driver()
        driver.set_setpoint(float(value), channel=channel)
        self._last_flow_setpoints[channel] = float(value)

    def set_target_pressure(self, channel: int, value: float) -> None:
        """Program a pressure target on the connected pressure-capable MFC."""
        driver = self._require_mfc_driver()
        caps = driver.get_capabilities()
        if not caps.supports_pressure_control:
            raise RuntimeError(f"{type(driver).__name__} does not support pressure-control setpoints.")
        driver.set_setpoint(float(value), channel=channel)
        self._last_target_pressures[channel] = float(value)

    def set_gauge_channel_enabled(self, channel: int, enabled: bool) -> None:
        """Enable or disable one pressure-gauge channel."""
        driver = self._require_pressure_driver()
        driver.set_gauge_on(channel, enabled)
        self._gauge_channel_enabled[channel] = bool(enabled)

    def read_controller_state(self) -> PressureEngineState | None:
        """Poll connected controllers once and publish the resulting state."""
        with self._engine_lock:
            if self._driver is None and self._mfc_driver is None:
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
        return replace(
            self._latest_state,
            engine_status=self._status,
            driver_name=self._connected_driver_name,
            mfc_driver_name=self._connected_mfc_driver_name,
        )

    @pyqtSlot()
    def shutdown(self) -> None:
        """Stop polling, disconnect controllers, and release the singleton."""
        self._timer.stop()
        with self._engine_lock:
            if self._driver is not None:
                self._disconnect_driver(self._driver, log_context="on shutdown")
            if self._mfc_driver is not None:
                self._disconnect_driver(self._mfc_driver, log_context="on shutdown")
            self._driver = None
            self._mfc_driver = None
            self._connected_driver_name = None
            self._connected_transport_name = None
            self._connected_address = None
            self._connected_mfc_driver_name = None
            self._connected_mfc_transport_name = None
            self._connected_mfc_address = None
            self._gauge_channel_enabled.clear()
            self._last_flow_setpoints.clear()
            self._last_target_pressures.clear()
            self._last_flow_unit = None
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
        mfc_connection = config.get("mfc_connection")
        if isinstance(mfc_connection, dict):
            self._preferred_mfc_driver_name = str(mfc_connection.get("driver", ""))
            self._preferred_mfc_transport_name = str(mfc_connection.get("transport", "Null (test)"))
            self._preferred_mfc_address = str(mfc_connection.get("address", ""))
        poll_interval = config.get("poll_interval_ms")
        if isinstance(poll_interval, int):
            self.set_poll_interval(poll_interval)

    def _resolve_pressure_driver_class(self, driver_name: str) -> type[PressureGaugeController]:
        manager = InstrumentDriverManager()
        manager.discover()
        driver_cls = manager.get(driver_name)
        if driver_cls is None:
            raise ValueError(f"Unknown pressure driver: {driver_name!r}")
        if not issubclass(driver_cls, PressureGaugeController):
            raise ValueError(f"Driver {driver_name!r} is not a pressure-controller driver")
        return driver_cls

    def _resolve_mfc_driver_class(self, driver_name: str) -> type[MassFlowController]:
        manager = InstrumentDriverManager()
        manager.discover()
        driver_cls = manager.get(driver_name)
        if driver_cls is None:
            raise ValueError(f"Unknown mass-flow driver: {driver_name!r}")
        if not issubclass(driver_cls, MassFlowController):
            raise ValueError(f"Driver {driver_name!r} is not a mass-flow-controller driver")
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

    def _build_pressure_protocol(self, driver_name: str) -> BaseProtocol:
        if "leyboldcenter" in driver_name.replace("_", "").lower() or "center" in driver_name.lower():
            return LeyboldCenterProtocol()
        return ScpiProtocol()

    def _build_mfc_protocol(self, driver_name: str) -> BaseProtocol:
        lowered = driver_name.replace("_", "").lower()
        if "pr4000" in lowered:
            return MKSPR4000Protocol()
        if "psr" in lowered:
            return MKSPSRProtocol()
        return ScpiProtocol()

    def _disconnect_driver(self, driver: object, *, log_context: str) -> None:
        try:
            if getattr(driver, "is_connected", False):
                driver.disconnect()
        except Exception:
            logger.exception("Error while disconnecting %s", log_context)

    @pyqtSlot()
    def _poll(self) -> None:
        self.read_controller_state()

    def _build_state(self) -> PressureEngineState:
        now = datetime.now(tz=UTC)
        readings: dict[int, PressureReading] = {}
        flow_actual: dict[int, float] = {}
        flow_setpoints: dict[int, float] = dict(self._last_flow_setpoints)
        target_pressures: dict[int, float] = dict(self._last_target_pressures)
        gauge_channel_enabled: dict[int, bool | None] = dict(self._gauge_channel_enabled)
        pressure_unit: PressureUnit | str | None = None
        flow_unit: int | str | None = self._last_flow_unit

        if self._driver is not None:
            readings = self._driver.read_all_pressures()
            pressure_unit = next((reading.unit for reading in readings.values()), None)
            for channel, reading in readings.items():
                if reading.status == PressureStatus.SWITCHED_OFF:
                    gauge_channel_enabled[channel] = False
                else:
                    gauge_channel_enabled.setdefault(channel, True)

        if self._mfc_driver is not None:
            caps = self._mfc_driver.get_capabilities()
            for channel in range(1, caps.channel_count + 1):
                flow_actual[channel] = float(self._mfc_driver.read_actual_value(channel=channel))
                try:
                    value = float(self._mfc_driver.read_setpoint(channel=channel))
                    flow_setpoints.setdefault(channel, value)
                except Exception:
                    logging.getLogger(__name__).debug(
                        "Failed to read MFC setpoint for channel %s",
                        channel,
                        exc_info=True,
                    )
                try:
                    flow_unit = self._mfc_driver.read_unit(channel=channel)
                except Exception:
                    logging.getLogger(__name__).debug(
                        "Failed to read MFC engineering unit for channel %s",
                        channel,
                        exc_info=True,
                    )
            self._last_flow_unit = flow_unit
            self._last_flow_setpoints = dict(flow_setpoints)
            for channel, value in target_pressures.items():
                flow_setpoints.setdefault(channel, value)

        reading = PressureEngineReading(
            timestamp=now,
            readings=readings,
            flow_actual=flow_actual,
            flow_setpoints=flow_setpoints,
            target_pressures=target_pressures,
            unit=pressure_unit,
            flow_unit=flow_unit,
        )
        return PressureEngineState(
            reading=reading,
            readings=readings,
            flow_actual=flow_actual,
            flow_setpoints=flow_setpoints,
            target_pressures=target_pressures,
            gauge_channel_enabled=gauge_channel_enabled,
            engine_status=PressureEngineStatus.POLLING,
            driver_name=self._connected_driver_name,
            mfc_driver_name=self._connected_mfc_driver_name,
            unit=pressure_unit,
            flow_unit=flow_unit,
        )

    def _derive_status(self) -> PressureEngineStatus:
        if self._status == PressureEngineStatus.STOPPED:
            return PressureEngineStatus.STOPPED
        if self._driver is None and self._mfc_driver is None:
            return PressureEngineStatus.DISCONNECTED
        return PressureEngineStatus.CONNECTED

    def _set_status(self, status: PressureEngineStatus) -> None:
        if status == self._status:
            return
        self._status = status
        self.publisher.engine_status_changed.emit(status)

    def _ensure_running(self) -> None:
        if self._status == PressureEngineStatus.STOPPED:
            raise RuntimeError("Engine has been shut down and cannot accept new connections.")

    def _require_pressure_driver(self) -> PressureGaugeController:
        if self._driver is None:
            raise RuntimeError("No pressure controller is connected.")
        return self._driver

    def _require_mfc_driver(self) -> MassFlowController:
        if self._mfc_driver is None:
            raise RuntimeError("No mass flow controller is connected.")
        return self._mfc_driver


def _qapp():
    from qtpy.QtWidgets import QApplication

    return QApplication.instance()
