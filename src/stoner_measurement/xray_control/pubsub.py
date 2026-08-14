"""Qt signal bus for the X-ray diffractometer engine."""

from __future__ import annotations

from qtpy.QtCore import QObject

from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.xray_control.types import XrayEngineState, XrayEngineStatus


class XrayPublisher(QObject):
    """Distribute snapshots, status changes and operation outcomes."""

    state_updated: pyqtSignal = pyqtSignal(XrayEngineState)
    engine_status_changed: pyqtSignal = pyqtSignal(XrayEngineStatus)
    connection_changed: pyqtSignal = pyqtSignal()
    count_duration_changed: pyqtSignal = pyqtSignal(float)
    poll_activity: pyqtSignal = pyqtSignal()
    operation_failed: pyqtSignal = pyqtSignal(str)
    operation_finished: pyqtSignal = pyqtSignal()
