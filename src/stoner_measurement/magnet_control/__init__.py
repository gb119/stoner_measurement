"""Magnet controller engine and associated types.

Provides the singleton :class:`MagnetControllerEngine` that mediates all
communication with a magnet controller instrument, the pub/sub
:class:`MagnetPublisher` for distributing live data, and the data-model
types used to carry state between the engine and its subscribers.
"""

from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.magnet_control.pubsub import MagnetPublisher
from stoner_measurement.magnet_control.types import (
    MagnetEngineState,
    MagnetEngineStatus,
    MagnetReading,
    MagnetStabilityConfig,
)

__all__ = [
    "MagnetControllerEngine",
    "MagnetEngineState",
    "MagnetEngineStatus",
    "MagnetPublisher",
    "MagnetReading",
    "MagnetStabilityConfig",
]
