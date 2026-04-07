"""Main application window for the Stoner Measurement application."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QStyle,
    QToolBar,
)

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.plugins.trace import TracePlugin
from stoner_measurement.ui.icons import make_generate_icon
from stoner_measurement.ui.main_window import MainWindow


class MeasurementApp(QMainWindow):
    """Top-level application window.

    Composes the :class:`MainWindow` central widget and wires together the
    :class:`~stoner_measurement.core.plugin_manager.PluginManager` and
    :class:`~stoner_measurement.core.sequence_engine.SequenceEngine`.

    The window provides:

    * A **menu bar** with File, Sequence, View and Help menus.
    * A **toolbar** with Run, Pause, Stop, Generate Code, Open and Save actions.
    * A **status bar** that reflects engine status messages.

    When plugins are loaded, instances are automatically injected into the
    engine namespace under sanitised variable names (e.g. the ``"dummy"``
    entry-point plugin becomes ``dummy`` in the script namespace).
    :class:`~stoner_measurement.plugins.trace.TracePlugin` instances have their
    ``trace_point`` signals wired to the plot widget so that data appears
    automatically while a script runs.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Stoner Measurement")
        self.setMinimumSize(QSize(1200, 700))

        # Core objects ---------------------------------------------------------
        self._plugin_manager = PluginManager()
        self._engine = SequenceEngine(parent=self)

        # Tracks which plugins have been wired to the engine / plot so they can
        # be cleanly removed when the plugin list changes.
        self._engine_plugins: dict[str, object] = {}

        # Central widget -------------------------------------------------------
        self._main_window = MainWindow(plugin_manager=self._plugin_manager)
        self.setCentralWidget(self._main_window)

        # Status bar -----------------------------------------------------------
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready")
        self._engine.status_changed.connect(self._status_bar.showMessage)

        # Wire the console to the engine --------------------------------------
        console = self._main_window.script_tab.console
        console.connect_engine(self._engine)
        self._engine.status_changed.connect(console.write)

        # Connect plugin manager so plugins are synced to the engine ----------
        self._plugin_manager.plugins_changed.connect(self._on_plugins_changed)

        # Wire sequence step selection → config panel -------------------------
        self._main_window.dock_panel.plugin_selected.connect(
            self._main_window.config_panel.show_plugin
        )

        # Build the UI before discovering plugins (so signals are in place) ---
        self._build_actions()
        self._build_menu_bar()
        self._build_toolbar()

        # Update window title when the active script tab changes --------------
        self._main_window.script_tab._script_tabs.currentChanged.connect(  # noqa: SLF001
            lambda _: self._update_window_title()
        )

        self._restore_settings()

        # Discover plugins (emits plugins_changed → _on_plugins_changed) ------
        self._plugin_manager.discover()

    # ------------------------------------------------------------------
    # Plugin synchronisation
    # ------------------------------------------------------------------

    def _on_plugins_changed(self) -> None:
        """Synchronise the engine namespace and plot connections with the current plugins."""
        current = self._plugin_manager.plugins

        # Remove plugins that are no longer registered ----------------------
        for ep_name in list(self._engine_plugins):
            if ep_name not in current:
                old_plugin = self._engine_plugins.pop(ep_name)
                self._engine.remove_plugin(ep_name)
                if isinstance(old_plugin, TracePlugin):
                    try:
                        old_plugin.trace_point.disconnect(
                            self._main_window.plot_widget.append_point
                        )
                    except (TypeError, RuntimeError):
                        pass
                if hasattr(old_plugin, "instance_name_changed"):
                    try:
                        old_plugin.instance_name_changed.disconnect()
                    except (TypeError, RuntimeError):
                        pass

        # Add plugins that are newly registered -----------------------------
        for ep_name, plugin in current.items():
            if ep_name not in self._engine_plugins:
                self._engine.add_plugin(ep_name, plugin)
                self._engine_plugins[ep_name] = plugin
                if isinstance(plugin, TracePlugin):
                    plugin.trace_point.connect(
                        self._main_window.plot_widget.append_point
                    )
                if hasattr(plugin, "instance_name_changed"):
                    plugin.instance_name_changed.connect(
                        lambda _, new, ep=ep_name: self._engine.rename_plugin(ep, new)
                    )

    # ------------------------------------------------------------------
    # Action construction
    # ------------------------------------------------------------------

    def _build_actions(self) -> None:
        """Create all QAction instances used by the menu bar and toolbar."""
        # File actions
        style = QApplication.style()

        self._act_new = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            "&New",
            self,
        )
        self._act_new.setShortcut(QKeySequence.StandardKey.New)
        self._act_new.triggered.connect(self._on_new)

        self._act_open = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "&Open…",
            self,
        )
        self._act_open.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open.triggered.connect(self._on_open)

        self._act_save = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "&Save",
            self,
        )
        self._act_save.setShortcut(QKeySequence.StandardKey.Save)
        self._act_save.triggered.connect(self._on_save)

        self._act_save_as = QAction("Save &As…", self)
        self._act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self._act_save_as.triggered.connect(self._on_save_as)

        # Connect tab changes so action labels/tips stay current --------
        self._main_window.tabs.currentChanged.connect(self._on_tab_changed)
        # Initialise labels for the default (Measurement) tab -----------
        self._on_tab_changed(self._main_window.tabs.currentIndex())

        self._act_exit = QAction("E&xit", self)
        self._act_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self._act_exit.setStatusTip("Exit the application")
        self._act_exit.triggered.connect(self.close)

        # Sequence actions
        self._act_run = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay),
            "&Run",
            self,
        )
        self._act_run.setShortcut(Qt.Key.Key_F5)
        self._act_run.setStatusTip("Execute the sequence script in the editor")
        self._act_run.triggered.connect(self._on_run)

        self._act_pause = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPause),
            "&Pause",
            self,
        )
        self._act_pause.setShortcut(Qt.Key.Key_F7)
        self._act_pause.setStatusTip("Pause or resume the running sequence")
        self._act_pause.triggered.connect(self._on_pause)

        self._act_stop = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaStop),
            "S&top",
            self,
        )
        self._act_stop.setShortcut(Qt.Key.Key_F6)
        self._act_stop.setStatusTip("Stop the running sequence")
        self._act_stop.triggered.connect(self._on_stop)

        self._act_generate = QAction(make_generate_icon(), "&Generate Code", self)
        self._act_generate.setStatusTip(
            "Render the current sequence steps as Python code in the editor"
        )
        self._act_generate.triggered.connect(self._on_load_to_editor)

        # View actions
        self._act_view_measurement = QAction("&Measurement", self)
        self._act_view_measurement.setStatusTip("Switch to the Measurement tab")
        self._act_view_measurement.triggered.connect(
            lambda: self._main_window.tabs.setCurrentIndex(0)
        )

        self._act_view_editor = QAction("&Sequence Editor", self)
        self._act_view_editor.setStatusTip("Switch to the Sequence Editor tab")
        self._act_view_editor.triggered.connect(
            lambda: self._main_window.tabs.setCurrentIndex(1)
        )

        # Help actions
        self._act_about = QAction("&About", self)
        self._act_about.setStatusTip("Show information about this application")
        self._act_about.triggered.connect(self._on_about)

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def _build_menu_bar(self) -> None:
        """Populate the menu bar with File, Sequence, View and Help menus."""
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self._act_new)
        file_menu.addAction(self._act_open)
        file_menu.addAction(self._act_save)
        file_menu.addAction(self._act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self._act_exit)

        # Sequence menu
        seq_menu = menu_bar.addMenu("&Sequence")
        seq_menu.addAction(self._act_run)
        seq_menu.addAction(self._act_pause)
        seq_menu.addAction(self._act_stop)
        seq_menu.addSeparator()
        seq_menu.addAction(self._act_generate)

        # View menu
        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self._act_view_measurement)
        view_menu.addAction(self._act_view_editor)

        # Help menu
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self._act_about)

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        """Build the main toolbar."""
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction(self._act_new)
        toolbar.addSeparator()
        toolbar.addAction(self._act_open)
        toolbar.addAction(self._act_save)
        toolbar.addSeparator()
        toolbar.addAction(self._act_run)
        toolbar.addAction(self._act_pause)
        toolbar.addAction(self._act_stop)
        toolbar.addSeparator()
        toolbar.addAction(self._act_generate)

    # ------------------------------------------------------------------
    # Tab-change handler — keeps action labels/tips in sync
    # ------------------------------------------------------------------

    # Tab indices (must match the order addTab() is called in MainWindow)
    _TAB_MEASUREMENT = 0
    _TAB_EDITOR = 1

    def _on_tab_changed(self, index: int) -> None:
        """Update action labels and status tips when the active tab changes."""
        if index == self._TAB_MEASUREMENT:
            self._act_new.setText("&New Measurement")
            self._act_new.setStatusTip("Clear the measurement sequence and start a new one")
            self._act_open.setText("&Open Measurement…")
            self._act_open.setStatusTip("Open a saved measurement sequence from disk")
            self._act_save.setText("&Save Measurement")
            self._act_save.setStatusTip("Save the current measurement sequence")
            self._act_save_as.setText("Save Measurement &As…")
            self._act_save_as.setStatusTip("Save the current measurement sequence to a new file")
        elif index == self._TAB_EDITOR:
            self._act_new.setText("&New Sequence")
            self._act_new.setStatusTip("Clear the sequence editor and start a new script")
            self._act_open.setText("&Open Sequence…")
            self._act_open.setStatusTip("Open a Python sequence script from disk")
            self._act_save.setText("&Save Sequence")
            self._act_save.setStatusTip("Save the current sequence script")
            self._act_save_as.setText("Save Sequence &As…")
            self._act_save_as.setStatusTip("Save the current sequence script to a new file")

    # ------------------------------------------------------------------
    # Dispatcher — delegates to the correct handler for the active tab
    # ------------------------------------------------------------------

    def _on_new(self) -> None:
        """Dispatch the New action to the appropriate handler for the active tab."""
        if self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT:
            self._on_new_measurement()
        elif self._main_window.tabs.currentIndex() == self._TAB_EDITOR:
            self._on_new_script()

    def _on_open(self) -> None:
        """Dispatch the Open action to the appropriate handler for the active tab."""
        if self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT:
            self._on_open_measurement()
        elif self._main_window.tabs.currentIndex() == self._TAB_EDITOR:
            self._on_open_script()

    def _on_save(self) -> None:
        """Dispatch the Save action to the appropriate handler for the active tab."""
        if self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT:
            self._on_save_measurement()
        elif self._main_window.tabs.currentIndex() == self._TAB_EDITOR:
            self._on_save_script()

    def _on_save_as(self) -> None:
        """Dispatch the Save As action to the appropriate handler for the active tab."""
        if self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT:
            self._on_save_as_measurement()
        elif self._main_window.tabs.currentIndex() == self._TAB_EDITOR:
            self._on_save_as_script()

    # ------------------------------------------------------------------
    # Measurement-tab stubs (to be implemented once serialisation is ready)
    # ------------------------------------------------------------------

    def _on_new_measurement(self) -> None:
        """Clear the measurement sequence and start a new one.

        Notes:
            This is a stub — full implementation will follow once a
            serialisation format for the measurement sequence has been
            established.
        """

    def _on_open_measurement(self) -> None:
        """Open a saved measurement sequence from disk.

        Notes:
            This is a stub — full implementation will follow once a
            serialisation format for the measurement sequence has been
            established.
        """

    def _on_save_measurement(self) -> None:
        """Save the current measurement sequence to disk.

        Notes:
            This is a stub — full implementation will follow once a
            serialisation format for the measurement sequence has been
            established.
        """

    def _on_save_as_measurement(self) -> None:
        """Save the current measurement sequence to a new file.

        Notes:
            This is a stub — full implementation will follow once a
            serialisation format for the measurement sequence has been
            established.
        """

    # ------------------------------------------------------------------
    # Sequence-editor (script) action handlers
    # ------------------------------------------------------------------

    def _on_new_script(self) -> None:
        """Open a new empty script tab in the editor."""
        self._main_window.script_tab.new_tab()
        self._update_window_title()
        self._main_window.tabs.setCurrentIndex(self._TAB_EDITOR)

    def _on_open_script(self) -> None:
        """Prompt the user to open a Python sequence file in a new tab."""
        pane = self._main_window.script_tab.current_pane()
        start_dir = str(pane.path.parent) if pane and pane.path else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Sequence Script",
            start_dir,
            "Python Files (*.py);;All Files (*)",
        )
        if not path:
            return
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8")
        self._main_window.script_tab.add_tab(text, path=file_path)
        self._update_window_title()
        self._main_window.tabs.setCurrentIndex(self._TAB_EDITOR)

    def _on_save_script(self) -> None:
        """Save the active tab's editor contents, prompting for a path if needed."""
        pane = self._main_window.script_tab.current_pane()
        if pane is None or pane.path is None:
            self._on_save_as_script()
        else:
            self._write_current_file()

    def _on_save_as_script(self) -> None:
        """Prompt the user for a save path and write the active tab's editor contents."""
        pane = self._main_window.script_tab.current_pane()
        start = str(pane.path) if pane and pane.path else "sequence.py"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Sequence Script",
            start,
            "Python Files (*.py);;All Files (*)",
        )
        if not path:
            return
        if pane is not None:
            pane.path = Path(path)
        self._write_current_file()

    def _write_current_file(self) -> None:
        """Write the active tab's editor text to its associated path."""
        pane = self._main_window.script_tab.current_pane()
        if pane is None or pane.path is None:
            return
        pane.path.write_text(pane.editor.text(), encoding="utf-8")
        pane.mark_clean()
        self._main_window.script_tab._update_tab_title(pane)  # noqa: SLF001
        self._update_window_title()
        self._status_bar.showMessage(f"Saved {pane.path.name}")

    def _on_run(self) -> None:
        """Execute the current sequence script in the engine."""
        script = self._main_window.script_tab.text
        self._main_window.tabs.setCurrentIndex(self._TAB_EDITOR)
        self._engine.run_script(script)

    def _on_pause(self) -> None:
        """Pause or resume the running sequence."""
        if self._engine.is_paused:
            self._engine.resume()
        else:
            self._engine.pause()

    def _on_stop(self) -> None:
        """Stop the running sequence."""
        self._engine.stop()

    def _on_load_to_editor(self) -> None:
        """Render the current sequence steps as executable Python code in the editor.

        Calls :meth:`~stoner_measurement.core.sequence_engine.SequenceEngine.generate_sequence_code`
        to convert the sequence tree into a runnable Python script, with nested
        ``try/finally`` blocks reflecting the sub-sequence structure.  The
        generated script is loaded into the sequence editor so the user can
        inspect, edit, and run it.

        Per-step plugin instances (which may differ from the shared plugin
        manager instances when multiple steps use the same plugin type) are
        injected into the engine namespace so that the generated script can
        reference them by their :attr:`instance_name`.
        """
        from stoner_measurement.plugins.base_plugin import BasePlugin

        dock = self._main_window.dock_panel
        steps = dock.sequence_steps
        plugins = self._plugin_manager.plugins

        # Inject per-step plugin instances into the engine namespace so the
        # generated script can reference them by their instance_name variable.
        def _inject_step(step: object) -> None:
            if isinstance(step, tuple):
                plugin_or_name, sub_steps = step
            else:
                plugin_or_name = step
                sub_steps = []
            if isinstance(plugin_or_name, BasePlugin):
                self._engine._namespace[plugin_or_name.instance_name] = plugin_or_name  # noqa: SLF001
            for sub in sub_steps:
                _inject_step(sub)

        for step in steps:
            _inject_step(step)

        code = self._engine.generate_sequence_code(steps, plugins)
        script_tab = self._main_window.script_tab
        pane = script_tab.current_pane()
        if pane is None or pane.customised:
            # No open tabs, or current tab has been user-edited: open a new tab.
            script_tab.add_tab(code)
        else:
            # Current tab is unmodified generated (or fresh): replace its content.
            pane.set_text(code)
        self._main_window.tabs.setCurrentIndex(1)

    def _on_about(self) -> None:
        """Display the About dialogue."""
        QMessageBox.about(
            self,
            "About Stoner Measurement",
            "<b>Stoner Measurement</b><br/>"
            "A laboratory measurement application for communicating with "
            "scientific instruments via USB, Serial, GPIB and Ethernet.<br/><br/>"
            "© University of Leeds",
        )

    def _update_window_title(self) -> None:
        """Refresh the window title to reflect the active script tab."""
        pane = self._main_window.script_tab.current_pane()
        if pane is None or pane.path is None:
            self.setWindowTitle("Stoner Measurement")
        else:
            suffix = " *" if pane.dirty else ""
            self.setWindowTitle(f"Stoner Measurement — {pane.path.name}{suffix}")

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _restore_settings(self) -> None:
        """Restore window geometry from QSettings."""
        settings = QSettings()
        geometry = settings.value("mainWindow/geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Save window geometry and cleanly shut down the engine on close."""
        settings = QSettings()
        settings.setValue("mainWindow/geometry", self.saveGeometry())
        self._engine.shutdown()
        super().closeEvent(event)
