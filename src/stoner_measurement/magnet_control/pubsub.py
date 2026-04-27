"""Publisher/subscriber bus for the magnet controller engine.

Provides :class:`MagnetPublisher`, a :class:`~PyQt6.QtCore.QObject`
subclass whose Qt signals serve as the pub/sub channels between the
:class:`~stoner_measurement.magnet_control.engine.MagnetControllerEngine`
and any number of subscribers (UI panels, sequence plugins, monitors).
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from stoner_measurement.magnet_control.types import (
    MagnetEngineState,
    MagnetEngineStatus,
    MagnetReading,
)


class MagnetPublisher(QObject):
    """Qt-signal based pub/sub bus for magnet controller data.

    Holds one signal per logical topic.  The engine emits these signals after
    each polling cycle; subscribers connect to whichever topics they require.

    Because all objects live in the Qt main thread no explicit locking is
    needed — Qt's signal/slot mechanism provides the necessary serialisation.

    Attributes:
        reading_updated (pyqtSignal):
            Emitted after each poll with the latest
            :class:`~stoner_measurement.magnet_control.types.MagnetReading`.
        state_updated (pyqtSignal):
            Emitted once per poll with a complete
            :class:`~stoner_measurement.magnet_control.types.MagnetEngineState`
            snapshot.
        engine_status_changed (pyqtSignal):
            Emitted whenever the engine's
            :class:`~stoner_measurement.magnet_control.types.MagnetEngineStatus`
            changes.  Carries the new status value.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.magnet_control.pubsub import MagnetPublisher
        >>> pub = MagnetPublisher()
        >>> received = []
        >>> pub.engine_status_changed.connect(received.append)
        >>> from stoner_measurement.magnet_control.types import MagnetEngineStatus
        >>> pub.engine_status_changed.emit(MagnetEngineStatus.POLLING)
        >>> received[0]
        <MagnetEngineStatus.POLLING: 'polling'>
    """

    reading_updated: pyqtSignal = pyqtSignal(MagnetReading)
    state_updated: pyqtSignal = pyqtSignal(MagnetEngineState)
    engine_status_changed: pyqtSignal = pyqtSignal(MagnetEngineStatus)
