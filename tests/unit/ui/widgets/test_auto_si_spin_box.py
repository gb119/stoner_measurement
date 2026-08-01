"""Tests for the SI spin box's explicit Auto state."""

from __future__ import annotations

import pytest

from stoner_measurement.ui.widgets import AutoSISpinBox


class TestAutoSISpinBox:
    def test_can_select_auto_programmatically(self, qapp):
        spin = AutoSISpinBox(suffix="%", value=12.5)

        spin.setAuto(True)

        assert spin.isAuto()
        assert spin.lineEdit().text() == "Auto"
        assert spin.value() == pytest.approx(12.5)

    def test_accepts_typed_auto(self, qapp):
        spin = AutoSISpinBox(suffix="%", value=12.5)
        spin.lineEdit().setText("auto")

        spin.editingFinishedEvent()

        assert spin.isAuto()
        assert spin.lineEdit().text() == "Auto"

    def test_numeric_edit_clears_auto(self, qapp):
        spin = AutoSISpinBox(suffix="%", value=12.5, auto=True)
        spin.lineEdit().setText("25")

        spin.editingFinishedEvent()

        assert not spin.isAuto()
        assert spin.value() == pytest.approx(25.0)

    def test_context_menu_auto_action_selects_auto(self, qapp):
        spin = AutoSISpinBox(suffix="%", value=12.5)
        menu = spin._create_context_menu()
        auto_action = next(action for action in menu.actions() if action.text() == "Auto")

        auto_action.trigger()

        assert spin.isAuto()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
