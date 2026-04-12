"""Standalone log-viewer window for the Stoner Measurement application.

Provides :class:`LogViewerWindow`, a non-modal, always-on-top window that
displays log records emitted by the sequence-engine logger as a growing,
colour-coded list.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

#: Colour map from logging level to display colour.
_LEVEL_COLOURS: dict[int, QColor] = {
    logging.DEBUG: QColor("#808080"),
    logging.INFO: QColor("#000000"),
    logging.WARNING: QColor("#c07000"),
    logging.ERROR: QColor("#cc0000"),
    logging.CRITICAL: QColor("#880000"),
}


class LogViewerWindow(QWidget):
    """Non-modal, always-on-top window that displays sequence-engine log messages.

    Receives :class:`logging.LogRecord` objects via the :meth:`append_record`
    slot and renders them as a timestamped, colour-coded list in a read-only
    text area.  The window stays on top of the main application window but
    does not block interaction with it.

    The window can be opened and raised via :meth:`show_and_raise` and
    programmatically cleared with :meth:`clear`.

    Args:
        parent (QWidget | None):
            Optional Qt parent widget.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> app = QApplication.instance() or QApplication([])
        >>> viewer = LogViewerWindow()
        >>> viewer.windowTitle()
        'Log Viewer'
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowTitle("Log Viewer")
        self.resize(700, 400)

        # Output area ----------------------------------------------------------
        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)
        mono = QFont("Courier New", 9)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._output.setFont(mono)
        self._output.setMaximumBlockCount(2000)
        self._output.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Toolbar row ----------------------------------------------------------
        self._btn_clear = QPushButton("Clear", self)
        self._btn_clear.setFixedWidth(70)
        self._btn_clear.clicked.connect(self.clear)

        self._btn_close = QPushButton("Close", self)
        self._btn_close.setFixedWidth(70)
        self._btn_close.clicked.connect(self.hide)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_clear)
        btn_row.addWidget(self._btn_close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._output)
        layout.addLayout(btn_row)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def show_and_raise(self) -> None:
        """Show the window and bring it to the front.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> viewer = LogViewerWindow()
            >>> import logging
            >>> record = logging.LogRecord(
            ...     name="test", level=logging.INFO, pathname="",
            ...     lineno=0, msg="hello", args=(), exc_info=None)
            >>> viewer.append_record(record)
            >>> viewer.clear()
        """
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> viewer = LogViewerWindow()
            >>> import logging
            >>> record = logging.LogRecord(
            ...     name="test", level=logging.WARNING, pathname="",
            ...     lineno=0, msg="watch out", args=(), exc_info=None)
            >>> viewer.append_record(record)
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_name = record.levelname
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            message = str(record.msg)
        text = f"[{timestamp}] {level_name:8s} {message}"

        # Choose colour by level; fall back to the nearest lower level.
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
