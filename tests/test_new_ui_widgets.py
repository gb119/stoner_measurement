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

    def test_set_and_clear_syntax_error(self, qapp):
        editor = EditorWidget()
        editor.set_syntax_error(2, "invalid syntax")
        assert editor.syntax_error_line == 2
        assert editor.syntax_error_message == "invalid syntax"
        editor.clear_syntax_error()
        assert editor.syntax_error_line is None
        assert editor.syntax_error_message == ""


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

    def test_submit_print_output_shown_without_engine(self, qapp):
        """print() in the REPL without an engine should appear in the output area."""
        console = ConsoleWidget()
        console._input.setText("print('hello stdout')")
        console._submit()
        text = console._output.toPlainText()
        assert "hello stdout" in text

    def test_write_output_no_extra_blank_lines(self, qapp):
        """write_output should not add a spurious newline after each chunk."""
        console = ConsoleWidget()
        # Simulate how CPython's print() writes: text then "\n" as two calls.
        console.write_output("Hello World")
        console.write_output("\n")
        lines = [ln for ln in console._output.toPlainText().splitlines() if ln]
        assert lines == ["Hello World"]

    def test_write_output_does_not_merge_with_subsequent_write(self, qapp):
        """A status message written after raw output starts on its own line."""
        console = ConsoleWidget()
        console.write_output("partial")  # no trailing newline
        console.write("Status message")
        text = console._output.toPlainText()
        lines = text.splitlines()
        assert any("partial" in ln for ln in lines)
        assert not any("partial" in ln and "Status message" in ln for ln in lines)

    def test_submit_print_output_with_engine(self, qapp, engine):
        """print() executed via the engine should appear in the console output area."""
        import time

        console = ConsoleWidget()
        console.connect_engine(engine)

        console._input.setText("print('engine output')")
        console._submit()

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            qapp.processEvents()
            if not engine.is_running:
                break
            time.sleep(0.01)
        time.sleep(0.05)
        qapp.processEvents()

        text = console._output.toPlainText()
        assert "engine output" in text


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

    def test_sync_sequence_steps_dummy_traces_visible_to_plot_trace(self, qapp):
        """PlotTraceCommand config widget should see traces from a preceding DummyPlugin step.

        Regression test for: plot_trace and dummy plugin combination does not recognise
        any traces.  The root cause was that sequence-step plugin instances did not have
        ``sequence_engine`` set, so ``engine_namespace`` returned ``{}`` and ``_traces``
        was empty when ``config_widget()`` was built.
        """
        from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
        from stoner_measurement.plugins.trace import DummyPlugin

        app = MeasurementApp()
        dock = app._main_window.dock_panel

        # Load a DummyPlugin step and a PlotTraceCommand step via the dock panel.
        dummy_step = DummyPlugin()
        plot_step = PlotTraceCommand()
        dock.load_sequence([dummy_step, plot_step])

        # Sync step plugins into the engine namespace.
        app._sync_sequence_steps_to_engine()

        # After sync, the plot_step should have sequence_engine set.
        assert plot_step.sequence_engine is app._engine

        # The engine namespace _traces should include the dummy step's trace.
        traces = app._engine._namespace.get("_traces", {})
        assert any("Dummy" in key for key in traces), (
            f"Expected a 'Dummy' trace in _traces, got: {list(traces.keys())}"
        )

        app._engine.shutdown()

    def test_on_plugin_selected_for_config_syncs_and_shows(self, qapp):
        """_on_plugin_selected_for_config shows plugin config with traces populated."""
        from stoner_measurement.plugins.command.plot_trace import PlotTraceCommand
        from stoner_measurement.plugins.trace import DummyPlugin

        app = MeasurementApp()
        dock = app._main_window.dock_panel

        dummy_step = DummyPlugin()
        plot_step = PlotTraceCommand()
        dock.load_sequence([dummy_step, plot_step])

        # Calling the selection handler should not raise and should display config.
        app._on_plugin_selected_for_config(plot_step)

        # The config panel should now show the PlotTraceCommand's tabs.
        assert app._main_window.config_panel.tabs.count() > 0

        # _traces in the engine namespace should contain the dummy step's trace.
        traces = app._engine._namespace.get("_traces", {})
        assert any("Dummy" in key for key in traces)

        app._engine.shutdown()

    def test_sync_drops_stale_curve_fit_values_on_deselect(self, qapp):
        from stoner_measurement.plugins.transform import CurveFitPlugin

        app = MeasurementApp()
        dock = app._main_window.dock_panel
        curve_step = CurveFitPlugin()
        dock.load_sequence([curve_step])

        curve_step.param_names = ["slope", "offset"]
        app._on_plugin_selected_for_config(None)

        values = app._engine._namespace.get("_values", {})
        assert "curve_fit:slope" in values
        assert "curve_fit:offset" in values
        assert "curve_fit:a" not in values
        assert "curve_fit:b" not in values

        app._engine.shutdown()
