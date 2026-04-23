"""Publisher/subscriber bus for the temperature controller engine.

Provides :class:`TemperaturePublisher`, a :class:`~PyQt6.QtCore.QObject`
subclass whose Qt signals serve as the pub/sub channels between the
:class:`~stoner_measurement.temperature_control.engine.TemperatureControllerEngine`
and any number of subscribers (UI panels, sequence plugins, monitors).
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from stoner_measurement.temperature_control.types import (
    EngineStatus,
    TemperatureChannelReading,
    TemperatureEngineState,
)


class TemperaturePublisher(QObject):
    """Qt-signal based pub/sub bus for temperature controller data.

    Holds one signal per logical topic.  The engine emits these signals after
    each polling cycle; subscribers connect to whichever topics they require.

    Because all objects live in the Qt main thread no explicit locking is
    needed — Qt's signal/slot mechanism provides the necessary serialisation.

    Attributes:
        channel_reading (pyqtSignal):
            Emitted for each sensor channel after a poll.  Carries a
            :class:`~stoner_measurement.temperature_control.types.TemperatureChannelReading`.
        state_updated (pyqtSignal):
            Emitted once per poll with a complete
            :class:`~stoner_measurement.temperature_control.types.TemperatureEngineState`
            snapshot covering all channels and loops.
        engine_status_changed (pyqtSignal):
            Emitted whenever the engine's :class:`~stoner_measurement.temperature_control.types.EngineStatus`
            changes.  Carries the new :class:`~stoner_measurement.temperature_control.types.EngineStatus` value.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.temperature_control.pubsub import TemperaturePublisher
        >>> pub = TemperaturePublisher()
        >>> received = []
        >>> pub.engine_status_changed.connect(received.append)
        >>> from stoner_measurement.temperature_control.types import EngineStatus
        >>> pub.engine_status_changed.emit(EngineStatus.POLLING)
        >>> received[0]
        <EngineStatus.POLLING: 'polling'>
    """

    channel_reading: pyqtSignal = pyqtSignal(TemperatureChannelReading)
    state_updated: pyqtSignal = pyqtSignal(TemperatureEngineState)
    engine_status_changed: pyqtSignal = pyqtSignal(EngineStatus)
