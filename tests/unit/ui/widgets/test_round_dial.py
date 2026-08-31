"""Tests for RoundDialWidget and RoundDialDemoWidget."""

from __future__ import annotations

import pytest
from qtpy.QtCore import QPointF, QRectF
from qtpy.QtGui import QColor, QImage, QPainter

import stoner_measurement.ui.theme as theme_module
from stoner_measurement.ui.theme import colour
from stoner_measurement.ui.widgets import RoundDialDemoWidget, RoundDialWidget


class TestRoundDialWidget:
    def test_creates_widget(self, qapp):
        widget = RoundDialWidget()
        assert widget is not None

    def test_default_range(self, qapp):
        widget = RoundDialWidget()
        assert widget.minimumValue() == pytest.approx(0.0)
        assert widget.maximumValue() == pytest.approx(360.0)

    def test_set_range(self, qapp):
        widget = RoundDialWidget()
        widget.setRange(-10, 10)
        assert widget.minimumValue() == pytest.approx(-10.0)
        assert widget.maximumValue() == pytest.approx(10.0)

    def test_set_range_rejects_invalid(self, qapp):
        widget = RoundDialWidget()
        with pytest.raises(ValueError):
            widget.setRange(5, 5)

    def test_set_scale_angles(self, qapp):
        widget = RoundDialWidget()
        widget.setScaleAngles(-135, 135)
        assert widget.minimumAngle() == pytest.approx(-135.0)
        assert widget.maximumAngle() == pytest.approx(135.0)

    def test_set_value_clamps(self, qapp):
        widget = RoundDialWidget()
        widget.setRange(0, 100)
        widget.setValue(150)
        assert widget.value() == pytest.approx(100.0)

    def test_wrap_mode_wraps_value(self, qapp):
        widget = RoundDialWidget()
        widget.setRange(0, 360)
        widget.setWrap(True)
        widget.setValue(370)
        assert widget.value() == pytest.approx(10.0)

    def test_angle_mode_sets_expected_defaults(self, qapp):
        widget = RoundDialWidget()
        widget.setAngleValueMode()
        assert widget.minimumValue() == pytest.approx(0.0)
        assert widget.maximumValue() == pytest.approx(360.0)
        assert widget.minimumAngle() == pytest.approx(0.0)
        assert widget.maximumAngle() == pytest.approx(360.0)
        assert widget.wrap() is True
        assert widget.unitsText() == "°"

    def test_bidirectional_mode_sets_expected_defaults(self, qapp):
        widget = RoundDialWidget()
        widget.setBidirectionalAngleMode()
        assert widget.minimumValue() == pytest.approx(-180.0)
        assert widget.maximumValue() == pytest.approx(180.0)
        assert widget.wrap() is False

    def test_set_tick_steps_updates_all(self, qapp):
        widget = RoundDialWidget()
        widget.setTickSteps(20, 3, 40)
        assert widget.majorTickStep() == pytest.approx(20.0)
        assert widget.minorTicksPerMajor() == 3
        assert widget.labelStep() == pytest.approx(40.0)

    def test_theme_colors_follow_active_theme(self, qapp):
        widget = RoundDialWidget()
        original_theme = theme_module._current_theme_name  # noqa: SLF001
        try:
            theme_module._current_theme_name = "light"  # noqa: SLF001
            widget.resetThemeColors()
            assert widget._tick_color == QColor(colour("text"))  # noqa: SLF001

            theme_module._current_theme_name = "dark"  # noqa: SLF001
            widget.resetThemeColors()
            assert widget._pointer_color == QColor(colour("trace_red"))  # noqa: SLF001
        finally:
            theme_module._current_theme_name = original_theme  # noqa: SLF001

    def test_custom_color_survives_theme_change(self, qapp):
        widget = RoundDialWidget()
        custom = QColor("#123456")
        widget.setPointerColor(custom)
        original_theme = theme_module._current_theme_name  # noqa: SLF001
        try:
            theme_module._current_theme_name = "light"  # noqa: SLF001
            widget._apply_theme_colors()  # noqa: SLF001
            assert widget._pointer_color == custom  # noqa: SLF001
        finally:
            theme_module._current_theme_name = original_theme  # noqa: SLF001

    def test_show_flags_toggle(self, qapp):
        widget = RoundDialWidget()
        widget.setShowTicks(False)
        widget.setShowLabels(False)
        widget.setShowValueText(False)
        assert widget.showTicks() is False
        assert widget.showLabels() is False
        assert widget.showValueText() is False

    def test_preferred_label_values_reduces_full_circle_custom_labels_when_needed(self, qapp, monkeypatch):
        widget = RoundDialWidget()
        widget.setRange(0, 360)
        widget.setScaleAngles(0, 360)
        widget.setCustomLabels({index * 22.5: str(index) for index in range(16)})

        def fake_label_set_fits(values):
            return len(values) <= 8

        monkeypatch.setattr(widget, "_label_set_fits", fake_label_set_fits)

        assert widget._preferred_label_values() == [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]  # noqa: SLF001

    def test_preferred_label_values_deduplicates_full_circle_endpoint(
        self,
        qapp,
        monkeypatch,
    ):
        widget = RoundDialWidget()
        widget.setRange(0, 360)
        widget.setScaleAngles(0, 360)
        widget.setCustomLabels({0.0: "North", 360.0: "North"})
        monkeypatch.setattr(widget, "_label_set_fits", lambda _values: True)

        assert widget._preferred_label_values() == [0.0]  # noqa: SLF001

    def test_preferred_label_values_preserves_endpoints_with_middle_fallback(self, qapp, monkeypatch):
        widget = RoundDialWidget()
        widget.setRange(0, 100)
        widget.setScaleAngles(-135, 135)
        widget.setPreferredLabelCounts([5])

        monkeypatch.setattr(widget, "_label_set_fits", lambda values: False)

        assert widget._preferred_label_values() == [0.0, 50.0, 100.0]  # noqa: SLF001


class TestRoundDialAdditionalContracts:
    """Exercise the public configuration and rendering branches of the dial."""

    def test_scale_angles_reject_equal_values(self, qapp):
        widget = RoundDialWidget()
        with pytest.raises(ValueError, match="must differ"):
            widget.setScaleAngles(90, 90)

    def test_complete_turn_wraps_to_minimum(self, qapp):
        widget = RoundDialWidget()
        widget.setWrap(True)
        widget.setValue(720)
        assert widget.value() == pytest.approx(0.0)

    def test_value_changed_only_emits_for_new_value(self, qapp, qtbot):
        widget = RoundDialWidget()
        widget.setRange(0, 100)

        with qtbot.waitSignal(widget.valueChanged) as signal:
            widget.setValue(75)
        widget.setValue(75)

        assert signal.args == [75.0]

    @pytest.mark.parametrize(
        ("setter", "value", "message"),
        [
            ("setMajorTickStep", 0, "positive"),
            ("setMinorTicksPerMajor", -1, "non-negative"),
            ("setLabelStep", 0, "positive"),
            ("setLabelFontScale", 0, "positive"),
            ("setTitleFontScale", -1, "positive"),
            ("setValueFontScale", 0, "positive"),
            ("setLabelRadiusFactor", 0.05, "between"),
            ("setTopReservedFraction", 0.5, "between"),
            ("setBottomReservedFraction", -0.1, "between"),
            ("setTitleVerticalOffsetFraction", 0.2, "between"),
            ("setScaleBandWidthFactor", 0.0, "between"),
            ("setDecimals", -1, "non-negative"),
        ],
    )
    def test_numeric_configuration_rejects_out_of_range_values(
        self, qapp, setter, value, message
    ):
        widget = RoundDialWidget()
        with pytest.raises(ValueError, match=message):
            getattr(widget, setter)(value)

    def test_layout_and_text_configuration_round_trip(self, qapp):
        widget = RoundDialWidget()
        widget.setLabelFontScale(0.08)
        widget.setTitleFontScale(0.09)
        widget.setValueFontScale(0.18)
        widget.setLabelRadiusFactor(0.75)
        widget.setTopReservedFraction(0.2)
        widget.setBottomReservedFraction(0.15)
        widget.setTitleVerticalOffsetFraction(-0.03)
        widget.setPreferredLabelCounts([1, 8, 0, 4])
        widget.setPreserveEndpointLabels(False)
        widget.setValueTextSuffix(" rpm")
        widget.setDecimals(2)
        widget.setValue(12.5)

        assert widget.labelFontScale() == pytest.approx(0.08)
        assert widget.titleFontScale() == pytest.approx(0.09)
        assert widget.valueFontScale() == pytest.approx(0.18)
        assert widget.labelRadiusFactor() == pytest.approx(0.75)
        assert widget.topReservedFraction() == pytest.approx(0.2)
        assert widget.bottomReservedFraction() == pytest.approx(0.15)
        assert widget.titleVerticalOffsetFraction() == pytest.approx(-0.03)
        assert widget.preferredLabelCounts() == [8, 4]
        assert widget.preserveEndpointLabels() is False
        assert widget.formattedValueText() == "12.50 rpm"

    def test_custom_labels_and_scale_band_are_copied_and_sorted(self, qapp):
        widget = RoundDialWidget()
        labels = {90: "East", 0: "North"}
        widget.setCustomLabels(labels)
        labels[180] = "South"
        widget.setScaleBandStops([(100, "red"), (0, "green"), (50, "yellow")])

        returned = widget.customLabels()
        returned[270] = "West"

        assert widget.customLabels() == {90.0: "East", 0.0: "North"}
        assert [value for value, _color in widget.scaleBandStops()] == [0.0, 50.0, 100.0]

        widget.clearCustomLabels()
        assert widget.customLabels() == {}

    def test_display_flags_and_band_visibility_round_trip(self, qapp):
        widget = RoundDialWidget()
        widget.setLabelBackgroundVisible(True)
        widget.setScaleBandVisible(True)
        widget.setScaleBandWidthFactor(0.2)

        assert widget.labelBackgroundVisible() is True
        assert widget.scaleBandVisible() is True

    def test_clock_mode_formats_fractional_hours_and_rounds_minutes(self, qapp):
        widget = RoundDialWidget()
        widget.setClockMode()
        widget.setValue(0.5)
        assert widget.formattedValueText() == "12:30"

        widget.setValue(11.9999)
        assert widget.formattedValueText() == "12:00"
        assert widget.customLabels()[0.0] == "12"

    @pytest.mark.parametrize(
        ("points", "expected"),
        [(4, "E"), (8, "NE"), (16, "NNE")],
    )
    def test_compass_label_modes(self, qapp, points, expected):
        widget = RoundDialWidget()
        widget.setAngleValueMode()
        widget.setCompassLabelMode(points)

        assert expected in widget.customLabels().values()
        assert widget.majorTickStep() == pytest.approx(360 / points)

    def test_compass_label_mode_rejects_unsupported_point_count(self, qapp):
        widget = RoundDialWidget()
        with pytest.raises(ValueError, match="4, 8, or 16"):
            widget.setCompassLabelMode(12)

    def test_all_custom_colours_survive_theme_refresh(self, qapp):
        widget = RoundDialWidget()
        setters = {
            "setFaceColor": "_face_color",
            "setTickColor": "_tick_color",
            "setLabelColor": "_label_color",
            "setPointerColor": "_pointer_color",
            "setValueTextColor": "_value_text_color",
            "setTitleColor": "_title_color",
        }
        for index, (setter, _attribute) in enumerate(setters.items(), start=1):
            getattr(widget, setter)(QColor(index, index + 1, index + 2))

        widget._apply_theme_colors()  # noqa: SLF001

        for index, attribute in enumerate(setters.values(), start=1):
            assert getattr(widget, attribute) == QColor(index, index + 1, index + 2)

    def test_bidirectional_labels_keep_zero_and_fit_requested_range(self, qapp, monkeypatch):
        widget = RoundDialWidget()
        widget.setRange(-100, 70)
        widget.setScaleAngles(-135, 135)
        widget.setWrap(False)
        monkeypatch.setattr(widget, "_label_set_fits", lambda values: len(values) <= 3)

        values = widget._preferred_label_values()  # noqa: SLF001

        assert values == [-60.0, 0.0, 60.0]

    def test_geometry_helpers_map_dial_angles_clockwise(self, qapp):
        center = QPointF(10, 20)
        top = RoundDialWidget._point_on_circle(center, 5, 0)  # noqa: SLF001
        right = RoundDialWidget._point_on_circle(center, 5, 90)  # noqa: SLF001

        assert (top.x(), top.y()) == pytest.approx((10, 15))
        assert (right.x(), right.y()) == pytest.approx((15, 20))
        assert RoundDialWidget._normalise_angle(-90) == pytest.approx(270)  # noqa: SLF001

    def test_rect_overlap_respects_padding(self, qapp):
        first = QRectF(0, 0, 10, 10)
        second = QRectF(11, 0, 10, 10)
        assert RoundDialWidget._rects_overlap(first, second, 0) is False  # noqa: SLF001
        assert RoundDialWidget._rects_overlap(first, second, 1) is True  # noqa: SLF001

    @pytest.mark.parametrize("mode", ["angle", "clock", "compass", "bidirectional"])
    def test_dial_modes_render_complete_nonempty_images(
        self, qapp, managed_qt_widget, mode
    ):
        widget = managed_qt_widget(RoundDialWidget())
        widget.resize(320, 300)
        widget.setTitle("Rendered dial")
        method = {
            "angle": "setAngleValueMode",
            "clock": "setClockMode",
            "compass": "setCompassMode",
            "bidirectional": "setBidirectionalAngleMode",
        }[mode]
        getattr(widget, method)()
        widget.setValue(45 if mode != "clock" else 3.5)
        widget.setLabelBackgroundVisible(True)
        widget.setScaleBandVisible(True)
        widget.setScaleBandStops(
            [(widget.minimumValue(), "green"), (widget.maximumValue(), "red")]
        )
        image = QImage(widget.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("transparent"))
        painter = QPainter(image)

        widget.render(painter)
        painter.end()

        assert image.isNull() is False
        assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() > 0


class TestRoundDialDemoWidget:
    def test_creates_widget(self, qapp):
        widget = RoundDialDemoWidget()
        assert widget is not None

    def test_demo_contains_dial(self, qapp):
        widget = RoundDialDemoWidget()
        assert isinstance(widget.dial, RoundDialWidget)

    def test_compass_preset_sets_direction_title(self, qapp):
        widget = RoundDialDemoWidget()
        widget._apply_preset("compass")  # noqa: SLF001
        assert widget.dial.title() == "Direction"

    def test_percent_preset_sets_percentage_units(self, qapp):
        widget = RoundDialDemoWidget()
        widget._apply_preset("percent")  # noqa: SLF001
        assert widget.dial.unitsText() == "%"


if __name__ == "__main__":

    raise SystemExit(pytest.main([__file__, "--pdb"]))
