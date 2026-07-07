"""Status-bar indicators for background controller engines."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from qtpy.QtCore import QTimer
from qtpy.QtGui import QContextMenuEvent
from qtpy.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy, QWidget

from stoner_measurement.ui.theme import colour

_BLINK_MS = 140


class EngineActivityIndicator(QWidget):
    """Compact status indicator with a short pulse on each engine poll."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label_text = label
        self._status_text = "disconnected"
        self._base_colour = colour("status_default")
        self._menu_builder: Callable[[], QMenu | None] | None = None

        self._dot = QFrame(self)
        self._dot.setObjectName(f"{label.lower()}EngineActivityDot")
        self._dot.setFixedSize(10, 10)

        self._label = QLabel(label, self)
        self._label.setObjectName(f"{label.lower()}EngineActivityLabel")
        self._label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)
        layout.addWidget(self._dot)
        layout.addWidget(self._label)

        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(True)
        self._blink_timer.timeout.connect(self._restore_dot_colour)

        self.set_status("disconnected")

    @property
    def status_text(self) -> str:
        """Return the normalised status currently shown by the indicator."""
        return self._status_text

    def set_status(self, status: object) -> None:
        """Update the indicator colour and tooltip for an engine status."""
        status_text = _normalise_status(status)
        self._status_text = status_text
        self._base_colour = _colour_for_status(status_text)
        self._restore_dot_colour()
        self.setToolTip(f"{self._label_text}: {status_text}")

    def blink(self) -> None:
        """Briefly pulse the dot to show that a poll completed."""
        self._set_dot_colour(colour("highlight"))
        self._blink_timer.start(_BLINK_MS)

    def set_context_menu_builder(
        self, builder: Callable[[], QMenu | None] | None
    ) -> None:
        """Set the callable used to build a context menu for this indicator."""
        self._menu_builder = builder

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # type: ignore[override]
        """Show the indicator context menu, if one has been configured."""
        if self._menu_builder is None:
            super().contextMenuEvent(event)
            return
        menu = self._menu_builder()
        if menu is None:
            event.ignore()
            return
        menu.exec(event.globalPos())

    def _restore_dot_colour(self) -> None:
        self._set_dot_colour(self._base_colour)

    def _set_dot_colour(self, dot_colour: str) -> None:
        border = colour("border")
        self._dot.setStyleSheet(
            "QFrame { "
            f"background-color: {dot_colour}; "
            f"border: 1px solid {border}; "
            "border-radius: 5px; "
            "}"
        )


class EngineActivityStatusWidget(QWidget):
    """Container for the temperature, magnet, and motor engine indicators."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("engineActivityStatusWidget")
        self.temperature_indicator = EngineActivityIndicator("Temp", self)
        self.magnet_indicator = EngineActivityIndicator("Magnet", self)
        self.motor_indicator = EngineActivityIndicator("Motor", self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 2, 0)
        layout.setSpacing(8)
        layout.addWidget(self.temperature_indicator)
        layout.addWidget(self.magnet_indicator)
        layout.addWidget(self.motor_indicator)

    def set_temperature_status(self, status: object) -> None:
        """Update the temperature engine indicator."""
        self.temperature_indicator.set_status(status)

    def set_magnet_status(self, status: object) -> None:
        """Update the magnet engine indicator."""
        self.magnet_indicator.set_status(status)

    def set_motor_status(self, status: object) -> None:
        """Update the motor engine indicator."""
        self.motor_indicator.set_status(status)

    def blink_temperature(self) -> None:
        """Pulse the temperature engine indicator."""
        self.temperature_indicator.blink()

    def blink_magnet(self) -> None:
        """Pulse the magnet engine indicator."""
        self.magnet_indicator.blink()

    def blink_motor(self) -> None:
        """Pulse the motor engine indicator."""
        self.motor_indicator.blink()


def _normalise_status(status: object) -> str:
    if isinstance(status, Enum):
        return str(status.value).lower()
    return str(status).lower()


def _colour_for_status(status: str) -> str:
    if status == "error":
        return colour("status_error")
    if status in {"connected", "polling"}:
        return colour("status_connected")
    return colour("status_default")
