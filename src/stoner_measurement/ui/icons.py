"""Icon factories for the Stoner Measurement UI.

Provides functions that create :class:`~PyQt6.QtGui.QIcon` objects used
throughout the application.  Icons are rendered programmatically so that
no external image files are required.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap, QPolygonF


def make_generate_icon(size: int = 32) -> QIcon:
    """Create a gear-style icon for the *Generate Code* action.

    Draws a simple eight-toothed gear with a transparent centre hole.

    Keyword Parameters:
        size (int):
            Side length in pixels of the square icon.  Defaults to ``32``.

    Returns:
        (QIcon):
            The rendered gear icon.

    Examples:
        >>> icon = make_generate_icon()
        >>> icon.isNull()
        False
    """
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx = size / 2.0
    cy = size / 2.0
    outer_r = size * 0.45
    inner_r = size * 0.32
    hole_r = size * 0.15
    n_teeth = 8
    total = n_teeth * 4

    # Build the gear outline as a polygon with alternating inner/outer radii.
    points: list[QPointF] = []
    for i in range(total):
        angle = math.pi * 2.0 * i / total - math.pi / (n_teeth * 2)
        r = outer_r if i % 4 in (0, 3) else inner_r
        points.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))

    painter.setBrush(QColor(70, 70, 70))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPolygon(QPolygonF(points))

    # Punch out the centre hole.
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    painter.drawEllipse(QPointF(cx, cy), hole_r, hole_r)

    painter.end()
    return QIcon(QPixmap.fromImage(img))
