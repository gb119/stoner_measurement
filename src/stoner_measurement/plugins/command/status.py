"""StatusCommand — built-in command plugin for updating the application status bar.

:class:`StatusCommand` is a concrete :class:`CommandPlugin` that evaluates a
Python expression to obtain a status string and emits it to the sequence
engine's ``status_changed`` signal, which is wired to the application status
bar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin

if TYPE_CHECKING:
    from stoner_measurement.core.sequence_engine import SequenceEngine


def _safe_disconnect(signal: Any, slot: Any) -> None:
    """Disconnect *signal* from *slot*, silently ignoring errors if not connected.

    Args:
        signal (Any):
            The PyQt signal from which to disconnect.
        slot (Any):
            The callable slot to disconnect.
    """
    try:
        signal.disconnect(slot)
    except (TypeError, RuntimeError):
        pass


class StatusCommand(CommandPlugin):
    """Command plugin that sends a string message to the application status bar.

    The status text is given as a Python expression string (``status_expr``)
    that is evaluated against the sequence engine namespace at runtime using
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`.  This
    allows the message to incorporate live namespace variables::

        "f'Step {step_index} of {total_steps} complete'"

    At runtime :meth:`execute` emits the :attr:`status_message` signal with
    the resolved string.  The signal is automatically connected to the engine's
    ``status_changed`` signal when the plugin is attached, which in turn
    updates the application status bar.

    The :meth:`execute` and :meth:`__call__` methods accept an optional
    keyword parameter ``status`` that, when provided, overrides the evaluated
    ``status_expr`` setting.

    Attributes:
        status_expr (str):
            Python expression string that evaluates to the status string.
            Defaults to ``"'Ready'"``.
        status_message (pyqtSignal[str]):
            Emitted by :meth:`execute` with the resolved status string.
            Automatically connected to the engine's ``status_changed`` signal
            when the plugin is attached to a
            :class:`~stoner_measurement.core.sequence_engine.SequenceEngine`.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command.status import StatusCommand
        >>> cmd = StatusCommand()
        >>> cmd.name
        'Status'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        False
    """

    #: Signal emitted by execute() — the resolved status string.
    status_message = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        """Initialise with a default status expression."""
        super().__init__(parent)
        self._sequence_engine_ref: SequenceEngine | None = None
        self.status_expr: str = "'Ready'"

    # ------------------------------------------------------------------
    # sequence_engine property — auto-wires status_message to engine
    # ------------------------------------------------------------------

    @property  # type: ignore[override]
    def sequence_engine(self) -> SequenceEngine | None:
        """Active sequence engine, or ``None`` when the plugin is detached.

        Overrides the class-level attribute from
        :class:`~stoner_measurement.plugins.base_plugin.BasePlugin` with a
        full property so that the setter can automatically connect the
        :attr:`status_message` signal to the engine's ``status_changed``
        signal whenever the engine reference changes.

        Returns:
            (SequenceEngine | None):
                The owning engine, or ``None`` if not attached.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.status import StatusCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> cmd = StatusCommand()
            >>> cmd.sequence_engine is None
            True
            >>> engine.add_plugin("status", cmd)
            >>> cmd.sequence_engine is engine
            True
            >>> engine.shutdown()
        """
        return self._sequence_engine_ref

    @sequence_engine.setter
    def sequence_engine(self, engine: SequenceEngine | None) -> None:
        """Set the owning engine, wiring :attr:`status_message` to its signal.

        Disconnects from the old engine's ``status_changed`` signal (if any),
        then connects to the new engine's ``status_changed`` signal (if any).

        Args:
            engine (SequenceEngine | None):
                New owning engine, or ``None`` to detach.
        """
        if self._sequence_engine_ref is not None:
            _safe_disconnect(self.status_message, self._sequence_engine_ref.status_changed)

        self._sequence_engine_ref = engine

        if engine is not None:
            self.status_message.connect(engine.status_changed)

    @property
    def name(self) -> str:
        """Unique identifier for the status command.

        Returns:
            (str):
                ``"Status"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.status import StatusCommand
            >>> StatusCommand().name
            'Status'
        """
        return "Status"

    def execute(self, *, status: str | None = None) -> None:
        """Evaluate :attr:`status_expr` and emit the result as a status message.

        Emits :attr:`status_message` with the resolved string, which is
        automatically forwarded to the engine's ``status_changed`` signal and
        from there to the application status bar.

        Keyword Parameters:
            status (str | None):
                When provided, this string is used directly as the status
                message, overriding the evaluated :attr:`status_expr` setting.

        Raises:
            RuntimeError:
                If the plugin is not attached to a sequence engine and
                ``status`` is not provided.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.status import StatusCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> cmd = StatusCommand()
            >>> engine.add_plugin("status", cmd)
            >>> received = []
            >>> engine.status_changed.connect(received.append)
            >>> cmd.execute(status="Running step 1")
            >>> received[-1]
            'Running step 1'
            >>> engine.shutdown()
        """
        if status is None:
            status = str(self.eval(self.status_expr))
        self.status_message.emit(status)

    def __call__(self, *, status: str | None = None) -> None:
        """Invoke :meth:`execute`, allowing the plugin to be called as ``plugin()``.

        Keyword Parameters:
            status (str | None):
                Passed through to :meth:`execute`.  When provided, overrides
                the configured :attr:`status_expr` setting.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.status import StatusCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> cmd = StatusCommand()
            >>> engine.add_plugin("status", cmd)
            >>> received = []
            >>> engine.status_changed.connect(received.append)
            >>> cmd(status="Done")
            >>> received[-1]
            'Done'
            >>> engine.shutdown()
        """
        self.execute(status=status)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a settings widget with a status-expression editor.

        Displays a :class:`~PyQt6.QtWidgets.QFormLayout` containing a
        :class:`~PyQt6.QtWidgets.QLineEdit` that accepts a Python expression
        string for the status message, and a brief description label.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The settings widget for the *Settings* tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.status import StatusCommand
            >>> from PyQt6.QtWidgets import QWidget
            >>> isinstance(StatusCommand().config_widget(), QWidget)
            True
        """
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        status_edit = QLineEdit(self.status_expr, widget)
        status_edit.setToolTip(
            "Python expression evaluated in the sequence engine namespace. "
            "Must produce a string. "
            "Example: f'Step {step_index} complete'"
        )

        def _apply() -> None:
            self.status_expr = status_edit.text().strip()

        status_edit.editingFinished.connect(_apply)
        layout.addRow("Status expression:", status_edit)
        layout.addRow(
            QLabel(
                "<i>Expression is evaluated at runtime in the sequence "
                "engine namespace.  Result is sent to the status bar.</i>",
                widget,
            )
        )
        widget.setLayout(layout)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise the status command configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict from
                :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                extended with ``"status_expr"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.status import StatusCommand
            >>> d = StatusCommand().to_json()
            >>> d["type"]
            'command'
            >>> "status_expr" in d
            True
        """
        d = super().to_json()
        d["status_expr"] = self.status_expr
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore :attr:`status_expr` from a serialised dict.

        Args:
            data (dict[str, Any]):
                Serialised dict as produced by :meth:`to_json`.
        """
        if "status_expr" in data:
            self.status_expr = data["status_expr"]
