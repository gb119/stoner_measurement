"""SI-aware spin box with an explicit automatic-value state."""

from __future__ import annotations

from qtpy.QtCore import QPoint, Qt  # type: ignore[attr-defined]
from qtpy.QtGui import QContextMenuEvent
from qtpy.QtWidgets import QMenu

from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.widgets.si_spinbox import SISpinBox

__all__ = ["AutoSISpinBox"]


class AutoSISpinBox(SISpinBox):
    """An :class:`SISpinBox` that can display and retain an ``Auto`` state.

    ``Auto`` may be typed directly or selected from the editor's context menu.
    Entering, stepping to, or programmatically setting a numeric value clears
    the automatic state while retaining normal SI units and validation.
    """

    autoChanged = pyqtSignal(bool)  # noqa: N815 - preserve Qt signal naming convention

    def __init__(self, *args, auto: bool = False, **kwargs) -> None:
        """Initialise the spin box and optionally select automatic mode."""
        self._auto = False
        super().__init__(*args, **kwargs)
        self.lineEdit().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.lineEdit().customContextMenuRequested.connect(self._show_context_menu)
        if auto:
            self.setAuto(True)

    def isAuto(self) -> bool:  # noqa: N802 - Qt-style API
        """Return whether the widget currently represents automatic mode."""
        return self._auto

    def setAuto(self, automatic: bool = True) -> None:  # noqa: N802 - Qt-style API
        """Select or clear automatic mode."""
        automatic = bool(automatic)
        changed = automatic != self._auto
        self._auto = automatic
        self.updateText()
        if changed:
            self.autoChanged.emit(automatic)

    def setValue(self, value=None, update=True, delaySignal=False):  # noqa: N802
        """Set a numeric value, clearing automatic mode for explicit values."""
        was_auto = getattr(self, "_auto", False)
        if value is not None and was_auto:
            self._auto = False
        result = super().setValue(value, update=update, delaySignal=delaySignal)
        if value is not None and was_auto:
            self.autoChanged.emit(False)
        return result

    def interpret(self) -> float | int | bool:
        """Accept the literal text ``Auto`` as the current numeric value."""
        if self.lineEdit().text().strip().casefold() == "auto":
            return self.value()
        return super().interpret()

    def editingFinishedEvent(self) -> None:  # noqa: N802 - pyqtgraph callback name
        """Commit typed ``Auto`` or an explicit numeric value."""
        if self.lineEdit().text().strip().casefold() == "auto":
            self.setAuto(True)
            return

        parsed = super().interpret()
        if parsed is False:
            self.updateText()
            return
        was_auto = self._auto
        self._auto = False
        super().setValue(parsed, update=True, delaySignal=False)
        self.updateText()
        if was_auto:
            self.autoChanged.emit(False)

    def updateText(self) -> None:  # noqa: N802 - pyqtgraph override name
        """Render ``Auto`` instead of the retained numeric fallback value."""
        if not getattr(self, "_auto", False):
            super().updateText()
            return
        self.skipValidate = True
        try:
            self.lineEdit().setText("Auto")
            self.lastText = "Auto"
        finally:
            self.skipValidate = False

    def _create_context_menu(self) -> QMenu:
        """Create the standard editor menu with an additional Auto action."""
        menu = self.lineEdit().createStandardContextMenu()
        menu.addSeparator()
        auto_action = menu.addAction("Auto")
        auto_action.setCheckable(True)
        auto_action.setChecked(self._auto)
        auto_action.triggered.connect(lambda _checked=False: self.setAuto(True))
        return menu

    def _show_context_menu(self, position: QPoint) -> None:
        """Show the augmented editor context menu at *position*."""
        menu = self._create_context_menu()
        menu.exec(self.lineEdit().mapToGlobal(position))
        menu.deleteLater()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        """Show the augmented menu when the spin-box frame is right-clicked."""
        self._show_context_menu(self.lineEdit().mapFromGlobal(event.globalPos()))
        event.accept()
