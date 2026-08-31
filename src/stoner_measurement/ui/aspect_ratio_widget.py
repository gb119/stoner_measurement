"""Layout helper for widgets that should not grow taller than an aspect ratio."""

from __future__ import annotations

from qtpy.QtCore import QSize, Qt
from qtpy.QtWidgets import QSizePolicy, QStyle, QTableWidget, QVBoxLayout, QWidget

from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget


def set_table_visible_row_count(table: QTableWidget, row_count: int) -> None:
    """Fix *table* height to its header plus exactly *row_count* body rows."""
    if row_count < 0:
        raise ValueError("row_count must not be negative")
    header_height = 0 if table.horizontalHeader().isHidden() else table.horizontalHeader().height()
    height = (
        header_height
        + row_count * table.verticalHeader().defaultSectionSize()
        + 2 * table.frameWidth()
    )
    table.setFixedHeight(height)


class MaximumAspectRatioWidget(QWidget):
    """Host a child at full width, limiting its height when space is plentiful.

    The child may become wider than the requested ratio when vertical space is
    tight, but it will not become taller than the ratio allows when the parent
    layout supplies excess height.
    """

    def __init__(
        self,
        child: QWidget,
        aspect_ratio: float = 4.0 / 3.0,
        parent: QWidget | None = None,
    ) -> None:
        """Create a top-aligned container for *child*."""
        super().__init__(parent)
        if aspect_ratio <= 0.0:
            raise ValueError("aspect_ratio must be positive")
        self._child = child
        self._aspect_ratio = float(aspect_ratio)
        self._child.setMinimumHeight(0)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._child)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        """Report that the preferred height is derived from the width."""
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        """Return the height matching the configured aspect ratio."""
        return max(0, round(width / self._aspect_ratio))

    def sizeHint(self) -> QSize:  # noqa: N802
        """Return a ratio-correct hint based on the child's preferred width."""
        width = max(0, self._child.sizeHint().width())
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        """Allow parent layouts to shrink the container when space is tight."""
        return QSize(0, 0)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Keep the child no taller than the configured width-to-height ratio."""
        maximum_height = round(self.width() / self._aspect_ratio)
        self._child.setFixedHeight(min(self.height(), maximum_height))
        super().resizeEvent(event)


class ContentWrappingTabWidget(FontAwareTabWidget):
    """A tab widget whose preferred height wraps its tallest page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Create a horizontally expanding, vertically capped tab widget."""
        super().__init__(parent)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        """Report that page content may derive its height from tab width."""
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        """Return the height required by the tallest page at *width*."""
        frame = 2 * self.style().pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth, None, self)
        page_width = max(0, width - frame)
        page_heights: list[int] = []
        for index in range(self.count()):
            page_layout = self.widget(index).layout()
            if page_layout is None:
                page_heights.append(self.widget(index).sizeHint().height())
            else:
                margins = page_layout.contentsMargins()
                inner_width = max(0, page_width - margins.left() - margins.right())
                item_heights = []
                for item_index in range(page_layout.count()):
                    item = page_layout.itemAt(item_index)
                    item_widget = item.widget()
                    if item_widget is not None and item_widget.hasHeightForWidth():
                        item_heights.append(item_widget.heightForWidth(inner_width))
                    elif item.hasHeightForWidth():
                        item_heights.append(item.heightForWidth(inner_width))
                    else:
                        item_heights.append(item.sizeHint().height())
                spacing = max(0, page_layout.spacing()) * max(0, len(item_heights) - 1)
                page_heights.append(margins.top() + sum(item_heights) + spacing + margins.bottom())
        content_height = max(page_heights, default=0)
        return self.tabBar().sizeHint().height() + content_height + frame

    def sizeHint(self) -> QSize:  # noqa: N802
        """Return a height-for-width aware preferred size."""
        hint = super().sizeHint()
        width = max(hint.width(), self.width())
        return QSize(width, self.heightForWidth(width))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Recalculate the preferred height when the available width changes."""
        width_changed = event.size().width() != event.oldSize().width()
        super().resizeEvent(event)
        if width_changed:
            self.updateGeometry()
