"""Main window widget — assembles the tabbed layout."""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QHBoxLayout,
    QSplitter,
    QTabBar,
    QTabWidget,
    QWidget,
)

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.ui.config_panel import ConfigPanel
from stoner_measurement.ui.dock_panel import DockPanel
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.plotting.host import PlotDisplayHost
from stoner_measurement.ui.script_tab import ScriptTab


class MainWindow(QWidget):
    """Central widget that provides the tabbed layout.

    Contains two tabs:

    * **Measurement** — the three-panel layout (DockPanel | PlotDisplayHost | ConfigPanel).
    * **Script Editor** — a Python editor and interactive console.

    Layout of the *Measurement* tab (left → right):

    * **DockPanel** — 25 % of width, instrument / sequence control.
    * **PlotDisplayHost** — 50 % of width, selected measurement display.
    * **ConfigPanel** — 25 % of width, tabbed configuration.

    Args:
        plugin_manager (PluginManager):
            Shared plugin manager instance.

    Keyword Parameters:
        parent (QWidget | None):
            Optional parent widget.
        display_registry (PlotDisplayRegistry | None):
            Startup display factories; discover installed factories when omitted.
        display_factory_id (str):
            Startup factory ID, with Cartesian fallback on selection failure.
        display_settings (QSettings | None):
            Optional versioned display preferences, excluding measurement arrays.

    Attributes:
        dock_panel (DockPanel): Left panel of the Measurement tab.
        plot_display_host (PlotDisplayHost): Stable main display host and service.
        plot_widget (QWidget): Concrete display for GUI inspection and legacy access.
        config_panel (ConfigPanel): Right configuration panel.
        script_tab (ScriptTab): The Script Editor tab widget.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        parent: QWidget | None = None,
        *,
        display_registry=None,
        display_factory_id: str | None = None,
        display_settings=None,
    ) -> None:
        super().__init__(parent)

        self._plugin_manager = plugin_manager

        # ---- Measurement tab: three-panel splitter ----------------------
        self._dock_panel = DockPanel(plugin_manager=plugin_manager, parent=self)
        self._plot_display_host = PlotDisplayHost(
            self,
            registry=display_registry,
            factory_id=display_factory_id,
            settings=display_settings,
        )
        self._config_panel = ConfigPanel(plugin_manager=plugin_manager, parent=self)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self._dock_panel)
        self._splitter.addWidget(self._plot_display_host)
        self._splitter.addWidget(self._config_panel)
        self._splitter.setCollapsible(2, False)
        self._config_panel.collapsed_changed.connect(self._config_panel_collapsed)
        self._splitter_initialized = False
        self._expanded_config_width = 0

        # ---- Script Editor tab -----------------------------------------
        self._script_tab = ScriptTab(self)

        # ---- Tab container ---------------------------------------------
        self._tabs = FontAwareTabWidget(self)
        self._tabs.setTabPosition(QTabWidget.TabPosition.West)
        self._tabs.addTab(self._splitter, "Measurement")
        self._tabs.addTab(self._script_tab, "Script Editor")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)
        self.setLayout(layout)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Apply the initial 25 / 50 / 25 measurement-panel proportions."""
        super().resizeEvent(event)
        if self._splitter_initialized:
            return
        total = self._splitter.width()
        if total > 0:
            quarter = total // 4
            self._splitter.setSizes([quarter, total - 2 * quarter, quarter])
            self._expanded_config_width = quarter
            self._splitter_initialized = True

    def _config_panel_collapsed(self, collapsed: bool) -> None:
        """Give the plot the released width and restore it on expansion."""
        sizes = self._splitter.sizes()
        if len(sizes) != 3:
            return

        if collapsed:
            self._expanded_config_width = sizes[2]
            compact_width = self._config_panel.sizeHint().width()
            released_width = max(0, sizes[2] - compact_width)
            self._splitter.setSizes([sizes[0], sizes[1] + released_width, compact_width])
            return

        target_width = max(
            self._expanded_config_width,
            self._config_panel.minimumSizeHint().width(),
        )
        gained_width = max(0, target_width - sizes[2])
        minimum_plot_width = self._plot_display_host.minimumSizeHint().width()
        plot_width = max(minimum_plot_width, sizes[1] - gained_width)
        self._splitter.setSizes([sizes[0], plot_width, target_width])

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Close lifecycle-sensitive children before destroying the window."""
        self._script_tab.close()
        self._plot_display_host.close()
        super().closeEvent(event)

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
    def sequence_tabs(self) -> QTabBar:
        """Tab bar representing the open measurement-sequence documents."""
        return self._dock_panel.sequence_tabs

    @property
    def plot_widget(self) -> QWidget:
        """Concrete display widget; Cartesian compatibility and GUI inspection.

        Returns:
            (QWidget):
                The selected display's widget (PlotWidget for Cartesian).
        """
        return self._plot_display_host.display_widget

    @property
    def plot_display_host(self) -> PlotDisplayHost:
        """Stable host and producer service for the main measurement display."""
        return self._plot_display_host

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
