"""Icon factories for the Stoner Measurement UI.

Provides functions that create :class:`~PyQt6.QtGui.QIcon` objects used
throughout the application.  Most icons are rendered programmatically so that
no external image files are required; the application logo is loaded from
bundled package data.
"""

from __future__ import annotations

import importlib.resources
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap, QPolygonF


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


def make_temperature_icon(size: int = 32) -> QIcon:
    """Create a simple thermometer icon for the *Temperature Control* action.

    Draws a thermometer outline with a filled bulb at the bottom and a column
    representing the mercury level.

    Keyword Parameters:
        size (int):
            Side length in pixels of the square icon.  Defaults to ``32``.

    Returns:
        (QIcon):
            The rendered thermometer icon.

    Examples:
        >>> icon = make_temperature_icon()
        >>> icon.isNull()
        False
    """
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx = size / 2.0
    bulb_r = size * 0.18
    bulb_cy = size * 0.78
    stem_w = size * 0.12
    stem_top = size * 0.08
    stem_bottom = bulb_cy - bulb_r * 0.6

    # Stem outline
    painter.setBrush(QColor(220, 220, 220))
    painter.setPen(QColor(100, 100, 100))
    painter.drawRoundedRect(
        int(cx - stem_w / 2),
        int(stem_top),
        int(stem_w),
        int(stem_bottom - stem_top),
        int(stem_w / 2),
        int(stem_w / 2),
    )

    # Mercury fill in stem (roughly 60 % full)
    fill_top = stem_top + (stem_bottom - stem_top) * 0.40
    painter.setBrush(QColor(200, 30, 30))
    painter.setPen(Qt.PenStyle.NoPen)
    inner_w = stem_w * 0.55
    painter.drawRect(
        int(cx - inner_w / 2),
        int(fill_top),
        int(inner_w),
        int(stem_bottom - fill_top),
    )

    # Bulb
    painter.setBrush(QColor(200, 30, 30))
    painter.setPen(QColor(100, 100, 100))
    painter.drawEllipse(QPointF(cx, bulb_cy), bulb_r, bulb_r)

    painter.end()
    return QIcon(QPixmap.fromImage(img))


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
    # pylint: disable=too-many-locals
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
    painter.end()
    return QIcon(QPixmap.fromImage(img))


def make_magnet_icon(size: int = 32) -> QIcon:
    """Create a horseshoe-magnet icon for the *Magnet Control* action.

    Draws a stylised horseshoe magnet with two blue poles connected by a
    curved yoke, with red/blue pole tips labelled *N* and *S*.

    Keyword Parameters:
        size (int):
            Side length in pixels of the square icon.  Defaults to ``32``.

    Returns:
        (QIcon):
            The rendered magnet icon.

    Examples:
        >>> icon = make_magnet_icon()
        >>> icon.isNull()
        False
    """
    # pylint: disable=too-many-locals
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pole_w = size * 0.22
    pole_h = size * 0.45
    gap = size * 0.20
    total_w = 2 * pole_w + gap
    left_x = (size - total_w) / 2.0
    right_x = left_x + pole_w + gap
    top_y = size * 0.10
    yoke_h = size * 0.22

    yoke_colour = QColor(40, 80, 200)
    outline_colour = QColor(20, 40, 120)
    outline_pen_width = max(1, size // 24)

    # Build the horseshoe path: outer arch minus inner cut-out + two legs.
    yoke_rect = QRectF(left_x, top_y, total_w, yoke_h * 2)
    yoke_path = QPainterPath()
    yoke_path.addRoundedRect(yoke_rect, yoke_h, yoke_h)

    inner_inset = pole_w * 0.9
    inner_rect = QRectF(
        left_x + inner_inset,
        top_y,
        gap - (inner_inset - pole_w) * 2,
        yoke_h * 2.5,
    )
    inner_path = QPainterPath()
    inner_path.addRoundedRect(inner_rect, yoke_h * 0.7, yoke_h * 0.7)
    horseshoe = yoke_path.subtracted(inner_path)

    left_pole_rect = QRectF(left_x, top_y + yoke_h, pole_w, pole_h)
    horseshoe.addRect(left_pole_rect)
    right_pole_rect = QRectF(right_x, top_y + yoke_h, pole_w, pole_h)
    horseshoe.addRect(right_pole_rect)

    # Fill body then pole tips.
    outline_pen = painter.pen()
    outline_pen.setColor(outline_colour)
    outline_pen.setWidth(outline_pen_width)
    painter.setBrush(yoke_colour)
    painter.setPen(outline_pen)
    painter.drawPath(horseshoe)

    tip_h = pole_h * 0.30
    tip_top = top_y + yoke_h + pole_h - tip_h

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(200, 40, 40))
    painter.drawRect(QRectF(left_x, tip_top, pole_w, tip_h))
    painter.setBrush(QColor(40, 100, 200))
    painter.drawRect(QRectF(right_x, tip_top, pole_w, tip_h))

    label_font = painter.font()
    label_font.setPixelSize(max(6, int(size * 0.22)))
    label_font.setBold(True)
    painter.setFont(label_font)
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(QRectF(left_x, tip_top, pole_w, tip_h), Qt.AlignmentFlag.AlignCenter, "N")
    painter.drawText(QRectF(right_x, tip_top, pole_w, tip_h), Qt.AlignmentFlag.AlignCenter, "S")

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(outline_pen)
    painter.drawPath(horseshoe)

    painter.end()
    return QIcon(QPixmap.fromImage(img))
