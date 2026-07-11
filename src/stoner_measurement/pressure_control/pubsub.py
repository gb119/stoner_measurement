"""Publisher/subscriber bus for the pressure controller engine."""

from __future__ import annotations

from qtpy.QtCore import QObject

from stoner_measurement.pressure_control.types import (
    PressureEngineReading,
    PressureEngineState,
    PressureEngineStatus,
)
from stoner_measurement.qt_compat import pyqtSignal


class PressurePublisher(QObject):
    """Qt-signal based pub/sub bus for pressure controller data."""

    reading_updated: pyqtSignal = pyqtSignal(PressureEngineReading)
    state_updated: pyqtSignal = pyqtSignal(PressureEngineState)
    engine_status_changed: pyqtSignal = pyqtSignal(PressureEngineStatus)
    connection_changed: pyqtSignal = pyqtSignal()
    poll_activity: pyqtSignal = pyqtSignal()
