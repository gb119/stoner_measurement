"""Standalone log-viewer window for the Stoner Measurement application.

Provides :class:`LogViewerWindow`, a non-modal, always-on-top window that
displays log records emitted by the application logger as a growing,
colour-coded list with fine-grained filtering controls.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from qtpy.QtCore import QSettings, Qt
from qtpy.QtGui import QCloseEvent, QColor, QFont, QTextCharFormat, QTextCursor
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.qt_compat import pyqtSignal, pyqtSlot
from stoner_measurement.ui.theme import colour, validation_error_lineedit_stylesheet

#: Colour map from logging level to display colour.
_LEVEL_COLOURS: dict[int, QColor] = {
    logging.DEBUG: QColor(colour("log_debug")),
    logging.INFO: QColor(colour("log_info")),
    logging.WARNING: QColor(colour("log_warning")),
    logging.ERROR: QColor(colour("log_error")),
    logging.CRITICAL: QColor(colour("log_critical")),
}

_TRAFFIC_FILTER_LABELS: dict[str, str] = {
    "all": "All logs",
    "comms": "Instrument comms",
    "tx": "Instrument TX",
    "rx": "Instrument RX",
    "no-comms": "Hide comms",
}

_LEVEL_OPTIONS: tuple[tuple[str, int], ...] = (
    ("DEBUG", logging.DEBUG),
    ("INFO", logging.INFO),
    ("WARNING", logging.WARNING),
    ("ERROR", logging.ERROR),
    ("CRITICAL", logging.CRITICAL),
)

_SETTINGS_GROUP = "LogViewer"
_ALL_PREFIXES_SENTINEL = "__all__"
_ROOT_LOGGER_NAME = "stoner_measurement"
_SEQUENCE_PREFIX = f"{_ROOT_LOGGER_NAME}.sequence"
_INSTRUMENT_PREFIX = f"{_SEQUENCE_PREFIX}.comms."
_TEMPERATURE_PREFIX = f"{_ROOT_LOGGER_NAME}.temperature_control"
_MAGNET_PREFIX = f"{_ROOT_LOGGER_NAME}.magnet_control"
_PLUGIN_PREFIX = f"{_ROOT_LOGGER_NAME}.plugins."
_DISPLAY_SOURCE_BUTTON_TEXT = "Sources…"
_FILE_LOGGING_BUTTON_TEXT = "File logging…"
_FILE_LOG_FORMAT = "[%(asctime)s] %(levelname)-8s %(message)s"


@dataclass(slots=True)
class LogFilterState:
    """State describing how log records should be filtered.

    Attributes:
        min_level (int):
            Minimum level a record must meet to be included.
        enabled_prefixes (set[str] | None):
            Allowed logger-name prefixes. ``None`` means all discovered sources.
        traffic_mode (str):
            One of the keys in :data:`_TRAFFIC_FILTER_LABELS`.
        message_pattern (str):
            Optional regular expression that must match the rendered message.
    """

    min_level: int = logging.DEBUG
    enabled_prefixes: set[str] | None = None
    traffic_mode: str = "all"
    message_pattern: str = ""


@dataclass(slots=True)
class FileLogState:
    """State describing optional file logging configuration.

    Attributes:
        file_path (str | None):
            Destination path for the log file.
        min_level (int):
            Minimum level a record must meet to be written.
        enabled_prefixes (set[str] | None):
            Allowed logger-name prefixes. ``None`` means all discovered sources.
        message_pattern (str):
            Optional regular expression that must match the rendered message.
        traffic_mode (str):
            One of the keys in :data:`_TRAFFIC_FILTER_LABELS`.
        append (bool):
            When ``True``, append to an existing file instead of overwriting it.
    """

    file_path: str | None = None
    min_level: int = logging.DEBUG
    enabled_prefixes: set[str] | None = None
    message_pattern: str = ""
    traffic_mode: str = "all"
    append: bool = True


class LogSourcesWidget(QWidget):
    """Tree widget that tracks and selects discovered log sources.

    Sources are grouped into fixed top-level categories and each discovered
    logger prefix appears as a checkable child entry.
    """

    sources_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialise the widget.

        Args:
            parent (QWidget | None):
                Optional parent widget.
        """
        super().__init__(parent)
        self._desired_prefixes: set[str] | None = None
        self._items_by_prefix: dict[str, QTreeWidgetItem] = {}
        self._group_items: dict[str, QTreeWidgetItem] = {}

        self._btn_select_all = QPushButton("Select All", self)
        self._btn_select_all.clicked.connect(self.select_all)
        self._btn_deselect_all = QPushButton("Deselect All", self)
        self._btn_deselect_all.clicked.connect(self.deselect_all)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.itemChanged.connect(self._on_item_changed)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addWidget(self._btn_select_all)
        button_row.addWidget(self._btn_deselect_all)
        button_row.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(button_row)
        layout.addWidget(self._tree)
        self.setLayout(layout)

        for key, label in (
            ("sequence", "Sequence"),
            ("instruments", "Instruments"),
            ("temperature", "Temperature"),
            ("magnet", "Magnet"),
            ("plugins", "Plugins"),
            ("other", "Other"),
        ):
            item = QTreeWidgetItem([label])
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setHidden(True)
            item.setExpanded(True)
            self._tree.addTopLevelItem(item)
            self._group_items[key] = item

    @property
    def selected_prefixes(self) -> set[str] | None:
        """Return the selected prefixes, or ``None`` if every source is enabled."""
        if not self._items_by_prefix:
            return None if self._desired_prefixes is None else set(self._desired_prefixes)
        checked = {
            prefix
            for prefix, item in self._items_by_prefix.items()
            if item.checkState(0) == Qt.CheckState.Checked
        }
        if len(checked) == len(self._items_by_prefix):
            return None
        return checked

    def set_selected_prefixes(self, prefixes: set[str] | None) -> None:
        """Apply *prefixes* as the current selection."""
        self._desired_prefixes = None if prefixes is None else set(prefixes)
        self._tree.blockSignals(True)
        try:
            for prefix, item in self._items_by_prefix.items():
                check_state = self._check_state_for_prefix(prefix)
                item.setCheckState(0, check_state)
        finally:
            self._tree.blockSignals(False)
        self.sources_changed.emit()

    def register_source(self, name: str) -> None:
        """Add a discovered logger *name* to the tree if required."""
        group_key, prefix, label = self._classify_source(name)
        if prefix in self._items_by_prefix:
            return
        item = QTreeWidgetItem([label])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(0, Qt.ItemDataRole.UserRole, prefix)
        item.setCheckState(0, self._check_state_for_prefix(prefix))
        group_item = self._group_items[group_key]
        group_item.addChild(item)
        group_item.setHidden(False)
        self._items_by_prefix[prefix] = item

    @pyqtSlot()
    def select_all(self) -> None:
        """Select all currently discovered sources."""
        self._desired_prefixes = None
        self._tree.blockSignals(True)
        try:
            for item in self._items_by_prefix.values():
                item.setCheckState(0, Qt.CheckState.Checked)
        finally:
            self._tree.blockSignals(False)
        self.sources_changed.emit()

    @pyqtSlot()
    def deselect_all(self) -> None:
        """Deselect all currently discovered sources."""
        self._desired_prefixes = set()
        self._tree.blockSignals(True)
        try:
            for item in self._items_by_prefix.values():
                item.setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self._tree.blockSignals(False)
        self.sources_changed.emit()

    def _check_state_for_prefix(self, prefix: str) -> Qt.CheckState:
        """Return the check state for *prefix* using the desired selection."""
        if self._desired_prefixes is None or prefix in self._desired_prefixes:
            return Qt.CheckState.Checked
        return Qt.CheckState.Unchecked

    def _classify_source(self, name: str) -> tuple[str, str, str]:
        """Return group key, filter prefix, and label for *name*."""
        if name.startswith(_INSTRUMENT_PREFIX):
            return "instruments", name, name.rsplit(".", 1)[-1]
        if name == _SEQUENCE_PREFIX or name.startswith(f"{_SEQUENCE_PREFIX}."):
            return "sequence", _SEQUENCE_PREFIX, "Sequence"
        if name.startswith(_TEMPERATURE_PREFIX):
            label = name.removeprefix(f"{_TEMPERATURE_PREFIX}.")
            return "temperature", name, label or "temperature_control"
        if name.startswith(_MAGNET_PREFIX):
            label = name.removeprefix(f"{_MAGNET_PREFIX}.")
            return "magnet", name, label or "magnet_control"
        if name.startswith(_PLUGIN_PREFIX):
            return "plugins", name, name.rsplit(".", 1)[-1]
        label = name.removeprefix(f"{_ROOT_LOGGER_NAME}.")
        return "other", name, label or name

    @pyqtSlot(QTreeWidgetItem, int)
    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        """Update the desired selection after a child-item toggle."""
        prefix = item.data(0, Qt.ItemDataRole.UserRole)
        if not prefix:
            return
        self._desired_prefixes = self.selected_prefixes
        self.sources_changed.emit()


class LogViewerWindow(QWidget):
    """Non-modal, always-on-top window that displays application log messages.

    Receives :class:`logging.LogRecord` objects via the :meth:`append_record`
    slot and renders them as a timestamped, colour-coded list in a read-only
    text area. The window stays on top of the main application window but does
    not block interaction with it.

    The window can be opened and raised via :meth:`show_and_raise` and
    programmatically cleared with :meth:`clear`.

    Args:
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> app = QApplication.instance() or QApplication([])
        >>> viewer = LogViewerWindow()
        >>> viewer.windowTitle()
        'Log Viewer'
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowTitle("Log Viewer")
        self.resize(760, 520)
        self._records: list[logging.LogRecord] = []
        self._filter_state = LogFilterState()
        self._file_log_state = FileLogState()
        self._allow_exit_close = False
        self._file_handler: logging.FileHandler | None = None
        self._restoring_settings = False

        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)
        mono = QFont("Courier New", 9)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._output.setFont(mono)
        self._output.setMaximumBlockCount(2000)
        self._output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._btn_clear = QPushButton("Clear", self)
        self._btn_clear.setFixedWidth(70)
        self._btn_clear.clicked.connect(self.clear)

        self._btn_close = QPushButton("Close", self)
        self._btn_close.setFixedWidth(70)
        self._btn_close.clicked.connect(self.hide)

        self._display_level = self._build_level_combo(self)
        self._display_level.currentIndexChanged.connect(self._on_filter_changed)

        self._traffic_filter = QComboBox(self)
        for key, label in _TRAFFIC_FILTER_LABELS.items():
            self._traffic_filter.addItem(label, key)
        self._traffic_filter.currentIndexChanged.connect(self._on_filter_changed)
        self._message_filter = QLineEdit(self)
        self._message_filter.setPlaceholderText("Message regexp")
        self._message_filter.setClearButtonEnabled(True)
        self._message_filter.textChanged.connect(self._on_filter_changed)

        self._btn_display_sources = QPushButton(_DISPLAY_SOURCE_BUTTON_TEXT, self)
        self._btn_display_sources.setCheckable(True)
        self._btn_display_sources.toggled.connect(self._toggle_display_sources)

        self._display_sources = LogSourcesWidget(self)
        self._display_sources.sources_changed.connect(self._on_filter_changed)
        self._display_sources_scroll = self._build_sources_scroll_area(self._display_sources, self)
        self._display_sources_scroll.setVisible(False)

        self._btn_file_logging = QPushButton(_FILE_LOGGING_BUTTON_TEXT, self)
        self._btn_file_logging.setCheckable(True)
        self._btn_file_logging.toggled.connect(self._toggle_file_logging_panel)

        self._file_panel = QWidget(self)
        self._file_panel.setVisible(False)

        self._file_enabled = QCheckBox("Enable", self._file_panel)
        self._file_enabled.toggled.connect(self._on_file_enabled_toggled)
        self._file_status = QLabel("Not logging", self._file_panel)

        self._file_path = QLineEdit(self._file_panel)
        self._file_path.textChanged.connect(self._on_file_config_changed)
        self._btn_browse = QPushButton("Browse…", self._file_panel)
        self._btn_browse.clicked.connect(self._browse_for_log_file)

        self._file_mode = QComboBox(self._file_panel)
        self._file_mode.addItem("Append", True)
        self._file_mode.addItem("Overwrite", False)
        self._file_mode.currentIndexChanged.connect(self._on_file_config_changed)

        self._file_level = self._build_level_combo(self._file_panel)
        self._file_level.currentIndexChanged.connect(self._on_file_config_changed)

        self._file_traffic_filter = QComboBox(self._file_panel)
        for key, label in _TRAFFIC_FILTER_LABELS.items():
            self._file_traffic_filter.addItem(label, key)
        self._file_traffic_filter.currentIndexChanged.connect(self._on_file_config_changed)
        self._file_message_filter = QLineEdit(self._file_panel)
        self._file_message_filter.setPlaceholderText("Message regexp")
        self._file_message_filter.setClearButtonEnabled(True)
        self._file_message_filter.textChanged.connect(self._on_file_config_changed)
        self._file_sources = LogSourcesWidget(self._file_panel)
        self._file_sources.sources_changed.connect(self._on_file_config_changed)
        self._file_sources_scroll = self._build_sources_scroll_area(self._file_sources, self._file_panel)

        self._btn_file_apply = QPushButton("Apply", self._file_panel)
        self._btn_file_apply.clicked.connect(self._apply_file_logging)
        self._btn_file_stop = QPushButton("Stop", self._file_panel)
        self._btn_file_stop.clicked.connect(self._on_stop_file_logging_clicked)

        self._build_layout()
        self._restore_settings()
        self._sync_filter_state_from_controls()
        self._sync_file_state_from_controls()
        self._update_file_logging_controls()
        self._update_file_logging_status()

    def show_and_raise(self) -> None:
        """Show the window and bring it to the front.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> viewer = LogViewerWindow()
            >>> viewer.show_and_raise()
            >>> viewer.isVisible()
            True
        """
        self.show()
        self.raise_()
        self.activateWindow()

    @pyqtSlot()
    def clear(self) -> None:
        """Clear all log messages from the display.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> viewer = LogViewerWindow()
            >>> import logging
            >>> record = logging.LogRecord(
            ...     name="test", level=logging.INFO, pathname="",
            ...     lineno=0, msg="hello", args=(), exc_info=None)
            >>> viewer.append_record(record)
            >>> viewer.clear()
        """
        self._records.clear()
        self._output.clear()

    @pyqtSlot(logging.LogRecord)
    def append_record(self, record: logging.LogRecord) -> None:
        """Append a formatted log *record* to the display.

        Records at ``DEBUG`` level are shown in grey; ``INFO`` in black;
        ``WARNING`` in amber; ``ERROR`` in red; ``CRITICAL`` in dark red.

        Args:
            record (logging.LogRecord):
                The log record to display.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> viewer = LogViewerWindow()
            >>> import logging
            >>> record = logging.LogRecord(
            ...     name="test", level=logging.WARNING, pathname="",
            ...     lineno=0, msg="watch out", args=(), exc_info=None)
            >>> viewer.append_record(record)
        """
        self._on_source_registered(record.name)
        self._records.append(record)
        if self._record_matches_filter(record, self._filter_state):
            self._render_record(record)
        if self._file_handler is not None and self._record_matches_filter(record, self._file_log_state):
            self._file_handler.handle(record)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop file logging and persist settings before the window closes."""
        self._stop_file_logging()
        self._save_settings()
        super().closeEvent(event)

    def _build_layout(self) -> None:
        """Create the top-level layout for the viewer."""
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.addWidget(QLabel("Level", self))
        filter_row.addWidget(self._display_level)
        filter_row.addWidget(QLabel("Traffic", self))
        filter_row.addWidget(self._traffic_filter)
        filter_row.addWidget(QLabel("Message", self))
        filter_row.addWidget(self._message_filter, 1)
        filter_row.addWidget(self._btn_display_sources)
        filter_row.addStretch()
        filter_row.addWidget(self._btn_clear)
        filter_row.addWidget(self._btn_close)

        file_grid = QGridLayout(self._file_panel)
        file_grid.setContentsMargins(0, 0, 0, 0)
        file_grid.addWidget(self._file_enabled, 0, 0)
        file_grid.addWidget(self._file_status, 0, 1, 1, 3)
        file_grid.addWidget(QLabel("Path", self._file_panel), 1, 0)
        file_grid.addWidget(self._file_path, 1, 1, 1, 2)
        file_grid.addWidget(self._btn_browse, 1, 3)
        file_grid.addWidget(QLabel("Mode", self._file_panel), 2, 0)
        file_grid.addWidget(self._file_mode, 2, 1)
        file_grid.addWidget(QLabel("Min level", self._file_panel), 2, 2)
        file_grid.addWidget(self._file_level, 2, 3)
        file_grid.addWidget(QLabel("Traffic", self._file_panel), 3, 0)
        file_grid.addWidget(self._file_traffic_filter, 3, 1, 1, 3)
        file_grid.addWidget(QLabel("Message", self._file_panel), 4, 0)
        file_grid.addWidget(self._file_message_filter, 4, 1, 1, 3)
        file_grid.addWidget(self._file_sources_scroll, 5, 0, 1, 4)
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addStretch()
        button_row.addWidget(self._btn_file_apply)
        button_row.addWidget(self._btn_file_stop)
        file_grid.addLayout(button_row, 6, 0, 1, 4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._output)
        layout.addLayout(filter_row)
        layout.addWidget(self._display_sources_scroll)
        layout.addWidget(self._btn_file_logging)
        layout.addWidget(self._file_panel)
        self.setLayout(layout)

    def _build_level_combo(self, parent: QWidget) -> QComboBox:
        """Return a level-selection combo box."""
        combo = QComboBox(parent)
        for label, level in _LEVEL_OPTIONS:
            combo.addItem(label, level)
        return combo

    def _build_sources_scroll_area(self, widget: QWidget, parent: QWidget) -> QScrollArea:
        """Wrap *widget* in a bounded scroll area."""
        scroll_area = QScrollArea(parent)
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(180)
        scroll_area.setWidget(widget)
        return scroll_area

    def _toggle_display_sources(self, checked: bool) -> None:
        """Show or hide the display-sources panel."""
        self._display_sources_scroll.setVisible(checked)
        self._btn_display_sources.setText(
            f"{_DISPLAY_SOURCE_BUTTON_TEXT} {'▾' if checked else '▸'}"
        )
        self._save_settings()

    def _toggle_file_logging_panel(self, checked: bool) -> None:
        """Show or hide the file-logging panel."""
        self._file_panel.setVisible(checked)
        self._btn_file_logging.setText(
            f"{_FILE_LOGGING_BUTTON_TEXT} {'▾' if checked else '▸'}"
        )
        self._save_settings()

    def _on_filter_changed(self, *_args: object) -> None:
        """Rebuild the visible log list after a display filter change."""
        self._sync_filter_state_from_controls()
        self._validate_regex_field(self._message_filter)
        self._output.clear()
        for record in self._records:
            if self._record_matches_filter(record, self._filter_state):
                self._render_record(record)
        self._save_settings()

    def _on_file_config_changed(self, *_args: object) -> None:
        """Update cached file-logging state after a settings change."""
        self._sync_file_state_from_controls()
        self._validate_regex_field(self._file_message_filter)
        self._update_file_logging_controls()
        self._save_settings()

    def _on_file_enabled_toggled(self, checked: bool) -> None:
        """React to the file-logging enable checkbox."""
        self._sync_file_state_from_controls()
        if not checked and self._file_handler is not None:
            self._stop_file_logging()
            return
        self._update_file_logging_controls()
        self._save_settings()

    def _on_source_registered(self, name: str) -> None:
        """Register a new logger name with the source selectors."""
        self._display_sources.register_source(name)
        self._file_sources.register_source(name)

    def _sync_filter_state_from_controls(self) -> None:
        """Copy the display-filter controls into :attr:`_filter_state`."""
        self._filter_state.min_level = int(self._display_level.currentData() or logging.DEBUG)
        self._filter_state.traffic_mode = str(self._traffic_filter.currentData() or "all")
        self._filter_state.enabled_prefixes = self._display_sources.selected_prefixes
        self._filter_state.message_pattern = self._message_filter.text().strip()

    def _sync_file_state_from_controls(self) -> None:
        """Copy the file-logging controls into :attr:`_file_log_state`."""
        text = self._file_path.text().strip()
        self._file_log_state.file_path = text or None
        self._file_log_state.min_level = int(self._file_level.currentData() or logging.DEBUG)
        self._file_log_state.enabled_prefixes = self._file_sources.selected_prefixes
        self._file_log_state.traffic_mode = str(self._file_traffic_filter.currentData() or "all")
        self._file_log_state.message_pattern = self._file_message_filter.text().strip()
        self._file_log_state.append = bool(self._file_mode.currentData())

    def _logger_name_matches_prefix(self, logger_name: str, prefix: str) -> bool:
        """Return ``True`` when *prefix* matches *logger_name* on a name boundary."""
        return logger_name == prefix or logger_name.startswith(f"{prefix}.")

    def _record_matches_enabled_prefixes(
        self, record: logging.LogRecord, enabled_prefixes: set[str] | None
    ) -> bool:
        """Return ``True`` when *record* matches the most specific enabled prefix."""
        if enabled_prefixes is None:
            return True

        matching_prefixes = [
            prefix for prefix in enabled_prefixes if self._logger_name_matches_prefix(record.name, prefix)
        ]
        if not matching_prefixes:
            return False

        most_specific_prefix = max(matching_prefixes, key=len)
        return most_specific_prefix in enabled_prefixes

    def _record_matches_filter(self, record: logging.LogRecord, state: LogFilterState | FileLogState) -> bool:
        """Return ``True`` when *record* passes *state*."""
        if record.levelno < state.min_level:
            return False
        if not self._record_matches_enabled_prefixes(record, state.enabled_prefixes):
            return False
        if not self._record_matches_message_pattern(record, getattr(state, "message_pattern", "")):
            return False
        return self._record_matches_traffic_mode(record, getattr(state, "traffic_mode", "all"))

    def _record_matches_traffic_mode(self, record: logging.LogRecord, mode: str) -> bool:
        """Return ``True`` when *record* passes the traffic filter *mode*."""
        channel = getattr(record, "sm_traffic_channel", "")
        direction = getattr(record, "sm_traffic_direction", "")
        if mode == "all":
            return True
        if mode == "comms":
            return channel == "instrument_comms"
        if mode == "tx":
            return channel == "instrument_comms" and direction == "TX"
        if mode == "rx":
            return channel == "instrument_comms" and direction == "RX"
        if mode == "no-comms":
            return channel != "instrument_comms"
        return True

    def _validate_regex_field(self, field: QLineEdit) -> None:
        """Update *field* styling and tooltip based on regexp validity."""
        pattern = field.text().strip()
        if not pattern:
            field.setStyleSheet("")
            field.setToolTip("")
            return
        try:
            re.compile(pattern)
        except re.error as exc:
            field.setStyleSheet(validation_error_lineedit_stylesheet())
            field.setToolTip(f"Invalid regular expression: {exc}")
            return
        field.setStyleSheet("")
        field.setToolTip("")

    def _validate_regex_fields(self) -> None:
        """Refresh validation state for all regexp input fields."""
        self._validate_regex_field(self._message_filter)
        self._validate_regex_field(self._file_message_filter)

    def _record_matches_message_pattern(self, record: logging.LogRecord, pattern: str) -> bool:
        """Return ``True`` when *record* passes the message regexp *pattern*."""
        if not pattern:
            return True
        try:
            message = record.getMessage()
        except (TypeError, KeyError, ValueError):
            message = str(record.msg)
        try:
            return re.search(pattern, message) is not None
        except re.error:
            return True

    def _format_record_text(self, record: logging.LogRecord) -> str:
        """Return the on-screen text representation for *record*."""
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        level_name = record.levelname
        try:
            message = record.getMessage()
        except (TypeError, KeyError, ValueError):
            message = str(record.msg)
        return f"[{timestamp}] {level_name:8s} {message}"

    def _render_record(self, record: logging.LogRecord) -> None:
        """Render one log *record* into the output text area."""
        text = self._format_record_text(record)

        colour = _LEVEL_COLOURS.get(record.levelno)
        if colour is None:
            for level in sorted(_LEVEL_COLOURS, reverse=True):
                if record.levelno >= level:
                    colour = _LEVEL_COLOURS[level]
                    break

        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if colour is not None:
            fmt = QTextCharFormat()
            fmt.setForeground(colour)
            cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        cursor.setCharFormat(QTextCharFormat())
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _browse_for_log_file(self) -> None:
        """Open a save-file dialog for the file log destination."""
        start_dir = self._file_path.text().strip() or str(Path.home() / "stoner_measurement.log")
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Choose log file",
            start_dir,
            "Log files (*.log *.txt);;All files (*)",
        )
        if path:
            self._file_path.setText(path)

    def _apply_file_logging(self) -> None:
        """Open the configured file handler and start writing matching records."""
        self._sync_file_state_from_controls()
        if not self._file_enabled.isChecked() or not self._file_log_state.file_path:
            self._update_file_logging_status("File logging is disabled")
            return

        path = Path(self._file_log_state.file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stop_file_logging(update_status=False)
        mode = "a" if self._file_log_state.append else "w"
        self._file_handler = logging.FileHandler(path, mode=mode, encoding="utf-8")
        self._file_handler.setLevel(self._file_log_state.min_level)
        self._file_handler.setFormatter(logging.Formatter(_FILE_LOG_FORMAT, datefmt="%H:%M:%S"))
        self._update_file_logging_controls()
        self._update_file_logging_status()
        self._save_settings()

    @pyqtSlot(bool)
    def _on_stop_file_logging_clicked(self, _checked: bool = False) -> None:
        """Handle clicks from the file-logging stop button."""
        self._stop_file_logging()

    def _stop_file_logging(self, *, update_status: bool = True) -> None:
        """Close the file handler if one is active."""
        if self._file_handler is not None:
            self._file_handler.flush()
            self._file_handler.close()
            self._file_handler = None
        self._update_file_logging_controls()
        if update_status:
            self._update_file_logging_status()
        self._save_settings()

    def _update_file_logging_controls(self) -> None:
        """Enable or disable buttons based on file-logging state."""
        can_apply = self._file_enabled.isChecked() and bool(self._file_path.text().strip())
        self._btn_file_apply.setEnabled(can_apply)
        self._btn_file_stop.setEnabled(self._file_handler is not None)

    def _update_file_logging_status(self, text: str | None = None) -> None:
        """Refresh the status text for file logging."""
        if text is not None:
            self._file_status.setText(text)
            return
        if self._file_handler is None:
            self._file_status.setText("Not logging")
            return
        path = self._file_log_state.file_path or ""
        self._file_status.setText(f"Logging to: {path}")

    def _restore_settings(self) -> None:
        """Restore persisted viewer settings."""
        self._restoring_settings = True
        settings = QSettings()
        try:
            settings.beginGroup(_SETTINGS_GROUP)
            self._set_combo_data(self._display_level, settings.value("display_min_level", logging.DEBUG, int))
            self._set_combo_data(self._traffic_filter, settings.value("display_traffic_mode", "all", str))
            self._message_filter.setText(settings.value("display_message_pattern", "", str))
            self._display_sources.set_selected_prefixes(
                self._read_prefix_setting(settings, "display_enabled_prefixes")
            )

            self._btn_display_sources.setChecked(settings.value("display_sources_visible", False, bool))
            self._btn_file_logging.setChecked(settings.value("file_panel_visible", False, bool))

            self._file_enabled.setChecked(settings.value("file_enabled", False, bool))
            self._file_path.setText(settings.value("file_path", "", str))
            self._set_combo_data(self._file_mode, settings.value("file_append", True, bool))
            self._set_combo_data(self._file_level, settings.value("file_min_level", logging.DEBUG, int))
            self._set_combo_data(self._file_traffic_filter, settings.value("file_traffic_mode", "all", str))
            self._file_message_filter.setText(settings.value("file_message_pattern", "", str))
            self._file_sources.set_selected_prefixes(
                self._read_prefix_setting(settings, "file_enabled_prefixes")
            )
            settings.endGroup()
        finally:
            self._restoring_settings = False
        self._validate_regex_fields()

    def _save_settings(self) -> None:
        """Persist viewer settings using :class:`QSettings`."""
        if self._restoring_settings:
            return
        settings = QSettings()
        settings.beginGroup(_SETTINGS_GROUP)
        settings.setValue("display_min_level", int(self._display_level.currentData() or logging.DEBUG))
        settings.setValue("display_traffic_mode", self._traffic_filter.currentData() or "all")
        settings.setValue("display_message_pattern", self._message_filter.text().strip())
        settings.setValue(
            "display_enabled_prefixes",
            self._serialise_prefixes(self._display_sources.selected_prefixes),
        )
        settings.setValue("display_sources_visible", self._btn_display_sources.isChecked())
        settings.setValue("file_panel_visible", self._btn_file_logging.isChecked())
        settings.setValue("file_enabled", self._file_enabled.isChecked())
        settings.setValue("file_path", self._file_path.text().strip())
        settings.setValue("file_append", bool(self._file_mode.currentData()))
        settings.setValue("file_min_level", int(self._file_level.currentData() or logging.DEBUG))
        settings.setValue("file_traffic_mode", self._file_traffic_filter.currentData() or "all")
        settings.setValue("file_message_pattern", self._file_message_filter.text().strip())
        settings.setValue(
            "file_enabled_prefixes",
            self._serialise_prefixes(self._file_sources.selected_prefixes),
        )
        settings.endGroup()
        settings.sync()

    def _read_prefix_setting(self, settings: QSettings, key: str) -> set[str] | None:
        """Read a prefix selection from *settings*."""
        value = settings.value(key, _ALL_PREFIXES_SENTINEL)
        if value == _ALL_PREFIXES_SENTINEL:
            return None
        if isinstance(value, list):
            return {str(entry) for entry in value}
        if value in (None, ""):
            return set()
        return {str(value)}

    def _serialise_prefixes(self, prefixes: set[str] | None) -> str | list[str]:
        """Serialise *prefixes* for :class:`QSettings`."""
        if prefixes is None:
            return _ALL_PREFIXES_SENTINEL
        return sorted(prefixes)

    def _set_combo_data(self, combo: QComboBox, value: object) -> None:
        """Select the first combo-box entry whose data matches *value*."""
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
