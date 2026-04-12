"""WaitCommand — built-in command plugin for pausing sequence execution.

:class:`WaitCommand` is a concrete :class:`CommandPlugin` that evaluates a
Python expression to obtain a delay in seconds and then sleeps the sequence
execution for that duration.
"""

from __future__ import annotations

import time
from typing import Any

from PyQt6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin


class WaitCommand(CommandPlugin):
    """Command plugin that pauses sequence execution for a specified duration.

    The delay is given as a Python expression string (``delay_expr``) that is
    evaluated against the sequence engine namespace at runtime using
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`.  This
    allows the delay to incorporate namespace variables such as loop counters
    or instrument settings::

        "settling_time * 1.5"

    The :meth:`execute` and :meth:`__call__` methods accept an optional
    keyword parameter ``delay`` that, when provided, overrides the evaluated
    ``delay_expr`` setting.

    Attributes:
        delay_expr (str):
            Python expression string that evaluates to the delay in seconds
            (float).  Defaults to ``"1.0"``.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command.wait import WaitCommand
        >>> cmd = WaitCommand()
        >>> cmd.name
        'Wait'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        False
    """

    def __init__(self, parent=None) -> None:
        """Initialise with a default delay expression."""
        super().__init__(parent)
        self.delay_expr: str = "1.0"

    @property
    def name(self) -> str:
        """Unique identifier for the wait command.

        Returns:
            (str):
                ``"Wait"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.wait import WaitCommand
            >>> WaitCommand().name
            'Wait'
        """
        return "Wait"

    def execute(self, *, delay: float | None = None) -> None:
        """Evaluate :attr:`delay_expr` and sleep for the resulting duration.

        Keyword Parameters:
            delay (float | None):
                When provided, this value is used directly as the sleep
                duration in seconds, overriding the evaluated
                :attr:`delay_expr` setting.

        Raises:
            RuntimeError:
                If the plugin is not attached to a sequence engine and
                ``delay`` is not provided.
            TypeError:
                If :attr:`delay_expr` does not evaluate to a numeric value
                and ``delay`` is not provided.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.wait import WaitCommand
            >>> cmd = WaitCommand()
            >>> import time
            >>> t0 = time.monotonic()
            >>> cmd.execute(delay=0.01)
            >>> time.monotonic() - t0 >= 0.01
            True
        """
        if delay is None:
            delay = float(self.eval(self.delay_expr))
        time.sleep(delay)

    def __call__(self, *, delay: float | None = None) -> None:
        """Invoke :meth:`execute`, allowing the plugin to be called as ``plugin()``.

        Keyword Parameters:
            delay (float | None):
                Passed through to :meth:`execute`.  When provided, overrides
                the configured :attr:`delay_expr` setting.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.wait import WaitCommand
            >>> cmd = WaitCommand()
            >>> import time
            >>> t0 = time.monotonic()
            >>> cmd(delay=0.01)
            >>> time.monotonic() - t0 >= 0.01
            True
        """
        self.execute(delay=delay)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a settings widget with a delay-expression editor.

        Displays a :class:`~PyQt6.QtWidgets.QFormLayout` containing a
        :class:`~PyQt6.QtWidgets.QLineEdit` that accepts a Python expression
        string for the sleep duration, and a brief description label.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The settings widget for the *Settings* tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.wait import WaitCommand
            >>> from PyQt6.QtWidgets import QWidget
            >>> isinstance(WaitCommand().config_widget(), QWidget)
            True
        """
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        delay_edit = QLineEdit(self.delay_expr, widget)
        delay_edit.setToolTip(
            "Python expression evaluated in the sequence engine namespace. "
            "Must produce a numeric value (seconds). "
            "Example: 1.5 or settling_time * 2"
        )

        def _apply() -> None:
            self.delay_expr = delay_edit.text().strip()

        delay_edit.editingFinished.connect(_apply)
        layout.addRow("Delay expression:", delay_edit)
        layout.addRow(
            QLabel(
                "<i>Expression is evaluated at runtime in the sequence "
                "engine namespace.  Result is the sleep duration in seconds.</i>",
                widget,
            )
        )
        widget.setLayout(layout)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise the wait command configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict from
                :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                extended with ``"delay_expr"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.wait import WaitCommand
            >>> d = WaitCommand().to_json()
            >>> d["type"]
            'command'
            >>> "delay_expr" in d
            True
        """
        d = super().to_json()
        d["delay_expr"] = self.delay_expr
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore :attr:`delay_expr` from a serialised dict.

        Args:
            data (dict[str, Any]):
                Serialised dict as produced by :meth:`to_json`.
        """
        if "delay_expr" in data:
            self.delay_expr = data["delay_expr"]
