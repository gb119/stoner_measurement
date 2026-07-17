"""Entry point for the stoner_measurement application."""

import sys

from qtpy.QtWidgets import QApplication

from stoner_measurement.app import MeasurementApp
from stoner_measurement.app_config import theme_setting
from stoner_measurement.ui.icons import make_app_icon
from stoner_measurement.ui.theme import apply_theme


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
    apply_theme(app, theme_setting())

    window = MeasurementApp()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
