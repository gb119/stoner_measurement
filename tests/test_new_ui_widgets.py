"""Tests for the new UI widgets: EditorWidget, ConsoleWidget, ScriptTab."""

from __future__ import annotations

from stoner_measurement.app import MeasurementApp
from stoner_measurement.ui.console_widget import ConsoleWidget
from stoner_measurement.ui.editor_widget import EditorWidget, PythonHighlighter
from stoner_measurement.ui.script_tab import ScriptTab


class TestEditorWidget:
    def test_creates_widget(self, qapp):
        editor = EditorWidget()
        assert editor is not None

    def test_initial_text_empty(self, qapp):
        editor = EditorWidget()
        assert editor.text() == ""

    def test_set_and_get_text(self, qapp):
        editor = EditorWidget()
        editor.set_text("x = 1")
        assert editor.text() == "x = 1"

    def test_highlighter_attached(self, qapp):
        editor = EditorWidget()
        assert isinstance(editor.highlighter, PythonHighlighter)
        assert editor.highlighter.document() is editor.document()

    def test_line_number_area_width_positive(self, qapp):
        editor = EditorWidget()
        editor.set_text("line1\nline2\nline3")
        assert editor.line_number_area_width() > 0

    def test_tab_inserts_spaces(self, qapp):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent

        editor = EditorWidget()
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Tab,
            Qt.KeyboardModifier.NoModifier,
        )
        editor.keyPressEvent(event)
        assert editor.text() == "    "


class TestPythonHighlighter:
    def test_creates_highlighter(self, qapp):
        editor = EditorWidget()
        hl = PythonHighlighter(editor.document())
        assert hl is not None

    def test_rules_non_empty(self, qapp):
        editor = EditorWidget()
        hl = PythonHighlighter(editor.document())
        assert len(hl._rules) > 0


class TestConsoleWidget:
    def test_creates_widget(self, qapp):
        console = ConsoleWidget()
        assert console is not None

    def test_write_appends_text(self, qapp):
        console = ConsoleWidget()
        console.write("hello world")
        assert "hello world" in console._output.toPlainText()

    def test_write_error_appends_text(self, qapp):
        console = ConsoleWidget()
        console.write_error("something broke")
        assert "something broke" in console._output.toPlainText()

    def test_write_output_appends_raw_text(self, qapp):
        console = ConsoleWidget()
        console.write_output("raw line")
        assert "raw line" in console._output.toPlainText()

    def test_clear_empties_output(self, qapp):
        console = ConsoleWidget()
        console.write("some message")
        console.clear()
        assert console._output.toPlainText() == ""

    def test_history_navigation(self, qapp):
        console = ConsoleWidget()
        console._history = ["cmd1", "cmd2"]
        console._history_pos = len(console._history)

        console._history_up()
        assert console._input.text() == "cmd2"

        console._history_up()
        assert console._input.text() == "cmd1"

        console._history_down()
        assert console._input.text() == "cmd2"

    def test_submit_echoes_command(self, qapp):
        console = ConsoleWidget()
        console._input.setText("1 + 1")
        console._submit()
        assert ">>> 1 + 1" in console._output.toPlainText()

    def test_submit_evaluates_expression(self, qapp):
        console = ConsoleWidget()
        console._input.setText("2 + 2")
        console._submit()
        assert "4" in console._output.toPlainText()

    def test_submit_adds_to_history(self, qapp):
        console = ConsoleWidget()
        console._input.setText("my_command")
        console._submit()
        assert "my_command" in console._history


class TestScriptTab:
    def test_creates_widget(self, qapp):
        tab = ScriptTab()
        assert tab is not None

    def test_initial_text_empty(self, qapp):
        tab = ScriptTab()
        assert tab.text == ""

    def test_set_and_get_text(self, qapp):
        tab = ScriptTab()
        tab.set_text("# sequence")
        assert tab.text == "# sequence"

    def test_has_editor(self, qapp):
        tab = ScriptTab()
        assert isinstance(tab.editor, EditorWidget)

    def test_has_console(self, qapp):
        tab = ScriptTab()
        assert isinstance(tab.console, ConsoleWidget)

    def test_new_tab_increments_count(self, qapp):
        tab = ScriptTab()
        initial = tab._script_tabs.count()
        tab.new_tab()
        assert tab._script_tabs.count() == initial + 1

    def test_add_tab_sets_text_and_customised(self, qapp):
        tab = ScriptTab()
        pane = tab.add_tab("x = 1", customised=True)
        assert pane.editor.text() == "x = 1"
        assert pane.customised is True
        assert pane.dirty is False

    def test_dirty_flag_set_on_edit(self, qapp):
        tab = ScriptTab()
        pane = tab.current_pane()
        assert pane is not None
        assert pane.dirty is False
        pane.editor.insertPlainText("# edit")
        assert pane.dirty is True

    def test_customised_flag_set_on_edit(self, qapp):
        tab = ScriptTab()
        pane = tab.current_pane()
        assert pane is not None
        assert pane.customised is False
        pane.editor.insertPlainText("# edit")
        assert pane.customised is True

    def test_mark_clean_clears_dirty(self, qapp):
        tab = ScriptTab()
        pane = tab.current_pane()
        assert pane is not None
        pane.editor.insertPlainText("# edit")
        assert pane.dirty is True
        pane.mark_clean()
        assert pane.dirty is False

    def test_mark_clean_does_not_clear_customised(self, qapp):
        tab = ScriptTab()
        pane = tab.current_pane()
        assert pane is not None
        pane.editor.insertPlainText("# edit")
        assert pane.customised is True
        pane.mark_clean()
        assert pane.customised is True

    def test_set_text_does_not_set_dirty(self, qapp):
        tab = ScriptTab()
        pane = tab.current_pane()
        assert pane is not None
        tab.set_text("x = 99")
        assert pane.dirty is False

    def test_set_text_clears_customised(self, qapp):
        tab = ScriptTab()
        pane = tab.current_pane()
        assert pane is not None
        pane.editor.insertPlainText("# edit")
        assert pane.customised is True
        pane.set_text("x = 0")
        assert pane.customised is False

    def test_tab_title_shows_dirty_marker(self, qapp):
        tab = ScriptTab()
        pane = tab.current_pane()
        assert pane is not None
        clean_title = pane.tab_title()
        pane.editor.insertPlainText("# edit")
        assert pane.tab_title() == f"{clean_title} *"

    def test_close_last_tab_resets_not_removes(self, qapp):
        tab = ScriptTab()
        assert tab._script_tabs.count() == 1
        tab.set_text("some text")
        tab._on_close_tab(0)
        # Still one tab, but now empty
        assert tab._script_tabs.count() == 1
        assert tab.text == ""


class TestMeasurementApp:
    def test_has_menu_bar(self, qapp):
        app = MeasurementApp()
        mb = app.menuBar()
        assert mb is not None
        titles = [mb.actions()[i].text() for i in range(len(mb.actions()))]
        assert any("File" in t for t in titles)
        assert any("Sequence" in t for t in titles)
        assert any("View" in t for t in titles)
        assert any("Help" in t for t in titles)
        app._engine.shutdown()

    def test_has_toolbar(self, qapp):
        from PyQt6.QtWidgets import QToolBar
        app = MeasurementApp()
        toolbars = app.findChildren(QToolBar)
        assert len(toolbars) >= 1
        app._engine.shutdown()

    def test_has_status_bar(self, qapp):
        app = MeasurementApp()
        assert app.statusBar() is not None
        app._engine.shutdown()

    def test_central_widget_has_tabs(self, qapp):
        app = MeasurementApp()
        from PyQt6.QtWidgets import QTabWidget
        tabs = app._main_window.tabs
        assert isinstance(tabs, QTabWidget)
        assert tabs.count() == 2
        assert tabs.tabText(0) == "Measurement"
        assert tabs.tabText(1) == "Script Editor"
        app._engine.shutdown()

    def test_new_action_opens_new_tab(self, qapp):
        app = MeasurementApp()
        # Switch to editor tab so the New action targets it
        app._main_window.tabs.setCurrentIndex(app._TAB_EDITOR)
        app._main_window.script_tab.set_text("old content")
        initial_count = app._main_window.script_tab._script_tabs.count()
        app._act_new.trigger()
        # A new empty tab should have been added and be current
        assert app._main_window.script_tab._script_tabs.count() == initial_count + 1
        assert app._main_window.script_tab.text == ""
        app._engine.shutdown()

    def test_run_action_starts_engine(self, qapp):
        app = MeasurementApp()
        # With an empty editor, run_script is a no-op that does not raise
        app._act_run.trigger()
        app._act_stop.trigger()
        app._engine.shutdown()

    def test_pause_action(self, qapp):
        app = MeasurementApp()
        # Pause when not running is a no-op
        app._act_pause.trigger()
        # Resume via toggle
        app._act_pause.trigger()
        app._engine.shutdown()

    def test_generate_code_action_replaces_uncustomised_tab(self, qapp):
        app = MeasurementApp()
        # Initial tab is fresh (not customised); generate should reuse it.
        initial_count = app._main_window.script_tab._script_tabs.count()
        app._act_generate.trigger()
        assert app._main_window.script_tab._script_tabs.count() == initial_count
        text = app._main_window.script_tab.text
        assert len(text) > 0
        # The tab should NOT be marked customised (user has not edited it).
        pane = app._main_window.script_tab.current_pane()
        assert pane is not None
        assert pane.customised is False
        app._engine.shutdown()

    def test_generate_code_action_creates_new_tab_for_customised(self, qapp):
        app = MeasurementApp()
        # Mark the current tab as customised by having the user edit it.
        pane = app._main_window.script_tab.current_pane()
        assert pane is not None
        pane.editor.insertPlainText("# user edit")
        assert pane.customised is True
        initial_count = app._main_window.script_tab._script_tabs.count()
        app._act_generate.trigger()
        # A new tab should be created rather than replacing the customised one.
        assert app._main_window.script_tab._script_tabs.count() == initial_count + 1
        text = app._main_window.script_tab.text
        assert len(text) > 0
        app._engine.shutdown()


