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
    flow_actual: dict[int, float] = field(default_factory=dict)
    flow_setpoints: dict[int, float] = field(default_factory=dict)
    target_pressures: dict[int, float] = field(default_factory=dict)
    unit: PressureUnit | str | None = None
    flow_unit: int | str | None = None


@dataclass
class PressureEngineState:
    """A consolidated snapshot of the pressure controller engine state."""

    reading: PressureEngineReading | None = None
    readings: dict[int, PressureReading] = field(default_factory=dict)
    flow_actual: dict[int, float] = field(default_factory=dict)
    flow_setpoints: dict[int, float] = field(default_factory=dict)
    target_pressures: dict[int, float] = field(default_factory=dict)
    gauge_channel_enabled: dict[int, bool | None] = field(default_factory=dict)
    interlocks: dict[str, bool | str | int | None] = field(default_factory=dict)
    engine_status: PressureEngineStatus = field(default=PressureEngineStatus.DISCONNECTED)
    driver_name: str | None = None
    mfc_driver_name: str | None = None
    unit: PressureUnit | str | None = None
    flow_unit: int | str | None = None
