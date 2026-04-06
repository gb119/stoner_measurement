"""Dock panel — left 25 % of the main window.

Provides instrument listing, sequence building controls, a run button,
and a monitoring section where plugins can display live status widgets.
The sequence list is a tree widget that supports drag-and-drop reordering
and arbitrarily deep sub-sequence nesting for
:class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin` items
(including :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`),
enabling multi-dimensional measurement scans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListWidget,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.plugin_manager import PluginManager

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin

_EP_NAME_ROLE = Qt.ItemDataRole.UserRole

# Recursive type alias describing one element of the sequence_steps list.
# A leaf step is just the entry-point name string; a state-control step with
# sub-steps is a (ep_name, [sub-steps…]) tuple of arbitrary depth.
type _SequenceStep = str | tuple[str, list[_SequenceStep]]


class _SequenceTreeWidget(QTreeWidget):
    """Tree widget for sequence steps with drag-and-drop support.

    Supports:

    * **Reordering** — drag a step above or below another to reorder.
    * **Sub-sequencing** — drag any step *onto* a
      :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`
      item to nest it as a sub-step.  This includes dragging one
      :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`
      onto another, enabling arbitrarily deep nesting for multi-dimensional
      measurement scans.  Nested items are shown with indentation.
    * **Promotion** — drag a sub-step above or below any top-level item to
      move it back up the hierarchy.

    :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`
    items are displayed in bold to indicate that they may accept nested
    steps.  A tooltip explains the drag-onto behaviour.

    Args:
        plugin_manager (PluginManager):
            Used to look up plugin types when determining whether an item
            accepts child drops.

    Keyword Parameters:
        parent (QWidget | None):
            Optional Qt parent widget.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plugin_manager = plugin_manager
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(20)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_sequence_plugin(self, ep_name: str) -> bool:
        """Return ``True`` if *ep_name* identifies a SequencePlugin."""
        from stoner_measurement.plugins.sequence_plugin import SequencePlugin

        plugin = self._plugin_manager.plugins.get(ep_name)
        return isinstance(plugin, SequencePlugin)

    @staticmethod
    def _is_ancestor(candidate: QTreeWidgetItem, item: QTreeWidgetItem) -> bool:
        """Return ``True`` if *candidate* is *item* or an ancestor of *item*.

        Used to prevent a drag that would create a cycle (e.g. dropping a
        parent onto one of its own descendants).

        Args:
            candidate (QTreeWidgetItem):
                The item being tested as a potential ancestor.
            item (QTreeWidgetItem):
                The item whose ancestry chain is walked.

        Returns:
            (bool):
                ``True`` when *candidate* is the same object as *item* or
                appears somewhere above *item* in the tree hierarchy.
        """
        current: QTreeWidgetItem | None = item
        while current is not None:
            if current is candidate:
                return True
            current = current.parent()
        return False

    def make_item(self, ep_name: str, text: str) -> QTreeWidgetItem:
        """Create a styled :class:`QTreeWidgetItem` for *ep_name*.

        :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`
        items are displayed in bold and carry a tooltip that explains the
        drag-onto behaviour.

        Args:
            ep_name (str):
                Entry-point registry key for the plugin.
            text (str):
                Display label for the item.

        Returns:
            (QTreeWidgetItem):
                A new item ready to be inserted into the tree.
        """
        item = QTreeWidgetItem([text])
        item.setData(0, _EP_NAME_ROLE, ep_name)
        flags = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
        )
        if self._is_sequence_plugin(ep_name):
            flags |= Qt.ItemFlag.ItemIsDropEnabled
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            item.setToolTip(
                0,
                "Drag other steps onto this item to nest them as sub-steps.",
            )
        item.setFlags(flags)
        return item

    # ------------------------------------------------------------------
    # Drag-and-drop overrides
    # ------------------------------------------------------------------

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Reject drops *onto* non-SequencePlugin items or onto descendants."""
        pos_point = event.position().toPoint()
        target = self.itemAt(pos_point)
        pos = self.dropIndicatorPosition()

        if target is not None and pos == QAbstractItemView.DropIndicatorPosition.OnItem:
            # Only SequencePlugin items may accept children.
            ep_name = target.data(0, _EP_NAME_ROLE)
            if not self._is_sequence_plugin(ep_name):
                event.ignore()
                return
            # Prevent dropping an item onto itself or one of its own descendants.
            dragged = self.currentItem()
            if dragged is not None and self._is_ancestor(dragged, target):
                event.ignore()
                return

        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle reorder and nest-as-sub-step drops."""
        pos_point = event.position().toPoint()
        target = self.itemAt(pos_point)
        pos = self.dropIndicatorPosition()
        dragged = self.currentItem()

        if dragged is None:
            event.ignore()
            return

        # Only SequencePlugin items may accept children; also prevent
        # dropping an item onto itself or one of its own descendants.
        if target is not None and pos == QAbstractItemView.DropIndicatorPosition.OnItem:
            ep_name = target.data(0, _EP_NAME_ROLE)
            if not self._is_sequence_plugin(ep_name):
                event.ignore()
                return
            if self._is_ancestor(dragged, target):
                event.ignore()
                return

        # Remember target position before modifying the tree
        target_parent: QTreeWidgetItem | None = None
        target_index = 0
        if target is not None:
            target_parent = target.parent()
            if target_parent is not None:
                target_index = target_parent.indexOfChild(target)
            else:
                target_index = self.indexOfTopLevelItem(target)

        # Detach dragged item from its current location
        dragged_parent = dragged.parent()
        if dragged_parent is not None:
            dragged_idx = dragged_parent.indexOfChild(dragged)
            dragged_parent.takeChild(dragged_idx)
        else:
            dragged_idx = self.indexOfTopLevelItem(dragged)
            self.takeTopLevelItem(dragged_idx)

        # Adjust target_index when dragged and target shared the same parent
        # and dragged was before the target (its removal shifts the target down).
        if (
            target is not None
            and pos != QAbstractItemView.DropIndicatorPosition.OnItem
            and dragged_parent is target_parent
            and dragged_idx < target_index
        ):
            target_index -= 1

        # Insert at the new location
        if target is None:
            self.addTopLevelItem(dragged)
        elif pos == QAbstractItemView.DropIndicatorPosition.OnItem:
            target.addChild(dragged)
            target.setExpanded(True)
        elif pos == QAbstractItemView.DropIndicatorPosition.AboveItem:
            if target_parent is not None:
                target_parent.insertChild(target_index, dragged)
            else:
                self.insertTopLevelItem(target_index, dragged)
        else:  # BelowItem or OnViewport
            if target_parent is not None:
                target_parent.insertChild(target_index + 1, dragged)
            else:
                self.insertTopLevelItem(target_index + 1, dragged)

        self.setCurrentItem(dragged)
        event.accept()


class DockPanel(QWidget):
    """Left panel containing instrument, sequence controls, and monitoring widgets.

    Plugins may contribute a live-status widget via
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.monitor_widget`.
    Those widgets are displayed in a dedicated *Monitoring* section at the
    bottom of this panel and are removed automatically when the plugin is
    unregistered.

    When the user clicks a step in the *Sequence Steps* tree, the
    :attr:`plugin_selected` signal is emitted with the corresponding plugin
    instance so that the configuration panel can update itself accordingly.

    The sequence tree supports **drag-and-drop**:

    * Drag a step above or below another to reorder.
    * Drag any step *onto* a
      :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`
      item (e.g. a
      :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`)
      to nest it as a sub-step (shown with indentation).  This includes
      dragging one sequence-plugin step onto another, enabling multi-dimensional
      measurement scans at arbitrary depth.
    * Drag a sub-step to the top level to promote it.

    Attributes:
        sequence_steps (list[_SequenceStep]):
            The current sequence steps as a recursive structure.  Each element
            is either a plain entry-point name string (for a leaf step with no
            sub-steps) or a ``(ep_name, [sub-steps…])`` tuple for a
            :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`
            that has nested children.  The inner list follows the same
            ``_SequenceStep`` structure, so nesting may be arbitrarily deep.

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
        self._sequence_tree = _SequenceTreeWidget(plugin_manager=plugin_manager)
        self._sequence_tree.setObjectName("sequenceTree")
        layout.addWidget(self._sequence_tree)

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
        self._sequence_tree.currentItemChanged.connect(self._on_step_selected)

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
        """Add the selected instrument as a top-level sequence step."""
        current = self._instrument_list.currentItem()
        if current is None:
            return
        ep_name = current.text()
        plugin = self._plugin_manager.plugins.get(ep_name)
        if plugin is None:
            return
        item = self._sequence_tree.make_item(ep_name, f"{plugin.instance_name} ({plugin.name})")
        self._sequence_tree.addTopLevelItem(item)
        if ep_name not in self._connected_step_plugins and hasattr(plugin, "instance_name_changed"):
            plugin.instance_name_changed.connect(self._on_plugin_renamed)
            self._connected_step_plugins[ep_name] = plugin

    def _remove_step(self) -> None:
        """Remove the currently selected sequence step (or sub-step)."""
        item = self._sequence_tree.currentItem()
        if item is None:
            return
        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)
        else:
            idx = self._sequence_tree.indexOfTopLevelItem(item)
            if idx >= 0:
                self._sequence_tree.takeTopLevelItem(idx)

    def _on_step_selected(
        self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None
    ) -> None:
        """Emit :attr:`plugin_selected` when the sequence-step selection changes."""
        if current is None:
            self.plugin_selected.emit(None)
            return
        ep_name = current.data(0, _EP_NAME_ROLE)
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

        def _update_subtree(item: QTreeWidgetItem) -> None:
            """Recursively update text for any item whose plugin matches *new_name*."""
            ep_name = item.data(0, _EP_NAME_ROLE)
            plugin = self._plugin_manager.plugins.get(ep_name)
            if plugin is not None and plugin.instance_name == new_name:
                item.setText(0, f"{new_name} ({plugin.name})")
            for i in range(item.childCount()):
                _update_subtree(item.child(i))

        for i in range(self._sequence_tree.topLevelItemCount()):
            _update_subtree(self._sequence_tree.topLevelItem(i))

    def _update_monitor_visibility(self) -> None:
        """Show or hide the monitoring section depending on whether any widgets are present."""
        has_monitors = bool(self._monitor_widgets)
        self._monitor_label.setVisible(has_monitors)
        self._monitor_container.setVisible(has_monitors)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def sequence_steps(self) -> list[_SequenceStep]:
        """Return the current sequence steps as a (possibly nested) list.

        Each element is either:

        * a plain entry-point name string for a step that has no sub-steps, or
        * a ``(ep_name, [sub-steps…])`` tuple for a
          :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`
          step that has at least one nested child.  The inner list follows the
          same structure recursively, allowing arbitrarily deep nesting for
          multi-dimensional measurement scans.

        Returns:
            (list[_SequenceStep]):
                Ordered sequence of step descriptors.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> pm = PluginManager()
            >>> panel = DockPanel(plugin_manager=pm)
            >>> panel.sequence_steps
            []
        """

        def _item_to_step(item: QTreeWidgetItem) -> _SequenceStep:
            """Recursively convert a tree item to its _SequenceStep representation."""
            ep_name: str = item.data(0, _EP_NAME_ROLE)
            if item.childCount() == 0:
                return ep_name
            return (ep_name, [_item_to_step(item.child(j)) for j in range(item.childCount())])

        return [
            _item_to_step(self._sequence_tree.topLevelItem(i))
            for i in range(self._sequence_tree.topLevelItemCount())
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
