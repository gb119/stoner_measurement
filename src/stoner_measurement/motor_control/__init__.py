"""Motor controller engine and associated types.

Provides the singleton :class:`MotorControllerEngine` that mediates all
communication with a motor controller instrument, the pub/sub
:class:`MotorPublisher` for distributing live data, and the data-model
types used to carry state between the engine and its subscribers.
"""

from stoner_measurement.motor_control.engine import MotorControllerEngine
from stoner_measurement.motor_control.pubsub import MotorPublisher
from stoner_measurement.motor_control.types import (
    MotorEngineState,
    MotorEngineStatus,
    MotorReading,
    MotorStabilityConfig,
)

__all__ = [
    "MotorControllerEngine",
    "MotorEngineState",
    "MotorEngineStatus",
    "MotorPublisher",
    "MotorReading",
    "MotorStabilityConfig",
]