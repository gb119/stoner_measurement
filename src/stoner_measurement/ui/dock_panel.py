"""Dock panel — left 25 % of the main window.

Provides instrument listing, sequence building controls, a run button,
and a monitoring section where plugins can display live status widgets.
The sequence list is a tree widget that supports drag-and-drop reordering
and arbitrarily deep sub-sequence nesting for
:class:`~stoner_measurement.plugins.sequence.base.SequencePlugin` items
(including :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`),
enabling multi-dimensional measurement scans.  Plugins may also be dragged
directly from the *Available sequence commands* list into the sequence tree to
insert new steps at any position or into a sub-sequence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt6.QtCore import QMimeData, QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
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

# Custom MIME type used when dragging a plugin entry-point from the available
# plugins list into the sequence tree.  The payload is the UTF-8–encoded
# entry-point name (plugin registry key).
_PLUGIN_EP_MIME_TYPE = "application/x-stoner-plugin-ep"

# Recursive type alias describing one element of the sequence_steps list.
# A leaf step is a plugin instance; a sequence-plugin step with sub-steps is a
# (plugin_instance, [sub-steps…]) tuple of arbitrary depth.
type _SequenceStep = BasePlugin | tuple[BasePlugin, list[_SequenceStep]]

# Regex that matches an instance name whose suffix is an underscore followed by
# digits, e.g. ``"my_step_3"``.  Group 1 is the base name, group 2 is the
# numeric part.  Underscore is used so that pasted names remain valid Python
# identifiers.
_PASTE_SUFFIX_RE = re.compile(r"^(.*)_(\d+)$")

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


class _PluginListWidget(QListWidget):
    """Plugin list widget that supports dragging plugins into the sequence tree.

    Each list item carries both the standard Qt item-model MIME payload (so
    that the sequence tree's drop-indicator machinery works correctly) and a
    custom :data:`_PLUGIN_EP_MIME_TYPE` payload carrying the entry-point
    registry key as a UTF-8–encoded byte string.

    The widget is configured for *drag-only* mode — items may be dragged out
    but nothing may be dropped onto it.

    Keyword Parameters:
        parent (QWidget | None):
            Optional Qt parent widget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    # ------------------------------------------------------------------
    # Drag support
    # ------------------------------------------------------------------

    def mimeData(self, items: list[QListWidgetItem]) -> QMimeData:  # type: ignore[override]
        """Return MIME data for *items*, adding the plugin entry-point name.

        The ``# type: ignore[override]`` suppresses a mypy error because
        ``QListWidget.mimeData`` is annotated to return ``Optional[QMimeData]``
        in some stubs while we always return a concrete ``QMimeData`` instance.

        The standard ``application/x-qabstractitemmodeldatalist`` payload from
        the base class is preserved so that the sequence tree's Qt-internal
        drop-indicator code recognises the drag as acceptable and shows the
        insertion line.  An additional :data:`_PLUGIN_EP_MIME_TYPE` entry
        carries the entry-point name so that :class:`_SequenceTreeWidget` can
        look up and instantiate the correct plugin.

        Args:
            items (list[QListWidgetItem]):
                The items being dragged (typically a single-element list).

        Returns:
            (QMimeData):
                Extended MIME data object.
        """
        data = super().mimeData(items)
        if items:
            data.setData(_PLUGIN_EP_MIME_TYPE, items[0].text().encode())
        return data


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
    * **New steps from the plugin list** — drag a plugin from the
      *Available sequence commands* :class:`_PluginListWidget` and drop it
      above, below or onto an existing step (or onto the empty area) to
      insert a brand-new step instance at that position.

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
        self._new_item_factory: Callable[[str], QTreeWidgetItem | None] | None = None
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(20)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setStyleSheet(_TREE_STYLESHEET)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def set_new_item_factory(
        self, factory: Callable[[str], QTreeWidgetItem | None] | None
    ) -> None:
        """Register *factory* as the callable used to create new tree items.

        The factory is invoked when a plugin is dragged from the
        *Available sequence commands* list and dropped onto the sequence tree.

        Args:
            factory (Callable[[str], QTreeWidgetItem | None] | None):
                A callable that accepts an entry-point name string and returns
                a newly created :class:`QTreeWidgetItem` ready for insertion,
                or ``None`` if the plugin cannot be found.  Pass ``None`` to
                disable plugin-list drops.
        """
        self._new_item_factory = factory

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

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept drags from the plugin list as well as internal tree reorders.

        Drops carrying :data:`_PLUGIN_EP_MIME_TYPE` originate from
        :class:`_PluginListWidget` and represent requests to insert a new
        plugin instance into the sequence.

        Args:
            event (QDragEnterEvent):
                The incoming drag-enter event.
        """
        if event.mimeData().hasFormat(_PLUGIN_EP_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Reject drops *onto* non-SequencePlugin items or onto descendants.

        For drops originating from the plugin list (detected via
        :data:`_PLUGIN_EP_MIME_TYPE`), the ancestor-cycle check is skipped
        because the dragged item does not yet exist in the tree.

        Args:
            event (QDragMoveEvent):
                The incoming drag-move event.
        """
        is_external = event.mimeData().hasFormat(_PLUGIN_EP_MIME_TYPE)
        pos_point = event.position().toPoint()
        target = self.itemAt(pos_point)

        # For external drops call super() first so Qt can update
        # dropIndicatorPosition() before we read it.
        if is_external:
            super().dragMoveEvent(event)
            pos = self.dropIndicatorPosition()
            if target is not None and pos == QAbstractItemView.DropIndicatorPosition.OnItem:
                target_plugin = target.data(0, _PLUGIN_INSTANCE_ROLE)
                if not self._is_sequence_plugin_instance(target_plugin):
                    event.ignore()
                    return
            event.acceptProposedAction()
            return

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
        """Handle reorder, nest-as-sub-step, and new-plugin drops.

        Drops carrying :data:`_PLUGIN_EP_MIME_TYPE` create a new plugin
        instance at the drop position.  All other drops are internal
        reorder/nesting moves.

        Args:
            event (QDropEvent):
                The incoming drop event.
        """
        # -- External drop: new plugin from the available-plugins list --
        if event.mimeData().hasFormat(_PLUGIN_EP_MIME_TYPE):
            self._handle_external_plugin_drop(event)
            return

        # -- Internal drop: reorder or nest existing tree items --
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

    def _handle_external_plugin_drop(self, event: QDropEvent) -> None:
        """Insert a brand-new plugin step at the location indicated by *event*.

        Called from :meth:`dropEvent` when the MIME data carries
        :data:`_PLUGIN_EP_MIME_TYPE`, indicating that the user dragged a
        plugin from the *Available sequence commands* list.

        A new plugin instance is created via :attr:`_new_item_factory`.  If no
        factory has been registered the event is ignored.

        Args:
            event (QDropEvent):
                The incoming drop event; must contain :data:`_PLUGIN_EP_MIME_TYPE`.
        """
        if self._new_item_factory is None:
            event.ignore()
            return

        ep_name = bytes(event.mimeData().data(_PLUGIN_EP_MIME_TYPE)).decode()
        new_item = self._new_item_factory(ep_name)
        if new_item is None:
            event.ignore()
            return

        pos_point = event.position().toPoint()
        target = self.itemAt(pos_point)
        pos = self.dropIndicatorPosition()

        if target is None:
            self.addTopLevelItem(new_item)
        elif pos == QAbstractItemView.DropIndicatorPosition.OnItem:
            target_plugin = target.data(0, _PLUGIN_INSTANCE_ROLE)
            if not self._is_sequence_plugin_instance(target_plugin):
                event.ignore()
                return
            target.addChild(new_item)
            target.setExpanded(True)
        elif pos == QAbstractItemView.DropIndicatorPosition.AboveItem:
            target_parent = target.parent()
            idx = (
                target_parent.indexOfChild(target)
                if target_parent is not None
                else self.indexOfTopLevelItem(target)
            )
            if target_parent is not None:
                target_parent.insertChild(idx, new_item)
            else:
                self.insertTopLevelItem(idx, new_item)
        else:  # BelowItem or OnViewport with non-None target
            target_parent = target.parent()
            idx = (
                target_parent.indexOfChild(target)
                if target_parent is not None
                else self.indexOfTopLevelItem(target)
            )
            if target_parent is not None:
                target_parent.insertChild(idx + 1, new_item)
            else:
                self.insertTopLevelItem(idx + 1, new_item)

        self.setCurrentItem(new_item)
        event.acceptProposedAction()


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
    * Drag a plugin from the *Available sequence commands* list and drop it
      above, below, or onto any existing step (or onto the empty area below all
      steps) to insert a brand-new step instance at that position.  Dropping
      onto a :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
      item adds the new step as the last child of that sub-sequence.

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

    #: Emitted with the plugin instance when exactly one sequence step is
    #: selected, or ``None`` when the selection is cleared or multiple steps
    #: are selected simultaneously.
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
        # JSON clipboard for cut/copy/paste of sequence steps.
        self._clipboard_step_json: str | None = None

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- Available sequence commands / plugins ---
        layout.addWidget(QLabel("<b>Available sequence commands</b>"))
        self._instrument_filter = QLineEdit()
        self._instrument_filter.setObjectName("instrumentFilter")
        self._instrument_filter.setPlaceholderText("Filter plugins...")
        self._instrument_filter.setClearButtonEnabled(True)
        layout.addWidget(self._instrument_filter)
        self._instrument_list = _PluginListWidget()
        self._instrument_list.setObjectName("instrumentList")
        layout.addWidget(self._instrument_list)

        # --- Sequence steps ---
        layout.addWidget(QLabel("<b>Sequence Steps</b>"))
        self._sequence_tree = _SequenceTreeWidget(plugin_manager=plugin_manager)
        self._sequence_tree.setObjectName("sequenceTree")
        layout.addWidget(self._sequence_tree)
        # Wire the factory so that plugin-list drops create new step items.
        self._sequence_tree.set_new_item_factory(self._make_new_step_item)
        # Enable right-click context menu on the sequence tree.
        self._sequence_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._sequence_tree.customContextMenuRequested.connect(
            self._show_sequence_context_menu
        )

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
        self._sequence_tree.itemSelectionChanged.connect(self._on_selection_changed)
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

        Delegates to :meth:`_make_new_step_item` to create the item, then
        appends it at the top level of the sequence tree.
        """
        current = self._instrument_list.currentItem()
        if current is None:
            return
        item = self._make_new_step_item(current.text())
        if item is None:
            return
        self._sequence_tree.addTopLevelItem(item)

    def _make_new_step_item(self, ep_name: str) -> QTreeWidgetItem | None:
        """Create a new sequence-step tree item for the plugin *ep_name*.

        A fresh plugin instance is created from the registered class, assigned
        a unique :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.instance_name`
        (e.g. ``counter``, ``counter_2``, ``counter_3`` …), wired to the
        rename-validation handler, and kept alive in :attr:`_step_plugins`.

        This method is used both by :meth:`_add_step` (button / double-click)
        and by :class:`_SequenceTreeWidget`'s drop handler when a plugin is
        dragged from the *Available sequence commands* list.

        Args:
            ep_name (str):
                Entry-point registry key identifying the plugin to instantiate.

        Returns:
            (QTreeWidgetItem | None):
                A new tree item ready for insertion into the sequence tree, or
                ``None`` if *ep_name* is not found in the plugin manager.
        """
        base_plugin = self._plugin_manager.plugins.get(ep_name)
        if base_plugin is None:
            return None

        # Create a new, independent instance of the same plugin class.
        new_plugin: BasePlugin = type(base_plugin)()

        # Assign a unique instance name, guaranteed not to clash with any
        # step already in the tree.
        self._step_counts[ep_name] = self._step_counts.get(ep_name, 0) + 1
        unique_name = self._unique_step_name(base_plugin.instance_name)
        if unique_name != new_plugin.instance_name:
            new_plugin.instance_name = unique_name

        # Wire instance_name_changed so the label in the tree stays in sync.
        if hasattr(new_plugin, "instance_name_changed"):
            new_plugin.instance_name_changed.connect(self._on_plugin_renamed)

        # Keep a strong Python reference so the instance is not garbage-collected
        # while it is stored only via QTreeWidgetItem.setData().
        self._step_plugins.append(new_plugin)

        text = f"{new_plugin.instance_name} ({new_plugin.name})"
        return self._sequence_tree.make_item(new_plugin, text, ep_name=ep_name)

    def _remove_step(self) -> None:
        """Remove all currently selected sequence steps (and sub-steps)."""
        items = self._sequence_tree.selectedItems()
        if not items:
            return
        # Only remove items that do not have a selected ancestor: removing a
        # parent automatically removes its children, so operating on a child
        # that has already been deleted would cause a crash.
        # Use id() because QTreeWidgetItem is not hashable in PyQt6.
        selected_ids = {id(item) for item in items}

        def _has_selected_ancestor(item: QTreeWidgetItem) -> bool:
            """Return True if any ancestor of item is also in the selection."""
            parent = item.parent()
            while parent is not None:
                if id(parent) in selected_ids:
                    return True
                parent = parent.parent()
            return False

        for item in items:
            if _has_selected_ancestor(item):
                continue
            self._release_step_plugins(item)
            parent = item.parent()
            if parent is not None:
                parent.removeChild(item)
            else:
                idx = self._sequence_tree.indexOfTopLevelItem(item)
                if idx >= 0:
                    self._sequence_tree.takeTopLevelItem(idx)

    def _on_selection_changed(self) -> None:
        """Emit :attr:`plugin_selected` when the sequence-step selection changes.

        Emits the plugin instance when exactly one step is selected.  Emits
        ``None`` when the selection is empty or when more than one step is
        selected (in the latter case the configuration panel is hidden so that
        the panel cannot show ambiguous settings for multiple different plugins).
        """
        selected = self._sequence_tree.selectedItems()
        if len(selected) == 1:
            plugin = selected[0].data(0, _PLUGIN_INSTANCE_ROLE)
            self.plugin_selected.emit(plugin)
        else:
            self.plugin_selected.emit(None)

    def _on_plugin_renamed(self, old_name: str, new_name: str) -> None:
        """Validate uniqueness and update sequence step labels when a plugin's instance name changes.

        This slot is connected to the ``instance_name_changed(old, new)``
        signal on each per-step plugin instance.  It uses ``self.sender()``
        to identify which plugin was renamed.

        If *new_name* is already used by a **different** step the rename is
        rejected: the plugin's :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.instance_name`
        is reverted to *old_name* and a warning dialog is shown.  Otherwise
        the matching tree item label is updated to reflect the new name.

        Args:
            old_name (str):
                Previous instance name.
            new_name (str):
                Requested new instance name.
        """
        renamed_plugin = self.sender()

        # Reject the rename if the requested name is already taken by a
        # different step in the current sequence.
        if new_name in self._current_instance_names(exclude_plugin=renamed_plugin):
            # Revert to the previous name before showing the warning so that
            # any connected QLineEdit is updated first (via instance_name_changed).
            renamed_plugin.instance_name = old_name  # type: ignore[union-attr]
            QMessageBox.warning(
                self,
                "Instance Name Conflict",
                f"The name {new_name!r} is already used by another step in the sequence.\n"
                f"The name has been reverted to {old_name!r}.",
            )
            return

        def _update_subtree(item: QTreeWidgetItem) -> None:
            """Recursively update text for the item whose plugin was renamed."""
            plugin = item.data(0, _PLUGIN_INSTANCE_ROLE)
            if plugin is renamed_plugin:
                item.setText(0, f"{new_name} ({plugin.name})")
            for i in range(item.childCount()):
                _update_subtree(item.child(i))

        for i in range(self._sequence_tree.topLevelItemCount()):
            _update_subtree(self._sequence_tree.topLevelItem(i))

    # ------------------------------------------------------------------
    # Instance-name uniqueness helpers
    # ------------------------------------------------------------------

    def _current_instance_names(
        self, exclude_plugin: BasePlugin | None = None
    ) -> set[str]:
        """Return instance names of all step plugins currently in the tree.

        Args:
            exclude_plugin (BasePlugin | None):
                If provided, this plugin's name is *not* included in the
                returned set.  Pass the plugin that is about to be renamed so
                its *current* name is not treated as a collision with itself.

        Returns:
            (set[str]):
                Set of instance name strings.
        """
        names: set[str] = set()

        def _collect(item: QTreeWidgetItem) -> None:
            """Recursively add the instance name of each tree item's plugin to *names*, skipping *exclude_plugin*."""
            plugin: BasePlugin = item.data(0, _PLUGIN_INSTANCE_ROLE)
            if plugin is not None and plugin is not exclude_plugin:
                names.add(plugin.instance_name)
            for i in range(item.childCount()):
                _collect(item.child(i))

        for i in range(self._sequence_tree.topLevelItemCount()):
            _collect(self._sequence_tree.topLevelItem(i))
        return names

    def _unique_step_name(self, base_name: str) -> str:
        """Return a name derived from *base_name* that is unique in the current sequence.

        If *base_name* is not yet taken it is returned unchanged.  Otherwise a
        numeric suffix is appended (``_2``, ``_3``, …) until a free name is
        found.

        Args:
            base_name (str):
                Preferred name, typically the plugin's default
                :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.instance_name`.

        Returns:
            (str):
                A name that does not clash with any step currently in the tree.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> pm = PluginManager()
            >>> pm.register("Dummy", DummyPlugin())
            >>> panel = DockPanel(plugin_manager=pm)
            >>> panel._unique_step_name("dummy")
            'dummy'
            >>> panel._instrument_list.setCurrentRow(0)
            >>> panel._add_step()
            >>> panel._unique_step_name("dummy")
            'dummy_2'
        """
        existing = self._current_instance_names()
        if base_name not in existing:
            return base_name
        count = 2
        while f"{base_name}_{count}" in existing:
            count += 1
        return f"{base_name}_{count}"

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
        self,
        step: _SequenceStep,
        parent_item: QTreeWidgetItem | None,
        insert_index: int | None = None,
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

        Keyword Parameters:
            insert_index (int | None):
                When given, insert the new item at this position within
                *parent_item*'s children (or at the given top-level index when
                *parent_item* is ``None``).  When ``None`` the item is appended.

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
            if insert_index is not None:
                self._sequence_tree.insertTopLevelItem(insert_index, item)
            else:
                self._sequence_tree.addTopLevelItem(item)
        else:
            if insert_index is not None:
                parent_item.insertChild(insert_index, item)
            else:
                parent_item.addChild(item)

        for sub_step in sub_steps:
            self._load_step(sub_step, parent_item=item)

        if sub_steps:
            item.setExpanded(True)

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

    # ------------------------------------------------------------------
    # Clipboard helpers — instance-name adjustment
    # ------------------------------------------------------------------

    @property
    def has_clipboard_step(self) -> bool:
        """``True`` when the internal sequence-step clipboard contains data.

        Returns:
            (bool):
                Whether there is a copied/cut step ready to paste.
        """
        return self._clipboard_step_json is not None

    @staticmethod
    def _compute_paste_name(name: str, existing: set[str]) -> str:
        """Return a collision-free variant of *name* using underscore-numeric suffixes.

        If *name* is not in *existing* it is returned unchanged.  Otherwise:

        * If *name* already ends in ``_<n>`` the counter is incremented from
          ``n + 1`` until a free slot is found.
        * Otherwise the suffix ``_2`` is tried first and the counter is
          incremented until a free slot is found.

        Underscores are used so that the resulting names remain valid Python
        identifiers.

        Args:
            name (str):
                Proposed instance name.
            existing (set[str]):
                Set of names already in use.

        Returns:
            (str):
                A name not present in *existing*.

        Examples:
            >>> DockPanel._compute_paste_name("foo", set())
            'foo'
            >>> DockPanel._compute_paste_name("foo", {"foo"})
            'foo_2'
            >>> DockPanel._compute_paste_name("foo_2", {"foo_2", "foo_3"})
            'foo_4'
        """
        if name not in existing:
            return name
        m = _PASTE_SUFFIX_RE.match(name)
        if m:
            base = m.group(1)
            num = int(m.group(2)) + 1
        else:
            base = name
            num = 2
        while f"{base}_{num}" in existing:
            num += 1
        return f"{base}_{num}"

    def _paste_adjust_names(
        self, step: _SequenceStep, allocated: set[str]
    ) -> _SequenceStep:
        """Recursively adjust plugin instance names in *step* to avoid collisions.

        Mutates the plugin instances in *step* in-place (safe because they have
        just been deserialised and are not yet attached to the tree or any
        signals).  *allocated* is updated with every name that is assigned so
        that sub-steps within the same paste operation do not collide with each
        other.

        Args:
            step (_SequenceStep):
                The step (or sub-step) whose names to adjust.
            allocated (set[str]):
                Set of names already allocated in this paste operation.
                Updated in place as each name is confirmed.

        Returns:
            (_SequenceStep):
                The same *step* object with adjusted instance names.
        """
        # Snapshot the current tree names once; the tree does not change
        # during this adjustment pass, so re-reading it per-recursion is
        # redundant and wasteful for deeply nested sequences.
        existing = self._current_instance_names()
        return self._paste_adjust_names_inner(step, allocated, existing)

    def _paste_adjust_names_inner(
        self,
        step: _SequenceStep,
        allocated: set[str],
        existing: set[str],
    ) -> _SequenceStep:
        """Inner recursive worker for :meth:`_paste_adjust_names`.

        Receives the pre-computed *existing* set so it is not re-fetched on
        every recursive call.

        Args:
            step (_SequenceStep):
                The step (or sub-step) whose names to adjust.
            allocated (set[str]):
                Set of names already allocated in this paste operation.
                Updated in place as each name is confirmed.
            existing (set[str]):
                Snapshot of instance names already in the tree, taken before
                the paste operation began.

        Returns:
            (_SequenceStep):
                The same *step* object with adjusted instance names.
        """
        if isinstance(step, tuple):
            plugin, sub_steps = step
            new_name = self._compute_paste_name(plugin.instance_name, existing | allocated)
            plugin.instance_name = new_name
            allocated.add(new_name)
            new_sub = [
                self._paste_adjust_names_inner(s, allocated, existing) for s in sub_steps
            ]
            return (plugin, new_sub)
        new_name = self._compute_paste_name(step.instance_name, existing | allocated)
        step.instance_name = new_name
        allocated.add(new_name)
        return step

    # ------------------------------------------------------------------
    # Cut / Copy / Paste public API
    # ------------------------------------------------------------------

    def copy_selected_step(self) -> bool:
        """Copy the currently selected sequence step(s) to the internal clipboard.

        All selected steps (including any sub-steps) are serialised to JSON
        and stored in :attr:`_clipboard_step_json`.  When a selected item's
        parent is also selected the child is omitted — its data is already
        captured inside the parent's serialised sub-steps.  Returns ``False``
        when nothing is selected.

        Returns:
            (bool):
                ``True`` if at least one step was copied, ``False`` if nothing
                was selected.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> pm = PluginManager()
            >>> panel = DockPanel(plugin_manager=pm)
            >>> panel.load_sequence([DummyPlugin()])
            >>> panel._sequence_tree.setCurrentItem(panel._sequence_tree.topLevelItem(0))
            >>> panel.copy_selected_step()
            True
            >>> panel.has_clipboard_step
            True
        """
        from stoner_measurement.core.serializer import sequence_to_json

        items = self._sequence_tree.selectedItems()
        if not items:
            return False

        # Omit items whose parent is also selected (parent serialisation
        # already captures the sub-step).
        selected_set = set(items)

        def _has_selected_ancestor(item: QTreeWidgetItem) -> bool:
            """Return True if any ancestor of item is also in the selection."""
            parent = item.parent()
            while parent is not None:
                if parent in selected_set:
                    return True
                parent = parent.parent()
            return False

        root_items = [item for item in items if not _has_selected_ancestor(item)]
        steps = [self._item_to_step(item) for item in root_items]
        self._clipboard_step_json = json.dumps(sequence_to_json(steps))
        return True

    def cut_selected_step(self) -> bool:
        """Cut the currently selected sequence step(s) to the internal clipboard.

        Equivalent to :meth:`copy_selected_step` followed by removing all
        selected steps from the tree.  Returns ``False`` when nothing is
        selected.

        Returns:
            (bool):
                ``True`` if at least one step was cut, ``False`` if nothing was
                selected.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> pm = PluginManager()
            >>> panel = DockPanel(plugin_manager=pm)
            >>> panel.load_sequence([DummyPlugin()])
            >>> panel._sequence_tree.setCurrentItem(panel._sequence_tree.topLevelItem(0))
            >>> panel.cut_selected_step()
            True
            >>> panel._sequence_tree.topLevelItemCount()
            0
        """
        if not self.copy_selected_step():
            return False
        self._remove_step()
        return True

    def paste_step(self) -> bool:
        """Paste step(s) from the internal clipboard into the sequence tree.

        All steps in the clipboard are inserted immediately after the current
        item (at the same level of nesting), preserving their original order.
        When nothing is selected every step is appended at the top level.
        Instance names are adjusted using :meth:`_compute_paste_name` to avoid
        collisions with existing names.  All newly inserted items are selected
        after the paste.

        Returns:
            (bool):
                ``True`` if at least one step was pasted, ``False`` when the
                clipboard is empty.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> pm = PluginManager()
            >>> panel = DockPanel(plugin_manager=pm)
            >>> panel.load_sequence([DummyPlugin()])
            >>> panel._sequence_tree.setCurrentItem(panel._sequence_tree.topLevelItem(0))
            >>> panel.copy_selected_step()
            True
            >>> panel.paste_step()
            True
            >>> panel._sequence_tree.topLevelItemCount()
            2
        """
        from stoner_measurement.core.serializer import sequence_from_json

        if self._clipboard_step_json is None:
            return False

        data = json.loads(self._clipboard_step_json)
        steps = sequence_from_json(data)
        if not steps:
            return False

        # Adjust all instance names to avoid collisions; share a single
        # allocated set so names across multiple pasted steps don't collide
        # with each other either.
        allocated: set[str] = set()
        steps = [self._paste_adjust_names(step, allocated) for step in steps]

        # Determine the insertion anchor: after the current item.
        anchor = self._sequence_tree.currentItem()
        new_items: list[QTreeWidgetItem] = []
        if anchor is None:
            for step in steps:
                new_items.append(self._load_step(step, parent_item=None))
        else:
            parent = anchor.parent()
            if parent is None:
                base_idx = self._sequence_tree.indexOfTopLevelItem(anchor)
                for i, step in enumerate(steps):
                    new_items.append(
                        self._load_step(step, parent_item=None, insert_index=base_idx + 1 + i)
                    )
            else:
                base_idx = parent.indexOfChild(anchor)
                for i, step in enumerate(steps):
                    new_items.append(
                        self._load_step(step, parent_item=parent, insert_index=base_idx + 1 + i)
                    )

        # Select all newly pasted items so the user can see what was inserted.
        self._sequence_tree.clearSelection()
        for item in new_items:
            item.setSelected(True)
        if new_items:
            self._sequence_tree.setCurrentItem(new_items[-1])
        return True

    # ------------------------------------------------------------------
    # Sequence tree context menu
    # ------------------------------------------------------------------

    def _item_to_step(self, item: QTreeWidgetItem) -> _SequenceStep:
        """Convert a tree item (and its subtree) to a :data:`_SequenceStep`.

        Args:
            item (QTreeWidgetItem):
                The item to convert.

        Returns:
            (_SequenceStep):
                A plugin instance (for leaf items) or a
                ``(plugin, [sub-steps…])`` tuple when the item has children.
        """
        plugin: BasePlugin = item.data(0, _PLUGIN_INSTANCE_ROLE)
        if item.childCount() == 0:
            return plugin
        sub_steps = [self._item_to_step(item.child(i)) for i in range(item.childCount())]
        return (plugin, sub_steps)

    def _show_sequence_context_menu(self, pos: QPoint) -> None:
        """Display a context menu for the sequence tree at *pos*.

        The menu provides **Copy Step**, **Cut Step** and **Paste Step**
        entries that mirror the application-level Edit-menu actions.

        If the right-click lands on an item that is **not** already part of
        the current selection, the selection is cleared and only that item is
        selected before the menu is shown.  Right-clicking on an already-selected
        item preserves the existing multi-selection so that the menu can act on
        all selected items.

        Args:
            pos (QPoint):
                Position (in viewport coordinates) where the right-click
                occurred.
        """
        item = self._sequence_tree.itemAt(pos)
        if item is not None and not item.isSelected():
            # Right-click on an unselected item: replace the selection.
            self._sequence_tree.clearSelection()
            item.setSelected(True)
            self._sequence_tree.setCurrentItem(item)

        has_selection = bool(self._sequence_tree.selectedItems())

        menu = QMenu(self)

        act_copy = menu.addAction("&Copy Step")
        act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        act_copy.setEnabled(has_selection)
        act_copy.triggered.connect(self.copy_selected_step)

        act_cut = menu.addAction("Cu&t Step")
        act_cut.setShortcut(QKeySequence.StandardKey.Cut)
        act_cut.setEnabled(has_selection)
        act_cut.triggered.connect(self.cut_selected_step)

        act_paste = menu.addAction("&Paste Step")
        act_paste.setShortcut(QKeySequence.StandardKey.Paste)
        act_paste.setEnabled(self._clipboard_step_json is not None)
        act_paste.triggered.connect(self.paste_step)

        menu.exec(self._sequence_tree.viewport().mapToGlobal(pos))

