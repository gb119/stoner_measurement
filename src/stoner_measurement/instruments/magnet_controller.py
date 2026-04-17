"""Abstract interfaces for superconducting magnet power supply instruments.

Defines shared types and abstract interfaces for magnet controller drivers.
Magnetic field values are in tesla and ramp rates in tesla per minute unless
otherwise stated.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class MagnetState(Enum):
    STANDBY = "standby"
    RAMPING = "ramping"
    AT_TARGET = "at_target"
    PERSISTENT = "persistent"
    QUIESCENT = "quiescent"
    FAULT = "fault"
    QUENCH = "quench"
    UNKNOWN = "unknown"


@dataclass
class MagnetLimits:
    max_current: float  # A
    max_field: float | None = None  # T
    max_ramp_rate: float | None = None  # A/s or T/min


@dataclass
class MagnetStatus:
    state: MagnetState
    current: float          # A
    field: float | None  # T, if known
    voltage: float | None  # V
    persistent: bool
    heater_on: bool | None
    at_target: bool
    message: str | None = None


class MagnetSupply(Protocol):
    # --- lifecycle ---
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...

    # context manager sugar
    def __enter__(self) -> MagnetSupply: ...
    def __exit__(self, exc_type, exc, tb) -> None: ...

    # --- identity & configuration ---
    def identify(self) -> str: ...
    def get_model(self) -> str: ...
    def get_firmware_version(self) -> str: ...

    # --- readings as properties ---
    @property
    def current(self) -> float: ...

    @property
    def field(self) -> float: ...

    @property
    def voltage(self) -> float: ...

    @property
    def status(self) -> MagnetStatus: ...

    @property
    def magnet_constant(self) -> float: ...

    @property
    def limits(self) -> MagnetLimits: ...

    @property
    def heater(self) -> bool: ...

    # --- configuration as methods ---
    def set_target_current(self, current: float) -> None: ...
    def set_target_field(self, field: float) -> None: ...
    def set_ramp_rate_current(self, rate: float) -> None: ...
    def set_ramp_rate_field(self, rate: float) -> None: ...
    def set_magnet_constant(self, tesla_per_amp: float) -> None: ...
    def set_limits(self, limits: MagnetLimits) -> None: ...

    # --- actions as methods ---
    def ramp_to_target(self) -> None: ...
    def ramp_to_current(self, current: float, *, wait: bool = False) -> None: ...
    def ramp_to_field(self, field: float, *, wait: bool = False) -> None: ...
    def pause_ramp(self) -> None: ...
    def abort_ramp(self) -> None: ...

    # --- persistent switch ---
    def heater_on(self) -> None: ...
    def heater_off(self) -> None: ...


class MagnetController(BaseInstrument):
    """Abstract base class for superconducting magnet power supply drivers.

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol layer instance.
    """

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol) -> None:
        """Initialise the magnet controller.

        Args:
            transport (BaseTransport):
                Transport layer used for physical I/O.
            protocol (BaseProtocol):
                Protocol layer used for command formatting/parsing.
        """
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def get_model(self) -> str:
        """Return the instrument model identifier."""

    @abstractmethod
    def get_firmware_version(self) -> str:
        """Return the firmware version string."""

    @property
    @abstractmethod
    def current(self) -> float:
        """Return current output in amps."""

    @property
    @abstractmethod
    def field(self) -> float:
        """Return field output in tesla."""

    @property
    @abstractmethod
    def voltage(self) -> float:
        """Return output voltage in volts."""

    @property
    @abstractmethod
    def status(self) -> MagnetStatus:
        """Return consolidated magnet status."""

    @property
    @abstractmethod
    def magnet_constant(self) -> float:
        """Return magnet constant in tesla per amp."""

    @property
    @abstractmethod
    def limits(self) -> MagnetLimits:
        """Return configured magnet limits."""

    @property
    @abstractmethod
    def heater(self) -> bool:
        """Return persistent switch heater state."""

    @abstractmethod
    def set_target_current(self, current: float) -> None:
        """Set target current in amps."""

    @abstractmethod
    def set_target_field(self, field: float) -> None:
        """Set target field in tesla."""

    @abstractmethod
    def set_ramp_rate_current(self, rate: float) -> None:
        """Set current ramp rate."""

    @abstractmethod
    def set_ramp_rate_field(self, rate: float) -> None:
        """Set field ramp rate."""

    @abstractmethod
    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        """Set magnet constant."""

    @abstractmethod
    def set_limits(self, limits: MagnetLimits) -> None:
        """Set controller limits."""

    @abstractmethod
    def ramp_to_target(self) -> None:
        """Ramp to the currently programmed target."""

    @abstractmethod
    def ramp_to_current(self, current: float, *, wait: bool = False) -> None:
        """Ramp to a specific current."""

    @abstractmethod
    def ramp_to_field(self, field: float, *, wait: bool = False) -> None:
        """Ramp to a specific field."""

    @abstractmethod
    def pause_ramp(self) -> None:
        """Pause an active ramp."""

    @abstractmethod
    def abort_ramp(self) -> None:
        """Abort ramping immediately."""

    @abstractmethod
    def heater_on(self) -> None:
        """Enable persistent heater."""

    @abstractmethod
    def heater_off(self) -> None:
        """Disable persistent heater."""
