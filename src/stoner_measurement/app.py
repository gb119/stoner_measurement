"""Main application window for the Stoner Measurement application."""

from __future__ import annotations

from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtWidgets import QMainWindow, QStatusBar

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.core.runner import SequenceRunner
from stoner_measurement.ui.main_window import MainWindow


class MeasurementApp(QMainWindow):
    """Top-level application window.

    Composes the :class:`MainWindow` central widget and wires together the
    :class:`~stoner_measurement.core.plugin_manager.PluginManager` and
    :class:`~stoner_measurement.core.runner.SequenceRunner`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Stoner Measurement")
        self.setMinimumSize(QSize(1200, 700))

        # Core objects
        self._plugin_manager = PluginManager()
        self._plugin_manager.discover()

        self._runner = SequenceRunner()

        # Central widget
        self._main_window = MainWindow(
            plugin_manager=self._plugin_manager,
            runner=self._runner,
        )
        self.setCentralWidget(self._main_window)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")

        self._runner.status_changed.connect(self._status_bar.showMessage)

        self._restore_settings()

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _restore_settings(self) -> None:
        """Restore window geometry from QSettings."""
        settings = QSettings()
        geometry = settings.value("mainWindow/geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Save window geometry on close."""
        settings = QSettings()
        settings.setValue("mainWindow/geometry", self.saveGeometry())
        self._runner.stop()
        super().closeEvent(event)
