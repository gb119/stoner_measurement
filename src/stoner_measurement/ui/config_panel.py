"""Configuration panel — right 25 % of the main window.

A :class:`QTabWidget` that displays the configuration tabs of whichever plugin
is currently selected in the sequence editor.  Tabs are shown by calling
:meth:`ConfigPanel.show_plugin` and cleared when no step is selected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QTabWidget, QVBoxLayout, QWidget

from stoner_measurement.core.plugin_manager import PluginManager

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin


class ConfigPanel(QWidget):
    """Right-hand tabbed configuration panel.

    Displays the configuration tabs of the plugin that is currently selected
    in the sequence editor.  Call :meth:`show_plugin` to load a plugin's tabs
    or pass ``None`` to return to the idle placeholder.

    When the plugin manager notifies that a plugin has been removed,
    :meth:`show_plugin` is called with ``None`` automatically if the removed
    plugin was the one currently being displayed.

    Attributes:
        tabs (QTabWidget):
            The underlying tab widget.

    Args:
        plugin_manager (PluginManager):
            The application
            :class:`~stoner_measurement.core.plugin_manager.PluginManager`
            instance — used to detect when the currently displayed plugin is
            unregistered.

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
        self._shown_plugin: BasePlugin | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("configTabs")
        layout.addWidget(self._tabs)
        self.setLayout(layout)

        plugin_manager.plugins_changed.connect(self._sync_tabs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync_tabs(self) -> None:
        """Clear the panel if the currently shown plugin has been unregistered."""
        if self._shown_plugin is not None:
            if self._shown_plugin not in self._plugin_manager.plugins.values():
                self.show_plugin(None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def tabs(self) -> QTabWidget:
        """The underlying :class:`QTabWidget`."""
        return self._tabs

    def show_plugin(self, plugin: BasePlugin | None) -> None:
        """Display the configuration tabs for *plugin*, replacing any currently shown tabs.

        Tab widgets are sourced from
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_tabs`.
        Because :class:`~stoner_measurement.plugins.trace.TracePlugin` caches
        its tab widgets, user-edited state is preserved when a plugin is
        deselected and re-selected in the sequence editor.

        Passing ``None`` removes all tabs and shows an empty panel.

        Args:
            plugin (BasePlugin | None):
                The plugin whose tabs should be displayed, or ``None`` to
                clear the panel.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> pm = PluginManager()
            >>> panel = ConfigPanel(plugin_manager=pm)
            >>> plugin = DummyPlugin()
            >>> panel.show_plugin(plugin)
            >>> panel.tabs.count()
            3
            >>> panel.show_plugin(None)
            >>> panel.tabs.count()
            0
        """
        # Remove all tabs without deleting widgets (they may be cached on the plugin).
        while self._tabs.count() > 0:
            self._tabs.removeTab(0)

        if plugin is None:
            self._shown_plugin = None
            return

        for title, widget in plugin.config_tabs():
            self._tabs.addTab(widget, title)
        self._shown_plugin = plugin

    def show_placeholder(self) -> None:
        """Display a centred 'no step selected' message in the panel.

        Convenience wrapper around ``show_plugin(None)`` that also adds a
        single informational tab so the panel does not appear completely empty.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> pm = PluginManager()
            >>> panel = ConfigPanel(plugin_manager=pm)
            >>> panel.show_placeholder()
            >>> panel.tabs.count()
            1
        """
        while self._tabs.count() > 0:
            self._tabs.removeTab(0)
        self._shown_plugin = None
        placeholder = QLabel("Select a sequence step to configure.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tabs.addTab(placeholder, "Configuration")

    def commit_pending_changes(self) -> None:
        """Commit any pending edits in the currently displayed configuration tabs.

        Some input widgets (e.g. :class:`~PyQt6.QtWidgets.QLineEdit`) only
        apply their value to the plugin when the widget loses focus or the user
        presses Return.  Toolbar and menu actions that do not take keyboard
        focus (the default Qt behaviour for toolbar buttons) would otherwise
        bypass this mechanism, so unsaved text would not reach the plugin before
        the action executes.

        This method inspects the application-wide focus widget.  If it is a
        descendant of this panel's tab widget it is explicitly cleared of focus,
        which causes Qt to emit the ``editingFinished`` signal on any focused
        :class:`~PyQt6.QtWidgets.QLineEdit` and flush the edit to the plugin
        before the action proceeds.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> pm = PluginManager()
            >>> panel = ConfigPanel(plugin_manager=pm)
            >>> panel.commit_pending_changes()  # no-op when nothing is focused
        """
        focused = QApplication.focusWidget()
        if focused is not None and self._tabs.isAncestorOf(focused):
            focused.clearFocus()
