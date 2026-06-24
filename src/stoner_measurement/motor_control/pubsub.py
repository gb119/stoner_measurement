"""Publisher/subscriber bus for the motor controller engine."""

from __future__ import annotations

from qtpy.QtCore import QObject
from stoner_measurement.qt_compat import pyqtSignal

from stoner_measurement.motor_control.types import (
    MotorEngineState,
    MotorEngineStatus,
    MotorReading,
)


class MotorPublisher(QObject):
    """Qt-signal based pub/sub bus for motor controller data."""

    reading_updated: pyqtSignal = pyqtSignal(MotorReading)
    state_updated: pyqtSignal = pyqtSignal(MotorEngineState)
    engine_status_changed: pyqtSignal = pyqtSignal(MotorEngineStatus)