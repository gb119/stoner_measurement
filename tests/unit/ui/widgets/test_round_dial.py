"""Tests for RoundDialWidget and RoundDialDemoWidget."""

from __future__ import annotations

import pytest
from qtpy.QtGui import QColor

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
