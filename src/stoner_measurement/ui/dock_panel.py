"""Dock panel — left 25 % of the main window.

Provides instrument listing, sequence building controls, a run button,
and a monitoring section where plugins can display live status widgets.
The sequence list is a tree widget that supports drag-and-drop reordering
and arbitrarily deep sub-sequence nesting for
:class:`~stoner_measurement.plugins.sequence.base.SequencePlugin` items
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
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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
_PLUGIN_INSTANCE_ROLE = Qt.ItemDataRole.UserRole + 1

# Recursive type alias describing one element of the sequence_steps list.
# A leaf step is a plugin instance; a sequence-plugin step with sub-steps is a
# (plugin_instance, [sub-steps…]) tuple of arbitrary depth.
type _SequenceStep = BasePlugin | tuple[BasePlugin, list[_SequenceStep]]

# QSS stylesheet for the sequence tree widget to ensure consistent branch
# indicators (expand/collapse markers and lead lines) across platforms.
# The style uses simple solid lines for lead lines and relies on Qt's
# built-in item-view branch indicators (which respect the platform style)
# by keeping them enabled via show-decoration-selected.
_TREE_STYLESHEET = """
QTreeWidget {
    show-decoration-selected: 1;
}
QTreeWidget::branch:has-siblings:!adjoins-item {
    border-left: 1px solid gray;
    margin-left: 5px;
}
QTreeWidget::branch:has-siblings:adjoins-item,
QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {
    border-left: 1px solid gray;
    margin-left: 5px;
    border-bottom: 1px solid gray;
}
"""


class _SequenceTreeWidget(QTreeWidget):
    """Tree widget for sequence steps with drag-and-drop support.

    Supports:

    * **Reordering** — drag a step above or below another to reorder.
    * **Sub-sequencing** — drag any step *onto* a
      :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
      item to nest it as a sub-step.  This includes dragging one
      :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
      onto another, enabling arbitrarily deep nesting for multi-dimensional
      measurement scans.  Nested items are shown with indentation.
    * **Promotion** — drag a sub-step above or below any top-level item to
      move it back up the hierarchy.

    :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
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
        self.setStyleSheet(_TREE_STYLESHEET)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_sequence_plugin_instance(plugin: BasePlugin) -> bool:
        """Return ``True`` if *plugin* is a SequencePlugin instance."""
        from stoner_measurement.plugins.sequence import SequencePlugin

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

    def make_item(self, plugin: BasePlugin, text: str, ep_name: str = "") -> QTreeWidgetItem:
        """Create a styled :class:`QTreeWidgetItem` for *plugin*.

        :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
        items are displayed in bold and carry a tooltip that explains the
        drag-onto behaviour.

        Args:
            plugin (BasePlugin):
                The plugin instance associated with this sequence step.
            text (str):
                Display label for the item.

        Keyword Parameters:
            ep_name (str):
                Entry-point registry key for the plugin.  Stored in
                :data:`_EP_NAME_ROLE` so that existing code that looks up
                items by entry-point name continues to work.  Defaults to
                an empty string when the step was created without a registry
                key.

        Returns:
            (QTreeWidgetItem):
                A new item ready to be inserted into the tree.
        """
        item = QTreeWidgetItem([text])
        item.setData(0, _EP_NAME_ROLE, ep_name)
        item.setData(0, _PLUGIN_INSTANCE_ROLE, plugin)
        flags = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
        )
        if self._is_sequence_plugin_instance(plugin):
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
            target_plugin = target.data(0, _PLUGIN_INSTANCE_ROLE)
            if not self._is_sequence_plugin_instance(target_plugin):
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
            target_plugin = target.data(0, _PLUGIN_INSTANCE_ROLE)
            if not self._is_sequence_plugin_instance(target_plugin):
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
        # Tell Qt the drop action was CopyAction so that its internal
        # startDrag post-drop cleanup (clearOrRemove) is NOT triggered.
        # We have already moved the item manually above; if Qt's MoveAction
        # cleanup ran it would remove the item a second time from its new
        # location, causing the "disappearing item" bug.
        event.setDropAction(Qt.DropAction.CopyAction)
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
      :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
      item (e.g. a
      :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`)
      to nest it as a sub-step (shown with indentation).  This includes
      dragging one sequence-plugin step onto another, enabling multi-dimensional
      measurement scans at arbitrary depth.
    * Drag a sub-step to the top level to promote it.

    Attributes:
        sequence_steps (list[_SequenceStep]):
            The current sequence steps as a recursive structure.  Each element
            is either a plugin instance (for a leaf step with no sub-steps) or
            a ``(plugin_instance, [sub-steps…])`` tuple for a
            :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
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
        # Counts how many step instances have been created per ep_name,
        # used to generate unique instance names for additional copies.
        self._step_counts: dict[str, int] = {}
        # Keeps strong Python references to per-step plugin instances so they
        # are not garbage-collected while stored only via QTreeWidgetItem.setData()..
        self._step_plugins: list[BasePlugin] = []

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- Available sequence commands / plugins ---
        layout.addWidget(QLabel("<b>Available sequence commands</b>"))
        self._instrument_filter = QLineEdit()
        self._instrument_filter.setObjectName("instrumentFilter")
        self._instrument_filter.setPlaceholderText("Filter plugins...")
        self._instrument_filter.setClearButtonEnabled(True)
        layout.addWidget(self._instrument_filter)
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
        self._instrument_list.itemDoubleClicked.connect(self._on_instrument_double_clicked)
        self._instrument_filter.textChanged.connect(self._filter_instruments)

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
        for name, plugin in self._plugin_manager.plugins.items():
            item = QListWidgetItem(name)
            item.setToolTip(plugin.tooltip())
            self._instrument_list.addItem(item)
        self._filter_instruments(self._instrument_filter.text())

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

    def _on_instrument_double_clicked(self) -> None:
        """Add the double-clicked instrument as a sequence step."""
        self._add_step()

    def _filter_instruments(self, text: str) -> None:
        """Show only instrument list items whose name contains *text*.

        The filter is case-insensitive.  An empty *text* shows all items.

        Args:
            text (str):
                The filter string typed into the filter box.
        """
        text_lower = text.lower()
        for i in range(self._instrument_list.count()):
            item = self._instrument_list.item(i)
            if item is not None:
                item.setHidden(text_lower not in item.text().lower())

    def _release_step_plugins(self, item: QTreeWidgetItem) -> None:
        """Remove the strong reference to the plugin in *item* (and all children).

        Called before an item is removed from the tree so that the plugin
        instances are no longer held alive by :attr:`_step_plugins` after
        the tree item is gone.

        Args:
            item (QTreeWidgetItem):
                The item (and its subtree) whose plugin references should be
                released.
        """
        plugin = item.data(0, _PLUGIN_INSTANCE_ROLE)
        if plugin is not None and plugin in self._step_plugins:
            self._step_plugins.remove(plugin)
        for i in range(item.childCount()):
            self._release_step_plugins(item.child(i))

    def _add_step(self) -> None:
        """Add the selected instrument as a top-level sequence step.

        Each invocation creates a **new** plugin instance from the selected
        plugin's class so that multiple steps of the same plugin type each have
        independent configuration.  The new instance is assigned a unique
        ``instance_name`` (e.g. ``counter``, ``counter_2``, ``counter_3`` …).
        """
        current = self._instrument_list.currentItem()
        if current is None:
            return
        ep_name = current.text()
        base_plugin = self._plugin_manager.plugins.get(ep_name)
        if base_plugin is None:
            return

        # Create a new, independent instance of the same plugin class.
        new_plugin: BasePlugin = type(base_plugin)()

        # Assign a unique instance name.
        count = self._step_counts.get(ep_name, 0)
        self._step_counts[ep_name] = count + 1
        if count > 0:
            # Subsequent instances: append a numeric suffix.
            new_plugin.instance_name = f"{base_plugin.instance_name}_{count + 1}"

        # Wire instance_name_changed so the label in the tree stays in sync.
        if hasattr(new_plugin, "instance_name_changed"):
            new_plugin.instance_name_changed.connect(self._on_plugin_renamed)

        # Keep a strong Python reference so the instance is not garbage-collected
        # while it is stored only via QTreeWidgetItem.setData().
        self._step_plugins.append(new_plugin)

        text = f"{new_plugin.instance_name} ({new_plugin.name})"
        item = self._sequence_tree.make_item(new_plugin, text, ep_name=ep_name)
        self._sequence_tree.addTopLevelItem(item)

    def _remove_step(self) -> None:
        """Remove the currently selected sequence step (or sub-step)."""
        item = self._sequence_tree.currentItem()
        if item is None:
            return
        # Release strong references for the item and all nested children.
        self._release_step_plugins(item)
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
        plugin = current.data(0, _PLUGIN_INSTANCE_ROLE)
        self.plugin_selected.emit(plugin)

    def _on_plugin_renamed(self, old_name: str, new_name: str) -> None:
        """Update sequence step labels when a plugin's instance name changes.

        This slot is connected to the ``instance_name_changed(old, new)``
        signal on each per-step plugin instance.  It uses ``self.sender()``
        to identify which plugin was renamed and updates only the matching
        tree item(s).

        Args:
            old_name (str):
                Previous instance name (used for logging context).
            new_name (str):
                New instance name to display.
        """
        renamed_plugin = self.sender()

        def _update_subtree(item: QTreeWidgetItem) -> None:
            """Recursively update text for the item whose plugin was renamed."""
            plugin = item.data(0, _PLUGIN_INSTANCE_ROLE)
            if plugin is renamed_plugin:
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

        * a plugin instance for a step that has no sub-steps, or
        * a ``(plugin_instance, [sub-steps…])`` tuple for a
          :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
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
            plugin: BasePlugin = item.data(0, _PLUGIN_INSTANCE_ROLE)
            if item.childCount() == 0:
                return plugin
            return (plugin, [_item_to_step(item.child(j)) for j in range(item.childCount())])

        return [
            _item_to_step(self._sequence_tree.topLevelItem(i))
            for i in range(self._sequence_tree.topLevelItemCount())
        ]

    def load_sequence(self, steps: list[_SequenceStep]) -> None:
        """Replace the current sequence tree with *steps*.

        All existing steps are removed and their plugin references released
        before the new steps are inserted.  Each plugin is added to
        :attr:`_step_plugins` so that it is not garbage-collected, and its
        ``instance_name_changed`` signal (if present) is wired to the tree's
        label-update handler.

        This method is the programmatic counterpart of the interactive
        drag-and-drop sequence builder.  Use it when loading a sequence from a
        file (see :mod:`stoner_measurement.core.serializer`).

        Args:
            steps (list[_SequenceStep]):
                Sequence steps in the same nested format returned by
                :attr:`sequence_steps`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> pm = PluginManager()
            >>> panel = DockPanel(plugin_manager=pm)
            >>> plugin = DummyPlugin()
            >>> panel.load_sequence([plugin])
            >>> len(panel.sequence_steps)
            1
        """
        # Release all existing step plugins and clear the tree.
        for i in range(self._sequence_tree.topLevelItemCount() - 1, -1, -1):
            item = self._sequence_tree.topLevelItem(i)
            self._release_step_plugins(item)
            self._sequence_tree.takeTopLevelItem(i)
        self._step_plugins.clear()
        self._step_counts.clear()

        for step in steps:
            self._load_step(step, parent_item=None)

    def _load_step(
        self, step: _SequenceStep, parent_item: QTreeWidgetItem | None
    ) -> QTreeWidgetItem:
        """Insert a single *step* into the tree under *parent_item*.

        Recursively processes sub-steps for
        :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
        steps.

        Args:
            step (_SequenceStep):
                A plugin instance or ``(plugin, [sub-steps…])`` tuple.
            parent_item (QTreeWidgetItem | None):
                Parent tree item, or ``None`` for top-level items.

        Returns:
            (QTreeWidgetItem):
                The newly created tree item.
        """
        if isinstance(step, tuple):
            plugin, sub_steps = step
        else:
            plugin, sub_steps = step, []

        if hasattr(plugin, "instance_name_changed"):
            plugin.instance_name_changed.connect(self._on_plugin_renamed)
        self._step_plugins.append(plugin)

        text = f"{plugin.instance_name} ({plugin.name})"
        item = self._sequence_tree.make_item(plugin, text)
        if parent_item is None:
            self._sequence_tree.addTopLevelItem(item)
        else:
            parent_item.addChild(item)

        for sub_step in sub_steps:
            self._load_step(sub_step, parent_item=item)

        return item

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
