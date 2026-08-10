"""Editable, refreshable selector for attached Thorlabs APT controllers."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QSizePolicy, QWidget

from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.widgets.visa_resource_widget import VisaResourceStatus

if TYPE_CHECKING:
    from stoner_measurement.instruments.thorlabs.hdr50 import AptControllerInfo

logger = logging.getLogger(__name__)

_DiscoveryFunction = Callable[[], Sequence["AptControllerInfo"]]
_STATUS_COLOURS = {
    VisaResourceStatus.CONNECTING: "#fff3cd",
    VisaResourceStatus.CONNECTED: "#90ee90",
    VisaResourceStatus.ERROR: "#f8d7da",
}


def _discover_apt_controllers() -> Sequence[AptControllerInfo]:
    from stoner_measurement.instruments.thorlabs.hdr50 import ThorlabsHDR50

    return ThorlabsHDR50.discover_controllers()


class AptControllerComboBox(QWidget):
    """Select an enumerated APT controller or manually enter its serial number."""

    serial_changed: pyqtSignal = pyqtSignal(str)
    refresh_requested: pyqtSignal = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        discover: _DiscoveryFunction | None = None,
        placeholder: str = "e.g. 70000001",
        auto_refresh: bool = False,
    ) -> None:
        super().__init__(parent)
        self._discover = discover or _discover_apt_controllers
        self._status = VisaResourceStatus.DISCONNECTED
        self._build_ui(placeholder)
        if auto_refresh:
            self.refresh()

    def current_serial(self) -> str:
        """Return the selected controller serial number or manual entry."""
        index = self._combo.currentIndex()
        data = self._combo.currentData()
        if data and index >= 0 and self._combo.currentText() == self._combo.itemText(index):
            return str(data).strip()
        return self._combo.currentText().strip()

    def set_serial(self, serial_number: str) -> None:
        """Select *serial_number*, retaining it as a manual entry if undiscovered."""
        serial = str(serial_number).strip()
        if not serial:
            self.clear()
            return
        index = self._combo.findData(serial)
        if index >= 0:
            self._combo.setCurrentIndex(index)
        else:
            self._combo.setCurrentIndex(-1)
            self._combo.setEditText(serial)

    def text(self) -> str:
        """Provide QLineEdit-compatible access for connection helpers."""
        return self.current_serial()

    def setText(self, text: str) -> None:  # noqa: N802 - QLineEdit compatibility
        self.set_serial(text)

    def clear(self) -> None:
        self._combo.setCurrentIndex(-1)
        self._combo.setEditText("")

    def refresh(self) -> None:
        """Re-enumerate controllers while preserving the current serial number."""
        previous = self.current_serial()
        try:
            controllers = list(self._discover())
        except Exception as exc:
            logger.error(f"Failed to refresh attached APT controllers: {exc}")
            controllers = []

        self._combo.blockSignals(True)
        self._combo.clear()
        for controller in controllers:
            label = controller.serial_number
            if controller.model:
                label = f"{label} — {controller.model}"
            self._combo.addItem(label, controller.serial_number)
            index = self._combo.count() - 1
            details = [controller.software_version, controller.hardware_notes]
            tooltip = "\n".join(value for value in details if value)
            if tooltip:
                self._combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
        self.set_serial(previous)
        self._combo.blockSignals(False)
        self.refresh_requested.emit()

    def set_status(self, status: VisaResourceStatus) -> None:
        self._status = status
        colour = _STATUS_COLOURS.get(status, "")
        self._combo.setStyleSheet(f"QComboBox {{ background-color: {colour}; }}" if colour else "")

    @property
    def status(self) -> VisaResourceStatus:
        return self._status

    @property
    def combo(self) -> QComboBox:
        return self._combo

    def _build_ui(self, placeholder: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._combo = QComboBox(self)
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._combo.setPlaceholderText(placeholder)
        self._combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._combo.currentTextChanged.connect(lambda _text: self.serial_changed.emit(self.current_serial()))
        layout.addWidget(self._combo)
        self._refresh_button = QPushButton("Refresh", self)
        self._refresh_button.setMinimumWidth(70)
        self._refresh_button.setToolTip("Re-scan for attached Thorlabs APT motor controllers")
        self._refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self._refresh_button)
