"""Interactive console widget for communicating with the sequence engine."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from stoner_measurement.core.sequence_engine import SequenceEngine


class ConsoleWidget(QWidget):
    """Read-only output area combined with a command-input line.

    The output area displays timestamped messages written via :meth:`write`.
    The input line supports a command history navigated with the Up/Down arrow
    keys; pressing Return (or clicking *Run*) submits the command.

    When a :class:`~stoner_measurement.core.sequence_engine.SequenceEngine` is
    connected via :meth:`connect_engine`, submitted commands are forwarded to
    the engine's shared namespace and the engine's output is displayed here.
    Without a connected engine the widget falls back to local ``eval``/``exec``.

    Args:
        parent (QWidget | None):
            Optional parent widget.

    Attributes:
        MAX_HISTORY (int): Maximum number of commands retained in history.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> app = QApplication.instance() or QApplication([])
        >>> console = ConsoleWidget()
        >>> console.write("Hello from console")
    """

    MAX_HISTORY: int = 100

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._engine: SequenceEngine | None = None

        # Output display -------------------------------------------------------
        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)
        mono = QFont("Courier New", 9)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._output.setFont(mono)
        self._output.setMaximumBlockCount(5000)

        # Input row ------------------------------------------------------------
        self._input = QLineEdit(self)
        self._input.setPlaceholderText("Enter Python expression or statement…")
        self._input.setFont(mono)

        self._run_btn = QPushButton("Run", self)
        self._run_btn.setFixedWidth(60)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.addWidget(self._input)
        input_row.addWidget(self._run_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._output)
        layout.addLayout(input_row)
        self.setLayout(layout)

        # Command history ------------------------------------------------------
        self._history: list[str] = []
        self._history_pos: int = -1

        # Connections ----------------------------------------------------------
        self._run_btn.clicked.connect(self._submit)
        self._input.returnPressed.connect(self._submit)

    # ------------------------------------------------------------------
    # Public slots
    # ------------------------------------------------------------------

    @pyqtSlot(str)
    def write(self, text: str) -> None:
        """Append *text* to the output area with a timestamp prefix.

        Args:
            text (str):
                Message to display.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> console = ConsoleWidget()
            >>> console.write("test message")
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_text(f"[{timestamp}] {text}", color=None)

    @pyqtSlot(str)
    def write_error(self, text: str) -> None:
        """Append *text* in red to signal an error condition.

        Args:
            text (str):
                Error message to display.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> console = ConsoleWidget()
            >>> console.write_error("something went wrong")
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_text(f"[{timestamp}] ERROR: {text}", color=QColor("#cc0000"))

    @pyqtSlot(str)
    def write_output(self, text: str) -> None:
        """Append raw *text* (no timestamp) in the default colour.

        Useful for forwarding stdout produced by runner code.

        Args:
            text (str):
                Raw output text.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> console = ConsoleWidget()
            >>> console.write_output("raw output line")
        """
        self._append_text(text, color=None)

    def clear(self) -> None:
        """Clear all text from the output area.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> app = QApplication.instance() or QApplication([])
            >>> console = ConsoleWidget()
            >>> console.write("something")
            >>> console.clear()
        """
        self._output.clear()

    def connect_engine(self, engine: SequenceEngine) -> None:
        """Connect this console to a :class:`~stoner_measurement.core.sequence_engine.SequenceEngine`.

        After calling this method, commands entered in the input line are
        forwarded to *engine* for execution in its shared namespace.  The
        engine's ``output`` and ``error_output`` signals are connected to
        :meth:`write_output` and :meth:`write_error` respectively.

        Args:
            engine (SequenceEngine):
                The sequence engine to use for command execution.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> console = ConsoleWidget()
            >>> console.connect_engine(engine)
            >>> engine.shutdown()
        """
        self._engine = engine
        engine.output.connect(self.write_output)
        engine.error_output.connect(self.write_error)

    # ------------------------------------------------------------------
    # Key handling for the input line
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        """Forward Up/Down arrow keys to navigate command history.

        Args:
            event: The key-press event.
        """
        if self._input.hasFocus():
            if event.key() == Qt.Key.Key_Up:
                self._history_up()
                return
            if event.key() == Qt.Key.Key_Down:
                self._history_down()
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _append_text(self, text: str, color: QColor | None) -> None:
        """Append *text* to the output widget, optionally coloured.

        Args:
            text (str):
                Line of text to add.
            color (QColor | None):
                Foreground colour, or ``None`` for the default colour.
        """
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if color is not None:
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        # Reset to default colour
        cursor.setCharFormat(QTextCharFormat())
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _submit(self) -> None:
        """Submit the command currently in the input line."""
        command = self._input.text().strip()
        if not command:
            return
        # Add to history (avoid consecutive duplicates)
        if not self._history or self._history[-1] != command:
            self._history.append(command)
            if len(self._history) > self.MAX_HISTORY:
                self._history.pop(0)
        self._history_pos = len(self._history)
        self._input.clear()
        # Echo the command
        self._append_text(f">>> {command}", color=QColor("#005fbf"))
        # Execute inside the widget's local namespace
        self._execute(command)

    def _execute(self, command: str) -> None:
        """Run *command* via the connected engine or local ``exec``/``eval``.

        When a :class:`~stoner_measurement.core.sequence_engine.SequenceEngine`
        has been connected via :meth:`connect_engine`, the command is forwarded
        to the engine's background thread; output will arrive asynchronously
        via the engine's signals.  Without a connected engine the command is
        evaluated locally (useful for standalone testing).

        Args:
            command (str):
                Python expression or statement to execute.

        Notes:
            The local fallback uses ``eval``/``exec`` deliberately because this
            widget is an interactive Python console intended for use by the
            scientist operating the instrument.  It is functionally equivalent
            to a Python REPL and carries the same trust assumptions: the person
            typing commands is trusted to supply safe input.
        """
        if self._engine is not None:
            self._engine.execute_command(command)
            return

        ns: dict = {}
        try:
            result = eval(command, ns)  # noqa: S307
            if result is not None:
                self._append_text(repr(result), color=None)
        except SyntaxError:
            try:
                exec(command, ns)  # noqa: S102
            except Exception as exc:
                self.write_error(str(exc))
        except Exception as exc:
            self.write_error(str(exc))

    def _history_up(self) -> None:
        """Navigate one step back in command history."""
        if not self._history:
            return
        self._history_pos = max(0, self._history_pos - 1)
        self._input.setText(self._history[self._history_pos])

    def _history_down(self) -> None:
        """Navigate one step forward in command history."""
        if not self._history:
            return
        self._history_pos = min(len(self._history), self._history_pos + 1)
        if self._history_pos == len(self._history):
            self._input.clear()
        else:
            self._input.setText(self._history[self._history_pos])
