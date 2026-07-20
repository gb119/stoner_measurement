"""Focused tests for the SI-aware spin box widget."""

from __future__ import annotations

import pytest

from stoner_measurement.ui.theme import theme_stylesheet
from stoner_measurement.ui.widgets import SISpinBox


class TestSISpinBox:
    """Tests for :class:`SISpinBox` and its relaxed suffix-validation behaviour."""

    def test_is_subclass_of_pg_spinbox(self, qapp):
        import pyqtgraph as pg

        assert issubclass(SISpinBox, pg.SpinBox)

    def test_creates_widget(self, qapp):
        spin = SISpinBox()
        assert spin is not None

    def test_applies_minimum_height_for_readability(self, qapp):
        """Spin box and editor should use a taller default height."""
        spin = SISpinBox()
        assert spin.minimumHeight() >= 28
        assert spin.lineEdit().minimumHeight() >= 24

    def test_theme_stylesheet_contains_checkbox_and_tab_polish(self, qapp):
        """Global theme stylesheet should include checkbox and tab styling."""
        qss = theme_stylesheet()
        assert "QCheckBox::indicator" in qss
        assert "QTabBar::tab:selected" in qss

    def test_value_with_explicit_suffix_unchanged(self, qapp):
        """Standard behaviour: user types the full unit string."""
        spin = SISpinBox(suffix="K", siPrefix=True, value=100.0)
        spin.lineEdit().setText("200 K")
        result = spin.interpret()
        assert result is not False
        assert float(result) == 200.0

    def test_value_without_suffix_appends_suffix(self, qapp):
        """Bare number without suffix is accepted and the suffix is appended."""
        spin = SISpinBox(suffix="K", siPrefix=True, value=100.0)
        spin.lineEdit().setText("200")
        result = spin.interpret()
        assert result is not False
        assert float(result) == 200.0

    def test_si_prefix_without_suffix_appends_suffix(self, qapp):
        """SI prefix followed by number, but missing the unit, is accepted."""
        spin = SISpinBox(suffix="K", siPrefix=True, value=100.0)
        spin.lineEdit().setText("200m")
        result = spin.interpret()
        assert result is not False
        # 200 mK = 0.2 K
        assert abs(float(result) - 0.2) < 1e-9

    def test_empty_suffix_no_change(self, qapp):
        """When no suffix is configured the base behaviour is unchanged."""
        spin = SISpinBox(value=42.0)
        spin.lineEdit().setText("99")
        result = spin.interpret()
        assert result is not False
        assert float(result) == 99.0

    def test_invalid_input_returns_false(self, qapp):
        """Garbage input still returns False."""
        spin = SISpinBox(suffix="K", siPrefix=True, value=100.0)
        spin.lineEdit().setText("not-a-number")
        result = spin.interpret()
        assert result is False

    def test_int_spinbox_without_suffix(self, qapp):
        """Integer SpinBox (no suffix) continues to work normally."""
        spin = SISpinBox(int=True, value=5)
        spin.lineEdit().setText("10")
        result = spin.interpret()
        assert result is not False
        assert int(result) == 10

    def test_exported_from_ui_widgets(self, qapp):
        """SISpinBox is accessible via the widgets package public API."""
        import stoner_measurement.ui.widgets as widgets

        assert widgets.SISpinBox is SISpinBox

    def test_exported_from_ui(self, qapp):
        """SISpinBox is accessible via the top-level ui package."""
        import stoner_measurement.ui as ui

        assert ui.SISpinBox is SISpinBox


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
