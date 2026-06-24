"""stoner_measurement — A Qt (PyQt5/PyQt6 via qtpy) application for running scientific measurements."""

from stoner_measurement.magnet_control import (
    MagnetControllerEngine,
    MagnetEngineState,
    MagnetEngineStatus,
    MagnetPublisher,
    MagnetReading,
    MagnetStabilityConfig,
)
from stoner_measurement.instruments import (
    SimulatedMagnetController,
    SimulatedMotorController,
    SimulatedTemperatureController,
)
from stoner_measurement.motor_control import (
    MotorControllerEngine,
    MotorEngineState,
    MotorEngineStatus,
    MotorPublisher,
    MotorReading,
    MotorStabilityConfig,
)
from stoner_measurement.temperature_control import (
    EngineStatus,
    LoopSettings,
    StabilityConfig,
    TemperatureChannelReading,
    TemperatureControllerEngine,
    TemperatureEngineState,
    TemperaturePublisher,
)

__version__ = "0.1.0"
__author__ = "Gavin Burnell"

__all__ = [
    "__author__",
    "__version__",
    "EngineStatus",
    "LoopSettings",
    "MagnetControllerEngine",
    "SimulatedMagnetController",
    "SimulatedMotorController",
    "SimulatedTemperatureController",
    "MagnetEngineState",
    "MagnetEngineStatus",
    "MagnetPublisher",
    "MagnetReading",
    "MagnetStabilityConfig",
    "MotorControllerEngine",
    "MotorEngineState",
    "MotorEngineStatus",
    "MotorPublisher",
    "MotorReading",
    "MotorStabilityConfig",
    "StabilityConfig",
    "TemperatureChannelReading",
    "TemperatureControllerEngine",
    "TemperatureEngineState",
    "TemperaturePublisher",
]
