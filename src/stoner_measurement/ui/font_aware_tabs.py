"""Tab widgets whose labels reserve enough space for their selected font."""

from __future__ import annotations

from qtpy.QtCore import QEvent, QSize, Qt  # pylint: disable=no-name-in-module
from qtpy.QtGui import QFont, QFontMetrics  # pylint: disable=no-name-in-module
from qtpy.QtWidgets import QTabBar, QTabWidget, QWidget  # pylint: disable=no-name-in-module


class FontAwareTabBar(QTabBar):
    """Keep tab extents stable when the selected label becomes demi-bold."""

    def __init__(self, parent: QWidget | None = None) -> None:
        self._reserved_extents: dict[tuple[int, bool], int] = {}
        super().__init__(parent)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.setUsesScrollButtons(True)

    def tabSizeHint(self, index: int) -> QSize:  # noqa: N802
        """Reserve the selected-font width regardless of selection order."""
        result = super().tabSizeHint(index)
        text = self.tabText(index)
        normal_font = self.font()
        selected_font = QFont(normal_font)
        selected_font.setWeight(QFont.Weight.DemiBold)
        normal_width = QFontMetrics(normal_font).horizontalAdvance(text)
        selected_width = QFontMetrics(selected_font).horizontalAdvance(text)
        width_allowance = max(0, selected_width - normal_width)
        vertical = self.shape() in {
            QTabBar.Shape.RoundedWest,
            QTabBar.Shape.RoundedEast,
            QTabBar.Shape.TriangularWest,
            QTabBar.Shape.TriangularEast,
        }
        if vertical:
            result.setHeight(result.height() + width_allowance)
        else:
            result.setWidth(result.width() + width_allowance)

        # A newly inserted first tab is already selected before Qt asks for its
        # size hint, while other tabs begin unselected. Applying the allowance
        # in both states avoids caching a normal-font width for that first tab.
        # Retaining the largest result also absorbs style rounding differences.
        cache_key = (index, vertical)
        extent = result.height() if vertical else result.width()
        reserved_extent = max(extent, self._reserved_extents.get(cache_key, 0))
        self._reserved_extents[cache_key] = reserved_extent
        if vertical:
            result.setHeight(reserved_extent)
        else:
            result.setWidth(reserved_extent)
        return result

    def setTabText(self, index: int, text: str) -> None:  # noqa: N802
        """Discard cached extents when a tab's label changes."""
        self._reserved_extents.clear()
        super().setTabText(index, text)

    def tabInserted(self, index: int) -> None:  # noqa: N802
        """Reset index-based reservations after inserting a tab."""
        self._reserved_extents.clear()
        super().tabInserted(index)

    def tabRemoved(self, index: int) -> None:  # noqa: N802
        """Reset index-based reservations after removing a tab."""
        self._reserved_extents.clear()
        super().tabRemoved(index)

    def event(self, event: QEvent) -> bool:
        """Recalculate reservations after font or style changes."""
        if event.type() in {
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        }:
            self._reserved_extents.clear()
        return super().event(event)


class FontAwareTabWidget(QTabWidget):
    """QTabWidget using :class:`FontAwareTabBar` for stable label sizing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabBar(FontAwareTabBar(self))
