"""Tests for the main UI components."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QTreeWidgetItem

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.core.runner import SequenceRunner
from stoner_measurement.plugins.base_plugin import _ABCQObjectMeta
from stoner_measurement.plugins.dummy import DummyPlugin
from stoner_measurement.plugins.state_control import StateControlPlugin
from stoner_measurement.ui.config_panel import ConfigPanel
from stoner_measurement.ui.dock_panel import DockPanel
from stoner_measurement.ui.main_window import MainWindow
from stoner_measurement.ui.plot_widget import PlotWidget


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

    def test_instrument_list_populated(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        assert panel._instrument_list.count() == 1
        assert panel._instrument_list.item(0).text() == "Dummy"

    def test_sequence_steps_empty_initially(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        assert panel.sequence_steps == []

    def test_add_step(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        panel._instrument_list.setCurrentRow(0)
        panel._add_step()
        assert panel.sequence_steps == ["Dummy"]

    def test_remove_step(self, plugin_manager):
        panel = DockPanel(plugin_manager=plugin_manager)
        panel._instrument_list.setCurrentRow(0)
        panel._add_step()
        panel._sequence_tree.setCurrentItem(panel._sequence_tree.topLevelItem(0))
        panel._remove_step()
        assert panel.sequence_steps == []

    def test_refresh_on_plugin_registration(self, qapp):
        pm = PluginManager()
        panel = DockPanel(plugin_manager=pm)
        assert panel._instrument_list.count() == 0

        pm.register("Dummy", DummyPlugin())
        assert panel._instrument_list.count() == 1

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
        """Selecting a sequence step emits plugin_selected with the plugin instance."""
        pm = PluginManager()
        plugin = DummyPlugin()
        pm.register("Dummy", plugin)
        panel = DockPanel(plugin_manager=pm)

        received = []
        panel.plugin_selected.connect(lambda p: received.append(p))

        panel._instrument_list.setCurrentRow(0)
        panel._add_step()
        panel._sequence_tree.setCurrentItem(panel._sequence_tree.topLevelItem(0))

        assert len(received) == 1
        assert received[0] is plugin

    def test_plugin_selected_emits_none_when_selection_cleared(self, qapp):
        """Clearing the sequence tree current item emits plugin_selected(None)."""
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._instrument_list.setCurrentRow(0)
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
        plugin = DummyPlugin()
        pm.register("Dummy", plugin)
        panel = DockPanel(plugin_manager=pm)

        panel._instrument_list.setCurrentRow(0)
        panel._add_step()

        item = panel._sequence_tree.topLevelItem(0)
        assert item.text(0) == f"{plugin.instance_name} ({plugin.name})"

    def test_step_label_updates_on_rename(self, qapp):
        """Renaming a plugin's instance_name updates matching step labels."""
        pm = PluginManager()
        plugin = DummyPlugin()
        pm.register("Dummy", plugin)
        panel = DockPanel(plugin_manager=pm)

        panel._instrument_list.setCurrentRow(0)
        panel._add_step()

        plugin.instance_name = "my_sensor"

        item = panel._sequence_tree.topLevelItem(0)
        assert item.text(0) == f"my_sensor ({plugin.name})"

    def test_step_ep_name_preserved_in_user_role(self, qapp):
        """The ep_name is stored in UserRole data, not the display text."""
        pm = PluginManager()
        plugin = DummyPlugin()
        pm.register("ep_key", plugin)
        panel = DockPanel(plugin_manager=pm)

        panel._instrument_list.setCurrentRow(0)
        panel._add_step()

        item = panel._sequence_tree.topLevelItem(0)
        assert item.data(0, Qt.ItemDataRole.UserRole) == "ep_key"
        assert panel.sequence_steps == ["ep_key"]

    # --- Sub-step / nesting tests ---

    def _find_item(self, panel: DockPanel, ep_name: str) -> QTreeWidgetItem:
        """Return the top-level tree item whose ep_name data matches *ep_name*."""
        tree = panel._sequence_tree
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == ep_name:
                return item
        raise KeyError(ep_name)

    def test_sequence_steps_nested_tuple_when_sub_step_present(self, qapp):
        """sequence_steps returns a (ep_name, [sub_ep]) tuple when a step has children."""
        pm = PluginManager()
        state_plugin = _FakeStatePlugin()
        trace_plugin = DummyPlugin()
        pm.register("state", state_plugin)
        pm.register("trace", trace_plugin)
        panel = DockPanel(plugin_manager=pm)

        # Add both as top-level steps
        panel._instrument_list.setCurrentRow(0)
        panel._add_step()
        panel._instrument_list.setCurrentRow(1)
        panel._add_step()

        # Manually nest the trace item under the state item
        state_item = panel._sequence_tree.topLevelItem(0)
        trace_item = panel._sequence_tree.topLevelItem(1)
        panel._sequence_tree.takeTopLevelItem(1)
        state_item.addChild(trace_item)
        state_item.setExpanded(True)

        steps = panel.sequence_steps
        assert len(steps) == 1
        ep_name, sub_steps = steps[0]
        assert ep_name == "state"
        assert sub_steps == ["trace"]

    def test_remove_sub_step(self, qapp):
        """Removing a sub-step removes only the child, leaving the parent intact."""
        pm = PluginManager()
        pm.register("state", _FakeStatePlugin())
        pm.register("trace", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._instrument_list.setCurrentRow(0)
        panel._add_step()
        panel._instrument_list.setCurrentRow(1)
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
        assert panel.sequence_steps == ["state"]

    def test_state_control_item_is_bold(self, qapp):
        """StateControlPlugin items are rendered with a bold font in the tree."""
        pm = PluginManager()
        pm.register("state", _FakeStatePlugin())
        panel = DockPanel(plugin_manager=pm)

        panel._instrument_list.setCurrentRow(0)
        panel._add_step()

        item = panel._sequence_tree.topLevelItem(0)
        assert item.font(0).bold()

    def test_step_label_updates_on_rename_in_sub_step(self, qapp):
        """Renaming a plugin updates its label even when it is a sub-step."""
        pm = PluginManager()
        pm.register("state", _FakeStatePlugin())
        trace_plugin = DummyPlugin()
        pm.register("trace", trace_plugin)
        panel = DockPanel(plugin_manager=pm)

        panel._instrument_list.setCurrentRow(0)
        panel._add_step()
        panel._instrument_list.setCurrentRow(1)
        panel._add_step()

        state_item = panel._sequence_tree.topLevelItem(0)
        trace_item = panel._sequence_tree.topLevelItem(1)
        panel._sequence_tree.takeTopLevelItem(1)
        state_item.addChild(trace_item)

        trace_plugin.instance_name = "renamed_trace"

        assert trace_item.text(0) == f"renamed_trace ({trace_plugin.name})"

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
        for row in range(3):
            panel._instrument_list.setCurrentRow(row)
            panel._add_step()

        # Locate items by ep_name (plugin_names is sorted, so positions may vary)
        outer_item = self._find_item(panel, "outer")
        inner_item = self._find_item(panel, "inner")
        trace_item = self._find_item(panel, "trace")

        # Nest inner state under outer state
        outer_idx = panel._sequence_tree.indexOfTopLevelItem(inner_item)
        panel._sequence_tree.takeTopLevelItem(outer_idx)
        outer_item.addChild(inner_item)
        outer_item.setExpanded(True)

        # Nest trace under inner state (second-level nesting)
        trace_idx = panel._sequence_tree.indexOfTopLevelItem(trace_item)
        panel._sequence_tree.takeTopLevelItem(trace_idx)
        inner_item.addChild(trace_item)
        inner_item.setExpanded(True)

        steps = panel.sequence_steps
        assert len(steps) == 1
        outer_ep, outer_sub = steps[0]
        assert outer_ep == "outer"
        assert len(outer_sub) == 1
        inner_ep, inner_sub = outer_sub[0]
        assert inner_ep == "inner"
        assert inner_sub == ["trace"]

    def test_remove_nested_state_control_removes_subtree(self, qapp):
        """Removing a nested StateControlPlugin also removes its own sub-steps."""
        pm = PluginManager()
        pm.register("outer", _FakeStatePlugin())
        pm.register("inner", _FakeStatePlugin())
        pm.register("trace", DummyPlugin())
        panel = DockPanel(plugin_manager=pm)

        for row in range(3):
            panel._instrument_list.setCurrentRow(row)
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
        assert panel._sequence_tree.topLevelItem(0).childCount() == 0
        assert panel.sequence_steps == ["outer"]

    def test_is_ancestor_helper(self, qapp):
        """_SequenceTreeWidget._is_ancestor returns correct values for parent/child/unrelated."""
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


class TestPlotWidget:
    def test_creates_widget(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget is not None

    def test_initial_data_empty(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget.x_data() == []
        assert widget.y_data() == []

    def test_append_point(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("sig", 1.0, 2.0)
        assert widget.x_data("sig") == [1.0]
        assert widget.y_data("sig") == [2.0]

    def test_append_point_multiple_traces(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("a", 1.0, 10.0)
        widget.append_point("b", 2.0, 20.0)
        assert widget.x_data("a") == [1.0]
        assert widget.x_data("b") == [2.0]
        assert sorted(widget.trace_names) == ["a", "b"]

    def test_set_trace(self, runner):
        widget = PlotWidget(runner=runner)
        widget.set_trace("sig", [0.0, 1.0, 2.0], [3.0, 4.0, 5.0])
        assert widget.x_data("sig") == [0.0, 1.0, 2.0]
        assert widget.y_data("sig") == [3.0, 4.0, 5.0]

    def test_set_trace_replaces_data(self, runner):
        widget = PlotWidget(runner=runner)
        widget.set_trace("sig", [0.0, 1.0], [2.0, 3.0])
        widget.set_trace("sig", [10.0], [20.0])
        assert widget.x_data("sig") == [10.0]
        assert widget.y_data("sig") == [20.0]

    def test_remove_trace(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("sig", 1.0, 2.0)
        widget.remove_trace("sig")
        assert "sig" not in widget.trace_names
        assert widget.x_data("sig") == []

    def test_remove_trace_missing_noop(self, runner):
        widget = PlotWidget(runner=runner)
        widget.remove_trace("nonexistent")  # should not raise

    def test_clear_all(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("a", 1.0, 2.0)
        widget.append_point("b", 3.0, 4.0)
        widget.clear_all()
        assert widget.trace_names == []

    def test_clear_data_deprecated(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("default", 1.0, 2.0)
        with pytest.warns(DeprecationWarning):
            widget.clear_data()
        assert widget.trace_names == []

    def test_append_data_deprecated(self, runner):
        widget = PlotWidget(runner=runner)
        with pytest.warns(DeprecationWarning):
            widget.append_data(1.0, 2.0)
        assert widget.x_data("default") == [1.0]

    def test_pg_widget_exists(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget.pg_widget is not None

    def test_default_axis_names(self, runner):
        widget = PlotWidget(runner=runner)
        assert "left" in widget.axis_names
        assert "bottom" in widget.axis_names

    def test_add_y_axis(self, runner):
        widget = PlotWidget(runner=runner)
        widget.add_y_axis("temperature", "Temperature (K)", side="right")
        assert "temperature" in widget.axis_names

    def test_add_y_axis_duplicate_noop(self, runner):
        widget = PlotWidget(runner=runner)
        widget.add_y_axis("temp", "Temp", side="right")
        widget.add_y_axis("temp", "Other", side="right")  # should not raise
        assert widget.axis_names.count("temp") == 1

    def test_add_x_axis(self, runner):
        widget = PlotWidget(runner=runner)
        widget.add_x_axis("freq", "Frequency (Hz)", position="top")
        assert "freq" in widget.axis_names

    def test_assign_trace_axes(self, runner):
        widget = PlotWidget(runner=runner)
        widget.add_y_axis("temp", "Temperature (K)")
        widget.append_point("sig", 0.0, 300.0)
        widget.assign_trace_axes("sig", y_axis="temp")
        assert widget._trace_axes["sig"] == ("bottom", "temp")

    def test_assign_trace_axes_unknown_trace_raises(self, runner):
        widget = PlotWidget(runner=runner)
        with pytest.raises(KeyError, match="unknown"):
            widget.assign_trace_axes("unknown", y_axis="left")

    def test_assign_trace_axes_unknown_axis_raises(self, runner):
        widget = PlotWidget(runner=runner)
        widget.append_point("sig", 0.0, 1.0)
        with pytest.raises(KeyError, match="no_such"):
            widget.assign_trace_axes("sig", y_axis="no_such")

    def test_x_data_unknown_trace_returns_empty(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget.x_data("nonexistent") == []

    def test_y_data_unknown_trace_returns_empty(self, runner):
        widget = PlotWidget(runner=runner)
        assert widget.y_data("nonexistent") == []


class TestConfigPanel:
    def test_creates_widget(self, plugin_manager):
        panel = ConfigPanel(plugin_manager=plugin_manager)
        assert panel is not None

    def test_tabs_empty_initially(self, qapp):
        """No tabs shown until show_plugin() is called."""
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        assert panel.tabs.count() == 0

    def test_show_plugin_displays_tabs(self, plugin_manager):
        """show_plugin() populates the tab widget with the plugin's tabs."""
        panel = ConfigPanel(plugin_manager=plugin_manager)
        plugin = DummyPlugin()
        panel.show_plugin(plugin)
        assert panel.tabs.count() == 3
        assert panel.tabs.tabText(0) == "Dummy \u2013 Scan"
        assert panel.tabs.tabText(1) == "Dummy \u2013 Settings"
        assert panel.tabs.tabText(2) == "Dummy \u2013 About"

    def test_show_plugin_none_clears_tabs(self, plugin_manager):
        panel = ConfigPanel(plugin_manager=plugin_manager)
        plugin = DummyPlugin()
        panel.show_plugin(plugin)
        panel.show_plugin(None)
        assert panel.tabs.count() == 0

    def test_show_plugin_replaces_previous_plugin_tabs(self, qapp):
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        plugin_a = DummyPlugin()
        plugin_b = DummyPlugin()
        panel.show_plugin(plugin_a)
        first_count = panel.tabs.count()
        panel.show_plugin(plugin_b)
        assert panel.tabs.count() == first_count  # same type, same count
        # Widgets belong to plugin_b (different cache)
        assert panel.tabs.widget(0) is plugin_b.config_tabs()[0][1]

    def test_show_plugin_caches_widgets(self, qapp):
        """Tabs are cached on the plugin; re-showing reuses the same widgets."""
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        plugin = DummyPlugin()
        panel.show_plugin(plugin)
        first_widget = panel.tabs.widget(0)
        panel.show_plugin(None)
        panel.show_plugin(plugin)
        assert panel.tabs.widget(0) is first_widget

    def test_sync_clears_tabs_on_plugin_removal(self, qapp):
        pm = PluginManager()
        pm.register("Dummy", DummyPlugin())
        panel = ConfigPanel(plugin_manager=pm)
        plugin = pm.plugins["Dummy"]
        panel.show_plugin(plugin)
        assert panel.tabs.count() == 3

        pm.unregister("Dummy")
        assert panel.tabs.count() == 0

    def test_sync_leaves_other_plugin_intact(self, qapp):
        """Removing an unrelated plugin does not clear the current plugin's tabs."""
        pm = PluginManager()
        plugin_a = DummyPlugin()
        plugin_b = DummyPlugin()
        pm.register("A", plugin_a)
        pm.register("B", plugin_b)
        panel = ConfigPanel(plugin_manager=pm)
        panel.show_plugin(plugin_a)
        assert panel.tabs.count() == 3

        pm.unregister("B")
        assert panel.tabs.count() == 3  # plugin_a tabs unaffected

    def test_show_placeholder(self, qapp):
        pm = PluginManager()
        panel = ConfigPanel(plugin_manager=pm)
        panel.show_placeholder()
        assert panel.tabs.count() == 1


class TestMainWindow:
    def test_creates_window(self, plugin_manager, runner):
        window = MainWindow(plugin_manager=plugin_manager, runner=runner)
        assert window is not None

    def test_has_three_panels(self, plugin_manager, runner):
        window = MainWindow(plugin_manager=plugin_manager, runner=runner)
        assert window.dock_panel is not None
        assert window.plot_widget is not None
        assert window.config_panel is not None
