"""Standalone demo entry point for the round dial widgets."""

from __future__ import annotations

import sys

from qtpy.QtWidgets import QApplication, QMainWindow

from stoner_measurement.app_config import theme_setting
from stoner_measurement.ui.icons import make_app_icon
from stoner_measurement.ui.theme import apply_theme
from stoner_measurement.ui.widgets import RoundDialDemoWidget


def main(argv: list[str] | None = None) -> int:
    """Launch a small standalone window demonstrating the round dial widgets."""
    if argv is None:
        argv = sys.argv

    app = QApplication(argv)
    app.setApplicationName("Stoner Measurement Round Dial Demo")
    app.setOrganizationName("University of Leeds")
    app.setWindowIcon(make_app_icon())

    apply_theme(app, theme_setting())

    window = QMainWindow()
    window.setWindowTitle("Round Dial Demo")
    window.setCentralWidget(RoundDialDemoWidget(window))
    window.resize(420, 520)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
