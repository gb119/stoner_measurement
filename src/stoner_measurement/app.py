"""Main application window for the Stoner Measurement application."""

from __future__ import annotations

import json
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
from stoner_measurement.ui.icons import make_generate_icon, make_log_icon, make_temperature_icon
from stoner_measurement.ui.log_viewer import LogViewerWindow
from stoner_measurement.ui.main_window import MainWindow
from stoner_measurement.ui.settings_dialog import (
    KEY_DEFAULT_DATA_DIR,
    KEY_DEFAULT_SEQUENCE_TEMPLATE,
    SettingsDialog,
    make_app_settings,
)


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
    :class:`~stoner_measurement.plugins.command.PlotTraceCommand` instances
    have their ``plot_trace`` signals wired to the plot widget so that data
    can be sent to the plot from within a sequence.
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

        # Path to the most recently saved/loaded measurement sequence file.
        self._current_measurement_path: Path | None = None

        # Central widget -------------------------------------------------------
        self._main_window = MainWindow(plugin_manager=self._plugin_manager)
        self.setCentralWidget(self._main_window)

        # Wire the engine to the plot widget so that PlotTraceCommand instances
        # can deliver data regardless of how they were added to the sequence.
        self._engine.plot_widget = self._main_window.plot_widget

        # Log viewer (created before actions so actions can reference it) ------
        self._log_viewer = LogViewerWindow(parent=None)
        self._engine.log_handler.record_emitted.connect(self._log_viewer.append_record)

        # Temperature control panel (hidden initially) -------------------------
        from stoner_measurement.ui.temperature_panel import TemperatureControlPanel

        self._temp_panel = TemperatureControlPanel(parent=None)

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
        # Use an intermediate slot so step plugins are synced into the engine
        # namespace (and _traces rebuilt) before the config widget is shown.
        self._main_window.dock_panel.plugin_selected.connect(self._on_plugin_selected_for_config)

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

        # Load the template sequence (or empty sequence if none configured) ----
        self._load_template_sequence()

    # ------------------------------------------------------------------
    # Plugin synchronisation
    # ------------------------------------------------------------------

    def _on_plugin_selected_for_config(self, plugin: object) -> None:
        """Sync sequence-step plugins into the engine namespace, then show config.

        This intermediate slot is wired to
        :attr:`~stoner_measurement.ui.dock_panel.DockPanel.plugin_selected`.
        Before delegating to :meth:`~stoner_measurement.ui.config_panel.ConfigPanel.show_plugin`
        it calls :meth:`_sync_sequence_steps_to_engine` so that the ``_traces``
        and ``_values`` catalogs in the engine namespace reflect the current
        sequence steps.  This ensures that command-plugin configuration widgets
        (such as :class:`~stoner_measurement.plugins.command.PlotTraceCommand`)
        can populate their dropdowns from the live trace catalogue even before
        a sequence has been run.

        Args:
            plugin (object):
                The plugin instance selected in the sequence editor, or ``None``
                when the selection is cleared.
        """
        self._sync_sequence_steps_to_engine()
        self._main_window.config_panel.show_plugin(plugin)  # type: ignore[arg-type]
        self._update_disable_action(plugin)

    def _sync_sequence_steps_to_engine(self) -> None:
        """Inject sequence-step plugins into the engine namespace and rebuild catalogs.

        Traverses every step in the current sequence (including nested sub-steps)
        and, for each plugin instance that is not yet attached to the engine,
        sets its :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.sequence_engine`
        to this application's engine.  The ``_traces`` and ``_values`` entries
        in the engine namespace are then rebuilt from both the base plugins
        (registered via :meth:`~stoner_measurement.core.sequence_engine.SequenceEngine.add_plugin`)
        and the step plugins discovered here.

        This makes the trace catalogue available to configuration widgets (e.g.
        :class:`~stoner_measurement.plugins.command.PlotTraceCommand`) which
        read ``engine_namespace["_traces"]`` to populate their dropdowns.

        Notes:
            Step plugins are attached to the engine so that
            ``engine_namespace`` becomes functional in their configuration
            widgets.  The catalog is rebuilt by
            :meth:`~stoner_measurement.core.sequence_engine.SequenceEngine.update_step_plugin_catalog`,
            which includes contributions from both base plugins and the
            step plugins passed here.
        """
        from stoner_measurement.plugins.base_plugin import BasePlugin

        step_plugins: list[BasePlugin] = []

        def _process(steps: list) -> None:
            """Recursively collect step plugins and attach them to the engine."""
            for step in steps:
                if isinstance(step, tuple):
                    step_plugin, sub_steps = step
                    _process(sub_steps)
                else:
                    step_plugin = step
                if isinstance(step_plugin, BasePlugin):
                    if step_plugin.sequence_engine is None:
                        step_plugin.sequence_engine = self._engine
                    step_plugins.append(step_plugin)

        _process(self._main_window.dock_panel.sequence_steps)
        self._engine.update_step_plugin_catalog(step_plugins)

    def _on_plugins_changed(self) -> None:
        """Synchronise the engine namespace with the current plugins."""
        current = self._plugin_manager.plugins

        # Remove plugins that are no longer registered ----------------------
        for ep_name in list(self._engine_plugins):
            if ep_name not in current:
                old_plugin = self._engine_plugins.pop(ep_name)
                self._engine.remove_plugin(ep_name)
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
                if hasattr(plugin, "instance_name_changed"):
                    plugin.instance_name_changed.connect(
                        lambda _, new, ep=ep_name: self._engine.rename_plugin(ep, new)
                    )

    # ------------------------------------------------------------------
    # Disable / enable action helpers
    # ------------------------------------------------------------------

    def _update_disable_action(self, plugin: object) -> None:
        """Update the toggle-disable action label and enabled state.

        Called whenever the sequence-step selection changes (via
        :attr:`~stoner_measurement.ui.dock_panel.DockPanel.plugin_selected`).
        When *plugin* is a
        :class:`~stoner_measurement.plugins.base_plugin.BasePlugin` instance
        (single-item selection) the action is enabled and its label reflects
        the plugin's current :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.disabled`
        state.  Otherwise the action is disabled.

        Args:
            plugin (object):
                The selected plugin, or ``None`` when nothing is selected or
                multiple steps are selected.
        """
        from stoner_measurement.plugins.base_plugin import BasePlugin

        if isinstance(plugin, BasePlugin):
            self._act_toggle_disable.setEnabled(True)
            label = "Enable Plugin" if plugin.disabled else "Disable Plugin"
            self._act_toggle_disable.setText(label)
        else:
            self._act_toggle_disable.setEnabled(False)
            self._act_toggle_disable.setText("Disable Plugin")

    def _on_toggle_disable(self) -> None:
        """Toggle the disabled state of the selected sequence step(s).

        Delegates to
        :meth:`~stoner_measurement.ui.dock_panel.DockPanel.toggle_disable_selected_steps`.
        """
        self._main_window.dock_panel.toggle_disable_selected_steps()

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
        self._act_run.setStatusTip("Run the current sequence or script")
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
        self._act_generate.setStatusTip("Render the current sequence steps as Python code in the editor")
        self._act_generate.triggered.connect(self._on_load_to_editor)

        # Edit actions
        self._act_cut = QAction("Cu&t", self)
        self._act_cut.setShortcut(QKeySequence.StandardKey.Cut)
        self._act_cut.triggered.connect(self._on_cut)

        self._act_copy = QAction("&Copy", self)
        self._act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        self._act_copy.triggered.connect(self._on_copy)

        self._act_paste = QAction("&Paste", self)
        self._act_paste.setShortcut(QKeySequence.StandardKey.Paste)
        self._act_paste.triggered.connect(self._on_paste)

        self._act_toggle_disable = QAction("Disable Plugin", self)
        self._act_toggle_disable.setStatusTip("Disable or re-enable the selected sequence step")
        self._act_toggle_disable.setEnabled(False)
        self._act_toggle_disable.triggered.connect(self._on_toggle_disable)

        self._act_settings = QAction("&Preferences…", self)
        self._act_settings.setShortcut(QKeySequence.StandardKey.Preferences)
        self._act_settings.setStatusTip("Configure application preferences")
        self._act_settings.setMenuRole(QAction.MenuRole.PreferencesRole)
        self._act_settings.triggered.connect(self._on_settings)

        # View actions
        self._act_view_measurement = QAction("&Measurement", self)
        self._act_view_measurement.setStatusTip("Switch to the Measurement tab")
        self._act_view_measurement.triggered.connect(lambda: self._main_window.tabs.setCurrentIndex(0))

        self._act_view_editor = QAction("&Script Editor", self)
        self._act_view_editor.setStatusTip("Switch to the Script Editor tab")
        self._act_view_editor.triggered.connect(lambda: self._main_window.tabs.setCurrentIndex(1))

        self._act_show_log = QAction(make_log_icon(), "Show &Log", self)
        self._act_show_log.setStatusTip("Open the log viewer window")
        self._act_show_log.triggered.connect(self._on_show_log)

        # Temperature control actions
        self._act_show_temp_panel = QAction(make_temperature_icon(), "Show &Temperature Control", self)
        self._act_show_temp_panel.setStatusTip("Open the temperature controller panel")
        self._act_show_temp_panel.triggered.connect(self._on_show_temp_panel)

        self._act_stop_temp_engine = QAction("Stop Temperature &Engine", self)
        self._act_stop_temp_engine.setStatusTip("Stop the temperature controller engine and disconnect hardware")
        self._act_stop_temp_engine.triggered.connect(self._on_stop_temp_engine)

        # Help actions
        self._act_about = QAction("&About", self)
        self._act_about.setStatusTip("Show information about this application")
        self._act_about.triggered.connect(self._on_about)

        # Connect tab changes so action labels/tips stay current.
        # Must be done after all actions are created so _on_tab_changed can
        # safely reference self._act_run and self._act_generate.
        self._main_window.tabs.currentChanged.connect(self._on_tab_changed)
        # Initialise labels for the default (Measurement) tab -----------
        self._on_tab_changed(self._main_window.tabs.currentIndex())

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

        # Edit menu
        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self._act_cut)
        edit_menu.addAction(self._act_copy)
        edit_menu.addAction(self._act_paste)
        edit_menu.addAction(self._act_toggle_disable)
        edit_menu.addSeparator()
        edit_menu.addAction(self._act_settings)

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
        view_menu.addSeparator()
        view_menu.addAction(self._act_show_log)

        # Temperature menu
        temp_menu = menu_bar.addMenu("&Temperature")
        temp_menu.addAction(self._act_show_temp_panel)
        temp_menu.addSeparator()
        temp_menu.addAction(self._act_stop_temp_engine)

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
        toolbar.addSeparator()
        toolbar.addAction(self._act_show_log)
        toolbar.addAction(self._act_show_temp_panel)

    # ------------------------------------------------------------------
    # Tab-change handler — keeps action labels/tips in sync
    # ------------------------------------------------------------------

    # Tab indices (must match the order addTab() is called in MainWindow)
    _TAB_MEASUREMENT = 0
    _TAB_EDITOR = 1

    def _on_tab_changed(self, index: int) -> None:
        """Update action labels and status tips when the active tab changes."""
        if index == self._TAB_MEASUREMENT:
            self._act_new.setText("&New Sequence")
            self._act_new.setStatusTip("Clear the measurement sequence and start a new one")
            self._act_open.setText("&Open Sequence…")
            self._act_open.setStatusTip("Open a saved measurement sequence from disk")
            self._act_save.setText("&Save Sequence")
            self._act_save.setStatusTip("Save the current measurement sequence")
            self._act_save_as.setText("Save Sequence &As…")
            self._act_save_as.setStatusTip("Save the current measurement sequence to a new file")
            self._act_run.setStatusTip("Convert the measurement sequence to a script and execute it")
            self._act_generate.setStatusTip(
                "Render the current sequence steps as Python code in the editor" " (without switching tabs)"
            )
            self._act_cut.setText("Cu&t Step")
            self._act_cut.setStatusTip("Cut the selected sequence step to the clipboard")
            self._act_copy.setText("&Copy Step")
            self._act_copy.setStatusTip("Copy the selected sequence step to the clipboard")
            self._act_paste.setText("&Paste Step")
            self._act_paste.setStatusTip("Paste the sequence step from the clipboard")
        elif index == self._TAB_EDITOR:
            self._act_new.setText("&New Script")
            self._act_new.setStatusTip("Clear the sequence editor and start a new script")
            self._act_open.setText("&Open Script…")
            self._act_open.setStatusTip("Open a Python sequence script from disk")
            self._act_save.setText("&Save Script")
            self._act_save.setStatusTip("Save the current sequence script")
            self._act_save_as.setText("Save Script &As…")
            self._act_save_as.setStatusTip("Save the current sequence script to a new file")
            self._act_run.setStatusTip("Execute the sequence script in the editor")
            self._act_generate.setStatusTip("Render the current sequence steps as Python code in the editor")
            self._act_cut.setText("Cu&t")
            self._act_cut.setStatusTip("Cut the selected text")
            self._act_copy.setText("&Copy")
            self._act_copy.setStatusTip("Copy the selected text")
            self._act_paste.setText("&Paste")
            self._act_paste.setStatusTip("Paste text from the clipboard")

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
        self._main_window.config_panel.commit_pending_changes()
        if self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT:
            self._on_save_measurement()
        elif self._main_window.tabs.currentIndex() == self._TAB_EDITOR:
            self._on_save_script()

    def _on_save_as(self) -> None:
        """Dispatch the Save As action to the appropriate handler for the active tab."""
        self._main_window.config_panel.commit_pending_changes()
        if self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT:
            self._on_save_as_measurement()
        elif self._main_window.tabs.currentIndex() == self._TAB_EDITOR:
            self._on_save_as_script()

    def _on_cut(self) -> None:
        """Dispatch the Cut action to the appropriate handler for the active tab.

        On the *Measurement* tab the selected sequence step is cut to the
        internal JSON clipboard.  On the *Script Editor* tab, the standard
        ``cut()`` method is called on whichever focusable text widget currently
        has keyboard focus (i.e. the script editor or the REPL command line).
        """
        if self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT:
            self._main_window.dock_panel.cut_selected_step()
        else:
            widget = QApplication.focusWidget()
            cut = getattr(widget, "cut", None)
            if callable(cut):
                cut()

    def _on_copy(self) -> None:
        """Dispatch the Copy action to the appropriate handler for the active tab.

        On the *Measurement* tab the selected sequence step is copied to the
        internal JSON clipboard.  On the *Script Editor* tab, the standard
        ``copy()`` method is called on the focused text widget.
        """
        if self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT:
            self._main_window.dock_panel.copy_selected_step()
        else:
            widget = QApplication.focusWidget()
            copy = getattr(widget, "copy", None)
            if callable(copy):
                copy()

    def _on_paste(self) -> None:
        """Dispatch the Paste action to the appropriate handler for the active tab.

        On the *Measurement* tab the step stored in the internal JSON clipboard
        is inserted into the sequence tree after the currently selected item.
        On the *Script Editor* tab, the standard ``paste()`` method is called
        on the focused text widget.
        """
        if self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT:
            self._main_window.dock_panel.paste_step()
        else:
            widget = QApplication.focusWidget()
            paste = getattr(widget, "paste", None)
            if callable(paste):
                paste()

    # ------------------------------------------------------------------
    # Measurement-tab actions
    # ------------------------------------------------------------------

    def _load_template_sequence(self) -> None:
        """Load the default sequence template, or an empty sequence if none is set.

        Reads the ``app/default_sequence_template`` setting from the application
        preferences INI file.  If the path is non-empty and the file exists the
        sequence is deserialised and loaded into the dock panel.  In all other
        cases (no path configured, file missing, or parse error) an empty
        sequence is loaded instead.
        """
        from stoner_measurement.core.serializer import sequence_from_json

        settings = make_app_settings()
        template_str = settings.value(KEY_DEFAULT_SEQUENCE_TEMPLATE, "", type=str)
        if template_str:
            template_path = Path(template_str)
            if template_path.exists():
                try:
                    data = json.loads(template_path.read_text(encoding="utf-8"))
                    steps = sequence_from_json(data)
                    self._main_window.dock_panel.load_sequence(steps)
                    return
                except (OSError, json.JSONDecodeError, KeyError, ImportError, AttributeError):
                    pass
        self._main_window.dock_panel.load_sequence([])

    def _on_new_measurement(self) -> None:
        """Clear the measurement sequence and start a new one.

        Asks the user to confirm discarding the current sequence, then clears
        the sequence tree and resets the current file path.  If a default
        sequence template is configured in the application preferences and the
        file exists, that template is loaded instead of an empty sequence.
        """
        self._load_template_sequence()
        self._current_measurement_path = None
        self._update_window_title()
        self._engine._rebuild_data_catalogs()


    def _on_open_measurement(self) -> None:
        """Open a saved measurement sequence from a JSON file.

        Prompts the user to select a ``.json`` file, loads it, deserialises
        the sequence, and populates the sequence tree.  Displays an error
        message if the file cannot be parsed.
        """
        from stoner_measurement.core.serializer import sequence_from_json

        dock = self._main_window.dock_panel
        start_dir = (
            str(self._current_measurement_path.parent)
            if self._current_measurement_path
            else make_app_settings().value(KEY_DEFAULT_DATA_DIR, "", type=str)
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Sequence",
            start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        file_path = Path(path)
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            steps = sequence_from_json(data)
        except (OSError, json.JSONDecodeError, KeyError, ImportError, AttributeError) as exc:
            QMessageBox.critical(
                self,
                "Open Sequence",
                f"Could not load sequence from {file_path.name!r}:\n{exc}",
            )
            return
        dock.load_sequence(steps)
        self._current_measurement_path = file_path
        self._update_window_title()
        self._engine._rebuild_data_catalogs()

    def _on_save_measurement(self) -> None:
        """Save the current measurement sequence to the last-used file.

        Falls back to :meth:`_on_save_as_measurement` when no file has been
        chosen yet.
        """
        if self._current_measurement_path is None:
            self._on_save_as_measurement()
            return
        self._save_measurement_to(self._current_measurement_path)

    def _on_save_as_measurement(self) -> None:
        """Prompt the user for a file path and save the measurement sequence.

        Displays a save-file dialog restricted to ``.json`` files.  On
        success the chosen path becomes the new :attr:`_current_measurement_path`
        so that subsequent *Save* operations write to the same file.
        """
        start_dir = (
            str(self._current_measurement_path.parent)
            if self._current_measurement_path
            else make_app_settings().value(KEY_DEFAULT_DATA_DIR, "", type=str)
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Sequence",
            start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        file_path = Path(path)
        if file_path.suffix.lower() != ".json":
            file_path = file_path.with_suffix(".json")
        if self._save_measurement_to(file_path):
            self._current_measurement_path = file_path
            self._update_window_title()

    def _save_measurement_to(self, path: Path) -> bool:
        """Serialise the current sequence tree and write it to *path*.

        Args:
            path (Path):
                Destination file path.

        Returns:
            (bool):
                ``True`` on success, ``False`` if an error occurred (an error
                message box is shown to the user in that case).
        """
        from stoner_measurement.core.serializer import sequence_to_json

        steps = self._main_window.dock_panel.sequence_steps
        try:
            data = sequence_to_json(steps)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "Save Sequence",
                f"Could not save sequence to {path.name!r}:\n{exc}",
            )
            return False
        return True

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
        start_dir = (
            str(pane.path.parent)
            if pane and pane.path
            else make_app_settings().value(KEY_DEFAULT_DATA_DIR, "", type=str)
        )
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
        default_dir = make_app_settings().value(KEY_DEFAULT_DATA_DIR, "", type=str)
        if pane and pane.path:
            start = str(pane.path)
        elif default_dir:
            start = str(Path(default_dir) / "sequence.py")
        else:
            start = "sequence.py"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Script",
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
        """Dispatch the Run action to the appropriate handler for the active tab.

        On the *Script Editor* tab the current script pane is executed as-is
        (existing behaviour).  On the *Measurement* tab the sequence tree is
        converted to a script first and executed without switching away from
        the Measurement tab.
        """
        self._main_window.config_panel.commit_pending_changes()
        if self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT:
            self._on_run_from_measurement()
        else:
            self._on_run_from_editor()

    def _on_run_from_editor(self) -> None:
        """Execute the current script in the editor pane."""
        pane = self._main_window.script_tab.current_pane()
        script = self._main_window.script_tab.text
        customised = pane.customised if pane is not None else True
        line_map = None
        if not customised:
            # Auto-generated script: build the line-number → plugin map so that
            # exceptions can be attributed to the responsible sequence step.
            dock = self._main_window.dock_panel
            steps = dock.sequence_steps
            plugins = self._plugin_manager.plugins
            _, line_map = self._engine.generate_sequence_code(steps, plugins, return_line_map=True)
        self._main_window.tabs.setCurrentIndex(self._TAB_EDITOR)
        self._engine.run_script(script, customised=customised, line_map=line_map)

    def _on_run_from_measurement(self) -> None:
        """Convert the sequence to a script and execute it without switching tabs."""
        code, line_map = self._generate_to_script_tab(switch_to_editor=False)
        self._engine.run_script(code, customised=False, line_map=line_map)

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

        When called from the *Measurement* tab the script tab is updated in the
        background without switching away from the Measurement tab.  When called
        from the *Script Editor* tab the editor tab is brought to the front.
        """
        self._main_window.config_panel.commit_pending_changes()
        on_measurement = self._main_window.tabs.currentIndex() == self._TAB_MEASUREMENT
        self._generate_to_script_tab(switch_to_editor=not on_measurement)

    def _generate_to_script_tab(self, *, switch_to_editor: bool) -> tuple[str, dict]:
        """Generate sequence code and place it in a script pane.

        Injects per-step plugin instances into the engine namespace, generates
        executable Python code from the current sequence tree, and places the
        result into the script editor — reusing the current pane when it has
        not been user-edited, otherwise opening a new tab.

        Keyword Parameters:
            switch_to_editor (bool):
                When ``True``, the *Script Editor* tab is brought to the front
                after the code is written.  Pass ``False`` to keep the current
                tab active (e.g. when called from the Measurement tab).

        Returns:
            (tuple):
                A two-element tuple containing:

                - ``str`` — the generated Python source code.
                - ``dict`` — the line-number → plugin mapping produced by
                  :meth:`~stoner_measurement.core.sequence_engine.SequenceEngine.generate_sequence_code`
                  with ``return_line_map=True``.
        """
        from stoner_measurement.plugins.base_plugin import BasePlugin

        dock = self._main_window.dock_panel
        steps = dock.sequence_steps
        plugins = self._plugin_manager.plugins

        # Sync step plugins into the engine namespace so that sequence_engine
        # is set on all step plugins (including PlotTraceCommand instances) and
        # the _traces/_values catalogs are up to date before code generation.
        # This ensures PlotTraceCommand step plugins have their plot signals
        # connected to the plot widget before the script runs.
        self._sync_sequence_steps_to_engine()

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

        code, line_map = self._engine.generate_sequence_code(steps, plugins, return_line_map=True)
        script_tab = self._main_window.script_tab
        pane = script_tab.current_pane()
        if pane is None or pane.customised:
            # No open tabs, or current tab has been user-edited: open a new tab.
            script_tab.add_tab(code)
        else:
            # Current tab is unmodified generated (or fresh): replace its content.
            pane.set_text(code)
        if switch_to_editor:
            self._main_window.tabs.setCurrentIndex(self._TAB_EDITOR)
        return code, line_map

    def _on_show_temp_panel(self) -> None:
        """Show the temperature control panel, raising it if already open."""
        self._temp_panel.show_and_raise()

    def _on_stop_temp_engine(self) -> None:
        """Stop the temperature controller engine and disconnect the instrument."""
        from stoner_measurement.temperature_control.engine import TemperatureControllerEngine

        TemperatureControllerEngine.instance().shutdown()

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

    def _on_settings(self) -> None:
        """Open the Preferences dialogue."""
        dlg = SettingsDialog(parent=self)
        dlg.exec()

    def _on_show_log(self) -> None:
        """Show the log viewer window, bringing it to the front if already open."""
        self._log_viewer.show_and_raise()

    def _update_window_title(self) -> None:
        """Refresh the window title to reflect the active tab and file."""
        tab_idx = self._main_window.tabs.currentIndex()
        if tab_idx == self._TAB_MEASUREMENT:
            if self._current_measurement_path is None:
                self.setWindowTitle("Stoner Measurement")
            else:
                self.setWindowTitle(f"Stoner Measurement — {self._current_measurement_path.name}")
            return
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
        """Save window geometry and cleanly shut down engines on close."""
        settings = QSettings()
        settings.setValue("mainWindow/geometry", self.saveGeometry())
        self._engine.shutdown()
        from stoner_measurement.temperature_control.engine import TemperatureControllerEngine

        TemperatureControllerEngine.instance().shutdown()
        super().closeEvent(event)
