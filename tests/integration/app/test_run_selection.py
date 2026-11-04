"""One-off sequence selections use normal generation without replacing scripts."""

import pytest
from qtpy.QtCore import QPoint, Qt
from qtpy.QtWidgets import QMenu

from stoner_measurement.plugins.command import WaitCommand
from stoner_measurement.plugins.sequence import RunSequentiallyPlugin


def _step(name):
    plugin = WaitCommand()
    plugin.instance_name = name
    return plugin


def test_selection_runs_complete_subtrees_once_in_tree_order(
    managed_measurement_app, monkeypatch, qtbot
):
    app = managed_measurement_app()
    dock = app._main_window.dock_panel
    first, child, nested, last, omitted = [
        _step(name) for name in ("first", "child", "nested", "last", "omitted")
    ]
    parent = RunSequentiallyPlugin()
    inner = RunSequentiallyPlugin()
    inner.instance_name = "inner"
    dock.load_sequence([first, (parent, [child, (inner, [nested])]), omitted, last])
    calls = []
    for plugin in (first, child, nested, last, omitted):
        monkeypatch.setattr(
            plugin, "execute", lambda p=plugin, **_kw: calls.append(p.instance_name)
        )
    tree = dock._sequence_tree
    tree.clearSelection()
    # Select in reverse order, including a descendant of the selected parent.
    for item in (
        tree.topLevelItem(3),
        tree.topLevelItem(1).child(1).child(0),
        tree.topLevelItem(1),
        tree.topLevelItem(0),
    ):
        item.setSelected(True)
    script_tab = app._main_window.script_tab
    original = script_tab.current_pane()
    original.editor.set_text("# existing user script")
    original_text = original.editor.text()
    sequence_before = app._current_sequence_data()
    errors = []
    app._engine.error_output.connect(errors.append)
    with qtbot.waitSignal(
        app._engine.status_changed,
        timeout=10000,
        check_params_cb=lambda s: s in {"Idle", "Error", "Stopped"},
    ):
        dock.run_selection_requested.emit()
    assert not errors
    qtbot.waitUntil(lambda: app._selection_script_pane is None)

    assert calls == ["first", "child", "nested", "last"]
    assert script_tab._script_tabs.count() == 1
    assert script_tab.current_pane() is original
    assert original.editor.text() == original_text
    assert original.dirty
    assert app._current_sequence_data() == sequence_before
    assert app._main_window.tabs.currentIndex() == app._TAB_MEASUREMENT


def test_selected_child_runs_without_unselected_parent_or_siblings(
    managed_measurement_app, monkeypatch, qtbot
):
    app = managed_measurement_app()
    dock = app._main_window.dock_panel
    parent = RunSequentiallyPlugin()
    child, sibling = _step("child"), _step("sibling")
    dock.load_sequence([(parent, [child, sibling])])
    calls = []
    monkeypatch.setattr(parent, "execute", lambda *_args: pytest.fail("parent executed"))
    monkeypatch.setattr(child, "execute", lambda **_kw: calls.append("child"))
    monkeypatch.setattr(sibling, "execute", lambda **_kw: pytest.fail("sibling executed"))
    dock._sequence_tree.clearSelection()
    dock._sequence_tree.topLevelItem(0).child(0).setSelected(True)
    errors = []
    app._engine.error_output.connect(errors.append)
    with qtbot.waitSignal(
        app._engine.status_changed,
        timeout=10000,
        check_params_cb=lambda s: s in {"Idle", "Error", "Stopped"},
    ):
        app._on_run_selection()
    assert not errors
    assert calls == ["child"]


def test_failed_selection_kept_after_later_success(managed_measurement_app, monkeypatch, qtbot):
    app = managed_measurement_app()
    dock = app._main_window.dock_panel
    plugin = _step("failure")
    dock.load_sequence([plugin])
    dock._sequence_tree.selectAll()

    def fail(**_kw):
        raise RuntimeError("selection failure")

    monkeypatch.setattr(plugin, "execute", fail)
    errors = []
    app._engine.error_output.connect(errors.append)
    with qtbot.waitSignal(app._engine.status_changed, check_params_cb=lambda s: s == "Error"):
        app._on_run_selection()
    script_tab = app._main_window.script_tab
    failed_pane = script_tab.current_pane()
    failed_text = failed_pane.editor.text()
    assert failed_text
    assert any("selection failure" in message for message in errors)
    assert app._selection_script_pane is None
    with qtbot.waitSignal(app._engine.script_finished):
        app._engine.run_script("pass")
    assert script_tab.current_pane() is failed_pane
    assert failed_pane.editor.text() == failed_text


@pytest.mark.parametrize("outcome", ["success", "Stopped", "Error", "edited", "saved", "closed"])
def test_temporary_script_lifecycle(managed_measurement_app, monkeypatch, tmp_path, outcome):
    app = managed_measurement_app()
    dock = app._main_window.dock_panel
    dock.load_sequence([_step("selected")])
    dock._sequence_tree.selectAll()
    submitted = []
    monkeypatch.setattr(app._engine, "run_script", lambda *a, **kw: submitted.append((a, kw)))
    app._on_run_selection()
    pane = app._selection_script_pane
    assert pane is not None
    app._on_run_selection()  # A second click before the worker starts is ignored.
    assert len(submitted) == 1
    tabs = app._main_window.script_tab
    if outcome in {"Stopped", "Error"}:
        app._engine.status_changed.emit(outcome)
    elif outcome == "edited":
        pane.editor.set_text("# keep my edits")
    elif outcome == "saved":
        pane.path = tmp_path / "saved.py"
    elif outcome == "closed":
        tabs.close_current_tab()
    # Completion must affect only the original temporary pane, even if another
    # tab is now active or the selection was stopped before a later run.
    other = tabs.add_tab("# other script")
    app._engine.script_finished.emit()
    assert tabs.current_pane() is other
    assert (tabs._find_pane_index(pane) >= 0) == (outcome not in {"success", "closed"})


def test_empty_selection_and_context_menu(managed_measurement_app, monkeypatch, qapp, qtbot):
    app = managed_measurement_app()
    dock = app._main_window.dock_panel
    dock.load_sequence([_step("selected")])
    dock._sequence_tree.clearSelection()
    submissions = []
    monkeypatch.setattr(app._engine, "run_script", lambda *a, **kw: submissions.append(a))
    app._on_run_selection()
    assert not submissions
    menus = []
    qapp.clipboard().setText("unrelated clipboard text")

    def inspect_menu(menu, *_args):
        action = next(a for a in menu.actions() if a.text() == "Run Selection...")
        menus.append(action.isEnabled())
        if action.isEnabled():
            action.trigger()

    monkeypatch.setattr(QMenu, "exec", inspect_menu)
    dock._show_sequence_context_menu(QPoint(-1, -1))
    dock._sequence_tree.selectAll()
    dock._show_sequence_context_menu(QPoint(-1, -1))
    assert menus == [False, True]
    assert len(submissions) == 1
    assert dock._act_run_selection.shortcut().toString() == "Shift+F5"
    app._engine.status_changed.emit("Stopped")
    app.show()
    app.activateWindow()
    dock._sequence_tree.setFocus()
    qtbot.waitUntil(dock._sequence_tree.hasFocus)
    qtbot.keyClick(dock._sequence_tree, Qt.Key.Key_F5, Qt.KeyboardModifier.ShiftModifier)
    # Offscreen Qt can retain the synthetic modifier after shortcut dispatch;
    # release it so later table selections do not inherit Shift.
    qtbot.keyRelease(dock._sequence_tree, Qt.Key.Key_Shift)
    assert len(submissions) == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
