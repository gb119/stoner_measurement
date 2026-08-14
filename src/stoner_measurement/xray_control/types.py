"""Published data types for the X-ray diffractometer engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from stoner_measurement.instruments.xray import XraySnapshot


class XrayEngineStatus(Enum):
    """Operational state of the X-ray engine."""

    STOPPED = "stopped"
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    POLLING = "polling"
    MOVING = "moving"
    COUNTING = "counting"
    ERROR = "error"


class XrayMotionMode(Enum):
    """Supported diffractometer motion relationships."""

    THETA = "theta"
    COUPLED = "theta-2theta"
    TWO_THETA = "2theta"


@dataclass(frozen=True)
class XrayEngineState:
    """One consolidated view of position, detector and engine state."""

    snapshot: XraySnapshot | None = None
    count_rate_hz: float | None = None
    count_elapsed_s: float | None = None
    target_deg: float | None = None
    theta_target_deg: float | None = None
    two_theta_target_deg: float | None = None
    theta_speed_deg_per_min: float = 0.0
    two_theta_speed_deg_per_min: float = 0.0
    moving: bool = False
    at_target: bool = False
    updated_at: datetime | None = None
    motion_mode: XrayMotionMode = XrayMotionMode.COUPLED
    two_theta_offset_deg: float = 0.0
    speed_deg_per_min: float = 1.0
    motion_enabled: bool = False
    engine_status: XrayEngineStatus = field(default=XrayEngineStatus.DISCONNECTED)


@dataclass(frozen=True)
class XrayConnectionInfo:
    """Current instrument selection exposed to the control panel."""

    instrument_name: str | None = None
    address: str | None = None

    @property
    def transport_name(self) -> str | None:
        """Compatibility alias for older callers."""
        return self.instrument_name
