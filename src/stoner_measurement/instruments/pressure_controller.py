"""Abstract pressure-gauge controller interfaces."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class PressureUnit(Enum):
    """Pressure units reported by supported gauge controllers."""

    MBAR = "mbar"
    TORR = "Torr"
    PASCAL = "Pa"
    MICRON = "Micron"


class PressureStatus(Enum):
    """Normalised pressure-channel status."""

    OK = "ok"
    UNDERRANGE = "underrange"
    OVERRANGE = "overrange"
    TRANSMITTER_ERROR = "transmitter_error"
    SWITCHED_OFF = "switched_off"
    NO_TRANSMITTER = "no_transmitter"
    IDENTIFICATION_ERROR = "identification_error"
    ITR_ERROR = "itr_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PressureReading:
    """One pressure-channel reading.

    ``value`` is ``None`` unless ``status`` is :attr:`PressureStatus.OK`.
    """

    channel: int
    value: float | None
    unit: PressureUnit | str
    status: PressureStatus | str
    raw_status: int | str | None = None


@dataclass(frozen=True)
class PressureSetpoint:
    """Relay/setpoint threshold configuration."""

    source_channel: int | None
    lower: float
    upper: float
    unit: PressureUnit | str
    enabled: bool = True


@dataclass(frozen=True)
class PressureRelayState:
    """Relay state reported by a pressure-gauge controller."""

    index: int
    state: bool | None
    raw_state: int | str


@dataclass(frozen=True)
class PressureControllerCapabilities:
    """Static pressure-controller capability descriptor."""

    serial: bool
    pressure_query: bool
    remote_setpoints: bool
    remote_gauge_control: bool
    pump_control: bool
    analogue_only: bool
    max_channels: int
    max_relays: int
    interlocks: bool = False


class PressureGaugeController(BaseInstrument):
    """Abstract base class for pressure-gauge controller instruments."""

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol) -> None:
        """Initialise the pressure-gauge controller."""
        super().__init__(transport=transport, protocol=protocol, auto_check_errors=False)

    @abstractmethod
    def identify(self) -> str:
        """Return an instrument identity or model string."""

    @abstractmethod
    def read_pressure(self, channel: int) -> PressureReading:
        """Read one pressure channel."""

    @abstractmethod
    def read_all_pressures(self) -> dict[int, PressureReading]:
        """Read all available pressure channels."""

    @abstractmethod
    def get_gauge_type(self, channel: int) -> str | None:
        """Return the transmitter type for *channel*, if known."""

    @abstractmethod
    def set_gauge_on(self, channel: int, enabled: bool) -> None:
        """Switch a gauge channel on or off when supported."""

    @abstractmethod
    def zero_gauge(self, channel: int) -> None:
        """Zero a gauge channel when supported."""

    @abstractmethod
    def degas_gauge(self, channel: int, enabled: bool) -> None:
        """Enable or disable degas for *channel* when supported."""

    @abstractmethod
    def get_setpoint(self, index: int) -> PressureSetpoint:
        """Return one relay/setpoint configuration."""

    @abstractmethod
    def set_setpoint(self, index: int, setpoint: PressureSetpoint) -> None:
        """Update one relay/setpoint configuration."""

    @abstractmethod
    def read_relay(self, index: int) -> PressureRelayState:
        """Return one relay output state."""

    @abstractmethod
    def set_relay(self, index: int, enabled: bool) -> None:
        """Enable or disable one relay output when supported."""

    def read_interlocks(self) -> dict[str, bool | str | int | None]:
        """Return current named interlock states when supported."""
        return {}

    @abstractmethod
    def get_capabilities(self) -> PressureControllerCapabilities:
        """Return static capability metadata."""
