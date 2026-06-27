"""Always-on-top live value watch window for the Stoner Measurement application.

Provides :class:`ValueWatchWindow`, a non-modal window that lets the user pick
entries from the sequence engine's ``_values`` catalogue and display their live
values using large readouts. The window includes an expandable configuration
panel for filtering and selecting watched values.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite, log10

from qtpy import QtCore, QtGui, QtWidgets  # pylint: disable=no-name-in-module
from qtpy.QtCore import QSettings, Qt  # pylint: disable=no-name-in-module

from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.qt_compat import pyqtSignal, pyqtSlot
from stoner_measurement.resources import bundled_resource_path
from stoner_measurement.ui.theme import (
    colour,
    muted_label_stylesheet,
    value_display_frame_stylesheet,
)

_SETTINGS_GROUP = "ValueWatch"
_CONFIG_BUTTON_TEXT = "Configure…"
_MAX_COLUMNS = 2
_BUTTON_STYLE_CHECKED = (
    "QPushButton:checked { "
    f"background-color: {colour('highlight')}; "
    f"color: {colour('highlighted_text')}; "
    f"border: 1px solid {colour('link')}; "
    "}"
)
_EDGE_SNAP_THRESHOLD_PX = 24
_EDGE_SNAP_WIDTH_RATIO = 0.25
_EDGE_SNAP_MIN_WIDTH_PX = 320
_EDGE_SNAP_MAX_COLUMNS = 3
_EDGE_SNAP_VERTICAL_PADDING_PX = 8
_REFRESH_INTERVAL_MS = 250
_DISPLAY_FIXED_WIDTH = 280
_DEFAULT_SIGNIFICANT_FIGURES = 4
_FORMAT_SI = "si"
_FORMAT_FLOAT = "float"
_FORMAT_SCIENTIFIC = "scientific"


class _SnapPreviewOverlay(QtWidgets.QWidget):
    """Translucent overlay showing the pending snap target."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowOpacity(0.18)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Paint the snap preview overlay."""
        _ = event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor("#60a5fa"))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(QtGui.QColor(96, 165, 250, 96))
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawRoundedRect(rect, 10, 10)

    def show_preview(self, geometry: QtCore.QRect) -> None:
        """Show the overlay at *geometry*."""
        self.setGeometry(geometry)
        self.show()
        self.raise_()


@dataclass(slots=True)
class WatchEntry:
    """State describing one watched value.

    Attributes:
        key (str):
            Human-readable value key from the engine ``_values`` catalogue.
        expression (str):
            Python expression used to read the live value from the namespace.
        enabled (bool):
            Whether this value should currently be displayed.
        format_style (str):
            Display formatting style for numeric values.
        significant_figures (int):
            Number of significant figures used for numeric values.
    """

    key: str
    expression: str
    enabled: bool = True
    format_style: str = _FORMAT_SI
    significant_figures: int = _DEFAULT_SIGNIFICANT_FIGURES


class ValueSelectionWidget(QtWidgets.QWidget):
    """Filterable list of checkboxes for selecting watched values."""

    selection_changed = pyqtSignal()
    empty_state_requested = pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        """Initialise the selector widget.

        Args:
            parent (QWidget | None):
                Optional parent widget.
        """
        super().__init__(parent)
        self._checkboxes: dict[str, QtWidgets.QCheckBox] = {}
        self._expressions: dict[str, str] = {}

        self._rebuilding_catalog = False
        self._btn_select_all = QtWidgets.QPushButton("Select All", self)
        self._btn_select_all.clicked.connect(self.select_all)
        self._btn_deselect_all = QtWidgets.QPushButton("Deselect All", self)
        self._btn_deselect_all.clicked.connect(self.deselect_all)

        self._filter_edit = QtWidgets.QLineEdit(self)
        self._filter_edit.setPlaceholderText("Filter values...")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._apply_filter)

        self._list_container = QtWidgets.QWidget(self)
        self._list_layout = QtWidgets.QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()

        self._empty_label = QtWidgets.QLabel(self._list_container)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(muted_label_stylesheet())
        self._empty_label.hide()
        self._list_layout.insertWidget(0, self._empty_label)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.addWidget(self._btn_select_all)
        button_row.addWidget(self._btn_deselect_all)
        button_row.addStretch()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._filter_edit)
        layout.addLayout(button_row)
        layout.addWidget(self._list_container)
        self.setLayout(layout)

    @property
    def selected_keys(self) -> set[str]:
        """Return the set of currently selected value keys."""
        return {key for key, checkbox in self._checkboxes.items() if checkbox.isChecked()}

    def set_catalog(self, catalog: dict[str, str], selected_keys: set[str] | None = None) -> None:
        """Replace the displayed value list from *catalog*.

        Args:
            catalog (dict[str, str]):
                Value catalogue mapping display keys to expressions.
            selected_keys (set[str] | None):
                Optional set of keys that should remain selected. If ``None``,
                the current selection is preserved where possible.
        """
        if selected_keys is None:
            selected_keys = self.selected_keys

        self._rebuilding_catalog = True
        self._expressions = dict(sorted(catalog.items(), key=lambda item: item[0].lower()))
        try:
            while self._list_layout.count() > 2:
                item = self._list_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    try:
                        widget.setParent(None)
                    except RuntimeError:
                        pass
                    widget.deleteLater()

            self._checkboxes.clear()
            self.blockSignals(True)
            try:
                for key in self._expressions:
                    checkbox = QtWidgets.QCheckBox(key, self._list_container)
                    checkbox.setChecked(key in selected_keys)
                    checkbox.toggled.connect(self.selection_changed)
                    self._list_layout.insertWidget(self._list_layout.count() - 1, checkbox)
                    self._checkboxes[key] = checkbox
            finally:
                self.blockSignals(False)

            self._update_empty_state()
            self._apply_filter(self._filter_edit.text())
        finally:
            self._rebuilding_catalog = False

        self.selection_changed.emit()

    @pyqtSlot()
    def select_all(self) -> None:
        """Select all displayed values."""
        self.blockSignals(True)
        try:
            for checkbox in self._checkboxes.values():
                checkbox.setChecked(True)
        finally:
            self.blockSignals(False)
        self.selection_changed.emit()

    @pyqtSlot()
    def deselect_all(self) -> None:
        """Deselect all displayed values."""
        self.blockSignals(True)
        try:
            for checkbox in self._checkboxes.values():
                checkbox.setChecked(False)
        finally:
            self.blockSignals(False)
        self.selection_changed.emit()

    @pyqtSlot(str)
    def _apply_filter(self, text: str) -> None:
        """Show only value names containing *text*.

        Args:
            text (str):
                Filter text.
        """
        if self._rebuilding_catalog:
            return
        needle = text.strip().lower()
        any_visible = False
        for key, checkbox in self._checkboxes.items():
            visible = not needle or needle in key.lower()
            checkbox.setVisible(visible)
            any_visible = any_visible or visible
        if self._checkboxes:
            if any_visible:
                self._empty_label.hide()
            else:
                self._empty_label.setText("No values match the current filter.")
                self._empty_label.show()

    def _update_empty_state(self) -> None:
        """Show a helpful message when no values are available."""
        if self._rebuilding_catalog:
            return
        has_values = bool(self._checkboxes)
        self._btn_select_all.setEnabled(has_values)
        self._btn_deselect_all.setEnabled(has_values)
        if has_values:
            self._empty_label.setText("No values match the current filter.")
            self._empty_label.hide()
            return
        self._empty_label.setText(
            "No watchable values are currently available.\n"
            "Try generating code so the engine can rebuild the value catalogue."
        )
        self._empty_label.show()
        self.empty_state_requested.emit()


class _WatchDisplay(QtWidgets.QWidget):
    """Large readout widget for a single watched value."""

    format_changed = pyqtSignal(str, int)

    def __init__(
        self,
        key: str,
        format_style: str,
        significant_figures: int,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        """Initialise the readout.

        Args:
            key (str):
                Display label for the watched value.
            format_style (str):
                Initial numeric formatting style.
            significant_figures (int):
                Initial number of significant figures.
            parent (QWidget | None):
                Optional parent widget.
        """
        super().__init__(parent)
        self._key = key
        self._format_style = format_style
        self._significant_figures = significant_figures
        self._suffix_text = ""
        self.setFixedWidth(_DISPLAY_FIXED_WIDTH)

        self._name_label = QtWidgets.QLabel(key, self)
        name_font = QtGui.QFont()
        name_font.setPointSize(13)
        name_font.setBold(True)
        self._name_label.setFont(name_font)
        self._name_label.setWordWrap(True)

        self._value_label = QtWidgets.QLabel("—", self)
        value_font = QtGui.QFont(_seven_segment_font_family() or "Courier New")
        if not _seven_segment_font_family():
            value_font.setStyleHint(QtGui.QFont.StyleHint.TypeWriter)
        value_font.setPointSize(34)
        value_font.setBold(True)
        self._value_label.setFont(value_font)
        self._value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._value_label.setMinimumHeight(56)
        self._value_label.setStyleSheet(f"QLabel {{ color: {colour('value_display_text')}; }}")
        self._value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._suffix_label = QtWidgets.QLabel("", self)
        suffix_font = QtGui.QFont()
        suffix_font.setPointSize(20)
        suffix_font.setBold(True)
        self._suffix_label.setFont(suffix_font)
        self._suffix_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._suffix_label.setMinimumHeight(56)
        self._suffix_label.setStyleSheet(f"QLabel {{ color: {colour('value_display_text')}; }}")
        self._suffix_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._display_frame = QtWidgets.QFrame(self)
        self._display_frame.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self._display_frame.setStyleSheet(
            value_display_frame_stylesheet() +
            "QLabel {"
            " background: transparent;"
            "}"
        )
        display_layout = QtWidgets.QHBoxLayout(self._display_frame)
        display_layout.setContentsMargins(12, 6, 12, 6)
        display_layout.setSpacing(2)
        display_layout.addWidget(self._value_label, 0)
        display_layout.addWidget(self._suffix_label, 0)
        display_layout.addStretch()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._name_label)
        layout.addWidget(self._display_frame)
        self.setLayout(layout)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        """Open the per-display formatting context menu."""
        menu = QtWidgets.QMenu(self)

        format_menu = menu.addMenu("Format")
        action_group = QtGui.QActionGroup(menu)
        action_group.setExclusive(True)

        for text, format_style in (
            ("SI prefixes", _FORMAT_SI),
            ("Float", _FORMAT_FLOAT),
            ("Scientific", _FORMAT_SCIENTIFIC),
        ):
            action = format_menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(self._format_style == format_style)
            action_group.addAction(action)
            action.triggered.connect(
                lambda checked=False, style=format_style: self._set_format_style(style)
            )

        digits_menu = menu.addMenu("Significant figures")
        for digits in range(2, 9):
            action = digits_menu.addAction(str(digits))
            action.setCheckable(True)
            action.setChecked(self._significant_figures == digits)
            action.triggered.connect(
                lambda checked=False, value=digits: self._set_significant_figures(value)
            )

        menu.exec(event.globalPos())

    def _set_format_style(self, format_style: str) -> None:
        self._format_style = format_style
        self.format_changed.emit(self._format_style, self._significant_figures)

    def _set_significant_figures(self, significant_figures: int) -> None:
        self._significant_figures = significant_figures
        self.format_changed.emit(self._format_style, self._significant_figures)

    def set_value_text(self, text: str) -> None:
        """Update the displayed value text.

        Args:
            text (str):
                Text to display.
        """
        self._suffix_text = ""
        self._value_label.setText(text)
        self._suffix_label.clear()

    def set_value_parts(self, value_text: str, suffix_text: str = "") -> None:
        """Update the displayed value and optional suffix text.

        Args:
            value_text (str):
                Main numeric text to display.
            suffix_text (str):
                Optional suffix, such as an SI prefix, rendered in a normal font.
        """
        self._suffix_text = suffix_text
        self._value_label.setText(value_text)
        self._suffix_label.setText(suffix_text)


def _seven_segment_font_family() -> str:
    """Load and return the bundled seven-segment font family name."""
    cached = getattr(_seven_segment_font_family, "_cached_family", None)
    if cached is not None:
        return cached
    family = ""
    try:
        path = bundled_resource_path("resources", "7segment.ttf")
        if path is not None:
            font_id = QtGui.QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    family = families[0]
    except Exception:  # pylint: disable=broad-except
        family = ""
    setattr(_seven_segment_font_family, "_cached_family", family)
    return family


def _format_with_si_prefix(value: float, significant_figures: int) -> str:
    """Format a float using SI prefixes and significant figures."""
    if not isfinite(value):
        return str(value), ""
    if value == 0:
        return "0", ""

    prefixes = {
        -24: "y",
        -21: "z",
        -18: "a",
        -15: "f",
        -12: "p",
        -9: "n",
        -6: "µ",
        -3: "m",
        0: "",
        3: "k",
        6: "M",
        9: "G",
        12: "T",
        15: "P",
        18: "E",
        21: "Z",
        24: "Y",
    }
    exponent = int(floor(log10(abs(value)) / 3.0) * 3)
    exponent = min(max(exponent, min(prefixes)), max(prefixes))
    scaled = value / (10 ** exponent)
    return f"{scaled:.{significant_figures}g}", prefixes[exponent]


class ValueWatchWindow(QtWidgets.QWidget):
    """Always-on-top window showing large live readouts for selected values.

    Args:
        engine (SequenceEngine):
            Sequence engine providing the live namespace and ``_values``
            catalogue.
        parent (QWidget | None):
            Optional parent widget.
    """

    _request_apply_catalog = pyqtSignal()
    _request_refresh = pyqtSignal()
    _request_relayout = pyqtSignal()

    def __init__(
        self,
        engine: SequenceEngine,
        parent: QtWidgets.QWidget | None = None,
        snap_reference_widget: QtWidgets.QWidget | None = None,
    ) -> None:
        """Initialise the value-watch window.

        Args:
            engine (SequenceEngine):
                Sequence engine providing the live namespace.
            parent (QWidget | None):
                Optional parent widget.
            snap_reference_widget (QWidget | None):
                Widget whose on-screen geometry should define snapped height and top position.
        """
        super().__init__(
            parent,
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowTitle("Value Watch")
        self.resize(720, 520)

        self._engine = engine
        self._restoring_settings = False
        self._restored_selected_keys: set[str] = set()
        self._restored_formats: dict[str, tuple[str, int]] = {}
        self._watch_entries: dict[str, WatchEntry] = {}
        self._displays: dict[str, _WatchDisplay] = {}
        self._closing = False
        self._catalog_update_pending = False
        self._refresh_pending = False
        self._pending_catalog: dict[str, str] | None = None
        self._rebuilding_displays = False
        self._relayout_pending = False
        self._engine_signals_connected = False
        self._normal_geometry = QtCore.QRect(self.geometry())  # type: ignore[attr-defined]  # pylint: disable=no-member
        self._snap_mode: str | None = None
        self._suspend_snap_handling = False
        self._snap_timer = QtCore.QTimer(self)  # type: ignore[attr-defined]  # pylint: disable=no-member
        self._snap_preview = _SnapPreviewOverlay(parent=None)
        self._preview_mode: str | None = None
        self._empty_state_label: QtWidgets.QLabel | None = None
        self._snap_reference_widget = snap_reference_widget

        self._btn_close = QtWidgets.QPushButton("Close", self)
        self._btn_close.setFixedWidth(70)
        self._btn_close.clicked.connect(self.hide)

        self._btn_config = QtWidgets.QPushButton(_CONFIG_BUTTON_TEXT, self)
        self._btn_config.setCheckable(True)
        self._btn_config.setStyleSheet(_BUTTON_STYLE_CHECKED)
        self._btn_config.setText(f"{_CONFIG_BUTTON_TEXT} ▸")
        self._btn_config.toggled.connect(self._toggle_config_panel)

        self._selector = ValueSelectionWidget(self)
        self._selector.selection_changed.connect(self._on_selection_changed)
        self._selector.empty_state_requested.connect(self._queue_relayout)

        self._config_panel = QtWidgets.QWidget(self)
        self._config_panel.setVisible(False)
        config_layout = QtWidgets.QVBoxLayout(self._config_panel)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.addWidget(self._selector)

        self._display_widget = QtWidgets.QWidget(self)
        self._display_layout = QtWidgets.QGridLayout(self._display_widget)
        self._display_layout.setContentsMargins(4, 4, 4, 4)
        self._display_layout.setSpacing(8)

        self._display_scroll = QtWidgets.QScrollArea(self)
        self._display_scroll.setWidgetResizable(True)
        self._display_scroll.setWidget(self._display_widget)
        self._display_scroll.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )

        top_row = QtWidgets.QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(self._btn_config)
        top_row.addStretch()
        top_row.addWidget(self._btn_close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top_row)
        layout.addWidget(self._config_panel)
        layout.addWidget(self._display_scroll)
        self.setLayout(layout)

        self._engine.values_catalog_changed.connect(self._handle_values_catalog_changed)
        self._engine.namespace_updated.connect(self._handle_namespace_updated)
        self._engine_signals_connected = True
        self._request_apply_catalog.connect(self._apply_pending_catalog, Qt.QueuedConnection)
        self._request_refresh.connect(self._apply_refresh_values, Qt.QueuedConnection)
        self._request_relayout.connect(self._apply_relayout, Qt.QueuedConnection)

        self._refresh_timer = QtCore.QTimer(self)  # type: ignore[attr-defined]  # pylint: disable=no-member
        self._allow_exit_close = False
        self._refresh_timer.setInterval(_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._queue_refresh_values)
        self._snap_timer.setSingleShot(True)
        self._snap_timer.setInterval(150)
        self._snap_timer.timeout.connect(self._apply_pending_edge_snap)

        self._restore_settings()
        self._apply_values_catalog(dict(self._engine.values_catalog))

    def show_and_raise(self) -> None:
        """Show the window and bring it to the front."""
        self.show()
        self._refresh_timer.start()
        self._queue_refresh_values()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event) -> None:  # type: ignore[override]
        """Start periodic refresh when the window is shown."""
        super().showEvent(event)
        self._refresh_timer.start()
        self._apply_values_catalog(dict(self._engine.values_catalog))
        self._queue_refresh_values()
        if self._pending_catalog is not None:
            self._queue_catalog_apply()

    def moveEvent(self, event) -> None:  # type: ignore[override]
        """Handle move events and debounce edge snapping."""
        super().moveEvent(event)
        if self._suspend_snap_handling:
            return
        if self._snap_mode is None:
            self._normal_geometry = self.geometry()
        self._snap_timer.start()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        """Stop periodic refresh when the window is hidden."""
        self._snap_timer.stop()
        if self._preview_mode is not None:
            self._snap_preview.hide()
        self._refresh_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Persist settings before the window closes.

        Args:
            event (QCloseEvent):
                Close event from Qt.
        """
        self._closing = True
        self._disconnect_engine_signals()
        self._snap_timer.stop()
        self._refresh_timer.stop()
        self._snap_preview.hide()
        self._watch_entries.clear()
        self._displays.clear()
        self._empty_state_label = None
        self._selector.blockSignals(True)
        self._save_settings()
        super().closeEvent(event)

    def _disconnect_engine_signals(self) -> None:
        """Disconnect sequence-engine signals once during shutdown/close."""
        if not self._engine_signals_connected:
            return
        try:
            self._engine.values_catalog_changed.disconnect(self._handle_values_catalog_changed)
        except (TypeError, RuntimeError):
            pass
        try:
            self._engine.namespace_updated.disconnect(self._handle_namespace_updated)
        except (TypeError, RuntimeError):
            pass
        self._engine_signals_connected = False

    @pyqtSlot(dict)
    def _handle_values_catalog_changed(self, catalog: dict[str, str]) -> None:
        """Queue catalogue application onto the GUI thread."""
        if self._closing:
            return
        self._pending_catalog = dict(catalog)
        if not self.isVisible():
            return
        self._queue_catalog_apply()

    @pyqtSlot()
    def _handle_namespace_updated(self) -> None:
        """Queue namespace refresh onto the GUI thread."""
        if not self.isVisible():
            return
        self._queue_refresh_values()

    @pyqtSlot()
    def _queue_catalog_apply(self) -> None:
        """Coalesce catalogue updates and apply only the latest one on the GUI thread."""
        if self._closing:
            return
        if self._catalog_update_pending:
            return
        self._catalog_update_pending = True
        self._request_apply_catalog.emit()

    @pyqtSlot()
    def _apply_pending_catalog(self) -> None:
        """Apply the latest queued catalogue snapshot, if any."""
        self._catalog_update_pending = False
        if self._closing:
            return
        catalog = self._pending_catalog
        self._pending_catalog = None
        if catalog is None:
            return
        self._apply_values_catalog(catalog)

    @pyqtSlot()
    def _queue_refresh_values(self) -> None:
        """Debounce refresh requests and run them on the GUI thread."""
        if self._closing:
            return
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._request_refresh.emit()

    @pyqtSlot()
    def _queue_relayout(self) -> None:
        """Debounce relayout requests and run them on the GUI thread."""
        if self._closing:
            return
        if self._relayout_pending:
            return
        self._relayout_pending = True
        self._request_relayout.emit()

    @pyqtSlot()
    def _apply_relayout(self) -> None:
        """Apply any pending relayout request."""
        self._relayout_pending = False
        if self._closing:
            return
        self._relayout_displays()

    @pyqtSlot()
    def _apply_refresh_values(self) -> None:
        """Apply any pending value refresh."""
        self._refresh_pending = False
        if not self.isVisible():
            return
        self.refresh_values()

    @pyqtSlot(dict)
    def _apply_values_catalog(self, catalog: dict[str, str]) -> None:
        """Refresh the selectable watch list from *catalog*.

        Args:
            catalog (dict[str, str]):
                Current engine value catalogue.
        """
        if self._closing:
            return
        self._catalog_update_pending = False
        if self._restoring_settings and not self._watch_entries:
            enabled_keys = set(self._restored_selected_keys)
        else:
            enabled_keys = {key for key, entry in self._watch_entries.items() if entry.enabled}

        new_entries: dict[str, WatchEntry] = {}
        current_formats = {
            key: (entry.format_style, entry.significant_figures) for key, entry in self._watch_entries.items()
        }
        for key, expression in sorted(catalog.items(), key=lambda item: item[0].lower()):
            restored_formats = {**self._restored_formats, **current_formats}
            format_style, significant_figures = restored_formats.get(key, (_FORMAT_SI, _DEFAULT_SIGNIFICANT_FIGURES))
            new_entries[key] = WatchEntry(
                key=key,
                expression=expression,
                enabled=key in enabled_keys,
                format_style=format_style,
                significant_figures=significant_figures,
            )
        self._watch_entries = new_entries
        if self.isVisible():
            self._selector.set_catalog(catalog, enabled_keys)
            self._rebuild_displays()
            self._queue_refresh_values()
        if self.isVisible() and not self._restoring_settings:
            self._save_settings()

    @pyqtSlot()
    def _on_selection_changed(self) -> None:
        """Update watched values from the selection widget."""
        if self._closing or self._selector._rebuilding_catalog:
            return
        selected = self._selector.selected_keys
        for key, entry in self._watch_entries.items():
            entry.enabled = key in selected
        self._rebuild_displays()
        self._queue_refresh_values()
        if not self._restoring_settings:
            self._save_settings()

    @pyqtSlot(bool)
    def _toggle_config_panel(self, checked: bool) -> None:
        """Show or hide the configuration panel.

        Args:
            checked (bool):
                ``True`` when the panel should be shown.
        """
        self._config_panel.setVisible(checked)
        if checked:
            self._refresh_catalog_from_engine()
            self._apply_values_catalog(dict(self._engine.values_catalog))
            self._queue_refresh_values()
        self._btn_config.setText(f"{_CONFIG_BUTTON_TEXT} {'▾' if checked else '▸'}")
        if not self._restoring_settings:
            self._save_settings()

    @pyqtSlot()
    def refresh_values(self) -> None:
        """Re-evaluate all watched expressions and refresh their displays."""
        if QtCore.QThread.currentThread() is not self.thread():
            self._queue_refresh_values()
            return
        if self._closing:
            return
        for key, entry in self._watch_entries.items():
            if not entry.enabled or key not in self._displays:
                continue
            display = self._displays[key]
            try:
                value = self._engine.evaluate_expression(entry.expression)
                text, suffix = self._format_value_for_entry(value, entry)
            except Exception as exc:  # pylint: disable=broad-except
                text = f"Error: {exc}"
                suffix = ""
            display.set_value_parts(text, suffix)

    def _rebuild_displays(self) -> None:
        """Recreate the display grid from the current watch selection."""
        if self._closing or self._rebuilding_displays:
            return
        self._rebuilding_displays = True
        try:
            while self._display_layout.count():
                item = self._display_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    try:
                        widget.setParent(None)
                    except RuntimeError:
                        pass
                    widget.deleteLater()
            self._displays.clear()
            self._empty_state_label = None

            enabled_entries = [entry for entry in self._watch_entries.values() if entry.enabled]
            if not enabled_entries:
                empty = QtWidgets.QLabel("No watched values selected.", self._display_widget)
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setStyleSheet(f"QLabel {{ color: {colour('muted_text')}; padding: 24px; }}")
                self._display_layout.addWidget(empty, 0, 0)
                self._empty_state_label = empty
                return

            for entry in enabled_entries:
                display = _WatchDisplay(
                    entry.key,
                    entry.format_style,
                    entry.significant_figures,
                    self._display_widget,
                )
                display.format_changed.connect(
                    lambda format_style, significant_figures, key=entry.key: self._on_display_format_changed(
                        key,
                        format_style,
                        significant_figures,
                    )
                )
                self._displays[entry.key] = display

            self._relayout_displays()
        finally:
            self._rebuilding_displays = False

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Reflow the watch tiles when the window is resized."""
        super().resizeEvent(event)
        self._queue_relayout()

    def _relayout_displays(self) -> None:
        """Lay out the current displays according to available width."""
        if self._closing or self._rebuilding_displays:
            return
        if self._empty_state_label is not None:
            return
        while self._display_layout.count():
            item = self._display_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                try:
                    self._display_layout.removeWidget(widget)
                except RuntimeError:
                    pass

        displays = list(self._displays.values())
        if not displays:
            return

        viewport_width = self._display_scroll.viewport().width()
        spacing = self._display_layout.horizontalSpacing()
        spacing = max(spacing, 0)
        columns = max(1, (viewport_width + spacing) // (_DISPLAY_FIXED_WIDTH + spacing))
        columns = min(columns, len(displays))

        for index, display in enumerate(displays):
            row = index // columns
            column = index % columns
            self._display_layout.addWidget(display, row, column, Qt.AlignmentFlag.AlignTop)

        for column in range(columns):
            self._display_layout.setColumnStretch(column, 0)
        self._display_layout.setColumnStretch(columns, 1)
        self._display_layout.setRowStretch((len(displays) + columns - 1) // columns, 1)

    @pyqtSlot(str, str, int)
    def _on_display_format_changed(self, key: str, format_style: str, significant_figures: int) -> None:
        """Update persistent formatting for one watched value."""
        entry = self._watch_entries.get(key)
        if entry is None:
            return
        entry.format_style = format_style
        entry.significant_figures = significant_figures
        self.refresh_values()
        if not self._restoring_settings:
            self._save_settings()

    def _format_value(self, value: object) -> str:
        """Return a user-friendly string for *value*.

        Args:
            value (object):
                Value to format.

        Returns:
            (str):
                Formatted display text.
        """
        text, suffix = self._format_value_for_entry(value, None)
        return f"{text} {suffix}".rstrip()

    def _format_value_for_entry(self, value: object, entry: WatchEntry | None) -> tuple[str, str]:
        """Return a user-friendly string for *value* using *entry* settings."""
        if value is None:
            return "None", ""
        if isinstance(value, bool):
            return str(value), ""
        if isinstance(value, int):
            return str(value), ""
        if isinstance(value, float):
            significant_figures = (
                entry.significant_figures if entry is not None else _DEFAULT_SIGNIFICANT_FIGURES
            )
            format_style = entry.format_style if entry is not None else _FORMAT_SI
            if format_style == _FORMAT_FLOAT:
                return f"{value:.{significant_figures}g}", ""
            if format_style == _FORMAT_SCIENTIFIC:
                return f"{value:.{max(significant_figures - 1, 0)}e}", ""
            return _format_with_si_prefix(value, significant_figures)
        return str(value), ""

    def _save_settings(self) -> None:
        """Persist window configuration and current watch selection."""
        settings = QSettings()
        settings.beginGroup(_SETTINGS_GROUP)
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("config_visible", self._btn_config.isChecked())
        settings.setValue("selected_keys", sorted(self._selector.selected_keys))
        settings.setValue(
            "formats",
            {
                key: {
                    "format_style": entry.format_style,
                    "significant_figures": entry.significant_figures,
                }
                for key, entry in self._watch_entries.items()
            },
        )
        settings.endGroup()

    def _restore_settings(self) -> None:
        """Restore window configuration and current watch selection."""
        settings = QSettings()
        settings.beginGroup(_SETTINGS_GROUP)
        self._restoring_settings = True
        try:
            geometry = settings.value("geometry")
            if geometry is not None:
                self.restoreGeometry(geometry)
            config_visible = settings.value("config_visible", False, type=bool)
            selected_keys = settings.value("selected_keys", [], type=list)
            format_map = settings.value("formats", {})
            self._restored_selected_keys = set(selected_keys)
            self._btn_config.setChecked(bool(config_visible))
            self._restore_format_settings(format_map)
        finally:
            self._restoring_settings = False
            settings.endGroup()

    def _restore_format_settings(self, format_map: object) -> None:
        """Restore per-key formatting settings from QSettings data."""
        if not isinstance(format_map, dict):
            return
        restored: dict[str, tuple[str, int]] = {}
        for key, value in format_map.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            format_style = value.get("format_style", _FORMAT_SI)
            significant_figures = value.get("significant_figures", _DEFAULT_SIGNIFICANT_FIGURES)
            if format_style not in {_FORMAT_SI, _FORMAT_FLOAT, _FORMAT_SCIENTIFIC}:
                format_style = _FORMAT_SI
            try:
                digits = int(significant_figures)
            except (TypeError, ValueError):
                digits = _DEFAULT_SIGNIFICANT_FIGURES
            restored[key] = (format_style, max(2, min(8, digits)))
        self._restored_formats = restored

    def _apply_pending_edge_snap(self) -> None:
        """Snap the window to the left or right screen edge when appropriate."""
        if not self.isVisible():
            return
        target_top, target_height = self._snap_vertical_geometry()
        if target_height <= 0:
            return
        screen = self.screen()
        if screen is None:
            screen = QtWidgets.QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            return

        available = screen.availableGeometry()
        frame = self.frameGeometry()

        left_distance = abs(frame.left() - available.left())
        right_distance = abs(frame.right() - available.right())

        max_snap_width = min(
            available.width(),
            _EDGE_SNAP_MAX_COLUMNS * _DISPLAY_FIXED_WIDTH,
        )
        target_width = max(_EDGE_SNAP_MIN_WIDTH_PX, int(available.width() * _EDGE_SNAP_WIDTH_RATIO))
        target_width = min(target_width, max_snap_width)

        visible_rows = max(1, target_height // self._estimated_tile_height())
        per_column_width = self._estimated_snap_column_width()
        enabled_count = sum(1 for entry in self._watch_entries.values() if entry.enabled)
        if enabled_count > 0:
            required_columns = (enabled_count + visible_rows - 1) // visible_rows
            target_width = min(
                max_snap_width,
                max(target_width, min(_EDGE_SNAP_MAX_COLUMNS, required_columns) * per_column_width),
            )

        target_mode: str | None = None
        target_geometry: QtCore.QRect | None = None
        if left_distance <= _EDGE_SNAP_THRESHOLD_PX:
            target_mode = "left"
            target_geometry = QtCore.QRect(  # pylint: disable=no-member
                available.left(), target_top, target_width, target_height
            )
        elif right_distance <= _EDGE_SNAP_THRESHOLD_PX:
            target_mode = "right"
            target_geometry = QtCore.QRect(  # pylint: disable=no-member
                available.right() - target_width + 1, target_top, target_width, target_height
            )

        if target_mode is None:
            self._snap_preview.hide()
            self._preview_mode = None
            if self._snap_mode is not None:
                self._suspend_snap_handling = True
                try:
                    self.setGeometry(self._normal_geometry)
                finally:
                    self._suspend_snap_handling = False
                self._snap_mode = None
            return

        if target_geometry is not None and self._preview_mode != target_mode:
            self._snap_preview.show_preview(target_geometry)
            self._preview_mode = target_mode

        if self._snap_mode is None:
            self._normal_geometry = self.geometry()
        self._snap_mode = target_mode
        self._suspend_snap_handling = True
        try:
            self.setGeometry(target_geometry)
        finally:
            self._suspend_snap_handling = False
        self._snap_preview.hide()
        self._preview_mode = None

    def _snap_vertical_geometry(self) -> tuple[int, int]:
        """Return the preferred snapped top position and height."""
        reference = self._snap_reference_widget
        if reference is not None and reference.isVisible():
            top_left = reference.mapToGlobal(reference.rect().topLeft())
            bottom_right = reference.mapToGlobal(reference.rect().bottomRight())
            top = top_left.y() + _EDGE_SNAP_VERTICAL_PADDING_PX
            bottom = bottom_right.y() - _EDGE_SNAP_VERTICAL_PADDING_PX
            return top, max(1, bottom - top + 1)

        screen = self.screen()
        if screen is None:
            screen = QtWidgets.QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            return 0, 0
        available = screen.availableGeometry()
        top = available.top() + _EDGE_SNAP_VERTICAL_PADDING_PX
        height = max(1, available.height() - (2 * _EDGE_SNAP_VERTICAL_PADDING_PX))
        return top, height

    def _estimated_tile_height(self) -> int:
        """Estimate the height of one display tile for snap-width calculations."""
        if self._displays:
            sample_display = next(iter(self._displays.values()))
            return max(1, sample_display.sizeHint().height())
        return 120

    def _estimated_snap_column_width(self) -> int:
        """Estimate the width needed to show one tile column when snapped."""
        spacing = max(self._display_layout.horizontalSpacing(), 0)
        viewport_margins = (
            self._display_layout.contentsMargins().left()
            + self._display_layout.contentsMargins().right()
        )
        scroll_frame = max(0, 2 * self._display_scroll.frameWidth())
        scrollbar_allowance = 24
        return max(
            _DISPLAY_FIXED_WIDTH,
            _DISPLAY_FIXED_WIDTH
            + spacing + viewport_margins + scroll_frame
            + scrollbar_allowance,
        )

    def _refresh_catalog_from_engine(self) -> None:
        """Rebuild the available value catalogue from the current engine state."""
        refresh_catalog = getattr(self._engine, "refresh_value_catalog", None)
        if callable(refresh_catalog):
            refresh_catalog()
            return
        self._apply_values_catalog(dict(self._engine.values_catalog))
