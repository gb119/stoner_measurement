"""Application-font responsive sizing for text-bearing controls."""

from __future__ import annotations

import pytest
from qtpy.QtCore import Qt
from qtpy.QtGui import QFont, QFontMetrics
from qtpy.QtWidgets import QWidget

from stoner_measurement.ui.data_manager import DataManagerWindow
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.log_viewer import LogViewerWindow
from stoner_measurement.ui.theme import apply_application_font


def test_auxiliary_window_buttons_can_grow_with_large_font(
    qapp,
    engine,
    managed_qt_widget,
):
    original_font = QFont(qapp.font())
    try:
        apply_application_font(qapp, 30)
        data_manager = managed_qt_widget(DataManagerWindow(engine))
        log_viewer = managed_qt_widget(LogViewerWindow())

        for button in (
            data_manager._btn_close,  # noqa: SLF001
            log_viewer._btn_clear,  # noqa: SLF001
            log_viewer._btn_close,  # noqa: SLF001
        ):
            label_width = button.fontMetrics().horizontalAdvance(button.text())
            assert button.maximumWidth() > button.sizeHint().width()
            assert button.sizeHint().width() > label_width
    finally:
        qapp.setFont(original_font)


def test_tabs_reserve_bold_selected_label_width(qapp, managed_qt_widget):
    original_font = QFont(qapp.font())
    tabs = managed_qt_widget(FontAwareTabWidget())
    label = "Long measurement settings"
    tabs.addTab(QWidget(), "Overview")
    tabs.addTab(QWidget(), label)
    tabs.setStyleSheet(
        "QTabBar::tab { padding: 6px 12px; } "
        "QTabBar::tab:selected { font-weight: 600; }"
    )

    try:
        apply_application_font(qapp, 30)
        tabs.tabBar().setExpanding(False)
        tabs.show()
        qapp.processEvents()

        unselected_width = tabs.tabBar().tabRect(1).width()
        bold_font = QFont(tabs.tabBar().font())
        bold_font.setWeight(QFont.Weight.DemiBold)
        bold_text_width = QFontMetrics(bold_font).horizontalAdvance(label)

        tabs.setCurrentIndex(1)
        qapp.processEvents()

        assert unselected_width >= bold_text_width + 24
        assert tabs.tabBar().tabRect(1).width() == unselected_width
        assert tabs.tabBar().elideMode() == Qt.TextElideMode.ElideNone
        assert tabs.tabBar().usesScrollButtons()
    finally:
        qapp.setFont(original_font)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
