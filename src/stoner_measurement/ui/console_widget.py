"""Interactive console widget backed by QtConsole with legacy fallback."""

from __future__ import annotations

import html as _html_lib
import logging
import weakref
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from io import StringIO
from typing import TYPE_CHECKING

from qtpy.QtCore import Qt
from qtpy.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.qt_compat import pyqtSlot
from stoner_measurement.ui.theme import colour

if TYPE_CHECKING:
    from stoner_measurement.core.sequence_engine import SequenceEngine

logger = logging.getLogger(__name__)

try:
    from qtconsole.inprocess import QtInProcessKernelManager
    from qtconsole.rich_jupyter_widget import RichJupyterWidget

    _IPYTHON_CONSOLE_AVAILABLE = True
except ImportError:
    QtInProcessKernelManager = None  # type: ignore[assignment]
    RichJupyterWidget = None  # type: ignore[assignment]
    _IPYTHON_CONSOLE_AVAILABLE = False


class _LegacyConsoleWidget(QWidget):
    """Read-only output area combined with a command-input line.

    This is the original console implementation and is used as a fallback when
    QtConsole/IPython dependencies are unavailable.

    Args:
        parent (QWidget | None):
            Optional parent widget.

    Attributes:
        MAX_HISTORY (int):
            Maximum number of commands retained in history.
    """

    MAX_HISTORY: int = 100

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._engine: SequenceEngine | None = None
        self._local_ns: dict = {}

        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)
        mono = QFont("Courier New", 9)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._output.setFont(mono)
        self._output.setMaximumBlockCount(5000)

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

        self._history: list[str] = []
        self._history_pos: int = -1

        self._run_btn.clicked.connect(self._submit)
        self._input.returnPressed.connect(self._submit)

    @pyqtSlot(str)
    def write(self, text: str) -> None:
        """Append *text* to the output area with a timestamp prefix."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_text(f"[{timestamp}] {text}", color=None)

    @pyqtSlot(str)
    def write_error(self, text: str) -> None:
        """Append *text* in red to signal an error condition."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_text(f"[{timestamp}] ERROR: {text}", color=QColor("#cc0000"))

    @pyqtSlot(str)
    def write_output(self, text: str) -> None:
        """Append raw *text* (no timestamp) in the default colour."""
        self._append_raw_text(text)

    def clear(self) -> None:
        """Clear all text from the output area."""
        self._output.clear()

    def connect_engine(self, engine: SequenceEngine) -> None:
        """Connect this console to a sequence engine."""
        self._engine = engine
        engine.output.connect(self.write_output)
        engine.error_output.connect(self.write_error)

    def execute_command(self, command: str) -> None:
        """Execute *command* using the legacy input/eval pipeline.

        Args:
            command (str):
                Python command or expression to execute.
        """
        self._input.setText(command)
        self._submit()

    def get_output_text(self) -> str:
        """Return the full visible output text."""
        return self._output.toPlainText()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        """Forward Up/Down arrow keys to navigate command history."""
        if self._input.hasFocus():
            if event.key() == Qt.Key.Key_Up:
                self._history_up()
                return
            if event.key() == Qt.Key.Key_Down:
                self._history_down()
                return
        super().keyPressEvent(event)

    def _append_text(self, text: str, color: QColor | None) -> None:
        """Append *text* to the output widget, optionally coloured."""
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if cursor.positionInBlock() > 0:
            cursor.insertText("\n")
        if color is not None:
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        cursor.setCharFormat(QTextCharFormat())
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _append_raw_text(self, text: str) -> None:
        """Insert *text* verbatim into the output area without extra newline."""
        if not text:
            return
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _submit(self) -> None:
        """Submit the command currently in the input line."""
        command = self._input.text().strip()
        if not command:
            return
        if not self._history or self._history[-1] != command:
            self._history.append(command)
            if len(self._history) > self.MAX_HISTORY:
                self._history.pop(0)
        self._history_pos = len(self._history)
        self._input.clear()
        self._append_text(f">>> {command}", color=QColor("#005fbf"))
        self._execute(command)

    def _execute(self, command: str) -> None:
        """Run *command* via the connected engine or local ``exec``/``eval``."""
        if self._engine is not None:
            self._engine.execute_command(command)
            return

        out = StringIO()
        err = StringIO()
        exc_messages: list[str] = []
        try:
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    result = eval(command, self._local_ns)  # noqa: S307  # nosec B307  # pylint: disable=eval-used
                    if result is not None:
                        out.write(repr(result) + "\n")
                except SyntaxError:
                    try:
                        exec(command, self._local_ns)  # noqa: S102  # nosec B102  # pylint: disable=exec-used
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        exc_messages.append(str(exc))
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    exc_messages.append(str(exc))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            exc_messages.append(str(exc))
        stdout_text = out.getvalue()
        if stdout_text:
            self.write_output(stdout_text)
        stderr_text = err.getvalue()
        if stderr_text:
            self.write_error(stderr_text)
        for msg in exc_messages:
            self.write_error(msg)

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


class _IPythonConsoleWidget(QWidget):
    """Interactive QtConsole widget running an in-process IPython kernel.

    Args:
        parent (QWidget | None):
            Optional parent widget.

    Attributes:
        _engine (SequenceEngine | None):
            Connected sequence engine, if any.
        _kernel_manager (QtInProcessKernelManager):
            In-process kernel manager hosting the IPython kernel.
        _kernel_client:
            Client connected to the in-process kernel channels.
        _kernel_active (bool):
            Tracks whether kernel channels are still active.
        _console (RichJupyterWidget):
            Embedded QtConsole widget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._engine: SequenceEngine | None = None
        assert QtInProcessKernelManager is not None
        assert RichJupyterWidget is not None

        self._kernel_manager = QtInProcessKernelManager()
        self._kernel_manager.start_kernel(show_banner=False)
        self._kernel_client = self._kernel_manager.client()
        self._kernel_client.start_channels()
        self._kernel_active = True

        self._console = RichJupyterWidget(self)
        self._console.kernel_manager = self._kernel_manager
        self._console.kernel_client = self._kernel_client

        mono = QFont("Courier New", 9)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._console.font = mono
        self._console.set_default_style(colors="linux")
        tooltip_base = colour("tooltip_base")
        tooltip_border = colour("border")
        tooltip_text = colour("tooltip_text")
        self._console.style_sheet = f"""
QWidget {{
    background-color: {colour("base")};
    color: {colour("text")};
}}

QPlainTextEdit, QTextEdit {{
    background-color: {colour("base")};
    color: {colour("text")};
    selection-background-color: {colour("highlight")};
    selection-color: {colour("highlighted_text")};
}}
QToolTip {{
    color: {tooltip_text};
    background-color: {tooltip_base};
    border: 1px solid {tooltip_border};
}}
"""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._console)
        self.setLayout(layout)

        self_ref = weakref.ref(self)

        def _shutdown_on_destroyed(*_args) -> None:
            widget = self_ref()
            if widget is not None:
                widget._shutdown_kernel()

        self.destroyed.connect(_shutdown_on_destroyed)

    @pyqtSlot(str)
    def write(self, text: str) -> None:
        """Append *text* with a timestamp prefix.

        Args:
            text (str):
                Message to append.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_stdout_stream(f"[{timestamp}] {text}\n")

    @pyqtSlot(str)
    def write_error(self, text: str) -> None:
        """Append *text* as a timestamped red error message.

        Args:
            text (str):
                Error text to append.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_stderr_stream(f"[{timestamp}] ERROR: {text}\n")

    @pyqtSlot(str)
    def write_output(self, text: str) -> None:
        """Append raw *text* exactly as provided.

        Args:
            text (str):
                Raw output text chunk.
        """
        if not text:
            return
        self._append_stdout_stream(text)

    def clear(self) -> None:
        """Clear the console output."""
        self._console.clear()

    def connect_engine(self, engine: SequenceEngine) -> None:
        """Connect this console to a sequence engine.

        The engine adopts the in-process IPython kernel's namespace as its
        live execution namespace.  Any variable created or mutated by a script
        — regardless of whether the script completes successfully, raises an
        exception, or is stopped — is therefore immediately visible in the
        QtConsole without a separate synchronisation step.

        Args:
            engine (SequenceEngine):
                Sequence engine whose output signals should be displayed.
        """
        if self._engine is not None:
            try:
                self._engine.output.disconnect(self.write_output)
            except TypeError:
                pass
            try:
                self._engine.error_output.disconnect(self.write_error)
            except TypeError:
                pass

        self._engine = engine
        engine.output.connect(self.write_output)
        engine.error_output.connect(self.write_error)
        kernel_ns = self._kernel_manager.kernel.shell.user_ns
        kernel_ns["engine"] = engine
        engine.adopt_namespace(kernel_ns)

    def execute_command(self, command: str) -> None:
        """Execute *command* in the embedded IPython kernel.

        Args:
            command (str):
                Python command or expression to execute.
        """
        stripped = command.strip()
        if not stripped:
            return
        self._console.execute(stripped, hidden=False, interactive=False)

    def _append_stdout_stream(self, text: str) -> None:
        """Append *text* to the console output stream.

        Args:
            text (str):
                Text to append.
        """
        self._console.append_stream(text)

    def _append_stderr_stream(self, text: str) -> None:
        """Append *text* as a red stderr stream entry before the prompt.

        Args:
            text (str):
                Error text to append.
        """
        escaped = _html_lib.escape(text).replace("\n", "<br/>")
        self._console._append_html(
            f'<span style="color: {colour("console_error")}">{escaped}</span>',
            before_prompt=True,
        )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Stop in-process kernel channels when this widget closes."""
        self.shutdown()
        super().closeEvent(event)

    def get_output_text(self) -> str:
        """Return the full visible output text."""
        return self._console._control.toPlainText()

    def shutdown(self) -> None:
        """Stop the embedded kernel before Qt child widgets are destroyed."""
        self._shutdown_kernel()

    def _shutdown_kernel(self) -> None:
        """Stop kernel channels safely once."""
        if not self._kernel_active:
            return
        self._kernel_active = False
        try:
            self._kernel_client.stop_channels()
        finally:
            self._kernel_manager.shutdown_kernel()

    def __del__(self) -> None:
        """Ensure in-process kernel channels are stopped on garbage collection."""
        try:
            self._shutdown_kernel()
        except Exception:
            logger.debug("Failed to shut down in-process console kernel during finalization", exc_info=True)


class ConsoleWidget(QWidget):
    """Interactive console with IPython QtConsole and legacy fallback.

    This façade selects the QtConsole-backed implementation when available,
    otherwise it falls back to the original split input/output widget while
    preserving the existing public API.

    Args:
        parent (QWidget | None):
            Optional parent widget.

    Attributes:
        using_ipython_console (bool):
            ``True`` when the QtConsole-backed implementation is active.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if _IPYTHON_CONSOLE_AVAILABLE:
            self._impl: QWidget = _IPythonConsoleWidget(self)
            self.using_ipython_console = True
        else:
            self._impl = _LegacyConsoleWidget(self)
            self.using_ipython_console = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._impl)
        self.setLayout(layout)

    @pyqtSlot(str)
    def write(self, text: str) -> None:
        """Append *text* to the console.

        Args:
            text (str):
                Message to append.
        """
        self._impl.write(text)  # type: ignore[attr-defined]

    @pyqtSlot(str)
    def write_error(self, text: str) -> None:
        """Append *text* as an error message.

        Args:
            text (str):
                Error message to append.
        """
        self._impl.write_error(text)  # type: ignore[attr-defined]

    @pyqtSlot(str)
    def write_output(self, text: str) -> None:
        """Append raw output text.

        Args:
            text (str):
                Raw output text chunk.
        """
        self._impl.write_output(text)  # type: ignore[attr-defined]

    def clear(self) -> None:
        """Clear all console content."""
        self._impl.clear()  # type: ignore[attr-defined]

    def connect_engine(self, engine: SequenceEngine) -> None:
        """Connect this console to a sequence engine.

        Args:
            engine (SequenceEngine):
                Engine to connect for asynchronous output forwarding.
        """
        self._impl.connect_engine(engine)  # type: ignore[attr-defined]

    def execute_command(self, command: str) -> None:
        """Execute *command* in whichever backend is active.

        Args:
            command (str):
                Python command or expression to execute.
        """
        self._impl.execute_command(command)  # type: ignore[attr-defined]

    def get_output_text(self) -> str:
        """Return the full visible output text from the active backend."""
        return self._impl.get_output_text()  # type: ignore[attr-defined]

    def shutdown(self) -> None:
        """Release resources owned by the active console backend."""
        shutdown = getattr(self._impl, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Release backend resources before Qt destroys child widgets."""
        self.shutdown()
        super().closeEvent(event)

    def __del__(self) -> None:
        """Best-effort backend shutdown for tests that drop widgets without closing them."""
        try:
            self.shutdown()
        except Exception:
            logger.debug("Failed to shut down console backend during finalization", exc_info=True)
