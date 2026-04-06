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

        # Current open file path (None = unsaved new sequence) ----------------
        self._current_path: Path | None = None

        # Wire the console to the engine --------------------------------------
        console = self._main_window.sequence_tab.console
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
            "&New Sequence",
            self,
        )
        self._act_new.setShortcut(QKeySequence.StandardKey.New)
        self._act_new.setStatusTip("Clear the sequence editor and start a new script")
        self._act_new.triggered.connect(self._on_new)

        self._act_open = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "&Open Sequence…",
            self,
        )
        self._act_open.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open.setStatusTip("Open a Python sequence script from disk")
        self._act_open.triggered.connect(self._on_open)

        self._act_save = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "&Save Sequence",
            self,
        )
        self._act_save.setShortcut(QKeySequence.StandardKey.Save)
        self._act_save.setStatusTip("Save the current sequence script")
        self._act_save.triggered.connect(self._on_save)

        self._act_save_as = QAction("Save Sequence &As…", self)
        self._act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self._act_save_as.setStatusTip("Save the current sequence script to a new file")
        self._act_save_as.triggered.connect(self._on_save_as)

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
            "Generate a Python script stub from the loaded plugins"
        )
        self._act_generate.triggered.connect(self._on_generate_code)

        self._act_load_editor = QAction("&Load Steps to Editor", self)
        self._act_load_editor.setStatusTip(
            "Render the current sequence steps as Python code in the editor"
        )
        self._act_load_editor.triggered.connect(self._on_load_to_editor)

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
        seq_menu.addAction(self._act_load_editor)

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
    # Action handlers
    # ------------------------------------------------------------------

    def _on_new(self) -> None:
        """Clear the editor and reset the current file path."""
        self._main_window.sequence_tab.set_text("")
        self._current_path = None
        self.setWindowTitle("Stoner Measurement — New Sequence")
        self._main_window.tabs.setCurrentIndex(1)

    def _on_open(self) -> None:
        """Prompt the user to open a Python sequence file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Sequence Script",
            str(self._current_path.parent) if self._current_path else "",
            "Python Files (*.py);;All Files (*)",
        )
        if not path:
            return
        self._current_path = Path(path)
        text = self._current_path.read_text(encoding="utf-8")
        self._main_window.sequence_tab.set_text(text)
        self.setWindowTitle(f"Stoner Measurement — {self._current_path.name}")
        self._main_window.tabs.setCurrentIndex(1)

    def _on_save(self) -> None:
        """Save the editor contents, prompting for a path if not yet saved."""
        if self._current_path is None:
            self._on_save_as()
        else:
            self._write_current_file()

    def _on_save_as(self) -> None:
        """Prompt the user for a save path and write the editor contents."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Sequence Script",
            str(self._current_path) if self._current_path else "sequence.py",
            "Python Files (*.py);;All Files (*)",
        )
        if not path:
            return
        self._current_path = Path(path)
        self._write_current_file()

    def _write_current_file(self) -> None:
        """Write the editor text to :attr:`_current_path`."""
        assert self._current_path is not None  # noqa: S101
        text = self._main_window.sequence_tab.text
        self._current_path.write_text(text, encoding="utf-8")
        self.setWindowTitle(f"Stoner Measurement — {self._current_path.name}")
        self._status_bar.showMessage(f"Saved {self._current_path.name}")

    def _on_run(self) -> None:
        """Execute the current sequence script in the engine."""
        script = self._main_window.sequence_tab.text
        self._main_window.tabs.setCurrentIndex(1)
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

    def _on_generate_code(self) -> None:
        """Generate a Python script stub from the loaded plugins and load it into the editor.

        The generated script references plugin instances by their sanitised
        variable names and provides usage examples appropriate for each plugin
        type.  The user can then edit and run the script.
        """
        plugins = self._plugin_manager.plugins
        code = self._engine.generate_code(plugins)
        self._main_window.sequence_tab.set_text(code)
        self._main_window.tabs.setCurrentIndex(1)

    def _on_load_to_editor(self) -> None:
        """Render the current sequence steps as Python code stubs in the editor.

        Each step is represented as a commented-out call stub, indented to
        reflect sub-sequence nesting beneath a
        :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
        step.  This gives the user a starting point for building a real script.
        """
        dock = self._main_window.dock_panel
        steps = dock.sequence_steps
        if not steps:
            lines = ["# No sequence steps defined yet.\n"]
        else:
            lines = ["# Auto-generated sequence script\n", "\n"]
            for step in steps:
                if isinstance(step, tuple):
                    ep_name, sub_steps = step
                    lines.append(f"# {ep_name}()\n")
                    for sub_step in sub_steps:
                        lines.append(f"#     {sub_step}()\n")
                else:
                    lines.append(f"# {step}()\n")
        self._main_window.sequence_tab.set_text("".join(lines))
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
