"""Dock panel — left 25 % of the main window.

Provides instrument listing, sequence building controls and a run button.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDockWidget,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.plugin_manager import PluginManager


class DockPanel(QWidget):
    """Left panel containing instrument and sequence controls.

    Parameters
    ----------
    plugin_manager:
        The application :class:`~stoner_measurement.core.plugin_manager.PluginManager`
        instance — used to populate the available-instruments list.
    parent:
        Optional Qt parent widget.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plugin_manager = plugin_manager

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- Available instruments / plugins ---
        layout.addWidget(QLabel("<b>Available Instruments</b>"))
        self._instrument_list = QListWidget()
        self._instrument_list.setObjectName("instrumentList")
        layout.addWidget(self._instrument_list)

        # --- Sequence steps ---
        layout.addWidget(QLabel("<b>Sequence Steps</b>"))
        self._sequence_list = QListWidget()
        self._sequence_list.setObjectName("sequenceList")
        layout.addWidget(self._sequence_list)

        # --- Control buttons ---
        self._add_step_btn = QPushButton("Add Step")
        self._add_step_btn.setObjectName("addStepButton")
        self._remove_step_btn = QPushButton("Remove Step")
        self._remove_step_btn.setObjectName("removeStepButton")
        layout.addWidget(self._add_step_btn)
        layout.addWidget(self._remove_step_btn)

        self.setLayout(layout)

        # Connect signals
        self._add_step_btn.clicked.connect(self._add_step)
        self._remove_step_btn.clicked.connect(self._remove_step)

        # Populate instrument list
        self._refresh_instruments()
        plugin_manager.plugins_changed.connect(self._refresh_instruments)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_instruments(self) -> None:
        """Reload the instrument list from the plugin manager."""
        self._instrument_list.clear()
        for name in self._plugin_manager.plugin_names:
            self._instrument_list.addItem(name)

    def _add_step(self) -> None:
        """Add the selected instrument as a sequence step."""
        current = self._instrument_list.currentItem()
        if current is not None:
            self._sequence_list.addItem(current.text())

    def _remove_step(self) -> None:
        """Remove the currently selected sequence step."""
        row = self._sequence_list.currentRow()
        if row >= 0:
            self._sequence_list.takeItem(row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def sequence_steps(self) -> list[str]:
        """Return the current sequence step names as a list of strings."""
        return [
            self._sequence_list.item(i).text()
            for i in range(self._sequence_list.count())
        ]
