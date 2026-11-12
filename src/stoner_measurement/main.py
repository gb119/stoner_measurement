"""Entry point for the stoner_measurement application."""

import argparse
import sys

from qtpy.QtWidgets import QApplication

from stoner_measurement.app import MeasurementApp
from stoner_measurement.app_config import font_size_setting, theme_setting
from stoner_measurement.telemetry import start_capture, stop_capture
from stoner_measurement.ui.icons import make_app_icon
from stoner_measurement.ui.theme import apply_application_font, apply_theme


def main(argv: list[str] | None = None) -> int:
    """Create and run the measurement application.

    Args:
        argv: Command-line arguments (defaults to sys.argv).

    Returns:
        Exit code (0 for success).
    """
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telemetry-log", metavar="PATH", help="append diagnostic telemetry to PATH")
    options, qt_args = parser.parse_known_args(argv[1:])
    if options.telemetry_log:
        start_capture(options.telemetry_log)
    try:
        return _run_application([argv[0], *qt_args])
    finally:
        stop_capture()


def _run_application(argv: list[str]) -> int:
    """Construct the Qt application and run its event loop."""
    app = QApplication(argv)
    app.setApplicationName("Stoner Measurement")
    app.setOrganizationName("University of Leeds")
    app.setWindowIcon(make_app_icon())
    apply_theme(app, theme_setting())
    apply_application_font(app, font_size_setting())

    window = MeasurementApp()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
