"""Icon factories for the Stoner Measurement UI.

Provides functions that create :class:`~PyQt6.QtGui.QIcon` objects used
throughout the application.  Where available, icons are loaded from bundled
PNG resources under ``stoner_measurement/ui/resources/``; others are rendered
programmatically.  Each loader falls back to a programmatic icon if the
resource file cannot be found.
"""

from __future__ import annotations

import importlib.resources
import importlib.resources.abc
import logging
import math

from qtpy.QtCore import QPointF, QRectF, Qt
from qtpy.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPixmap,
    QPolygonF,
)

from stoner_measurement.ui.theme import colour

logger = logging.getLogger(__name__)


def _load_resource_icon(resource_path: str) -> QIcon | None:
    """Load a PNG icon from the bundled resources directory.

    Args:
        resource_path (str):
            Path relative to the ``stoner_measurement.ui`` package root,
            e.g. ``"resources/build.png"``.

    Returns:
        (QIcon | None):
            The loaded icon, or ``None`` if the resource cannot be found or
            the resulting icon is null.
    """
    try:
        pkg = importlib.resources.files("stoner_measurement.ui")
        parts = resource_path.split("/")
        resource: importlib.resources.abc.Traversable = pkg
        for part in parts:
            resource = resource.joinpath(part)
        with importlib.resources.as_file(resource) as path:
            icon = QIcon(str(path))
            return icon if not icon.isNull() else None
    except (FileNotFoundError, ModuleNotFoundError):
        return None


def make_generate_icon(size: int = 32) -> QIcon:
    """Create an icon for the *Generate Code* action.

    Loads ``build.png`` from the bundled ``resources`` directory.  Falls back
    to a programmatically drawn gear icon if the resource cannot be found.

    Keyword Parameters:
        size (int):
            Side length in pixels of the square icon.  Defaults to ``32``.

    Returns:
        (QIcon):
            The build icon.

    Examples:
        >>> icon = make_generate_icon()
        >>> icon.isNull()
        False
    """
    try:
        icon = _load_resource_icon("resources/build.png")
        if icon is not None:
            return icon
    except Exception:  # noqa: BLE001
        logger.debug("Falling back to generated build icon after resource load failed", exc_info=True)

    # Programmatic fallback: eight-toothed gear.
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


def make_run_icon(size: int = 32) -> QIcon:
    """Create a dark-mode-friendly run icon."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#66bb6a"))
    margin = size * 0.18
    points = [
        QPointF(margin, margin),
        QPointF(size - margin, size / 2.0),
        QPointF(margin, size - margin),
    ]
    painter.drawPolygon(QPolygonF(points))
    painter.end()
    return QIcon(QPixmap.fromImage(img))


def make_pause_icon(size: int = 32) -> QIcon:
    """Create a dark-mode-friendly pause icon."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffca28"))
    bar_w = size * 0.18
    gap = size * 0.12
    total_w = 2 * bar_w + gap
    left = (size - total_w) / 2.0
    top = size * 0.18
    height = size * 0.64
    painter.drawRoundedRect(QRectF(left, top, bar_w, height), 2, 2)
    painter.drawRoundedRect(QRectF(left + bar_w + gap, top, bar_w, height), 2, 2)
    painter.end()
    return QIcon(QPixmap.fromImage(img))


def make_stop_icon(size: int = 32) -> QIcon:
    """Create a dark-mode-friendly stop icon."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ef5350"))
    side = size * 0.56
    left = (size - side) / 2.0
    top = (size - side) / 2.0
    painter.drawRoundedRect(QRectF(left, top, side, side), 3, 3)
    painter.end()
    return QIcon(QPixmap.fromImage(img))


def make_watch_icon(size: int = 32) -> QIcon:
    """Create a dark-mode-friendly binoculars icon for value watch."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    body = QColor(colour("plot_foreground"))
    highlight = QColor(colour("value_display_text"))
    bridge = QColor(colour("muted_text"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(body)
    left_body = QRectF(size * 0.12, size * 0.22, size * 0.28, size * 0.42)
    right_body = QRectF(size * 0.60, size * 0.22, size * 0.28, size * 0.42)
    painter.drawRoundedRect(left_body, size * 0.08, size * 0.08)
    painter.drawRoundedRect(right_body, size * 0.08, size * 0.08)
    painter.setBrush(QBrush(bridge))
    painter.drawRoundedRect(QRectF(size * 0.39, size * 0.28, size * 0.22, size * 0.10), 2, 2)
    painter.drawRoundedRect(QRectF(size * 0.31, size * 0.12, size * 0.38, size * 0.09), 2, 2)
    painter.setBrush(QBrush(highlight))
    painter.drawEllipse(QRectF(size * 0.17, size * 0.28, size * 0.18, size * 0.18))
    painter.drawEllipse(QRectF(size * 0.65, size * 0.28, size * 0.18, size * 0.18))
    painter.setBrush(QBrush(body))
    left_barrel = [
        QPointF(size * 0.19, size * 0.60),
        QPointF(size * 0.33, size * 0.60),
        QPointF(size * 0.29, size * 0.84),
        QPointF(size * 0.15, size * 0.84),
    ]
    right_barrel = [
        QPointF(size * 0.67, size * 0.60),
        QPointF(size * 0.81, size * 0.60),
        QPointF(size * 0.85, size * 0.84),
        QPointF(size * 0.71, size * 0.84),
    ]
    painter.drawPolygon(left_barrel)
    painter.drawPolygon(right_barrel)
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

    Draws a high-contrast thermometer outline with a filled bulb at the bottom
    and a bright mercury column for visibility in dark mode.

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
    bulb_r = size * 0.19
    bulb_cy = size * 0.77
    tube_w = size * 0.22
    tube_top = size * 0.08
    tube_bottom = bulb_cy - bulb_r * 0.45
    mercury_w = tube_w * 0.42
    fill_top = tube_top + (tube_bottom - tube_top) * 0.32
    glass_colour = QColor(245, 245, 245)
    outline_colour = QColor(35, 35, 35)
    mercury_colour = QColor("#ff5252")
    highlight_colour = QColor(255, 255, 255, 170)
    outline_pen = painter.pen()
    outline_pen.setColor(outline_colour)
    outline_pen.setWidth(max(1, size // 18))

    # Thermometer tube.
    painter.setBrush(glass_colour)
    painter.setPen(outline_pen)
    painter.drawRoundedRect(
        QRectF(cx - tube_w / 2, tube_top, tube_w, tube_bottom - tube_top),
        tube_w / 2,
        tube_w / 2,
    )

    # Mercury column.
    painter.setBrush(mercury_colour)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(
        QRectF(cx - mercury_w / 2, fill_top, mercury_w, tube_bottom - fill_top),
        mercury_w / 2,
        mercury_w / 2,
    )

    # Bulb.
    painter.setBrush(mercury_colour)
    painter.setPen(outline_pen)
    painter.drawEllipse(QPointF(cx, bulb_cy), bulb_r, bulb_r)

    # Bulb highlight.
    painter.setBrush(highlight_colour)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(
        QPointF(cx - bulb_r * 0.35, bulb_cy - bulb_r * 0.35),
        bulb_r * 0.32,
        bulb_r * 0.32,
    )

    # Scale ticks.
    tick_pen = painter.pen()
    tick_pen.setColor(outline_colour)
    tick_pen.setWidth(max(1, size // 28))
    painter.setPen(tick_pen)
    for fraction in (0.18, 0.34, 0.50, 0.66):
        y = tube_top + (tube_bottom - tube_top) * fraction
        painter.drawLine(
            QPointF(cx + tube_w * 0.78, y),
            QPointF(cx + tube_w * 1.18, y),
        )

    painter.end()
    return QIcon(QPixmap.fromImage(img))


def make_log_icon(size: int = 32) -> QIcon:
    """Create an icon for the *Show Log* action.

    Loads ``log.png`` from the bundled ``resources`` directory.  Falls back
    to a programmatically drawn document icon if the resource cannot be found.

    Keyword Parameters:
        size (int):
            Side length in pixels of the square icon.  Defaults to ``32``.

    Returns:
        (QIcon):
            The log icon.

    Examples:
        >>> icon = make_log_icon()
        >>> icon.isNull()
        False
    """
    # pylint: disable=too-many-locals
    try:
        icon = _load_resource_icon("resources/log.png")
        if icon is not None:
            return icon
    except Exception:  # noqa: BLE001
        logger.debug("Falling back to generated log icon after resource load failed", exc_info=True)

    # Programmatic fallback: document with coloured log lines.
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


def make_motor_icon(size: int = 32) -> QIcon:
    """Create a rotary-stage icon for the *Motor Control* action.

    Draws a high-contrast stepper-motor body beneath a wrapped rotary dial with
    a gold pointer, inspired by classic rotation-stage control buttons while
    remaining clear in both light and dark application themes.

    Keyword Parameters:
        size (int):
            Side length in pixels of the square icon.  Defaults to ``32``.

    Returns:
        (QIcon):
            The rendered motor-control icon.

    Examples:
        >>> icon = make_motor_icon()
        >>> icon.isNull()
        False
    """
    # pylint: disable=too-many-locals
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    outline_colour = QColor(40, 40, 40)
    dial_face = QColor(238, 238, 238)
    dial_ring = QColor(150, 150, 150)
    motor_body = QColor(70, 76, 86)
    motor_highlight = QColor(120, 128, 140)
    shaft_colour = QColor(220, 220, 220)
    pointer_colour = QColor("#f4b400")
    home_mark_colour = QColor("#42a5f5")

    outline_pen = painter.pen()
    outline_pen.setColor(outline_colour)
    outline_pen.setWidth(max(1, size // 18))

    dial_cx = size * 0.52
    dial_cy = size * 0.38
    dial_r = size * 0.26

    painter.setPen(outline_pen)
    painter.setBrush(dial_face)
    painter.drawEllipse(QPointF(dial_cx, dial_cy), dial_r, dial_r)

    ring_pen = painter.pen()
    ring_pen.setColor(dial_ring)
    ring_pen.setWidth(max(1, size // 24))
    painter.setPen(ring_pen)
    for angle_deg in range(-120, 241, 30):
        angle_rad = math.radians(angle_deg)
        outer = QPointF(
            dial_cx + math.cos(angle_rad) * dial_r * 0.92,
            dial_cy - math.sin(angle_rad) * dial_r * 0.92,
        )
        inner = QPointF(
            dial_cx + math.cos(angle_rad) * dial_r * 0.72,
            dial_cy - math.sin(angle_rad) * dial_r * 0.72,
        )
        painter.drawLine(inner, outer)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(home_mark_colour)
    painter.drawEllipse(QPointF(dial_cx, dial_cy - dial_r * 0.78), size * 0.035, size * 0.035)

    pointer_angle = math.radians(65)
    pointer_tip = QPointF(
        dial_cx + math.cos(pointer_angle) * dial_r * 0.78,
        dial_cy - math.sin(pointer_angle) * dial_r * 0.78,
    )
    pointer_left = QPointF(
        dial_cx + math.cos(pointer_angle + 2.45) * dial_r * 0.20,
        dial_cy - math.sin(pointer_angle + 2.45) * dial_r * 0.20,
    )
    pointer_right = QPointF(
        dial_cx + math.cos(pointer_angle - 2.45) * dial_r * 0.20,
        dial_cy - math.sin(pointer_angle - 2.45) * dial_r * 0.20,
    )
    painter.setBrush(pointer_colour)
    painter.drawPolygon(QPolygonF([pointer_tip, pointer_left, pointer_right]))

    painter.setBrush(shaft_colour)
    painter.drawEllipse(QPointF(dial_cx, dial_cy), size * 0.06, size * 0.06)

    motor_rect = QRectF(size * 0.18, size * 0.56, size * 0.46, size * 0.22)
    painter.setPen(outline_pen)
    painter.setBrush(motor_body)
    painter.drawRoundedRect(motor_rect, size * 0.05, size * 0.05)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(motor_highlight)
    painter.drawRoundedRect(
        QRectF(
            motor_rect.x() + size * 0.03,
            motor_rect.y() + size * 0.03,
            motor_rect.width() * 0.82,
            motor_rect.height() * 0.28,
        ),
        size * 0.03,
        size * 0.03,
    )

    painter.setBrush(shaft_colour)
    painter.drawRoundedRect(
        QRectF(size * 0.60, size * 0.62, size * 0.13, size * 0.09),
        size * 0.02,
        size * 0.02,
    )

    painter.end()
    return QIcon(QPixmap.fromImage(img))


def make_pressure_icon(size: int = 32) -> QIcon:
    """Create a round analogue pressure-gauge icon for pressure control.

    The icon is drawn programmatically so it remains available without bundled
    image resources.  It uses a circular dial, tick marks, a vacuum-blue needle,
    and a small ``P`` label to distinguish it from the motor-position dial.

    Keyword Parameters:
        size (int):
            Side length in pixels of the square icon.  Defaults to ``32``.

    Returns:
        (QIcon):
            The rendered pressure-control icon.

    Examples:
        >>> icon = make_pressure_icon()
        >>> icon.isNull()
        False
    """
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    centre = QPointF(size * 0.50, size * 0.52)
    radius = size * 0.38
    outline_colour = QColor(38, 45, 56)
    face_colour = QColor(245, 248, 252)
    ring_colour = QColor("#607d8b")
    needle_colour = QColor("#0288d1")
    warning_colour = QColor("#ef5350")

    outline_pen = painter.pen()
    outline_pen.setColor(outline_colour)
    outline_pen.setWidth(max(1, size // 15))

    painter.setPen(outline_pen)
    painter.setBrush(face_colour)
    painter.drawEllipse(centre, radius, radius)

    tick_pen = painter.pen()
    tick_pen.setColor(ring_colour)
    tick_pen.setWidth(max(1, size // 24))
    painter.setPen(tick_pen)
    for index, angle_deg in enumerate(range(210, -31, -30)):
        angle_rad = math.radians(angle_deg)
        tick_length = 0.24 if index % 2 == 0 else 0.16
        outer = QPointF(
            centre.x() + math.cos(angle_rad) * radius * 0.82,
            centre.y() - math.sin(angle_rad) * radius * 0.82,
        )
        inner = QPointF(
            centre.x() + math.cos(angle_rad) * radius * (0.82 - tick_length),
            centre.y() - math.sin(angle_rad) * radius * (0.82 - tick_length),
        )
        painter.drawLine(inner, outer)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(warning_colour)
    painter.drawPie(
        QRectF(centre.x() - radius * 0.74, centre.y() - radius * 0.74, radius * 1.48, radius * 1.48),
        25 * 16,
        35 * 16,
    )

    painter.setBrush(face_colour)
    painter.drawEllipse(centre, radius * 0.57, radius * 0.57)

    needle_angle = math.radians(48)
    needle_tip = QPointF(
        centre.x() + math.cos(needle_angle) * radius * 0.58,
        centre.y() - math.sin(needle_angle) * radius * 0.58,
    )
    needle_left = QPointF(
        centre.x() + math.cos(needle_angle + 2.5) * radius * 0.13,
        centre.y() - math.sin(needle_angle + 2.5) * radius * 0.13,
    )
    needle_right = QPointF(
        centre.x() + math.cos(needle_angle - 2.5) * radius * 0.13,
        centre.y() - math.sin(needle_angle - 2.5) * radius * 0.13,
    )
    painter.setBrush(needle_colour)
    painter.drawPolygon(QPolygonF([needle_tip, needle_left, needle_right]))
    painter.setBrush(outline_colour)
    painter.drawEllipse(centre, size * 0.055, size * 0.055)

    label_font = painter.font()
    label_font.setPixelSize(max(6, int(size * 0.20)))
    label_font.setBold(True)
    painter.setFont(label_font)
    painter.setPen(QColor("#455a64"))
    painter.drawText(
        QRectF(size * 0.33, size * 0.60, size * 0.34, size * 0.20),
        Qt.AlignmentFlag.AlignCenter,
        "P",
    )

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(outline_pen)
    painter.drawEllipse(centre, radius, radius)

    painter.end()
    return QIcon(QPixmap.fromImage(img))


def make_magnet_icon(size: int = 32) -> QIcon:
    """Create a horseshoe-magnet icon for the *Magnet Control* action.

    Draws a high-contrast stylised horseshoe magnet with a bright body and
    coloured pole tips for visibility in dark mode.

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

    outer_rect = QRectF(size * 0.14, size * 0.10, size * 0.72, size * 0.74)
    inner_rect = QRectF(size * 0.33, size * 0.25, size * 0.34, size * 0.44)
    body_colour = QColor(235, 235, 235)
    outline_colour = QColor(40, 40, 40)
    north_colour = QColor("#ff5252")
    south_colour = QColor("#42a5f5")
    outline_pen = painter.pen()
    outline_pen.setColor(outline_colour)
    outline_pen.setWidth(max(1, size // 16))

    horseshoe = QPainterPath()
    horseshoe.addRoundedRect(outer_rect, size * 0.24, size * 0.24)
    inner_path = QPainterPath()
    inner_path.addRoundedRect(inner_rect, size * 0.12, size * 0.12)
    horseshoe = horseshoe.subtracted(inner_path)
    horseshoe.addRect(QRectF(size * 0.34, size * 0.54, size * 0.32, size * 0.28))

    painter.setBrush(body_colour)
    painter.setPen(outline_pen)
    painter.drawPath(horseshoe)

    tip_y = size * 0.59
    tip_h = size * 0.22
    tip_w = size * 0.16

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(north_colour)
    painter.drawRoundedRect(QRectF(size * 0.14, tip_y, tip_w, tip_h), 2, 2)
    painter.setBrush(south_colour)
    painter.drawRoundedRect(QRectF(size * 0.70, tip_y, tip_w, tip_h), 2, 2)

    label_font = painter.font()
    label_font.setPixelSize(max(6, int(size * 0.18)))
    label_font.setBold(True)
    painter.setFont(label_font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(
        QRectF(size * 0.14, tip_y, tip_w, tip_h),
        Qt.AlignmentFlag.AlignCenter,
        "N",
    )
    painter.drawText(
        QRectF(size * 0.70, tip_y, tip_w, tip_h),
        Qt.AlignmentFlag.AlignCenter,
        "S",
    )

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(outline_pen)
    painter.drawPath(horseshoe)

    painter.end()
    return QIcon(QPixmap.fromImage(img))
