"""Tests for the new UI widgets: EditorWidget, ConsoleWidget, SequenceTab."""

from __future__ import annotations

import pytest

from stoner_measurement.app import MeasurementApp
from stoner_measurement.ui.console_widget import ConsoleWidget
from stoner_measurement.ui.editor_widget import EditorWidget, PythonHighlighter
from stoner_measurement.ui.sequence_tab import SequenceTab


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
        from PyQt6.QtWidgets import QApplication

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


class TestSequenceTab:
    def test_creates_widget(self, qapp):
        tab = SequenceTab()
        assert tab is not None

    def test_initial_text_empty(self, qapp):
        tab = SequenceTab()
        assert tab.text == ""

    def test_set_and_get_text(self, qapp):
        tab = SequenceTab()
        tab.set_text("# sequence")
        assert tab.text == "# sequence"

    def test_has_editor(self, qapp):
        tab = SequenceTab()
        assert isinstance(tab.editor, EditorWidget)

    def test_has_console(self, qapp):
        tab = SequenceTab()
        assert isinstance(tab.console, ConsoleWidget)


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
        assert tabs.tabText(1) == "Sequence Editor"
        app._engine.shutdown()

    def test_new_action_clears_editor(self, qapp):
        app = MeasurementApp()
        app._main_window.sequence_tab.set_text("old content")
        app._act_new.trigger()
        assert app._main_window.sequence_tab.text == ""
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

    def test_generate_code_action_populates_editor(self, qapp):
        app = MeasurementApp()
        app._act_generate.trigger()
        text = app._main_window.sequence_tab.text
        # Should contain some generated content
        assert len(text) > 0
        app._engine.shutdown()

    def test_load_to_editor_no_steps(self, qapp):
        app = MeasurementApp()
        app._act_load_editor.trigger()
        assert "No sequence steps" in app._main_window.sequence_tab.text
        app._engine.shutdown()
