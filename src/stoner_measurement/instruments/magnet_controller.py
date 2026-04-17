"""Abstract base class for magnet controller instruments.

Defines the common interface for superconducting magnet power supply
controllers.  Concrete subclasses (e.g. Oxford IPS 120-10) implement the
abstract methods for the specific instrument's command set.

Magnetic field values are in Tesla and ramp rates in Tesla per minute unless
otherwise stated.
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Protocol


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
    max_field: Optional[float] = None  # T
    max_ramp_rate: Optional[float] = None  # A/s or T/min


@dataclass
class MagnetStatus:
    state: MagnetState
    current: float          # A
    field: Optional[float]  # T, if known
    voltage: Optional[float]  # V
    persistent: bool
    heater_on: Optional[bool]
    at_target: bool
    message: Optional[str] = None


class MagnetSupply(Protocol):
    # --- lifecycle ---
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...

    # context manager sugar
    def __enter__(self) -> "MagnetSupply": ...
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
