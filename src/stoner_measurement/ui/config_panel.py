"""Configuration panel — right 25 % of the main window.

A :class:`QTabWidget` that displays the configuration tabs of whichever plugin
is currently selected in the sequence editor.  Tabs are shown by calling
:meth:`ConfigPanel.show_plugin` and cleared when no step is selected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QApplication,
    QLabel,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.ui.font_aware_tabs import FontAwareTabBar, FontAwareTabWidget

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
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.core.plugin_manager import PluginManager
        >>> pm = PluginManager()
        >>> panel = ConfigPanel(plugin_manager=pm)
        >>> panel.tabs.count()
        0
    """

    collapsed_changed = Signal(bool)

    def __init__(
        self,
        plugin_manager: PluginManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plugin_manager = plugin_manager
        self._shown_plugin: BasePlugin | None = None
        self._collapsed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = FontAwareTabWidget()
        self._tabs.setObjectName("configTabs")

        self._collapse_button = QToolButton(self._tabs)
        self._collapse_button.setObjectName("collapseConfigPanelButton")
        self._collapse_button.setText("»")
        chevron_font = self._collapse_button.font()
        chevron_font.setPointSizeF(chevron_font.pointSizeF() * 1.5)
        chevron_font.setBold(True)
        self._collapse_button.setFont(chevron_font)
        self._collapse_button.setToolTip("Collapse configuration panel")
        self._collapse_button.setAccessibleName("Collapse configuration panel")
        self._collapse_button.setAutoRaise(True)
        self._collapse_button.clicked.connect(lambda: self.set_collapsed(True))
        self._tabs.setCornerWidget(self._collapse_button, Qt.Corner.TopRightCorner)

        self._collapsed_view = QWidget(self)
        self._collapsed_view.setObjectName("collapsedConfigPanel")
        collapsed_layout = QVBoxLayout(self._collapsed_view)
        collapsed_layout.setContentsMargins(0, 0, 0, 0)
        collapsed_layout.setSpacing(0)

        self._expand_button = QToolButton(self._collapsed_view)
        self._expand_button.setObjectName("expandConfigPanelButton")
        self._expand_button.setText("«")
        self._expand_button.setFont(chevron_font)
        self._expand_button.setToolTip("Expand configuration panel")
        self._expand_button.setAccessibleName("Expand configuration panel")
        self._expand_button.setAutoRaise(True)
        self._expand_button.clicked.connect(lambda: self.set_collapsed(False))
        collapsed_layout.addWidget(self._expand_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self._collapsed_tabs = FontAwareTabBar(self._collapsed_view)
        self._collapsed_tabs.setObjectName("collapsedConfigTabs")
        self._collapsed_tabs.setShape(QTabBar.Shape.RoundedEast)
        self._collapsed_tabs.setExpanding(False)
        self._collapsed_tabs.setAccessibleName("Configuration tabs")
        self._collapsed_tabs.tabBarClicked.connect(self._expand_to_tab)
        collapsed_layout.addWidget(self._collapsed_tabs, 0, Qt.AlignmentFlag.AlignTop)
        collapsed_layout.addStretch(1)

        layout.addWidget(self._tabs)
        layout.addWidget(self._collapsed_view)
        self.setLayout(layout)
        self._collapsed_view.hide()

        plugin_manager.plugins_changed.connect(self._sync_tabs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync_tabs(self) -> None:
        """Clear the panel if the currently shown plugin has been unregistered."""
        if self._shown_plugin is not None:
            if self._shown_plugin not in self._plugin_manager.plugins.values():
                self.show_plugin(None)

    def _detach_all_tabs(self) -> None:
        """Remove and detach every page without deleting cached plugin widgets.

        ``QTabWidget.removeTab`` removes a page from the tab bar and stacked
        layout, but leaves it parented to the internal ``QStackedWidget``.
        Keeping old pages in that stack can leave stale native paint artefacts
        when configuration pages are replaced and later reused.
        """
        while self._tabs.count() > 0:
            widget = self._tabs.widget(0)
            self._tabs.removeTab(0)
            widget.hide()
            widget.setParent(None)
        while self._collapsed_tabs.count() > 0:
            self._collapsed_tabs.removeTab(0)

    def _sync_collapsed_tabs(self) -> None:
        """Mirror visible configuration labels into the collapsed tab strip."""
        while self._collapsed_tabs.count() > 0:
            self._collapsed_tabs.removeTab(0)
        for index in range(self._tabs.count()):
            collapsed_index = self._collapsed_tabs.addTab(
                self._tabs.tabIcon(index), self._tabs.tabText(index)
            )
            self._collapsed_tabs.setTabEnabled(collapsed_index, self._tabs.isTabEnabled(index))
            self._collapsed_tabs.setTabToolTip(collapsed_index, self._tabs.tabToolTip(index))

    def _expand_to_tab(self, index: int) -> None:
        """Expand the panel and focus the tab chosen in the collapsed strip."""
        if index < 0:
            return
        self._tabs.setCurrentIndex(index)
        self.set_collapsed(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def tabs(self) -> QTabWidget:
        """The underlying :class:`QTabWidget`."""
        return self._tabs

    @property
    def collapsed_tabs(self) -> QTabBar:
        """The vertical tab strip displayed while the panel is collapsed."""
        return self._collapsed_tabs

    @property
    def collapse_button(self) -> QToolButton:
        """Button that collapses the configuration panel."""
        return self._collapse_button

    @property
    def expand_button(self) -> QToolButton:
        """Button that restores the configuration panel."""
        return self._expand_button

    @property
    def is_collapsed(self) -> bool:
        """Whether only the vertical configuration tab strip is visible."""
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        """Switch between the full configuration pages and compact tab strip."""
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._tabs.setVisible(not collapsed)
        self._collapsed_view.setVisible(collapsed)
        self.updateGeometry()
        self.collapsed_changed.emit(collapsed)

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
            >>> from qtpy.QtWidgets import QApplication
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
        # Detach without deleting widgets (they may be cached on the plugin).
        self._detach_all_tabs()

        if plugin is None:
            self._shown_plugin = None
            return

        for title, widget in plugin.config_tabs():
            self._tabs.addTab(widget, title)
        self._sync_collapsed_tabs()
        self._shown_plugin = plugin

    def show_placeholder(self) -> None:
        """Display a centred 'no step selected' message in the panel.

        Convenience wrapper around ``show_plugin(None)`` that also adds a
        single informational tab so the panel does not appear completely empty.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> pm = PluginManager()
            >>> panel = ConfigPanel(plugin_manager=pm)
            >>> panel.show_placeholder()
            >>> panel.tabs.count()
            1
        """
        self._detach_all_tabs()
        self._shown_plugin = None
        placeholder = QLabel("Select a sequence step to configure.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tabs.addTab(placeholder, "Configuration")
        self._sync_collapsed_tabs()

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
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> pm = PluginManager()
            >>> panel = ConfigPanel(plugin_manager=pm)
            >>> panel.commit_pending_changes()  # no-op when nothing is focused
        """
        focused = QApplication.focusWidget()
        if focused is not None and self._tabs.isAncestorOf(focused):
            focused.clearFocus()
