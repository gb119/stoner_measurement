"""Tab widgets whose labels reserve enough width for their selected font."""

from __future__ import annotations

from qtpy.QtCore import QEvent, QSize, Qt  # pylint: disable=no-name-in-module
from qtpy.QtGui import QFont, QFontMetrics  # pylint: disable=no-name-in-module
from qtpy.QtWidgets import QTabBar, QTabWidget, QWidget  # pylint: disable=no-name-in-module


class FontAwareTabBar(QTabBar):
    """Keep tab widths stable when the selected label becomes demi-bold."""

    def __init__(self, parent: QWidget | None = None) -> None:
        self._reserved_widths: dict[int, int] = {}
        super().__init__(parent)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.setUsesScrollButtons(True)

    def tabSizeHint(self, index: int) -> QSize:  # noqa: N802
        """Reserve the selected-font width while a tab is unselected."""
        result = super().tabSizeHint(index)
        if index != self.currentIndex():
            text = self.tabText(index)
            normal_font = self.font()
            selected_font = QFont(normal_font)
            selected_font.setWeight(QFont.Weight.DemiBold)
            normal_width = QFontMetrics(normal_font).horizontalAdvance(text)
            selected_width = QFontMetrics(selected_font).horizontalAdvance(text)
            result.setWidth(result.width() + max(0, selected_width - normal_width))

        # Some styles round the normal and demi-bold metrics differently by a
        # pixel. Retaining the largest result makes selection width invariant.
        reserved_width = max(result.width(), self._reserved_widths.get(index, 0))
        self._reserved_widths[index] = reserved_width
        result.setWidth(reserved_width)
        return result

    def setTabText(self, index: int, text: str) -> None:  # noqa: N802
        """Discard a cached width when a tab's label changes."""
        self._reserved_widths.pop(index, None)
        super().setTabText(index, text)

    def tabInserted(self, index: int) -> None:  # noqa: N802
        """Reset index-based reservations after inserting a tab."""
        self._reserved_widths.clear()
        super().tabInserted(index)

    def tabRemoved(self, index: int) -> None:  # noqa: N802
        """Reset index-based reservations after removing a tab."""
        self._reserved_widths.clear()
        super().tabRemoved(index)

    def event(self, event: QEvent) -> bool:
        """Recalculate reservations after font or style changes."""
        if event.type() in {
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        }:
            self._reserved_widths.clear()
        return super().event(event)


class FontAwareTabWidget(QTabWidget):
    """QTabWidget using :class:`FontAwareTabBar` for stable label sizing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabBar(FontAwareTabBar(self))
