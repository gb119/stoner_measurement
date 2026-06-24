"""Reusable round dial widget for displaying angular or scalar values.

Provides :class:`RoundDialWidget`, a scalable Qt widget that renders a
LabVIEW-style circular dial face with configurable value range, angular span,
tick marks, labels, pointer styling, and automatic app-theme integration.

The dial uses a top-referenced angular convention:

* ``0`` degrees points vertically upwards.
* Positive angles advance clockwise.
* ``90`` degrees points to the right.
* ``180`` degrees points downwards.
* ``270`` degrees points to the left.

This convention matches common instrument-panel displays for position and
direction readback.

The widget is display-only by design and does not implement any interactive
knob or drag behaviour.
"""

from __future__ import annotations

import math

from qtpy.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from qtpy.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from qtpy.QtWidgets import QSizePolicy, QWidget

from stoner_measurement.ui.theme import colour


class RoundDialWidget(QWidget):
    """Scalable circular dial widget for angular and scalar readback.

    The widget maps a numeric value from a configurable range onto a circular
    scale whose minimum and maximum may be placed at arbitrary dial angles.
    The scale can cover a partial arc or a complete revolution. Labels and
    tick marks are generated automatically and the control scales with the
    widget size.

    Angles are specified in dial coordinates where ``0`` is vertically at the
    top and increases clockwise.

    Signals:
        valueChanged (float):
            Emitted whenever :meth:`setValue` changes the stored value.

    Args:
        parent:
            Optional parent widget.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> d = RoundDialWidget()
        >>> d.minimumValue()
        0.0
        >>> d.maximumValue()
        360.0
        >>> d.setRange(-180, 180)
        >>> d.setScaleAngles(-135, 135)
        >>> d.setValue(45)
        >>> round(d.value(), 1)
        45.0
    """

    valueChanged = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum = 0.0
        self._maximum = 360.0
        self._value = 0.0

        self._minimum_angle = 0.0
        self._maximum_angle = 360.0

        self._major_tick_step = 30.0
        self._minor_ticks_per_major = 4
        self._label_step = 30.0
        self._decimals = 0
        self._show_value_text = True
        self._value_text_suffix = ""
        self._title = ""
        self._units_text = ""
        self._wrap = False
        self._show_labels = True
        self._show_ticks = True

        self._face_color = QColor()
        self._rim_light = QColor()
        self._rim_dark = QColor()
        self._tick_color = QColor()
        self._label_color = QColor()
        self._pointer_color = QColor()
        self._hub_light = QColor()
        self._hub_dark = QColor()
        self._value_text_color = QColor()
        self._title_color = QColor()

        self._use_theme_face = True
        self._use_theme_tick = True
        self._use_theme_label = True
        self._use_theme_pointer = True
        self._use_theme_value_text = True
        self._use_theme_title = True

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(120, 120)
        self._apply_theme_colors()

    def sizeHint(self) -> QSize:
        """Return the recommended initial widget size."""
        return QSize(220, 220)

    def minimumSizeHint(self) -> QSize:
        """Return the minimum useful widget size."""
        return QSize(120, 120)

    def minimumValue(self) -> float:
        """Return the configured minimum numeric value."""
        return self._minimum

    def maximumValue(self) -> float:
        """Return the configured maximum numeric value."""
        return self._maximum

    def value(self) -> float:
        """Return the current numeric value."""
        return self._value

    def minimumAngle(self) -> float:
        """Return the dial angle corresponding to the minimum value."""
        return self._minimum_angle

    def maximumAngle(self) -> float:
        """Return the dial angle corresponding to the maximum value."""
        return self._maximum_angle

    def title(self) -> str:
        """Return the dial title text."""
        return self._title

    def setTitle(self, title: str) -> None:
        """Set the title shown above the dial."""
        if title == self._title:
            return
        self._title = title
        self.update()

    def setRange(self, minimum: float, maximum: float) -> None:
        """Set the numeric range displayed by the dial.

        Args:
            minimum:
                Value corresponding to :meth:`minimumAngle`.
            maximum:
                Value corresponding to :meth:`maximumAngle`.

        Raises:
            ValueError:
                If ``maximum`` is not greater than ``minimum``.
        """
        minimum = float(minimum)
        maximum = float(maximum)
        if maximum <= minimum:
            raise ValueError("maximum must be greater than minimum")
        self._minimum = minimum
        self._maximum = maximum
        self.setValue(self._value)
        self.update()

    def setScaleAngles(self, minimum_angle: float, maximum_angle: float) -> None:
        """Set dial angles for the numeric range endpoints.

        Angles are expressed in top-referenced clockwise degrees. The values
        are not wrapped internally, so a full-scale clockwise sweep from top
        back to top should be expressed as ``0`` to ``360``.

        Args:
            minimum_angle:
                Dial angle of the minimum value.
            maximum_angle:
                Dial angle of the maximum value.

        Raises:
            ValueError:
                If both angles are equal.
        """
        minimum_angle = float(minimum_angle)
        maximum_angle = float(maximum_angle)
        if math.isclose(minimum_angle, maximum_angle, abs_tol=1e-12):
            raise ValueError("minimum_angle and maximum_angle must differ")
        self._minimum_angle = minimum_angle
        self._maximum_angle = maximum_angle
        self.update()

    def setValue(self, value: float) -> None:
        """Set the displayed value.

        The value is clamped to the configured numeric range.
        If wrap mode is enabled, the value is first wrapped into the configured
        numeric interval before display.

        Args:
            value:
                New value to display.
        """
        value = float(value)
        if self._wrap:
            span = self._maximum - self._minimum
            if span > 0:
                value = ((value - self._minimum) % span) + self._minimum
                if math.isclose(value, self._minimum, abs_tol=1e-12) and value != float(self._minimum):
                    value = self._maximum
        clamped = min(max(value, self._minimum), self._maximum)
        if math.isclose(clamped, self._value, rel_tol=0.0, abs_tol=1e-12):
            return
        self._value = clamped
        self.valueChanged.emit(self._value)
        self.update()

    def setMajorTickStep(self, step: float) -> None:
        """Set the value spacing between adjacent major ticks."""
        step = float(step)
        if step <= 0:
            raise ValueError("step must be positive")
        self._major_tick_step = step
        self.update()

    def majorTickStep(self) -> float:
        """Return the value spacing between major ticks."""
        return self._major_tick_step

    def setMinorTicksPerMajor(self, count: int) -> None:
        """Set the number of minor subdivisions between major ticks."""
        count = int(count)
        if count < 0:
            raise ValueError("count must be non-negative")
        self._minor_ticks_per_major = count
        self.update()

    def minorTicksPerMajor(self) -> int:
        """Return the number of minor subdivisions between major ticks."""
        return self._minor_ticks_per_major

    def setLabelStep(self, step: float) -> None:
        """Set the value spacing between numeric labels."""
        step = float(step)
        if step <= 0:
            raise ValueError("step must be positive")
        self._label_step = step
        self.update()

    def labelStep(self) -> float:
        """Return the value spacing between numeric labels."""
        return self._label_step

    def setDecimals(self, decimals: int) -> None:
        """Set the number of decimal places used in labels and value text."""
        decimals = int(decimals)
        if decimals < 0:
            raise ValueError("decimals must be non-negative")
        self._decimals = decimals
        self.update()

    def decimals(self) -> int:
        """Return the number of decimal places used for text."""
        return self._decimals

    def setShowValueText(self, show: bool) -> None:
        """Show or hide the numeric readout beneath the dial hub."""
        show = bool(show)
        if show == self._show_value_text:
            return
        self._show_value_text = show
        self.update()

    def showValueText(self) -> bool:
        """Return whether the numeric readout is shown."""
        return self._show_value_text

    def setShowTicks(self, show: bool) -> None:
        """Show or hide all dial tick marks."""
        show = bool(show)
        if show == self._show_ticks:
            return
        self._show_ticks = show
        self.update()

    def showTicks(self) -> bool:
        """Return whether dial tick marks are shown."""
        return self._show_ticks

    def setShowLabels(self, show: bool) -> None:
        """Show or hide all numeric scale labels."""
        show = bool(show)
        if show == self._show_labels:
            return
        self._show_labels = show
        self.update()

    def showLabels(self) -> bool:
        """Return whether numeric scale labels are shown."""
        return self._show_labels

    def setValueTextSuffix(self, suffix: str) -> None:
        """Set text appended to the numeric readout."""
        if suffix == self._value_text_suffix:
            return
        self._value_text_suffix = suffix
        self.update()

    def valueTextSuffix(self) -> str:
        """Return the numeric readout suffix."""
        return self._value_text_suffix

    def setUnitsText(self, units: str) -> None:
        """Set the unit text appended to the numeric readout."""
        if units == self._units_text:
            return
        self._units_text = units
        self.update()

    def unitsText(self) -> str:
        """Return the unit text appended to the numeric readout."""
        return self._units_text

    def setWrap(self, enabled: bool) -> None:
        """Enable or disable cyclic wrapping for incoming values."""
        enabled = bool(enabled)
        if enabled == self._wrap:
            return
        self._wrap = enabled
        self.setValue(self._value)

    def wrap(self) -> bool:
        """Return whether cyclic wrapping is enabled."""
        return self._wrap

    def setTickSteps(self, major: float, minor_count: int, label_step: float | None = None) -> None:
        """Set major/minor tick and label spacing in one call."""
        self.setMajorTickStep(major)
        self.setMinorTicksPerMajor(minor_count)
        if label_step is not None:
            self.setLabelStep(label_step)

    def setAngleValueMode(self) -> None:
        """Configure the dial for conventional angular display."""
        self.setRange(0.0, 360.0)
        self.setScaleAngles(0.0, 360.0)
        self.setTickSteps(30.0, 4, label_step=30.0)
        self.setDecimals(0)
        self.setWrap(True)
        self.setUnitsText("°")

    def setCompassMode(self) -> None:
        """Configure the dial for compass-style direction display."""
        self.setAngleValueMode()
        self.setTitle("Direction")

    def setBidirectionalAngleMode(self) -> None:
        """Configure the dial for symmetric signed angular display."""
        self.setRange(-180.0, 180.0)
        self.setScaleAngles(-180.0, 180.0)
        self.setTickSteps(30.0, 2, label_step=30.0)
        self.setDecimals(0)
        self.setWrap(False)
        self.setUnitsText("°")

    def setFaceColor(self, color: QColor | str) -> None:
        """Set the dial face colour."""
        self._face_color = QColor(color)
        self._use_theme_face = False
        self.update()

    def setTickColor(self, color: QColor | str) -> None:
        """Set the tick mark colour."""
        self._tick_color = QColor(color)
        self._use_theme_tick = False
        self.update()

    def setLabelColor(self, color: QColor | str) -> None:
        """Set the label colour."""
        self._label_color = QColor(color)
        self._use_theme_label = False
        self.update()

    def setPointerColor(self, color: QColor | str) -> None:
        """Set the pointer colour."""
        self._pointer_color = QColor(color)
        self._use_theme_pointer = False
        self.update()

    def setValueTextColor(self, color: QColor | str) -> None:
        """Set the numeric readout colour."""
        self._value_text_color = QColor(color)
        self._use_theme_value_text = False
        self.update()

    def setTitleColor(self, color: QColor | str) -> None:
        """Set the title colour."""
        self._title_color = QColor(color)
        self._use_theme_title = False
        self.update()

    def resetThemeColors(self) -> None:
        """Restore all theme-derived colours for the dial."""
        self._use_theme_face = True
        self._use_theme_tick = True
        self._use_theme_label = True
        self._use_theme_pointer = True
        self._use_theme_value_text = True
        self._use_theme_title = True
        self._apply_theme_colors()
        self.update()

    def _span_angle(self) -> float:
        return self._maximum_angle - self._minimum_angle

    def _value_to_ratio(self, value: float) -> float:
        return (value - self._minimum) / (self._maximum - self._minimum)

    def _value_to_angle(self, value: float) -> float:
        return self._minimum_angle + self._value_to_ratio(value) * self._span_angle()

    def _apply_theme_colors(self) -> None:
        """Apply colours derived from the current application theme."""
        window = QColor(colour("window"))
        base = QColor(colour("base"))
        text = QColor(colour("text"))
        muted = QColor(colour("muted_text"))
        border = QColor(colour("border"))
        highlight = QColor(colour("trace_red"))

        if self._use_theme_face:
            self._face_color = base
        if self._use_theme_tick:
            self._tick_color = text
        if self._use_theme_label:
            self._label_color = text
        if self._use_theme_pointer:
            self._pointer_color = highlight
        if self._use_theme_value_text:
            self._value_text_color = text
        if self._use_theme_title:
            self._title_color = muted

        light_mix = self._blend(base, QColor("#ffffff"), 0.75)
        dark_mix = self._blend(window, border, 0.50)
        self._rim_light = light_mix
        self._rim_dark = dark_mix
        self._hub_light = self._blend(base, QColor("#ffffff"), 0.55)
        self._hub_dark = self._blend(window, border, 0.70)

    @staticmethod
    def _blend(first: QColor, second: QColor, ratio: float) -> QColor:
        ratio = max(0.0, min(1.0, float(ratio)))
        inv = 1.0 - ratio
        return QColor(
            int((first.red() * ratio) + (second.red() * inv)),
            int((first.green() * ratio) + (second.green() * inv)),
            int((first.blue() * ratio) + (second.blue() * inv)),
            int((first.alpha() * ratio) + (second.alpha() * inv)),
        )

    @staticmethod
    def _dial_to_scene_angle(angle: float) -> float:
        """Convert top-referenced clockwise angle to Qt scene angle."""
        return angle - 90.0

    @staticmethod
    def _point_on_circle(center: QPointF, radius: float, dial_angle: float) -> QPointF:
        scene_angle = math.radians(RoundDialWidget._dial_to_scene_angle(dial_angle))
        return QPointF(
            center.x() + radius * math.cos(scene_angle),
            center.y() + radius * math.sin(scene_angle),
        )

    def _iter_tick_values(self, step: float) -> list[float]:
        span = self._maximum - self._minimum
        count = int(math.floor((span / step) + 1e-9))
        values = [self._minimum + index * step for index in range(count + 1)]
        if not math.isclose(values[-1], self._maximum, abs_tol=1e-9):
            values.append(self._maximum)
        return values

    def changeEvent(self, event) -> None:  # noqa: ANN001
        """React to palette/style/theme changes."""
        if event is not None and event.type() in {
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.StyleChange,
        }:
            self._apply_theme_colors()
            self.update()
        super().changeEvent(event)

    def _format_value(self, value: float) -> str:
        if self._decimals == 0 and math.isclose(value, round(value), abs_tol=1e-9):
            return str(int(round(value)))
        return f"{value:.{self._decimals}f}"

    def paintEvent(self, event) -> None:  # noqa: D401, ANN001
        """Paint the dial."""
        del event

        side = min(self.width(), self.height())
        if side <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        margin = side * 0.04
        outer_rect = QRectF(
            (self.width() - side) / 2.0 + margin,
            (self.height() - side) / 2.0 + margin,
            side - 2.0 * margin,
            side - 2.0 * margin,
        )
        center = outer_rect.center()
        radius = outer_rect.width() / 2.0

        self._draw_rim(painter, outer_rect)
        self._draw_face(painter, center, radius * 0.95)
        if self._show_ticks:
            self._draw_ticks(painter, center, radius * 0.90)
        if self._show_labels:
            self._draw_labels(painter, center, radius * 0.72)
        self._draw_pointer(painter, center, radius * 0.78)
        self._draw_hub(painter, center, radius * 0.07)
        self._draw_title(painter, outer_rect)
        self._draw_value_text(painter, center, radius)

    def _draw_rim(self, painter: QPainter, rect: QRectF) -> None:
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, self._rim_light)
        gradient.setColorAt(0.45, QColor("#e8e8e8"))
        gradient.setColorAt(1.0, self._rim_dark)
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(rect)

    def _draw_face(self, painter: QPainter, center: QPointF, radius: float) -> None:
        rect = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
        gradient = QRadialGradient(
            QPointF(center.x() - radius * 0.25, center.y() - radius * 0.25),
            radius * 1.15,
            center,
        )
        gradient.setColorAt(0.0, QColor("#ffffff"))
        gradient.setColorAt(0.55, self._face_color)
        gradient.setColorAt(1.0, QColor("#ececec"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(rect)

    def _draw_ticks(self, painter: QPainter, center: QPointF, radius: float) -> None:
        major_pen = QPen(self._tick_color)
        major_pen.setWidthF(max(1.2, radius * 0.012))
        major_pen.setCapStyle(Qt.FlatCap)

        minor_pen = QPen(self._tick_color)
        minor_pen.setWidthF(max(0.8, radius * 0.006))
        minor_pen.setCapStyle(Qt.FlatCap)

        major_values = self._iter_tick_values(self._major_tick_step)
        minor_step = (
            self._major_tick_step / (self._minor_ticks_per_major + 1)
            if self._minor_ticks_per_major > 0
            else None
        )

        if minor_step is not None:
            for major_index in range(len(major_values) - 1):
                base = major_values[major_index]
                for offset in range(1, self._minor_ticks_per_major + 1):
                    value = base + offset * minor_step
                    if value >= self._maximum:
                        continue
                    self._draw_single_tick(
                        painter,
                        center,
                        radius,
                        self._value_to_angle(value),
                        radius * 0.045,
                        minor_pen,
                    )

        for value in major_values:
            self._draw_single_tick(
                painter,
                center,
                radius,
                self._value_to_angle(value),
                radius * 0.085,
                major_pen,
            )

    def _draw_single_tick(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        dial_angle: float,
        length: float,
        pen: QPen,
    ) -> None:
        outer = self._point_on_circle(center, radius, dial_angle)
        inner = self._point_on_circle(center, radius - length, dial_angle)
        painter.setPen(pen)
        painter.drawLine(inner, outer)

    def _draw_labels(self, painter: QPainter, center: QPointF, radius: float) -> None:
        font = QFont(self.font())
        font.setBold(False)
        font.setPointSizeF(max(7.0, min(self.width(), self.height()) * 0.055))
        painter.setFont(font)
        painter.setPen(self._label_color)
        metrics = QFontMetricsF(font)

        for value in self._iter_tick_values(self._label_step):
            text = self._format_value(value)
            pos = self._point_on_circle(center, radius, self._value_to_angle(value))
            text_rect = metrics.boundingRect(text)
            draw_rect = QRectF(
                pos.x() - text_rect.width() / 2.0,
                pos.y() - text_rect.height() / 2.0,
                text_rect.width(),
                text_rect.height(),
            )
            painter.drawText(draw_rect, Qt.AlignCenter, text)

    def _draw_pointer(self, painter: QPainter, center: QPointF, radius: float) -> None:
        angle = self._value_to_angle(self._value)
        tip = self._point_on_circle(center, radius, angle)
        left = self._point_on_circle(center, radius * 0.16, angle - 90.0)
        right = self._point_on_circle(center, radius * 0.16, angle + 90.0)
        tail = self._point_on_circle(center, radius * 0.10, angle + 180.0)
        neck_left = self._point_on_circle(center, radius * 0.05, angle - 90.0)
        neck_right = self._point_on_circle(center, radius * 0.05, angle + 90.0)

        path = QPainterPath()
        path.moveTo(tail)
        path.lineTo(left)
        path.lineTo(neck_left)
        path.lineTo(tip)
        path.lineTo(neck_right)
        path.lineTo(right)
        path.closeSubpath()

        painter.setPen(Qt.NoPen)
        painter.setBrush(self._pointer_color)
        painter.drawPath(path)

    def _draw_hub(self, painter: QPainter, center: QPointF, radius: float) -> None:
        rect = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
        gradient = QRadialGradient(
            QPointF(center.x() - radius * 0.3, center.y() - radius * 0.3),
            radius * 1.2,
            center,
        )
        gradient.setColorAt(0.0, self._hub_light)
        gradient.setColorAt(1.0, self._hub_dark)
        painter.setPen(QPen(QColor("#808080"), max(0.8, radius * 0.08)))
        painter.setBrush(gradient)
        painter.drawEllipse(rect)

    def _draw_title(self, painter: QPainter, rect: QRectF) -> None:
        if not self._title:
            return
        font = QFont(self.font())
        font.setBold(False)
        font.setPointSizeF(max(8.0, rect.width() * 0.05))
        painter.setFont(font)
        painter.setPen(self._title_color)
        title_rect = QRectF(rect.left(), rect.top() - rect.height() * 0.02, rect.width(), rect.height() * 0.16)
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignTop, self._title)

    def _draw_value_text(self, painter: QPainter, center: QPointF, radius: float) -> None:
        if not self._show_value_text:
            return
        font = QFont(self.font())
        font.setBold(False)
        font.setPointSizeF(max(8.0, radius * 0.16))
        painter.setFont(font)
        painter.setPen(self._value_text_color)

        suffix = self._units_text or self._value_text_suffix
        text = f"{self._format_value(self._value)}{suffix}"
        rect = QRectF(
            center.x() - radius * 0.35,
            center.y() + radius * 0.25,
            radius * 0.70,
            radius * 0.18,
        )
        painter.drawText(rect, Qt.AlignCenter, text)
