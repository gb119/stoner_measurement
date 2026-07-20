"""Qt compatibility helpers."""

from qtpy.QtCore import Signal, Slot

pyqtSignal = Signal  # noqa: N816 - preserve Qt/PyQt public naming convention
pyqtSlot = Slot  # noqa: N816 - preserve Qt/PyQt public naming convention
