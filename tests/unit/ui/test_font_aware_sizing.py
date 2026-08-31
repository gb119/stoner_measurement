"""Application-font responsive sizing for text-bearing controls."""

from __future__ import annotations

import pytest
from qtpy.QtCore import Qt
from qtpy.QtGui import QFont, QFontMetrics
from qtpy.QtWidgets import QWidget

from stoner_measurement.ui.aspect_ratio_widget import ContentWrappingTabWidget
from stoner_measurement.ui.data_manager import DataManagerWindow
from stoner_measurement.ui.font_aware_tabs import FontAwareTabBar, FontAwareTabWidget
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


@pytest.mark.parametrize("tab_type", [FontAwareTabWidget, ContentWrappingTabWidget])
def test_tabs_reserve_bold_selected_label_width(qapp, managed_qt_widget, tab_type):
    original_font = QFont(qapp.font())
    tabs = managed_qt_widget(tab_type())
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


def test_standalone_tab_bar_reserves_bold_selected_label_width(qapp, managed_qt_widget):
    bar = managed_qt_widget(FontAwareTabBar())
    label = "Long sequence document name"
    bar.addTab("Overview")
    bar.addTab(label)
    bar.setStyleSheet(
        "QTabBar::tab { padding: 6px 12px; } "
        "QTabBar::tab:selected { font-weight: 600; }"
    )
    bar.setExpanding(False)
    bar.show()
    qapp.processEvents()

    unselected_width = bar.tabRect(1).width()
    bar.setCurrentIndex(1)
    qapp.processEvents()

    assert bar.tabRect(1).width() == unselected_width


def test_initially_selected_first_tab_reserves_bold_label_width(qapp, managed_qt_widget):
    tabs = managed_qt_widget(FontAwareTabWidget())
    label = "Set DAQmx"
    tabs.addTab(QWidget(), label)
    tabs.addTab(QWidget(), "About")
    tabs.setStyleSheet(
        "QTabBar::tab { padding: 6px 12px; } "
        "QTabBar::tab:selected { font-weight: 600; }"
    )
    tabs.tabBar().setExpanding(False)
    tabs.show()
    qapp.processEvents()

    initial_width = tabs.tabBar().tabRect(0).width()
    bold_font = QFont(tabs.tabBar().font())
    bold_font.setWeight(QFont.Weight.DemiBold)
    bold_text_width = QFontMetrics(bold_font).horizontalAdvance(label)

    tabs.setCurrentIndex(1)
    qapp.processEvents()

    assert initial_width >= bold_text_width + 24
    assert tabs.tabBar().tabRect(0).width() == initial_width


def test_vertical_main_tabs_reserve_bold_label_height(qapp, managed_qt_widget):
    tabs = managed_qt_widget(FontAwareTabWidget())
    label = "Measurement"
    tabs.setTabPosition(FontAwareTabWidget.TabPosition.West)
    tabs.addTab(QWidget(), label)
    tabs.addTab(QWidget(), "Script Editor")
    tabs.setStyleSheet(
        "QTabBar::tab { padding: 6px 12px; } "
        "QTabBar::tab:selected { font-weight: 600; }"
    )
    tabs.tabBar().setExpanding(False)
    tabs.show()
    qapp.processEvents()

    initial_height = tabs.tabBar().tabRect(0).height()
    bold_font = QFont(tabs.tabBar().font())
    bold_font.setWeight(QFont.Weight.DemiBold)
    bold_text_width = QFontMetrics(bold_font).horizontalAdvance(label)

    tabs.setCurrentIndex(1)
    qapp.processEvents()

    assert initial_height >= bold_text_width + 12
    assert tabs.tabBar().tabRect(0).height() == initial_height


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
