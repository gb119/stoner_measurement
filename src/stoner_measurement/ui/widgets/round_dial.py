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
        self._label_font_scale = 0.041
        self._title_font_scale = 0.050
        self._value_font_scale = 0.160
        self._minimum_label_point_size = 8.0
        self._minimum_title_point_size = 8.0
        self._minimum_value_point_size = 8.0
        self._label_radius_factor = 0.72
        self._top_reserved_fraction = 0.16
        self._bottom_reserved_fraction = 0.18
        self._title_vertical_offset_fraction = 0.01
        self._label_collision_padding = 2.5
        self._preferred_label_counts: list[int] | None = None
        self._preserve_endpoint_labels = True
        self._custom_labels: dict[float, str] = {}
        self._label_background_visible = False
        self._label_background_color = QColor()
        self._scale_band_visible = False
        self._scale_band_width_factor = 0.10
        self._scale_band_stops: list[tuple[float, QColor]] = []
        self._units_text = ""
        self._wrap = False
        self._show_labels = True
        self._show_ticks = True

        self._value_text_mode = "numeric"
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

    def setLabelFontScale(self, scale: float) -> None:
        """Set label font size as a fraction of widget side length."""
        scale = float(scale)
        if scale <= 0:
            raise ValueError("scale must be positive")
        self._label_font_scale = scale
        self.update()

    def labelFontScale(self) -> float:
        """Return label font size as a fraction of widget side length."""
        return self._label_font_scale

    def setTitleFontScale(self, scale: float) -> None:
        """Set title font size as a fraction of dial width."""
        scale = float(scale)
        if scale <= 0:
            raise ValueError("scale must be positive")
        self._title_font_scale = scale
        self.update()

    def titleFontScale(self) -> float:
        """Return title font size as a fraction of dial width."""
        return self._title_font_scale

    def setValueFontScale(self, scale: float) -> None:
        """Set value text font size as a fraction of dial radius."""
        scale = float(scale)
        if scale <= 0:
            raise ValueError("scale must be positive")
        self._value_font_scale = scale
        self.update()

    def valueFontScale(self) -> float:
        """Return value text font size as a fraction of dial radius."""
        return self._value_font_scale

    def setLabelRadiusFactor(self, factor: float) -> None:
        """Set label placement radius as a fraction of dial radius."""
        factor = float(factor)
        if not 0.1 <= factor <= 1.2:
            raise ValueError("factor must be between 0.1 and 1.2")
        self._label_radius_factor = factor
        self.update()

    def labelRadiusFactor(self) -> float:
        """Return label placement radius as a fraction of dial radius."""
        return self._label_radius_factor

    def setTopReservedFraction(self, fraction: float) -> None:
        """Set the fraction of widget height reserved above the dial face."""
        fraction = float(fraction)
        if not 0.0 <= fraction <= 0.40:
            raise ValueError("fraction must be between 0.0 and 0.40")
        self._top_reserved_fraction = fraction
        self.update()

    def topReservedFraction(self) -> float:
        """Return the fraction of widget height reserved above the dial face."""
        return self._top_reserved_fraction

    def setBottomReservedFraction(self, fraction: float) -> None:
        """Set the fraction of widget height reserved below the dial face."""
        fraction = float(fraction)
        if not 0.0 <= fraction <= 0.40:
            raise ValueError("fraction must be between 0.0 and 0.40")
        self._bottom_reserved_fraction = fraction
        self.update()

    def bottomReservedFraction(self) -> float:
        """Return the fraction of widget height reserved below the dial face."""
        return self._bottom_reserved_fraction

    def setTitleVerticalOffsetFraction(self, fraction: float) -> None:
        """Set a small title offset relative to the dial bounding box height."""
        fraction = float(fraction)
        if not -0.10 <= fraction <= 0.10:
            raise ValueError("fraction must be between -0.10 and 0.10")
        self._title_vertical_offset_fraction = fraction
        self.update()

    def titleVerticalOffsetFraction(self) -> float:
        """Return the title offset fraction."""
        return self._title_vertical_offset_fraction

    def setPreferredLabelCounts(self, counts: list[int] | None) -> None:
        """Set preferred evenly spaced label counts to try before drawing."""
        if counts is None:
            self._preferred_label_counts = None
        else:
            cleaned = [int(count) for count in counts if int(count) >= 2]
            self._preferred_label_counts = cleaned or None
        self.update()

    def preferredLabelCounts(self) -> list[int] | None:
        """Return the preferred evenly spaced label counts."""
        return None if self._preferred_label_counts is None else list(self._preferred_label_counts)

    def setPreserveEndpointLabels(self, preserve: bool) -> None:
        """Set whether scale endpoint labels should be preferred when possible."""
        self._preserve_endpoint_labels = bool(preserve)
        self.update()

    def preserveEndpointLabels(self) -> bool:
        """Return whether scale endpoint labels should be preferred."""
        return self._preserve_endpoint_labels

    def setCustomLabels(self, labels: dict[float, str] | None) -> None:
        """Set explicit value-to-label text mappings."""
        self._custom_labels = {} if labels is None else {float(key): str(value) for key, value in labels.items()}
        self.update()

    def customLabels(self) -> dict[float, str]:
        """Return explicit value-to-label text mappings."""
        return dict(self._custom_labels)

    def clearCustomLabels(self) -> None:
        """Clear explicit scale-label mappings."""
        self._custom_labels.clear()
        self.update()

    def setLabelBackgroundVisible(self, visible: bool) -> None:
        """Show or hide a background patch behind label text."""
        self._label_background_visible = bool(visible)
        self.update()

    def labelBackgroundVisible(self) -> bool:
        """Return whether label background patches are shown."""
        return self._label_background_visible

    def setLabelBackgroundColor(self, color: QColor | str) -> None:
        """Set the background colour used behind labels."""
        self._label_background_color = QColor(color)
        self.update()

    def setScaleBandVisible(self, visible: bool) -> None:
        """Show or hide the coloured band behind the scale labels."""
        self._scale_band_visible = bool(visible)
        self.update()

    def scaleBandVisible(self) -> bool:
        """Return whether the coloured scale band is shown."""
        return self._scale_band_visible

    def setScaleBandWidthFactor(self, factor: float) -> None:
        """Set the coloured scale-band width as a fraction of dial radius."""
        factor = float(factor)
        if not 0.01 <= factor <= 0.50:
            raise ValueError("factor must be between 0.01 and 0.50")
        self._scale_band_width_factor = factor
        self.update()

    def setScaleBandStops(self, stops: list[tuple[float, QColor | str]]) -> None:
        """Set interpolated coloured scale-band stops as (value, colour)."""
        processed = [(float(value), QColor(colour_value)) for value, colour_value in stops]
        processed.sort(key=lambda item: item[0])
        self._scale_band_stops = processed
        self.update()

    def scaleBandStops(self) -> list[tuple[float, QColor]]:
        """Return the configured coloured scale-band stops."""
        return [(value, QColor(color)) for value, color in self._scale_band_stops]

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

    def formattedValueText(self) -> str:
        """Return the current value as formatted display text."""
        return self._format_value_text(self._value)

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
        self._value_text_mode = "numeric"
        self.setRange(0.0, 360.0)
        self.setScaleAngles(0.0, 360.0)
        self.setTickSteps(30.0, 4, label_step=30.0)
        self.setDecimals(0)
        self.setWrap(True)
        self.setPreferredLabelCounts([12, 8, 6, 4])
        self.setUnitsText("°")
        self.clearCustomLabels()

    def setClockMode(self) -> None:
        """Configure the dial for a 12-hour clock-face display."""
        self.clearCustomLabels()
        self.setPreferredLabelCounts(None)
        self.setPreserveEndpointLabels(False)
        self.setScaleBandVisible(False)
        self.setRange(0.0, 12.0)
        self.setScaleAngles(0.0, 360.0)
        self.setTickSteps(1.0, 4, label_step=1.0)
        self.setDecimals(0)
        self.setWrap(True)
        self.setUnitsText("")
        self.setValueTextSuffix("")
        self.setLabelRadiusFactor(0.72)
        self.setShowValueText(True)
        self._value_text_mode = "clock"
        self.setCustomLabels(
            {
                0.0: "12", 1.0: "1", 2.0: "2", 3.0: "3", 4.0: "4", 5.0: "5",
                6.0: "6", 7.0: "7", 8.0: "8", 9.0: "9", 10.0: "10", 11.0: "11", 12.0: "12",
            }
        )

    def setCompassMode(self) -> None:
        """Configure the dial for compass-style direction display."""
        self.setAngleValueMode()
        self.setCompassLabelMode(8)
        self.setTitle("Direction")

    def setBidirectionalAngleMode(self) -> None:
        """Configure the dial for symmetric signed angular display."""
        self._value_text_mode = "numeric"
        self.setRange(-180.0, 180.0)
        self.setScaleAngles(-180.0, 180.0)
        self.setTickSteps(30.0, 2, label_step=45.0)
        self.setDecimals(0)
        self.setWrap(False)
        self.setPreferredLabelCounts(None)
        self.setPreserveEndpointLabels(False)
        self.setUnitsText("°")
        self.clearCustomLabels()

    def setCompassLabelMode(self, points: int = 8) -> None:
        """Set compass labels with 4, 8, or 16 named directions."""
        points = int(points)
        if points == 4:
            labels = {0.0: "N", 90.0: "E", 180.0: "S", 270.0: "W", 360.0: "N"}
        elif points == 8:
            labels = {0.0: "N", 45.0: "NE", 90.0: "E", 135.0: "SE", 180.0: "S", 225.0: "SW", 270.0: "W", 315.0: "NW", 360.0: "N"}
        elif points == 16:
            names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW", "N"]
            labels = {float(index * 22.5): name for index, name in enumerate(names)}
        else:
            raise ValueError("points must be one of 4, 8, or 16")
        self.setCustomLabels(labels)
        self.setPreferredLabelCounts(None)
        self.setTickSteps(360.0 / points, 1, label_step=360.0 / points)

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

    def _is_full_circle_scale(self) -> bool:
        return math.isclose(abs(self._span_angle()), 360.0, abs_tol=1e-9)

    @staticmethod
    def _normalise_angle(angle: float) -> float:
        normalised = angle % 360.0
        return 0.0 if math.isclose(normalised, 360.0, abs_tol=1e-9) else normalised

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

        if not self._label_background_color.isValid():
            self._label_background_color = self._blend(base, window, 0.85)
        if self._use_theme_label and self._face_color.lightness() < 96:
            self._label_color = self._blend(text, QColor("#ffffff"), 0.82)
        elif self._use_theme_label:
            self._label_color = text
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

    def _format_value_text(self, value: float) -> str:
        if self._value_text_mode == "clock":
            wrapped = value % 12.0
            hours = int(math.floor(wrapped)) % 12
            minutes = int(round((wrapped - math.floor(wrapped)) * 60.0))
            if minutes >= 60:
                minutes = 0
                hours = (hours + 1) % 12
            display_hour = 12 if hours == 0 else hours
            return f"{display_hour:02d}:{minutes:02d}"
        suffix = self._units_text or self._value_text_suffix
        return f"{self._format_value(value)}{suffix}"

    def paintEvent(self, event) -> None:  # noqa: D401, ANN001
        """Paint the dial."""
        del event

        side = min(self.width(), self.height())
        if side <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        available_top = self.height() * self._top_reserved_fraction
        available_bottom = self.height() * self._bottom_reserved_fraction
        usable_height = max(1.0, self.height() - available_top - available_bottom)
        dial_side = min(self.width(), usable_height)
        margin = dial_side * 0.04
        outer_rect = QRectF(
            (self.width() - dial_side) / 2.0 + margin,
            available_top + (usable_height - dial_side) / 2.0 + margin,
            dial_side - 2.0 * margin,
            dial_side - 2.0 * margin,
        )
        center = outer_rect.center()
        radius = outer_rect.width() / 2.0

        self._draw_rim(painter, outer_rect)
        self._draw_face(painter, center, radius * 0.95)
        if self._scale_band_visible:
            self._draw_scale_band(painter, center, radius * 0.83)
        if self._show_ticks:
            self._draw_ticks(painter, center, radius * 0.90)
        if self._show_labels:
            self._draw_labels(painter, center, radius * self._label_radius_factor)
        self._draw_pointer(painter, center, radius * 0.78)
        self._draw_hub(painter, center, radius * 0.07)
        self._draw_title(painter, outer_rect)
        self._draw_label_legend_overlay_fix(painter)
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
            center,
            radius * 1.15,
            QPointF(center.x() - radius * 0.22, center.y() - radius * 0.22),
        )
        gradient.setColorAt(0.0, self._blend(self._face_color, QColor("#ffffff"), 0.35))
        gradient.setColorAt(0.38, self._blend(self._face_color, QColor("#ffffff"), 0.72))
        gradient.setColorAt(0.72, self._face_color)
        gradient.setColorAt(1.0, self._blend(self._face_color, self._rim_dark, 0.84))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(rect)

    def _draw_scale_band(self, painter: QPainter, center: QPointF, radius: float) -> None:
        if len(self._scale_band_stops) < 2:
            return
        width = radius * self._scale_band_width_factor
        for index in range(len(self._scale_band_stops) - 1):
            start_value, start_color = self._scale_band_stops[index]
            end_value, end_color = self._scale_band_stops[index + 1]
            if math.isclose(end_value, start_value, abs_tol=1e-12):
                continue
            step_count = max(2, int(abs(end_value - start_value) / max(self._label_step / 8.0, 1e-6)))
            for step_index in range(step_count):
                ratio0 = step_index / step_count
                ratio1 = (step_index + 1) / step_count
                value0 = start_value + (end_value - start_value) * ratio0
                value1 = start_value + (end_value - start_value) * ratio1
                angle0 = self._value_to_angle(value0)
                angle1 = self._value_to_angle(value1)
                color = self._blend(start_color, end_color, 1.0 - ((ratio0 + ratio1) * 0.5))
                self._draw_band_segment(painter, center, radius, width, angle0, angle1, color)

    def _draw_band_segment(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        width: float,
        start_angle: float,
        end_angle: float,
        color: QColor,
    ) -> None:
        outer_start = self._point_on_circle(center, radius + width / 2.0, start_angle)
        outer_end = self._point_on_circle(center, radius + width / 2.0, end_angle)
        inner_start = self._point_on_circle(center, radius - width / 2.0, start_angle)
        inner_end = self._point_on_circle(center, radius - width / 2.0, end_angle)

        path = QPainterPath()
        path.moveTo(inner_start)
        path.lineTo(outer_start)
        path.lineTo(outer_end)
        path.lineTo(inner_end)
        path.closeSubpath()

        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)
        painter.restore()

    def _label_text(self, value: float) -> str:
        for label_value, label_text in self._custom_labels.items():
            if math.isclose(value, label_value, abs_tol=max(1e-9, abs(self._label_step) * 1e-6)):
                return label_text
        return self._format_value(value)

    @staticmethod
    def _rects_overlap(first: QRectF, second: QRectF, padding: float) -> bool:
        expanded_first = first.adjusted(-padding, -padding, padding, padding)
        expanded_second = second.adjusted(-padding, -padding, padding, padding)
        return expanded_first.intersects(expanded_second)

    def _preferred_label_values(self) -> list[float]:
        centred_values = self._bidirectional_preferred_label_values()
        if centred_values is not None:
            return centred_values

        if self._custom_labels:
            custom_values = sorted(self._custom_labels.keys())
            deduplicated: list[float] = []
            seen_angles: list[float] = []
            for value in custom_values:
                angle = self._normalise_angle(self._value_to_angle(value))
                if any(math.isclose(angle, existing, abs_tol=1e-6) for existing in seen_angles):
                    continue
                deduplicated.append(value)
                seen_angles.append(angle)
            if deduplicated and self._label_set_fits(deduplicated):
                return deduplicated
            compass_candidates = self._reduced_compass_label_sets(deduplicated)
            for candidates in compass_candidates:
                if self._label_set_fits(candidates):
                    return candidates

        if not self._preferred_label_counts:
            return self._iter_tick_values(self._label_step)

        span = self._maximum - self._minimum
        if span <= 0:
            return [self._minimum]

        full_circle = self._is_full_circle_scale()
        for count in self._preferred_label_counts:
            if count < 2:
                continue
            if full_circle:
                step = span / count
                candidates = [self._minimum + (index * step) for index in range(count)]
            else:
                step = span / (count - 1)
                candidates = [self._minimum + (index * step) for index in range(count)]
                candidates[-1] = self._maximum
            if self._label_set_fits(candidates):
                return candidates

        fallback_count = self._preferred_label_counts[-1]
        if fallback_count >= 2:
            if full_circle:
                step = span / fallback_count
                candidates = [self._minimum + (index * step) for index in range(fallback_count)]
            else:
                step = span / (fallback_count - 1)
                candidates = [self._minimum + (index * step) for index in range(fallback_count)]
                candidates[-1] = self._maximum
            if (
                not full_circle
                and self._preserve_endpoint_labels
                and not self._label_set_fits(candidates)
                and len(candidates) > 2
            ):
                return [candidates[0], candidates[len(candidates) // 2], candidates[-1]]
            return candidates
        return self._iter_tick_values(self._label_step)

    def _bidirectional_preferred_label_values(self) -> list[float] | None:
        if self._wrap:
            return None
        if self._minimum >= 0.0 or self._maximum <= 0.0:
            return None

        candidate_sets = [
            [-150.0, -120.0, -90.0, -60.0, -30.0, 0.0, 30.0, 60.0, 90.0, 120.0, 150.0],
            [-135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0],
            [-120.0, -60.0, 0.0, 60.0, 120.0],
            [-90.0, 0.0, 90.0],
        ]

        valid_candidates = [
            [value for value in values if self._minimum <= value <= self._maximum]
            for values in candidate_sets
        ]

        for candidates in valid_candidates:
            if any(math.isclose(value, 0.0, abs_tol=1e-9) for value in candidates) and self._label_set_fits(candidates):
                return candidates

        for candidates in valid_candidates:
            if any(math.isclose(value, 0.0, abs_tol=1e-9) for value in candidates):
                return candidates

        full_range = [self._minimum, 0.0, self._maximum]
        deduplicated: list[float] = []
        for value in full_range:
            if not any(math.isclose(value, existing, abs_tol=1e-9) for existing in deduplicated):
                deduplicated.append(value)
        return deduplicated

    def _reduced_compass_label_sets(self, values: list[float]) -> list[list[float]]:
        if len(values) < 8 or not self._is_full_circle_scale():
            return []

        normalised = sorted(
            (
                (self._normalise_angle(self._value_to_angle(value)), value)
                for value in values
            ),
            key=lambda item: item[0],
        )
        sorted_values = [value for _, value in normalised]
        count = len(sorted_values)
        if count not in {8, 16}:
            return []

        candidate_sets: list[list[float]] = []
        if count == 16:
            candidate_sets.append([sorted_values[index] for index in range(0, 16, 2)])
            candidate_sets.append([sorted_values[index] for index in range(0, 16, 4)])
        elif count == 8:
            candidate_sets.append([sorted_values[index] for index in range(0, 8, 2)])

        return candidate_sets

    def _label_draw_rects(
        self,
        values: list[float],
        metrics: QFontMetricsF,
        center: QPointF,
        radius: float,
    ) -> list[QRectF]:
        rects: list[QRectF] = []
        for value in values:
            text = self._label_text(value)
            pos = self._point_on_circle(center, radius, self._value_to_angle(value))
            text_rect = metrics.boundingRect(text)
            rects.append(
                QRectF(
                    pos.x() - (text_rect.width() / 2.0) - 2.0,
                    pos.y() - (text_rect.height() / 2.0) - 1.0,
                    text_rect.width() + 4.0,
                    text_rect.height() + 2.0,
                )
            )
        return rects

    def _label_set_fits(self, values: list[float]) -> bool:
        font = QFont(self.font())
        font.setBold(False)
        font.setPointSizeF(max(self._minimum_label_point_size, min(self.width(), self.height()) * self._label_font_scale))
        metrics = QFontMetricsF(font)
        top_space = self.height() * self._top_reserved_fraction
        bottom_space = self.height() * self._bottom_reserved_fraction
        usable_height = max(1.0, self.height() - top_space - bottom_space)
        dial_side = min(self.width(), usable_height)
        radius = max(1.0, (dial_side * 0.92 / 2.0) * self._label_radius_factor)
        center = QPointF(self.width() / 2.0, top_space + (usable_height / 2.0))
        rects = self._label_draw_rects(values, metrics, center, radius)
        for left in range(len(rects)):
            for right in range(left + 1, len(rects)):
                if self._rects_overlap(rects[left], rects[right], self._label_collision_padding):
                    return False
        return True

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
        font.setPointSizeF(max(self._minimum_label_point_size, min(self.width(), self.height()) * self._label_font_scale))
        painter.setFont(font)
        painter.setPen(self._label_color)
        metrics = QFontMetricsF(font)
        values = self._preferred_label_values()
        rects = self._label_draw_rects(values, metrics, center, radius)

        for value, draw_rect in zip(values, rects, strict=False):
            text = self._label_text(value)
            if self._label_background_visible:
                painter.save()
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._label_background_color)
                painter.drawRoundedRect(draw_rect, 3.0, 3.0)
                painter.restore()
                painter.setPen(self._label_color)
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
        font.setPointSizeF(max(self._minimum_title_point_size, rect.width() * self._title_font_scale))
        painter.setFont(font)
        painter.setPen(self._title_color)
        title_rect = QRectF(
            rect.left(),
            rect.top() - rect.height() * self._top_reserved_fraction + rect.height() * self._title_vertical_offset_fraction,
            rect.width(),
            rect.height() * self._top_reserved_fraction * 0.95,
        )
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignTop, self._title)

    def _draw_value_text(self, painter: QPainter, center: QPointF, radius: float) -> None:
        if not self._show_value_text:
            return
        font = QFont(self.font())
        font.setBold(False)
        font.setPointSizeF(max(self._minimum_value_point_size, radius * self._value_font_scale))
        painter.setFont(font)
        painter.setPen(self._value_text_color)

        text = self._format_value_text(self._value)
        rect = QRectF(
            center.x() - radius * 0.35,
            center.y() + radius * 0.25,
            radius * 0.70,
            radius * 0.18,
        )
        painter.drawText(rect, Qt.AlignCenter, text)

    def _draw_label_legend_overlay_fix(self, painter: QPainter) -> None:
        """Reserved hook for future overlay polish."""
        del painter
