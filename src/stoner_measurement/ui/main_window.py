"""Main window widget — assembles the three-panel layout."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QSplitter, QWidget

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.core.runner import SequenceRunner
from stoner_measurement.ui.config_panel import ConfigPanel
from stoner_measurement.ui.dock_panel import DockPanel
from stoner_measurement.ui.plot_widget import PlotWidget


class MainWindow(QWidget):
    """Central widget that provides the three-panel layout.

    Layout (left → right):
    * **DockPanel** — 25 % of width, instrument / sequence control.
    * **PlotWidget** — 50 % of width, PyQtGraph plotting area.
    * **ConfigPanel** — 25 % of width, tabbed configuration.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        runner: SequenceRunner,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._plugin_manager = plugin_manager
        self._runner = runner

        # Build sub-widgets
        self._dock_panel = DockPanel(plugin_manager=plugin_manager, parent=self)
        self._plot_widget = PlotWidget(runner=runner, parent=self)
        self._config_panel = ConfigPanel(plugin_manager=plugin_manager, parent=self)

        # Three-way splitter (left | centre | right)
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.addWidget(self._dock_panel)
        self._splitter.addWidget(self._plot_widget)
        self._splitter.addWidget(self._config_panel)

        # Wire runner → plot (trace_name, x, y)
        self._runner.data_ready.connect(self._plot_widget.append_point)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._splitter)
        self.setLayout(layout)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Maintain 25 / 50 / 25 proportions when the window is resized."""
        super().resizeEvent(event)
        total = self._splitter.width()
        if total > 0:
            quarter = total // 4
            self._splitter.setSizes([quarter, total - 2 * quarter, quarter])

    # ------------------------------------------------------------------
    # Public accessors (useful for tests)
    # ------------------------------------------------------------------

    @property
    def dock_panel(self) -> DockPanel:
        """Left dock panel."""
        return self._dock_panel

    @property
    def plot_widget(self) -> PlotWidget:
        """Central plot widget."""
        return self._plot_widget

    @property
    def config_panel(self) -> ConfigPanel:
        """Right configuration panel."""
        return self._config_panel
