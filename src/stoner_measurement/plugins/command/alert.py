"""AlertCommand — built-in command plugin for displaying an alert dialog.

:class:`AlertCommand` is a concrete :class:`CommandPlugin` that evaluates a
Python expression to obtain a message string and then displays a modal
:class:`~PyQt6.QtWidgets.QMessageBox` with an *OK* button in the main thread,
blocking sequence execution until the user dismisses it.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QLabel, QLineEdit, QMessageBox, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin


class AlertCommand(CommandPlugin):
    """Command plugin that displays a modal alert dialog during sequence execution.

    The message is given as a Python expression string (``message_expr``) that
    is evaluated against the sequence engine namespace at runtime using
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`.  This
    allows the message to incorporate live namespace variables::

        "f'Measurement {run_index} complete — check sample temperature'"

    At runtime :meth:`execute` emits the :attr:`show_alert` signal with the
    resolved message string.  The signal is connected with
    :attr:`~PyQt6.QtCore.Qt.ConnectionType.BlockingQueuedConnection` so that
    the sequence thread blocks until the user clicks *OK*.

    The :meth:`execute` and :meth:`__call__` methods accept an optional
    keyword parameter ``message`` that, when provided, overrides the evaluated
    ``message_expr`` setting.

    Attributes:
        message_expr (str):
            Python expression string that evaluates to the alert message.
            Defaults to ``"'Alert'"``.
        show_alert (pyqtSignal[str]):
            Emitted by :meth:`execute` with the resolved message string.
            Connected with
            :attr:`~PyQt6.QtCore.Qt.ConnectionType.BlockingQueuedConnection`
            to :meth:`_display_alert` so that the sequence thread waits for
            the user to dismiss the dialog.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command.alert import AlertCommand
        >>> cmd = AlertCommand()
        >>> cmd.name
        'Alert'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        False
    """

    #: Signal emitted by execute() — the resolved alert message string.
    show_alert = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        """Initialise with a default message expression and wire the alert signal."""
        super().__init__(parent)
        self.message_expr: str = "'Alert'"
        # Connect with BlockingQueuedConnection so the worker thread blocks
        # until the user dismisses the dialog in the main thread.
        self.show_alert.connect(
            self._display_alert,
            Qt.ConnectionType.BlockingQueuedConnection,
        )

    @property
    def name(self) -> str:
        """Unique identifier for the alert command.

        Returns:
            (str):
                ``"Alert"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.alert import AlertCommand
            >>> AlertCommand().name
            'Alert'
        """
        return "Alert"

    def _display_alert(self, message: str) -> None:
        """Display a modal information dialog with *message*.

        This slot runs in the main thread (due to the
        :attr:`~PyQt6.QtCore.Qt.ConnectionType.BlockingQueuedConnection` used
        when connecting :attr:`show_alert`).

        Args:
            message (str):
                The message text to display in the dialog body.
        """
        QMessageBox.information(None, "Alert", message)

    def execute(self, *, message: str | None = None) -> None:
        """Evaluate :attr:`message_expr` and display a blocking alert dialog.

        Emits :attr:`show_alert` with the resolved message string, which
        triggers :meth:`_display_alert` in the main thread via a
        :attr:`~PyQt6.QtCore.Qt.ConnectionType.BlockingQueuedConnection`.
        The sequence thread is blocked until the user clicks *OK*.

        Keyword Parameters:
            message (str | None):
                When provided, this string is used directly as the alert
                message, overriding the evaluated :attr:`message_expr` setting.

        Raises:
            RuntimeError:
                If the plugin is not attached to a sequence engine and
                ``message`` is not provided.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.alert import AlertCommand
            >>> cmd = AlertCommand()
            >>> cmd.message_expr = "'Test alert'"
        """
        if message is None:
            message = str(self.eval(self.message_expr))
        self.show_alert.emit(message)

    def __call__(self, *, message: str | None = None) -> None:
        """Invoke :meth:`execute`, allowing the plugin to be called as ``plugin()``.

        Keyword Parameters:
            message (str | None):
                Passed through to :meth:`execute`.  When provided, overrides
                the configured :attr:`message_expr` setting.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.alert import AlertCommand
            >>> cmd = AlertCommand()
            >>> cmd.message_expr = "'Test alert'"
        """
        self.execute(message=message)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a settings widget with a message-expression editor.

        Displays a :class:`~PyQt6.QtWidgets.QFormLayout` containing a
        :class:`~PyQt6.QtWidgets.QLineEdit` that accepts a Python expression
        string for the alert message, and a brief description label.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The settings widget for the *Settings* tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.alert import AlertCommand
            >>> from PyQt6.QtWidgets import QWidget
            >>> isinstance(AlertCommand().config_widget(), QWidget)
            True
        """
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        message_edit = QLineEdit(self.message_expr, widget)
        message_edit.setToolTip(
            "Python expression evaluated in the sequence engine namespace. "
            "Must produce a string. "
            "Example: f'Run {run_index} complete — check sample'"
        )

        def _apply() -> None:
            self.message_expr = message_edit.text().strip()

        message_edit.editingFinished.connect(_apply)
        layout.addRow("Message expression:", message_edit)
        layout.addRow(
            QLabel(
                "<i>Expression is evaluated at runtime in the sequence "
                "engine namespace.  Result is shown in the alert dialog.</i>",
                widget,
            )
        )
        widget.setLayout(layout)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise the alert command configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict from
                :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                extended with ``"message_expr"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.alert import AlertCommand
            >>> d = AlertCommand().to_json()
            >>> d["type"]
            'command'
            >>> "message_expr" in d
            True
        """
        d = super().to_json()
        d["message_expr"] = self.message_expr
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore :attr:`message_expr` from a serialised dict.

        Args:
            data (dict[str, Any]):
                Serialised dict as produced by :meth:`to_json`.
        """
        if "message_expr" in data:
            self.message_expr = data["message_expr"]
