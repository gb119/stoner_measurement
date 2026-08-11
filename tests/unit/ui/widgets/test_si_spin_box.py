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
        spin = SISpinBox(suffix="K", siPrefix=True, value=100.0, allow_expressions=True)
        spin.lineEdit().setText("200 K")
        result = spin.interpret()
        assert result is not False
        assert float(result) == 200.0

    def test_value_without_suffix_appends_suffix(self, qapp):
        """Bare number without suffix is accepted and the suffix is appended."""
        spin = SISpinBox(suffix="K", siPrefix=True, value=100.0, allow_expressions=True)
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

    def test_expression_is_retained_for_runtime_evaluation(self, qapp):
        """Non-numeric text is retained rather than evaluated by the widget."""
        spin = SISpinBox(suffix="K", siPrefix=True, value=100.0, allow_expressions=True)
        spin.lineEdit().setText("target_temperature + offset")
        result = spin.interpret()
        assert result == "target_temperature + offset"

        spin.editingFinishedEvent()

        assert spin.value() == "target_temperature + offset"
        assert spin.lineEdit().text() == "target_temperature + offset"

    def test_expression_support_is_opt_in(self, qapp):
        """Direct-control widgets reject text without an evaluation context."""
        spin = SISpinBox(value=1.0)
        spin.lineEdit().setText("namespace_value")

        assert spin.interpret() is False

    def test_expression_can_be_supplied_as_initial_value(self, qapp):
        """A programmatic string value survives construction unchanged."""
        spin = SISpinBox(
            suffix="V", siPrefix=True, value="drive_voltage * gain", allow_expressions=True
        )

        assert spin.value() == "drive_voltage * gain"
        assert spin.lineEdit().text() == "drive_voltage * gain"

    def test_expression_emits_string_value(self, qapp, qtbot):
        """Consumers receive the expression through the standard value signal."""
        spin = SISpinBox(value=1.0, allow_expressions=True)
        with qtbot.waitSignal(spin.valueChanged) as blocker:
            spin.setValue("settling_time / 2")

        assert blocker.args == ["settling_time / 2"]

    def test_expression_signal_is_not_repeated_after_proxy_delay(self, qapp, qtbot):
        """The delayed-signal proxy does not duplicate an immediate change."""
        spin = SISpinBox(value=1.0, delay=0.01, allow_expressions=True)
        received = []
        spin.valueChanged.connect(received.append)

        spin.setValue("settling_time / 2")
        qtbot.wait(30)

        assert received == ["settling_time / 2"]

    def test_numeric_value_clears_expression_mode(self, qapp):
        """Setting a number restores normal SI formatting and return types."""
        spin = SISpinBox(
            suffix="A", siPrefix=True, value="source_current", allow_expressions=True
        )

        spin.setValue(0.002)

        assert spin.value() == pytest.approx(0.002)
        assert "mA" in spin.lineEdit().text()

    def test_numeric_fallback_emits_when_clearing_expression(self, qapp, qtbot):
        """Changing representation emits even if the retained number is equal."""
        spin = SISpinBox(value=2.0, allow_expressions=True)
        spin.setValue("requested_value")

        with qtbot.waitSignal(spin.valueChanged) as blocker:
            spin.setValue(2.0)

        assert blocker.args == [2.0]

    def test_arrow_step_replaces_expression_with_numeric_fallback(self, qapp):
        """Stepping remains useful and returns the editor to numeric mode."""
        spin = SISpinBox(value=2.0, step=0.5, allow_expressions=True)
        spin.setValue("requested_value")

        spin.stepBy(1)

        assert spin.value() == pytest.approx(2.5)

    def test_arrow_step_uses_numeric_string_as_initial_fallback(self, qapp):
        """A constant expression has a useful numeric stepping baseline."""
        spin = SISpinBox(value="2.0", step=0.5, allow_expressions=True)

        spin.stepBy(1)

        assert spin.value() == pytest.approx(2.5)

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
