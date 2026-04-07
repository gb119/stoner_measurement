"""Main window widget — assembles the tabbed layout."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QSplitter, QTabWidget, QWidget

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.ui.config_panel import ConfigPanel
from stoner_measurement.ui.dock_panel import DockPanel
from stoner_measurement.ui.plot_widget import PlotWidget
from stoner_measurement.ui.script_tab import ScriptTab


class MainWindow(QWidget):
    """Central widget that provides the tabbed layout.

    Contains two tabs:

    * **Measurement** — the three-panel layout (DockPanel | PlotWidget | ConfigPanel).
    * **Script Editor** — a Python editor and interactive console.

    Layout of the *Measurement* tab (left → right):

    * **DockPanel** — 25 % of width, instrument / sequence control.
    * **PlotWidget** — 50 % of width, PyQtGraph plotting area.
    * **ConfigPanel** — 25 % of width, tabbed configuration.

    Args:
        plugin_manager (PluginManager):
            Shared plugin manager instance.

    Keyword Parameters:
        parent (QWidget | None):
            Optional parent widget.

    Attributes:
        dock_panel (DockPanel): Left panel of the Measurement tab.
        plot_widget (PlotWidget): Central plot in the Measurement tab.
        config_panel (ConfigPanel): Right configuration panel.
        script_tab (ScriptTab): The Script Editor tab widget.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._plugin_manager = plugin_manager

        # ---- Measurement tab: three-panel splitter ----------------------
        self._dock_panel = DockPanel(plugin_manager=plugin_manager, parent=self)
        self._plot_widget = PlotWidget(parent=self)
        self._config_panel = ConfigPanel(plugin_manager=plugin_manager, parent=self)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self._dock_panel)
        self._splitter.addWidget(self._plot_widget)
        self._splitter.addWidget(self._config_panel)

        # ---- Script Editor tab -----------------------------------------
        self._script_tab = ScriptTab(self)

        # ---- Tab container ---------------------------------------------
        self._tabs = QTabWidget(self)
        self._tabs.setTabPosition(QTabWidget.TabPosition.West)
        self._tabs.addTab(self._splitter, "Measurement")
        self._tabs.addTab(self._script_tab, "Script Editor")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)
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
    def tabs(self) -> QTabWidget:
        """The top-level tab widget containing all tabs.

        Returns:
            (QTabWidget):
                The tab widget.
        """
        return self._tabs

    @property
    def dock_panel(self) -> DockPanel:
        """Left dock panel (Measurement tab).

        Returns:
            (DockPanel):
                The dock panel widget.
        """
        return self._dock_panel

    @property
    def plot_widget(self) -> PlotWidget:
        """Central plot widget (Measurement tab).

        Returns:
            (PlotWidget):
                The plot widget.
        """
        return self._plot_widget

    @property
    def config_panel(self) -> ConfigPanel:
        """Right configuration panel (Measurement tab).

        Returns:
            (ConfigPanel):
                The configuration panel widget.
        """
        return self._config_panel

    @property
    def script_tab(self) -> ScriptTab:
        """The Script Editor tab widget.

        Returns:
            (ScriptTab):
                The script tab widget.
        """
        return self._script_tab
