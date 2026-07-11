"""Data-model types for the pressure controller engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from stoner_measurement.instruments.pressure_controller import PressureReading, PressureUnit


class PressureEngineStatus(Enum):
    """Operational status of the pressure controller engine."""

    STOPPED = "stopped"
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    POLLING = "polling"
    ERROR = "error"


@dataclass
class PressureEngineReading:
    """A timestamped snapshot of pressure readings from one poll."""

    timestamp: datetime
    readings: dict[int, PressureReading]
    unit: PressureUnit | str | None = None


@dataclass
class PressureEngineState:
    """A consolidated snapshot of the pressure controller engine state."""

    reading: PressureEngineReading | None = None
    readings: dict[int, PressureReading] = field(default_factory=dict)
    engine_status: PressureEngineStatus = field(default=PressureEngineStatus.DISCONNECTED)
    driver_name: str | None = None
    unit: PressureUnit | str | None = None
