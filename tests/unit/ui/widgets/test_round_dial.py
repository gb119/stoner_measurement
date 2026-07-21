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

    def test_preferred_label_values_reduces_full_circle_custom_labels_when_needed(self, qapp, monkeypatch):
        widget = RoundDialWidget()
        widget.setRange(0, 360)
        widget.setScaleAngles(0, 360)
        widget.setCustomLabels({index * 22.5: str(index) for index in range(16)})

        def fake_label_set_fits(values):
            return len(values) <= 8

        monkeypatch.setattr(widget, "_label_set_fits", fake_label_set_fits)

        assert widget._preferred_label_values() == [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]  # noqa: SLF001

    def test_preferred_label_values_preserves_endpoints_with_middle_fallback(self, qapp, monkeypatch):
        widget = RoundDialWidget()
        widget.setRange(0, 100)
        widget.setScaleAngles(-135, 135)
        widget.setPreferredLabelCounts([5])

        monkeypatch.setattr(widget, "_label_set_fits", lambda values: False)

        assert widget._preferred_label_values() == [0.0, 50.0, 100.0]  # noqa: SLF001


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
