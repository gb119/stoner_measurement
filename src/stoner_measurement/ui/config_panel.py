"""Configuration panel — right 25 % of the main window.

A :class:`QTabWidget` whose tabs are populated by the loaded plugins.
Each plugin can contribute one or more configuration tabs.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from stoner_measurement.core.plugin_manager import PluginManager


class ConfigPanel(QWidget):
    """Right-hand tabbed configuration panel.

    Parameters
    ----------
    plugin_manager:
        The application :class:`~stoner_measurement.core.plugin_manager.PluginManager`
        instance — each plugin may contribute one or more tabs.
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
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("configTabs")
        layout.addWidget(self._tabs)
        self.setLayout(layout)

        self._build_tabs()
        plugin_manager.plugins_changed.connect(self._rebuild_tabs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_tabs(self) -> None:
        """Add one tab per loaded plugin (using the plugin's config widget)."""
        for name, plugin in self._plugin_manager.plugins.items():
            widget = plugin.config_widget(parent=self._tabs)
            self._tabs.addTab(widget, name)

    def _rebuild_tabs(self) -> None:
        """Clear and rebuild all tabs (called when the plugin list changes)."""
        self._tabs.clear()
        self._build_tabs()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def tabs(self) -> QTabWidget:
        """The underlying :class:`QTabWidget`."""
        return self._tabs
