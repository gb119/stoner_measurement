"""Icon factories for the Stoner Measurement UI.

Provides functions that create :class:`~PyQt6.QtGui.QIcon` objects used
throughout the application.  Most icons are rendered programmatically so that
no external image files are required; the application logo is loaded from
bundled package data.
"""

from __future__ import annotations

import importlib.resources
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


def make_app_icon() -> QIcon:
    """Create the application icon from the bundled logo image.

    Loads `StonerLogo2.png` from the `stoner_measurement.ui` package data
    and returns it as a :class:`~PyQt6.QtGui.QIcon`.  Falls back to a null
    icon if the resource cannot be found.

    Returns:
        (QIcon):
            The application logo icon, or a null icon on failure.

    Examples:
        >>> icon = make_app_icon()
        >>> isinstance(icon, QIcon)
        True
    """
    try:
        pkg = importlib.resources.files("stoner_measurement.ui")
        resource = pkg.joinpath("StonerLogo2.png")
        with importlib.resources.as_file(resource) as path:
            return QIcon(str(path))
    except (FileNotFoundError, ModuleNotFoundError):
        return QIcon()


def make_log_icon(size: int = 32) -> QIcon:
    """Create a simple document-with-lines icon for the *Show Log* action.

    Draws a white rectangle (page) with three horizontal lines representing
    log entries, and a small coloured bullet on the left of each line to
    suggest severity colouring.

    Keyword Parameters:
        size (int):
            Side length in pixels of the square icon.  Defaults to ``32``.

    Returns:
        (QIcon):
            The rendered log icon.

    Examples:
        >>> icon = make_log_icon()
        >>> icon.isNull()
        False
    """
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size * 0.1
    page_w = size * 0.75
    page_h = size * 0.85
    page_x = (size - page_w) / 2.0
    page_y = (size - page_h) / 2.0

    # Draw page background.
    painter.setBrush(QColor(240, 240, 240))
    painter.setPen(QColor(160, 160, 160))
    painter.drawRoundedRect(int(page_x), int(page_y), int(page_w), int(page_h), 2, 2)

    # Draw three log lines with coloured bullets.
    bullet_colours = [QColor(100, 100, 200), QColor(200, 140, 0), QColor(200, 50, 50)]
    n_lines = 3
    line_spacing = page_h / (n_lines + 1)
    bullet_r = size * 0.055
    line_left = page_x + margin + bullet_r * 2.5
    line_right = page_x + page_w - margin
    painter.setPen(QColor(80, 80, 80))
    for i in range(n_lines):
        y = page_y + line_spacing * (i + 1)
        # Bullet
        painter.setBrush(bullet_colours[i])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(page_x + margin + bullet_r, y), bullet_r, bullet_r)
        # Line
        painter.setPen(QColor(80, 80, 80))
        painter.drawLine(QPointF(line_left, y), QPointF(line_right, y))

    painter.end()
    return QIcon(QPixmap.fromImage(img))
