"""Dock panel — left 25 % of the main window.

Provides instrument listing, sequence building controls, a run button,
and a monitoring section where plugins can display live status widgets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.plugin_manager import PluginManager

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin

_EP_NAME_ROLE = Qt.ItemDataRole.UserRole


class DockPanel(QWidget):
    """Left panel containing instrument, sequence controls, and monitoring widgets.

    Plugins may contribute a live-status widget via
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.monitor_widget`.
    Those widgets are displayed in a dedicated *Monitoring* section at the
    bottom of this panel and are removed automatically when the plugin is
    unregistered.

    When the user clicks a step in the *Sequence Steps* list, the
    :attr:`plugin_selected` signal is emitted with the corresponding plugin
    instance so that the configuration panel can update itself accordingly.

    Attributes:
        sequence_steps (list[str]):
            The current sequence step names.

    Args:
        plugin_manager (PluginManager):
            The application
            :class:`~stoner_measurement.core.plugin_manager.PluginManager`
            instance — used to populate the available-instruments list and to
            manage monitoring widgets.

    Keyword Parameters:
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.core.plugin_manager import PluginManager
        >>> pm = PluginManager()
        >>> panel = DockPanel(plugin_manager=pm)
        >>> panel.sequence_steps
        []
    """

    #: Emitted with the plugin instance when a sequence step is selected, or
    #: ``None`` when the selection is cleared.
    plugin_selected = pyqtSignal(object)

    def __init__(
        self,
        plugin_manager: PluginManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plugin_manager = plugin_manager
        # Maps plugin name → monitor widget currently shown in the panel.
        self._monitor_widgets: dict[str, QWidget] = {}
        # Tracks plugin instances for which instance_name_changed is connected,
        # keyed by ep_name so they can be disconnected if the plugin is removed.
        self._connected_step_plugins: dict[str, BasePlugin] = {}

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

        # --- Monitoring section ---
        self._monitor_label = QLabel("<b>Monitoring</b>")
        self._monitor_label.setObjectName("monitoringLabel")
        self._monitor_label.setVisible(False)
        layout.addWidget(self._monitor_label)

        self._monitor_container = QWidget()
        self._monitor_container.setObjectName("monitorContainer")
        self._monitor_layout = QVBoxLayout(self._monitor_container)
        self._monitor_layout.setContentsMargins(0, 0, 0, 0)
        self._monitor_container.setVisible(False)
        layout.addWidget(self._monitor_container)

        self.setLayout(layout)

        # Connect signals
        self._add_step_btn.clicked.connect(self._add_step)
        self._remove_step_btn.clicked.connect(self._remove_step)
        self._sequence_list.currentItemChanged.connect(self._on_step_selected)

        # Populate instrument list and monitoring widgets
        self._refresh_instruments()
        self._refresh_monitors()
        plugin_manager.plugins_changed.connect(self._refresh_instruments)
        plugin_manager.plugins_changed.connect(self._refresh_monitors)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_instruments(self) -> None:
        """Reload the instrument list from the plugin manager."""
        self._instrument_list.clear()
        current_ep_names = set(self._plugin_manager.plugin_names)
        for ep_name in list(self._connected_step_plugins):
            if ep_name not in current_ep_names:
                plugin = self._connected_step_plugins.pop(ep_name)
                if hasattr(plugin, "instance_name_changed"):
                    try:
                        plugin.instance_name_changed.disconnect(self._on_plugin_renamed)
                    except (TypeError, RuntimeError):
                        pass
        for name in self._plugin_manager.plugin_names:
            self._instrument_list.addItem(name)

    def _refresh_monitors(self) -> None:
        """Sync monitoring widgets with the current plugin list."""
        current_plugins = set(self._plugin_manager.plugins.keys())
        registered_monitors = set(self._monitor_widgets.keys())

        for name in registered_monitors - current_plugins:
            self.remove_monitor_widget(name)

        for name, plugin in self._plugin_manager.plugins.items():
            if name not in self._monitor_widgets:
                widget = plugin.monitor_widget(parent=self._monitor_container)
                if widget is not None:
                    self.add_monitor_widget(name, widget)

    def _add_step(self) -> None:
        """Add the selected instrument as a sequence step."""
        current = self._instrument_list.currentItem()
        if current is None:
            return
        ep_name = current.text()
        plugin = self._plugin_manager.plugins.get(ep_name)
        if plugin is None:
            return
        item = QListWidgetItem(f"{plugin.instance_name} ({plugin.name})")
        item.setData(_EP_NAME_ROLE, ep_name)
        self._sequence_list.addItem(item)
        if ep_name not in self._connected_step_plugins and hasattr(plugin, "instance_name_changed"):
            plugin.instance_name_changed.connect(self._on_plugin_renamed)
            self._connected_step_plugins[ep_name] = plugin

    def _remove_step(self) -> None:
        """Remove the currently selected sequence step."""
        row = self._sequence_list.currentRow()
        if row >= 0:
            self._sequence_list.takeItem(row)

    def _on_step_selected(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        """Emit :attr:`plugin_selected` when the sequence-step selection changes."""
        if current is None:
            self.plugin_selected.emit(None)
            return
        ep_name = current.data(_EP_NAME_ROLE)
        plugin = self._plugin_manager.plugins.get(ep_name)
        self.plugin_selected.emit(plugin)

    def _on_plugin_renamed(self, old_name: str, new_name: str) -> None:
        """Update sequence step labels when a plugin's instance name changes.

        This slot is connected to the ``instance_name_changed(old, new)``
        signal.  The *old_name* argument is received as part of that signal
        but is not needed here — step items are identified by the ep_name
        stored in their ``UserRole`` data, and any item whose plugin now has
        ``instance_name == new_name`` is relabelled.

        Args:
            old_name (str):
                Previous instance name (received from the signal but not used
                for lookup).
            new_name (str):
                New instance name to display.
        """
        for i in range(self._sequence_list.count()):
            item = self._sequence_list.item(i)
            ep_name = item.data(_EP_NAME_ROLE)
            plugin = self._plugin_manager.plugins.get(ep_name)
            if plugin is not None and plugin.instance_name == new_name:
                item.setText(f"{new_name} ({plugin.name})")

    def _update_monitor_visibility(self) -> None:
        """Show or hide the monitoring section depending on whether any widgets are present."""
        has_monitors = bool(self._monitor_widgets)
        self._monitor_label.setVisible(has_monitors)
        self._monitor_container.setVisible(has_monitors)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def sequence_steps(self) -> list[str]:
        """Return the entry-point names of the current sequence steps.

        The returned names are the plugin registry keys (entry-point names)
        stored when each step was added, not the formatted display labels.
        """
        return [
            self._sequence_list.item(i).data(_EP_NAME_ROLE)
            for i in range(self._sequence_list.count())
        ]

    def add_monitor_widget(self, plugin_name: str, widget: QWidget) -> None:
        """Add a monitoring widget for the named plugin.

        If a monitoring widget for *plugin_name* is already present this call
        is a no-op.

        Args:
            plugin_name (str):
                Unique identifier for the owning plugin.
            widget (QWidget):
                The widget to display in the monitoring section.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication, QLabel
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> pm = PluginManager()
            >>> panel = DockPanel(plugin_manager=pm)
            >>> panel.add_monitor_widget("test", QLabel("Status: OK"))
            >>> "test" in panel.monitor_widgets
            True
        """
        if plugin_name in self._monitor_widgets:
            return
        widget.setParent(self._monitor_container)
        self._monitor_layout.addWidget(widget)
        self._monitor_widgets[plugin_name] = widget
        self._update_monitor_visibility()

    def remove_monitor_widget(self, plugin_name: str) -> None:
        """Remove the monitoring widget registered for *plugin_name*.

        If no widget is registered for *plugin_name* this call is a no-op.

        Args:
            plugin_name (str):
                Unique identifier for the owning plugin.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication, QLabel
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> pm = PluginManager()
            >>> panel = DockPanel(plugin_manager=pm)
            >>> panel.add_monitor_widget("test", QLabel("Status: OK"))
            >>> panel.remove_monitor_widget("test")
            >>> "test" in panel.monitor_widgets
            False
        """
        widget = self._monitor_widgets.pop(plugin_name, None)
        if widget is not None:
            self._monitor_layout.removeWidget(widget)
            widget.setParent(None)  # type: ignore[arg-type]
            widget.deleteLater()
        self._update_monitor_visibility()

    @property
    def monitor_widgets(self) -> dict[str, QWidget]:
        """Mapping of plugin name → currently displayed monitoring widget."""
        return dict(self._monitor_widgets)
