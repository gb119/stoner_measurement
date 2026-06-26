"""Tests for the dock panel UI."""

from __future__ import annotations

from qtpy.QtWidgets import QLabel, QLineEdit, QTreeWidgetItem

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.plugins.base_plugin import _ABCQObjectMeta
from stoner_measurement.plugins.state_control import StateControlPlugin
from stoner_measurement.plugins.trace import DummyPlugin
from stoner_measurement.ui.dock_panel import DockPanel


class _FakeStatePlugin(StateControlPlugin, metaclass=_ABCQObjectMeta):
    """Minimal concrete StateControlPlugin for use in tests."""

    @property
    def name(self):
        return "FakeState"

    @property
    def state_name(self):
        return "X"

    @property
    def units(self):
        return "au"

    def set_state(self, v):
        pass

    def get_state(self):
        return 0.0

    def is_at_target(self):
        return True

class TestDockPanel:
    def test_creates_widget(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        assert panel is not None

    def test_plugin_list_populated(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        # "Dummy" is a TracePlugin so it appears under a "Trace" category node.
        assert panel._plugin_list.topLevelItemCount() == 1
        category = panel._plugin_list.topLevelItem(0)
        assert category.text(0) == "Trace"
        assert category.childCount() == 1
        assert category.child(0).text(0) == "Dummy"

    def test_state_scan_and_sweep_show_user_facing_names(self, qapp):
        from stoner_measurement.plugins.state_scan.counter import CounterPlugin
        from stoner_measurement.plugins.state_sweep.sweep_time import SweepTimePlugin
        from stoner_measurement.ui.dock_panel import _EP_NAME_ROLE

        pm = PluginManager()
        pm.register("counter", CounterPlugin())
        pm.register("sweep_time", SweepTimePlugin())
        panel = DockPanel(plugin_manager=pm)

        category_map = {
            panel._plugin_list.topLevelItem(i).text(0): panel._plugin_list.topLevelItem(i)
            for i in range(panel._plugin_list.topLevelItemCount())
        }
        assert category_map["State Scan"].child(0).text(0) == "Counter"
        assert category_map["State Scan"].child(0).data(0, _EP_NAME_ROLE) == "counter"
        assert category_map["State Sweep"].child(0).text(0) == "Sweep Time"
        assert category_map["State Sweep"].child(0).data(0, _EP_NAME_ROLE) == "sweep_time"

    def test_sequence_steps_empty_initially(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        assert panel.sequence_steps == []

    def test_add_step(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()
        steps = panel.sequence_steps
        assert len(steps) == 1
        assert isinstance(steps[0], DummyPlugin)

    def test_remove_step(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()
        panel._sequence_tree.setCurrentItem(panel._sequence_tree.topLevelItem(0))
        panel._remove_step()
        assert panel.sequence_steps == []

    def test_refresh_on_plugin_registration(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        assert panel._plugin_list.topLevelItemCount() == 0

        pm.register("Dummy", DummyPlugin())
        assert panel._plugin_list.topLevelItemCount() == 1
        assert panel._plugin_list.topLevelItem(0).childCount() == 1

    # --- Monitoring widget tests ---

    def test_monitor_widgets_empty_initially(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        assert panel.monitor_widgets == {}

    def test_add_monitor_widget(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        lbl = QLabel("Status: OK")
        panel.add_monitor_widget("test_plugin", lbl)
        assert "test_plugin" in panel.monitor_widgets

    def test_add_monitor_widget_duplicate_noop(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        lbl1 = QLabel("First")
        lbl2 = QLabel("Second")
        panel.add_monitor_widget("p", lbl1)
        panel.add_monitor_widget("p", lbl2)  # should be ignored
        assert panel.monitor_widgets["p"] is lbl1

    def test_remove_monitor_widget(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        lbl = QLabel("Status")
        panel.add_monitor_widget("p", lbl)
        panel.remove_monitor_widget("p")
        assert "p" not in panel.monitor_widgets

    def test_remove_monitor_widget_missing_noop(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        panel.remove_monitor_widget("nonexistent")  # should not raise

    def test_monitoring_section_hidden_when_empty(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        assert not panel._monitor_label.isVisible()
        assert not panel._monitor_container.isVisible()

    def test_monitoring_section_visible_when_widget_added(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        panel.add_monitor_widget("p", QLabel("Status"))
        # isVisible() is False when the parent panel hasn't been shown, so
        # use isHidden() to confirm the widget was not explicitly hidden.
        assert not panel._monitor_label.isHidden()
        assert not panel._monitor_container.isHidden()

    def test_monitor_widget_removed_on_plugin_unregister(self, qapp):
        """A plugin that provides a monitor_widget should have it removed when unregistered."""

        class _MonitorPlugin(DummyPlugin):
            @property
            def name(self) -> str:
                return "MonitorPlugin"

            def monitor_widget(self, parent=None):
                return QLabel("Live reading", parent)

        pm = PluginManager()
        pm.register("MonitorPlugin", _MonitorPlugin())
        panel = DockPanel(plugin_manager=pm)
        assert "MonitorPlugin" in panel.monitor_widgets

        pm.unregister("MonitorPlugin")
        assert "MonitorPlugin" not in panel.monitor_widgets

    def test_plugin_selected_emitted_on_step_selection(self, qapp):
        """Selecting a sequence step emits plugin_selected with a DummyPlugin instance."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        received = []
        panel.plugin_selected.connect(lambda p: received.append(p))

        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()
        panel._sequence_tree.setCurrentItem(panel._sequence_tree.topLevelItem(0))

        assert len(received) == 1
        # Each step creates its own independent plugin instance.
        assert isinstance(received[0], DummyPlugin)

    def test_plugin_selected_emits_none_when_selection_cleared(self, qapp):
        """Clearing the sequence tree current item emits plugin_selected(None)."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()
        panel._sequence_tree.setCurrentItem(panel._sequence_tree.topLevelItem(0))

        received = []
        panel.plugin_selected.connect(lambda p: received.append(p))
        panel._sequence_tree.setCurrentItem(None)  # clear current item

        assert len(received) == 1
        assert received[0] is None

    def test_step_display_format(self, qapp):
        """Sequence step display text uses '{instance_name} ({plugin.name})' format."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()

        item = panel._sequence_tree.topLevelItem(0)
        from stoner_measurement.ui.dock_panel import _PLUGIN_INSTANCE_ROLE
        step_plugin = item.data(0, _PLUGIN_INSTANCE_ROLE)
        assert item.text(0) == f"{step_plugin.instance_name} ({step_plugin.name})"

    def test_step_label_updates_on_rename(self, qapp):
        """Renaming a step plugin's instance_name updates the step label."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()

        from stoner_measurement.ui.dock_panel import _PLUGIN_INSTANCE_ROLE
        item = panel._sequence_tree.topLevelItem(0)
        step_plugin = item.data(0, _PLUGIN_INSTANCE_ROLE)
        step_plugin.instance_name = "my_sensor"

        assert item.text(0) == f"my_sensor ({step_plugin.name})"

    def test_rename_to_unique_name_accepted(self, qapp):
        """Renaming a step to a name not used by any other step is accepted."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()

        steps = panel.sequence_steps
        steps[0].instance_name = "sensor_a"
        assert steps[0].instance_name == "sensor_a"

    def test_rename_to_existing_name_reverted(self, qapp, monkeypatch):
        """Renaming a step to a name already used by another step is rejected and reverted."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()

        steps = panel.sequence_steps
        name_before = steps[0].instance_name
        colliding_name = steps[1].instance_name

        # Suppress the QMessageBox so the test does not block.
        monkeypatch.setattr(
            "stoner_measurement.ui.dock_panel.QMessageBox.warning",
            lambda *args, **kwargs: None,
        )

        steps[0].instance_name = colliding_name  # attempt collision

        # The name must be reverted to the original value.
        assert steps[0].instance_name == name_before

    def test_name_edit_reverts_in_general_config_widget(self, qapp, monkeypatch):
        """The config-tab QLineEdit reflects the reverted name after a collision.

        :meth:`CommandPlugin.config_tabs` returns a single tab containing the
        instance-name editor at the top.  When a collision is detected and
        reverted, the instance_name_changed signal must update the QLineEdit.
        """
        from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand

        pm = PluginManager()
        pm.register("PlotTrace", PlotTraceCommand())
        panel = DockPanel(plugin_manager=pm)

        # Add two PlotTraceCommand steps.
        panel._plugin_list.select_plugin("PlotTrace")
        panel._add_step()
        panel._plugin_list.select_plugin("PlotTrace")
        panel._add_step()

        steps = panel.sequence_steps
        original_name = steps[0].instance_name
        colliding_name = steps[1].instance_name

        monkeypatch.setattr(
            "stoner_measurement.ui.dock_panel.QMessageBox.warning",
            lambda *args, **kwargs: None,
        )

        # Build the config widget so _sync_name_edit is wired up.
        tabs = steps[0].config_tabs()
        # Command plugins now have a single combined tab.
        combined_widget = tabs[0][1]
        name_edit = combined_widget.findChild(QLineEdit)
        assert name_edit is not None

        # Force collision â€” should revert and update the QLineEdit via the signal.
        steps[0].instance_name = colliding_name

        assert steps[0].instance_name == original_name
        assert name_edit.text() == original_name

    def test_step_plugin_instance_stored_in_role(self, qapp):
        """Each step stores its own independent plugin instance in _PLUGIN_INSTANCE_ROLE."""
        from stoner_measurement.ui.dock_panel import _PLUGIN_INSTANCE_ROLE
        pm = PluginManager()
        pm.register("ep_key", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("ep_key")
        panel._add_step()

        item = panel._sequence_tree.topLevelItem(0)
        step_plugin = item.data(0, _PLUGIN_INSTANCE_ROLE)
        # The step has its own DummyPlugin instance.
        assert isinstance(step_plugin, DummyPlugin)
        # sequence_steps returns the plugin instance.
        steps = panel.sequence_steps
        assert len(steps) == 1
        assert steps[0] is step_plugin

    def _find_item(self, panel: DockPanel, ep_name: str) -> QTreeWidgetItem:
        """Return the top-level tree item whose ep_name data matches *ep_name*."""
        from stoner_measurement.ui.dock_panel import _EP_NAME_ROLE
        tree = panel._sequence_tree
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.data(0, _EP_NAME_ROLE) == ep_name:
                return item
        raise KeyError(ep_name)

    def test_sequence_steps_nested_tuple_when_sub_step_present(self, qapp):
        """sequence_steps returns a (plugin, [sub_plugin]) tuple when a step has children."""
        pm = PluginManager()
        state_plugin = _FakeStatePlugin()
        trace_plugin = DummyPlugin()
        pm.register("state_scan", state_plugin)
        pm.register("trace", trace_plugin)
        panel = DockPanel(plugin_manager=pm)

        # Add both as top-level steps
        panel._plugin_list.select_plugin("state_scan")
        panel._add_step()
        panel._plugin_list.select_plugin("trace")
        panel._add_step()

        # Manually nest the trace item under the state item
        state_item = panel._sequence_tree.topLevelItem(0)
        trace_item = panel._sequence_tree.topLevelItem(1)
        panel._sequence_tree.takeTopLevelItem(1)
        state_item.addChild(trace_item)
        state_item.setExpanded(True)

        steps = panel.sequence_steps
        assert len(steps) == 1
        step_plugin, sub_steps = steps[0]
        assert isinstance(step_plugin, _FakeStatePlugin)
        assert len(sub_steps) == 1
        assert isinstance(sub_steps[0], DummyPlugin)

    def test_remove_sub_step(self, qapp):
        """Removing a sub-step removes only the child, leaving the parent intact."""
        pm = PluginManager()
        pm.register("state_scan", _FakeStatePlugin())
        pm.register("trace", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("state_scan")
        panel._add_step()
        panel._plugin_list.select_plugin("trace")
        panel._add_step()

        state_item = panel._sequence_tree.topLevelItem(0)
        trace_item = panel._sequence_tree.topLevelItem(1)
        panel._sequence_tree.takeTopLevelItem(1)
        state_item.addChild(trace_item)

        # Select and remove the sub-step
        panel._sequence_tree.setCurrentItem(trace_item)
        panel._remove_step()

        # Parent (state) still present, no children
        assert panel._sequence_tree.topLevelItemCount() == 1
        assert panel._sequence_tree.topLevelItem(0).childCount() == 0
        steps = panel.sequence_steps
        assert len(steps) == 1
        assert isinstance(steps[0], _FakeStatePlugin)

    def test_state_control_item_is_bold(self, qapp):
        """StateControlPlugin items are rendered with a bold font in the tree."""
        pm = PluginManager()
        pm.register("state_scan", _FakeStatePlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("state_scan")
        panel._add_step()

        item = panel._sequence_tree.topLevelItem(0)
        assert item.font(0).bold()

    def test_step_label_updates_on_rename_in_sub_step(self, qapp):
        """Renaming a step plugin's instance_name updates its label even when it is a sub-step."""
        from stoner_measurement.ui.dock_panel import _PLUGIN_INSTANCE_ROLE
        pm = PluginManager()
        pm.register("state_scan", _FakeStatePlugin())
        pm.register("trace", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("state_scan")
        panel._add_step()
        panel._plugin_list.select_plugin("trace")
        panel._add_step()

        state_item = panel._sequence_tree.topLevelItem(0)
        trace_item = panel._sequence_tree.topLevelItem(1)
        panel._sequence_tree.takeTopLevelItem(1)
        state_item.addChild(trace_item)

        # Rename the step's own plugin instance (not the registered plugin).
        step_trace_plugin = trace_item.data(0, _PLUGIN_INSTANCE_ROLE)
        step_trace_plugin.instance_name = "renamed_trace"

        assert trace_item.text(0) == f"renamed_trace ({step_trace_plugin.name})"

    # --- Multi-dimensional / nested state-control tests ---

    def test_state_control_nested_under_state_control(self, qapp):
        """A StateControlPlugin may be nested under another StateControlPlugin.

        This supports multi-dimensional scans, e.g. field inside temperature.
        sequence_steps returns a recursive tuple structure reflecting the nesting.
        """
        pm = PluginManager()
        pm.register("outer", _FakeStatePlugin())
        pm.register("inner", _FakeStatePlugin())
        pm.register("trace", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        # Add all three as top-level steps
        for ep_name in ("outer", "inner", "trace"):
            panel._plugin_list.select_plugin(ep_name)
            panel._add_step()

        # Locate items by ep_name (plugin_names is sorted, so positions may vary)
        outer_item = self._find_item(panel, "outer")
        inner_item = self._find_item(panel, "inner")
        trace_item = self._find_item(panel, "trace")

        # Nest inner state under outer state
        inner_idx = panel._sequence_tree.indexOfTopLevelItem(inner_item)
        panel._sequence_tree.takeTopLevelItem(inner_idx)
        outer_item.addChild(inner_item)
        outer_item.setExpanded(True)

        # Nest trace under inner state (second-level nesting)
        trace_idx = panel._sequence_tree.indexOfTopLevelItem(trace_item)
        panel._sequence_tree.takeTopLevelItem(trace_idx)
        inner_item.addChild(trace_item)
        inner_item.setExpanded(True)

        steps = panel.sequence_steps
        assert len(steps) == 1
        outer_plugin, outer_sub = steps[0]
        assert isinstance(outer_plugin, _FakeStatePlugin)
        assert len(outer_sub) == 1
        inner_plugin, inner_sub = outer_sub[0]
        assert isinstance(inner_plugin, _FakeStatePlugin)
        assert len(inner_sub) == 1
        assert isinstance(inner_sub[0], DummyPlugin)

    def test_remove_nested_state_control_removes_subtree(self, qapp):
        """Removing a nested StateControlPlugin also removes its own sub-steps."""
        pm = PluginManager()
        pm.register("outer", _FakeStatePlugin())
        pm.register("inner", _FakeStatePlugin())
        pm.register("trace", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        for ep_name in ("outer", "inner", "trace"):
            panel._plugin_list.select_plugin(ep_name)
            panel._add_step()

        outer_item = self._find_item(panel, "outer")
        inner_item = self._find_item(panel, "inner")
        trace_item = self._find_item(panel, "trace")

        inner_idx = panel._sequence_tree.indexOfTopLevelItem(inner_item)
        panel._sequence_tree.takeTopLevelItem(inner_idx)
        outer_item.addChild(inner_item)

        trace_idx = panel._sequence_tree.indexOfTopLevelItem(trace_item)
        panel._sequence_tree.takeTopLevelItem(trace_idx)
        inner_item.addChild(trace_item)

        # Remove the inner state-control item (which itself has a child)
        panel._sequence_tree.setCurrentItem(inner_item)
        panel._remove_step()

        # Only the outer state-control remains with no children
        assert panel._sequence_tree.topLevelItemCount() == 1
        steps = panel.sequence_steps
        assert len(steps) == 1
        assert isinstance(steps[0], _FakeStatePlugin)

    def test_multiple_instances_of_same_plugin_are_independent(self, qapp):
        """Adding the same plugin twice creates independent instances with separate configs."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        # Add the same plugin twice.
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()

        steps = panel.sequence_steps
        assert len(steps) == 2
        # Both steps are DummyPlugin instances.
        assert isinstance(steps[0], DummyPlugin)
        assert isinstance(steps[1], DummyPlugin)
        # They must be DIFFERENT instances.
        assert steps[0] is not steps[1]
        # They have different instance names.
        assert steps[0].instance_name != steps[1].instance_name

    def test_add_step_always_produces_unique_names(self, qapp):
        """Names generated by _add_step are always unique, even after manual renames."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        # Add first step and rename it so the default slot is occupied.
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()
        steps = panel.sequence_steps
        steps[0].instance_name = "my_sensor"

        # Adding a second step must not reuse "dummy" (now occupied by my_sensor
        # after initial rename) or clash with "my_sensor".
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()
        steps = panel.sequence_steps
        assert steps[0].instance_name != steps[1].instance_name

    def test_unique_step_name_increments_suffix(self, qapp):
        """_unique_step_name appends _2, _3 â€¦ until a free slot is found."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        # Add three Dummy steps (names: "dummy", "dummy_2", "dummy_3").
        for _ in range(3):
            panel._plugin_list.select_plugin("Dummy")
            panel._add_step()

        # The next unique name should be "dummy_4".
        assert panel._unique_step_name("dummy") == "dummy_4"

    def test_config_tab_isolation_between_multiple_instances(self, qapp):
        """Config tabs for two steps of the same type are independent widgets."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()

        steps = panel.sequence_steps
        # Each step's config_tabs() returns distinct widget objects.
        tabs0 = steps[0].config_tabs()
        tabs1 = steps[1].config_tabs()
        assert tabs0[0][1] is not tabs1[0][1]

    # --- Plugin-list drag-and-drop tests ---

    def test_plugin_list_is_plugin_tree_widget(self, plugin_manager):
        """DockPanel._plugin_list is a _PluginTreeWidget (drag-enabled)."""
        from qtpy.QtWidgets import QAbstractItemView

        from stoner_measurement.ui.dock_panel import _PluginTreeWidget

        panel = DockPanel(plugin_manager=plugin_manager)
        assert isinstance(panel._plugin_list, _PluginTreeWidget)
        assert panel._plugin_list.dragEnabled()
        assert (
            panel._plugin_list.dragDropMode()
            == QAbstractItemView.DragDropMode.DragOnly
        )

    def test_plugin_list_mime_data_includes_ep_name(self, plugin_manager):
        """_PluginTreeWidget.mimeData includes the custom MIME type with the ep name."""
        from stoner_measurement.ui.dock_panel import _EP_NAME_ROLE, _PLUGIN_EP_MIME_TYPE

        panel = DockPanel(plugin_manager=plugin_manager)
        # Get the "Dummy" leaf item under the first category.
        category = panel._plugin_list.topLevelItem(0)
        leaf = category.child(0)
        assert leaf.data(0, _EP_NAME_ROLE) == "Dummy"
        mime = panel._plugin_list.mimeData([leaf])
        assert mime.hasFormat(_PLUGIN_EP_MIME_TYPE)
        ep_name = bytes(mime.data(_PLUGIN_EP_MIME_TYPE)).decode()
        assert ep_name == "Dummy"

    def test_category_nodes_not_draggable(self, plugin_manager):
        """Category header nodes do not carry a drag-enabled flag."""
        from qtpy.QtCore import Qt

        panel = DockPanel(plugin_manager=plugin_manager)
        category = panel._plugin_list.topLevelItem(0)
        assert not (category.flags() & Qt.ItemFlag.ItemIsDragEnabled)

    def test_category_mime_data_excludes_ep_mime_type(self, plugin_manager):
        """mimeData for a category node does not include _PLUGIN_EP_MIME_TYPE."""
        from stoner_measurement.ui.dock_panel import _PLUGIN_EP_MIME_TYPE

        panel = DockPanel(plugin_manager=plugin_manager)
        category = panel._plugin_list.topLevelItem(0)
        mime = panel._plugin_list.mimeData([category])
        assert not mime.hasFormat(_PLUGIN_EP_MIME_TYPE)

    def test_add_step_ignores_category_node(self, plugin_manager):
        """Selecting a category node and clicking Add Step does not add a sequence step."""
        panel = DockPanel(plugin_manager=plugin_manager)
        category = panel._plugin_list.topLevelItem(0)
        panel._plugin_list.setCurrentItem(category)
        panel._add_step()
        assert panel.sequence_steps == []

    def test_make_new_step_item_returns_item(self, plugin_manager):
        """_make_new_step_item creates a QTreeWidgetItem for a valid ep_name."""
        from stoner_measurement.ui.dock_panel import _PLUGIN_INSTANCE_ROLE

        panel = DockPanel(plugin_manager=plugin_manager)
        item = panel._make_new_step_item("Dummy")
        assert item is not None
        step_plugin = item.data(0, _PLUGIN_INSTANCE_ROLE)
        assert isinstance(step_plugin, DummyPlugin)

    def test_make_new_step_item_returns_none_for_unknown(self, plugin_manager):
        """_make_new_step_item returns None for an unregistered entry-point name."""
        panel = DockPanel(plugin_manager=plugin_manager)
        assert panel._make_new_step_item("NoSuchPlugin") is None

    def test_make_new_step_item_assigns_unique_name(self, plugin_manager):
        """Each call to _make_new_step_item assigns a unique instance name."""
        panel = DockPanel(plugin_manager=plugin_manager)
        item1 = panel._make_new_step_item("Dummy")
        assert item1 is not None
        panel._sequence_tree.addTopLevelItem(item1)
        item2 = panel._make_new_step_item("Dummy")
        assert item2 is not None
        from stoner_measurement.ui.dock_panel import _PLUGIN_INSTANCE_ROLE

        plugin1 = item1.data(0, _PLUGIN_INSTANCE_ROLE)
        plugin2 = item2.data(0, _PLUGIN_INSTANCE_ROLE)
        assert plugin1.instance_name != plugin2.instance_name

    def test_sequence_tree_factory_wired(self, plugin_manager):
        """DockPanel wires _make_new_step_item as the tree's new-item factory."""
        panel = DockPanel(plugin_manager=plugin_manager)
        factory = panel._sequence_tree._new_item_factory
        assert getattr(factory, "__self__", None) is panel
        assert getattr(factory, "__func__", None) is panel._make_new_step_item.__func__

    def test_set_new_item_factory_can_be_replaced(self, plugin_manager):
        """set_new_item_factory replaces the factory callable."""

        def _null_factory(ep: str) -> None:
            return None

        panel = DockPanel(plugin_manager=plugin_manager)
        panel._sequence_tree.set_new_item_factory(_null_factory)
        assert panel._sequence_tree._new_item_factory is _null_factory

    def test_external_drop_appends_to_empty_tree(self, plugin_manager):
        """Dropping a plugin onto an empty tree adds a top-level step via the factory."""
        from qtpy.QtCore import QMimeData, QPointF, Qt
        from qtpy.QtGui import QDropEvent

        from stoner_measurement.ui.dock_panel import _PLUGIN_EP_MIME_TYPE

        panel = DockPanel(plugin_manager=plugin_manager)
        assert panel._sequence_tree.topLevelItemCount() == 0

        mime = QMimeData()
        mime.setData(_PLUGIN_EP_MIME_TYPE, b"Dummy")
        # Also add standard list MIME so Qt's internal canDrop returns True.
        mime.setData("application/x-qabstractitemmodeldatalist", b"")

        event = QDropEvent(
            QPointF(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        panel._sequence_tree._handle_external_plugin_drop(event)

        assert panel._sequence_tree.topLevelItemCount() == 1
        steps = panel.sequence_steps
        assert len(steps) == 1
        assert isinstance(steps[0], DummyPlugin)

    def test_external_drop_ignored_when_no_factory(self, plugin_manager):
        """_handle_external_plugin_drop ignores the event when no factory is set."""
        from qtpy.QtCore import QMimeData, QPointF, Qt
        from qtpy.QtGui import QDropEvent

        from stoner_measurement.ui.dock_panel import _PLUGIN_EP_MIME_TYPE

        panel = DockPanel(plugin_manager=plugin_manager)
        panel._sequence_tree.set_new_item_factory(None)

        mime = QMimeData()
        mime.setData(_PLUGIN_EP_MIME_TYPE, b"Dummy")

        event = QDropEvent(
            QPointF(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        panel._sequence_tree._handle_external_plugin_drop(event)

        assert panel._sequence_tree.topLevelItemCount() == 0

    def test_external_drop_ignored_for_unknown_ep_name(self, plugin_manager):
        """_handle_external_plugin_drop ignores the event for an unknown ep name."""
        from qtpy.QtCore import QMimeData, QPointF, Qt
        from qtpy.QtGui import QDropEvent

        from stoner_measurement.ui.dock_panel import _PLUGIN_EP_MIME_TYPE

        panel = DockPanel(plugin_manager=plugin_manager)

        mime = QMimeData()
        mime.setData(_PLUGIN_EP_MIME_TYPE, b"NoSuchPlugin")

        event = QDropEvent(
            QPointF(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        panel._sequence_tree._handle_external_plugin_drop(event)

        assert panel._sequence_tree.topLevelItemCount() == 0

    def test_external_drop_plugin_kept_alive(self, plugin_manager):
        """Plugins added via external drop are held in _step_plugins (not GC'd)."""
        from qtpy.QtCore import QMimeData, QPointF, Qt
        from qtpy.QtGui import QDropEvent

        from stoner_measurement.ui.dock_panel import _PLUGIN_EP_MIME_TYPE

        panel = DockPanel(plugin_manager=plugin_manager)

        mime = QMimeData()
        mime.setData(_PLUGIN_EP_MIME_TYPE, b"Dummy")

        event = QDropEvent(
            QPointF(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        panel._sequence_tree._handle_external_plugin_drop(event)

        assert len(panel._step_plugins) == 1
        assert isinstance(panel._step_plugins[0], DummyPlugin)

    # --- Keyboard navigation tests ---

    def _add_dummy_steps(self, panel: DockPanel, count: int) -> list:
        """Add *count* DummyPlugin steps to *panel* and return the top-level items.

        Args:
            panel (DockPanel):
                The dock panel to add steps to.
            count (int):
                Number of DummyPlugin steps to add.

        Returns:
            (list):
                List of the newly added top-level :class:`QTreeWidgetItem` objects.
        """
        for _ in range(count):
            panel._plugin_list.select_plugin("Dummy")
            panel._add_step()
        return [panel._sequence_tree.topLevelItem(i) for i in range(count)]

    def _send_key(self, tree, key, modifiers=None):
        """Simulate a key press on *tree*.

        Args:
            tree (_SequenceTreeWidget):
                The tree widget that receives the key event.
            key (Qt.Key):
                The key to press.

        Keyword Parameters:
            modifiers (Qt.KeyboardModifier | None):
                Keyboard modifiers to apply.  Defaults to
                :attr:`Qt.KeyboardModifier.ControlModifier`.
        """
        from qtpy.QtCore import Qt
        from qtpy.QtGui import QKeyEvent

        if modifiers is None:
            modifiers = Qt.KeyboardModifier.ControlModifier
        event = QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers)
        tree.keyPressEvent(event)

    def test_ctrl_up_moves_step_up(self, qapp):
        """Ctrl+Up moves the selected step up one position."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 3)

        # Select the second item (index 1) and move it up.
        panel._sequence_tree.setCurrentItem(items[1])
        items[1].setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Up)

        # items[1] should now be at index 0.
        assert panel._sequence_tree.indexOfTopLevelItem(items[1]) == 0
        assert panel._sequence_tree.indexOfTopLevelItem(items[0]) == 1

    def test_ctrl_up_noop_at_top(self, qapp):
        """Ctrl+Up does nothing when the selected step is already at the top."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 3)

        panel._sequence_tree.setCurrentItem(items[0])
        items[0].setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Up)

        assert panel._sequence_tree.indexOfTopLevelItem(items[0]) == 0

    def test_ctrl_down_moves_step_down(self, qapp):
        """Ctrl+Down moves the selected step down one position."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 3)

        panel._sequence_tree.setCurrentItem(items[1])
        items[1].setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Down)

        assert panel._sequence_tree.indexOfTopLevelItem(items[1]) == 2
        assert panel._sequence_tree.indexOfTopLevelItem(items[2]) == 1

    def test_ctrl_down_noop_at_bottom(self, qapp):
        """Ctrl+Down does nothing when the selected step is already at the bottom."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 3)

        panel._sequence_tree.setCurrentItem(items[2])
        items[2].setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Down)

        assert panel._sequence_tree.indexOfTopLevelItem(items[2]) == 2

    def test_ctrl_shift_up_moves_to_start(self, qapp):
        """Ctrl+Shift+Up moves the selected step to the start of the sequence."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 4)

        panel._sequence_tree.setCurrentItem(items[3])
        items[3].setSelected(True)
        self._send_key(
            panel._sequence_tree,
            Qt.Key.Key_Up,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )

        assert panel._sequence_tree.indexOfTopLevelItem(items[3]) == 0

    def test_ctrl_shift_down_moves_to_end(self, qapp):
        """Ctrl+Shift+Down moves the selected step to the end of the sequence."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 4)

        panel._sequence_tree.setCurrentItem(items[0])
        items[0].setSelected(True)
        self._send_key(
            panel._sequence_tree,
            Qt.Key.Key_Down,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )

        assert panel._sequence_tree.indexOfTopLevelItem(items[0]) == 3

    def test_ctrl_right_moves_into_sequence_above(self, qapp):
        """Ctrl+Right moves selected step into the sub-sequence of the SequencePlugin above."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("state_scan", _FakeStatePlugin())
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        # Add state (index 0) then dummy (index 1).
        panel._plugin_list.select_plugin("state_scan")
        panel._add_step()
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()

        dummy_item = panel._sequence_tree.topLevelItem(1)
        state_item = panel._sequence_tree.topLevelItem(0)
        panel._sequence_tree.setCurrentItem(dummy_item)
        dummy_item.setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Right)

        # dummy should now be a child of state.
        assert panel._sequence_tree.topLevelItemCount() == 1
        assert state_item.childCount() == 1
        assert state_item.child(0) is dummy_item

    def test_ctrl_right_noop_if_above_is_not_sequence(self, qapp):
        """Ctrl+Right does nothing when the item above is not a SequencePlugin."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 2)

        panel._sequence_tree.setCurrentItem(items[1])
        items[1].setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Right)

        # Nothing should have changed.
        assert panel._sequence_tree.topLevelItemCount() == 2

    def test_ctrl_right_noop_at_top(self, qapp):
        """Ctrl+Right does nothing when the selected step is the topmost item."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("state_scan", _FakeStatePlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("state_scan")
        panel._add_step()
        state_item = panel._sequence_tree.topLevelItem(0)
        state_item.setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Right)

        assert panel._sequence_tree.topLevelItemCount() == 1
        assert state_item.childCount() == 0

    def test_ctrl_left_promotes_step_out_of_subsequence(self, qapp):
        """Ctrl+Left moves selected step from a sub-sequence to the parent, after the container."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("state_scan", _FakeStatePlugin())
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("state_scan")
        panel._add_step()
        panel._plugin_list.select_plugin("Dummy")
        panel._add_step()

        state_item = panel._sequence_tree.topLevelItem(0)
        dummy_item = panel._sequence_tree.topLevelItem(1)
        # Nest dummy under state.
        panel._sequence_tree.takeTopLevelItem(1)
        state_item.addChild(dummy_item)

        # Promote dummy out of state.
        panel._sequence_tree.setCurrentItem(dummy_item)
        dummy_item.setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Left)

        # dummy should be back at the top level, after state.
        assert panel._sequence_tree.topLevelItemCount() == 2
        assert panel._sequence_tree.indexOfTopLevelItem(state_item) == 0
        assert panel._sequence_tree.indexOfTopLevelItem(dummy_item) == 1
        assert state_item.childCount() == 0

    def test_ctrl_left_noop_at_top_level(self, qapp):
        """Ctrl+Left does nothing when the selected step is already at the top level."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 2)

        panel._sequence_tree.setCurrentItem(items[0])
        items[0].setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Left)

        assert panel._sequence_tree.topLevelItemCount() == 2

    def test_ctrl_up_moves_multiple_steps_together(self, qapp):
        """Ctrl+Up moves a contiguous group of selected steps up as a unit."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 4)

        # Select items[1] and items[2] together.
        items[1].setSelected(True)
        items[2].setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Up)

        assert panel._sequence_tree.indexOfTopLevelItem(items[1]) == 0
        assert panel._sequence_tree.indexOfTopLevelItem(items[2]) == 1
        assert panel._sequence_tree.indexOfTopLevelItem(items[0]) == 2

    def test_ctrl_down_moves_multiple_steps_together(self, qapp):
        """Ctrl+Down moves a contiguous group of selected steps down as a unit."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 4)

        # Select items[1] and items[2] together.
        items[1].setSelected(True)
        items[2].setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Down)

        assert panel._sequence_tree.indexOfTopLevelItem(items[1]) == 2
        assert panel._sequence_tree.indexOfTopLevelItem(items[2]) == 3
        assert panel._sequence_tree.indexOfTopLevelItem(items[3]) == 1

    def test_ctrl_shift_up_multiple_steps(self, qapp):
        """Ctrl+Shift+Up moves a group of selected steps to the start preserving order."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 4)

        items[2].setSelected(True)
        items[3].setSelected(True)
        self._send_key(
            panel._sequence_tree,
            Qt.Key.Key_Up,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )

        assert panel._sequence_tree.indexOfTopLevelItem(items[2]) == 0
        assert panel._sequence_tree.indexOfTopLevelItem(items[3]) == 1

    def test_ctrl_shift_down_multiple_steps(self, qapp):
        """Ctrl+Shift+Down moves a group of selected steps to the end preserving order."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        items = self._add_dummy_steps(panel, 4)

        items[0].setSelected(True)
        items[1].setSelected(True)
        self._send_key(
            panel._sequence_tree,
            Qt.Key.Key_Down,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )

        assert panel._sequence_tree.indexOfTopLevelItem(items[0]) == 2
        assert panel._sequence_tree.indexOfTopLevelItem(items[1]) == 3

    def test_ctrl_right_multiple_steps_into_sequence(self, qapp):
        """Ctrl+Right moves multiple selected steps into the SequencePlugin above."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("state_scan", _FakeStatePlugin())
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("state_scan")
        panel._add_step()
        for _ in range(2):
            panel._plugin_list.select_plugin("Dummy")
            panel._add_step()

        state_item = panel._sequence_tree.topLevelItem(0)
        dummy0 = panel._sequence_tree.topLevelItem(1)
        dummy1 = panel._sequence_tree.topLevelItem(2)

        dummy0.setSelected(True)
        dummy1.setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Right)

        assert panel._sequence_tree.topLevelItemCount() == 1
        assert state_item.childCount() == 2

    def test_ctrl_left_multiple_steps_out_of_sequence(self, qapp):
        """Ctrl+Left promotes multiple sub-steps to the parent level after the container."""
        from qtpy.QtCore import Qt

        pm = PluginManager()
        pm.register("state_scan", _FakeStatePlugin())
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._plugin_list.select_plugin("state_scan")
        panel._add_step()
        for _ in range(2):
            panel._plugin_list.select_plugin("Dummy")
            panel._add_step()

        state_item = panel._sequence_tree.topLevelItem(0)
        dummy0 = panel._sequence_tree.topLevelItem(1)
        dummy1 = panel._sequence_tree.topLevelItem(2)

        panel._sequence_tree.takeTopLevelItem(2)
        panel._sequence_tree.takeTopLevelItem(1)
        state_item.addChild(dummy0)
        state_item.addChild(dummy1)

        dummy0.setSelected(True)
        dummy1.setSelected(True)
        self._send_key(panel._sequence_tree, Qt.Key.Key_Left)

        assert panel._sequence_tree.topLevelItemCount() == 3
        assert state_item.childCount() == 0
        assert panel._sequence_tree.indexOfTopLevelItem(state_item) == 0
        assert panel._sequence_tree.indexOfTopLevelItem(dummy0) == 1
        assert panel._sequence_tree.indexOfTopLevelItem(dummy1) == 2

    def test_non_ctrl_key_not_intercepted(self, qapp):
        """Non-Ctrl key presses are forwarded to the base class (not intercepted)."""
        from qtpy.QtCore import Qt
        from qtpy.QtGui import QKeyEvent

        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)
        self._add_dummy_steps(panel, 2)

        # Up arrow without Ctrl should not move anything.
        items_before = [
            panel._sequence_tree.topLevelItem(i) for i in range(2)
        ]
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
        panel._sequence_tree.keyPressEvent(event)

        assert panel._sequence_tree.topLevelItem(0) is items_before[0]
        assert panel._sequence_tree.topLevelItem(1) is items_before[1]
        from stoner_measurement.ui.dock_panel import _SequenceTreeWidget

        pm = PluginManager()
        tree = _SequenceTreeWidget(plugin_manager=pm)

        parent_item = QTreeWidgetItem(["parent"])
        child_item = QTreeWidgetItem(["child"])
        unrelated_item = QTreeWidgetItem(["unrelated"])
        tree.addTopLevelItem(parent_item)
        parent_item.addChild(child_item)
        tree.addTopLevelItem(unrelated_item)

        assert tree._is_ancestor(parent_item, child_item)
        assert tree._is_ancestor(child_item, child_item)  # item is its own ancestor
        assert not tree._is_ancestor(child_item, parent_item)
        assert not tree._is_ancestor(unrelated_item, child_item)
