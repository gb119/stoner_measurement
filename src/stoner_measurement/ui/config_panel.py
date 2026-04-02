"""Configuration panel — right 25 % of the main window.

A :class:`QTabWidget` whose tabs are populated by the loaded plugins.
Each plugin can contribute one or more configuration tabs via
:meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_tabs`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from stoner_measurement.core.plugin_manager import PluginManager

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin


class ConfigPanel(QWidget):
    """Right-hand tabbed configuration panel.

    Tabs are managed incrementally: when a plugin is registered its tabs are
    appended; when a plugin is unregistered its tabs are removed.  Tabs
    belonging to plugins that remain registered are preserved (along with any
    user-edited state they contain).

    Attributes:
        tabs (QTabWidget):
            The underlying tab widget.

    Args:
        plugin_manager (PluginManager):
            The application
            :class:`~stoner_measurement.core.plugin_manager.PluginManager`
            instance — each plugin may contribute one or more tabs via
            :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_tabs`.

    Keyword Parameters:
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.core.plugin_manager import PluginManager
        >>> pm = PluginManager()
        >>> panel = ConfigPanel(plugin_manager=pm)
        >>> panel.tabs.count()
        0
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plugin_manager = plugin_manager

        # Maps plugin name → list of tab indices currently in _tabs.
        # The indices are kept consistent by _remove_plugin_tabs.
        self._plugin_tab_titles: dict[str, list[str]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("configTabs")
        layout.addWidget(self._tabs)
        self.setLayout(layout)

        self._build_tabs()
        plugin_manager.plugins_changed.connect(self._sync_tabs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_tabs(self) -> None:
        """Add tabs for all currently loaded plugins."""
        for _name, plugin in self._plugin_manager.plugins.items():
            self.add_plugin_tabs(plugin)

    def _sync_tabs(self) -> None:
        """Incrementally sync tabs with the current plugin list."""
        current_plugins = set(self._plugin_manager.plugins.keys())
        registered_plugins = set(self._plugin_tab_titles.keys())

        for name in registered_plugins - current_plugins:
            self.remove_plugin_tabs(name)

        for name, plugin in self._plugin_manager.plugins.items():
            if name not in self._plugin_tab_titles:
                self.add_plugin_tabs(plugin)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def tabs(self) -> QTabWidget:
        """The underlying :class:`QTabWidget`."""
        return self._tabs

    def add_plugin_tabs(self, plugin: BasePlugin) -> None:
        """Add all tabs contributed by *plugin* to the configuration panel.

        If tabs for this plugin have already been added this call is a no-op
        so that calling code does not need to guard against duplicates.

        Args:
            plugin (BasePlugin):
                The plugin whose
                :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_tabs`
                will be called.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> pm = PluginManager()
            >>> panel = ConfigPanel(plugin_manager=pm)
            >>> plugin = DummyPlugin()
            >>> panel.add_plugin_tabs(plugin)
            >>> panel.tabs.count()
            1
        """
        if plugin.name in self._plugin_tab_titles:
            return
        tab_entries = plugin.config_tabs(parent=self._tabs)
        titles: list[str] = []
        for title, widget in tab_entries:
            self._tabs.addTab(widget, title)
            titles.append(title)
        self._plugin_tab_titles[plugin.name] = titles

    def remove_plugin_tabs(self, plugin_name: str) -> None:
        """Remove all tabs that were added by the plugin identified by *plugin_name*.

        If no tabs are registered for *plugin_name* this call is a no-op.

        Args:
            plugin_name (str):
                The :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name`
                of the plugin whose tabs should be removed.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> pm = PluginManager()
            >>> panel = ConfigPanel(plugin_manager=pm)
            >>> plugin = DummyPlugin()
            >>> panel.add_plugin_tabs(plugin)
            >>> panel.remove_plugin_tabs("Dummy")
            >>> panel.tabs.count()
            0
        """
        if plugin_name not in self._plugin_tab_titles:
            return
        titles_to_remove = set(self._plugin_tab_titles.pop(plugin_name))
        # Iterate in reverse so removing by index does not shift remaining tabs.
        for i in range(self._tabs.count() - 1, -1, -1):
            if self._tabs.tabText(i) in titles_to_remove:
                self._tabs.removeTab(i)
