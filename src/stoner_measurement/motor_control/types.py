"""Data-model types for the motor controller engine.

Defines the published data structures used to communicate state between the
:class:`~stoner_measurement.motor_control.engine.MotorControllerEngine`
and its subscribers (UI panels, sequence plugins, monitoring plugins).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MotorEngineStatus(Enum):
    """Operational status of the motor controller engine."""

    STOPPED = "stopped"
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    POLLING = "polling"
    ERROR = "error"


@dataclass
class MotorReading:
    """A timestamped snapshot of a single motor status reading."""

    timestamp: datetime
    angle: float
    target_angle: float | None
    moving: bool
    homed: bool | None = None
    displayed_angle: float | None = None
    angular_rate: float = 0.0
    at_target: bool = False
    revolutions: int = 0
    target_revolutions: int | None = None
    move_direction: str | None = None


@dataclass
class MotorEngineState:
    """A consolidated snapshot of the complete motor controller engine state."""

    reading: MotorReading | None = None
    target_angle: float | None = None
    velocity: float | None = None
    acceleration: float | None = None
    at_target: bool = False
    stable: bool = False
    engine_status: MotorEngineStatus = field(default=MotorEngineStatus.DISCONNECTED)
    displayed_angle: float | None = None
    revolutions: int = 0
    move_direction: str | None = None


@dataclass
class MotorStabilityConfig:
    """Configuration parameters defining what 'at target' means for a motor."""

    tolerance_deg: float = 0.01
    window_s: float = 0.5
    min_rate: float = 0.01
    unstable_holdoff_s: float = 0.2