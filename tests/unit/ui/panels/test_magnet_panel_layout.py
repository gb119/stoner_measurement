"""Responsive layout tests for the magnet control panel."""

from __future__ import annotations

import pytest
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QScrollArea

from stoner_measurement.magnet_control.engine import MagnetControllerEngine
from stoner_measurement.ui.magnet_panel import MagnetControlPanel


@pytest.fixture(autouse=True)
def cleanup_magnet_engine():
    """Keep the singleton engine isolated between panel tests."""
    engine = MagnetControllerEngine._singleton  # noqa: SLF001
    if engine is not None:
        engine.shutdown()
    yield
    engine = MagnetControllerEngine._singleton  # noqa: SLF001
    if engine is not None:
        engine.shutdown()


def test_configuration_tab_scrolls_when_panel_is_short(managed_qt_widget, qapp):
    """Configuration controls retain natural height and gain a vertical scrollbar."""
    panel = managed_qt_widget(MagnetControlPanel())
    config_tab = panel._tabs.widget(1)  # noqa: SLF001
    assert isinstance(config_tab, QScrollArea)
    assert config_tab.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded

    panel.resize(700, 300)
    panel.show()
    qapp.processEvents()

    assert config_tab.verticalScrollBar().maximum() > 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
