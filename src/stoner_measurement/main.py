"""Entry point for the stoner_measurement application."""

import sys

from qtpy.QtWidgets import QApplication

from stoner_measurement.app import MeasurementApp
from stoner_measurement.ui.icons import make_app_icon
from stoner_measurement.ui.settings_dialog import KEY_THEME, make_app_settings
from stoner_measurement.ui.theme import DEFAULT_THEME, apply_theme


def main(argv: list[str] | None = None) -> int:
    """Create and run the measurement application.

    Args:
        argv: Command-line arguments (defaults to sys.argv).

    Returns:
        Exit code (0 for success).
    """
    if argv is None:
        argv = sys.argv

    app = QApplication(argv)
    app.setApplicationName("Stoner Measurement")
    app.setOrganizationName("University of Leeds")
    app.setWindowIcon(make_app_icon())
    saved_theme = make_app_settings().value(KEY_THEME, DEFAULT_THEME, type=str)
    apply_theme(app, saved_theme)

    window = MeasurementApp()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
