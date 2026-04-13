"""PlotClearCommand — built-in command plugin that clears all plot traces.

:class:`PlotClearCommand` is a concrete :class:`CommandPlugin` that removes
all currently displayed traces from the main plot window by emitting a
``plot_clear`` signal connected to
:meth:`~stoner_measurement.ui.plot_widget.PlotWidget.clear_all`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLabel, QWidget

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


class PlotClearCommand(CommandPlugin):
    """Command plugin that clears all traces from the main plot window.

    When executed, emits the :attr:`plot_clear` signal which is automatically
    connected to
    :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.clear_all` whenever
    the plugin is attached to a
    :class:`~stoner_measurement.core.sequence_engine.SequenceEngine` whose
    :attr:`~stoner_measurement.core.sequence_engine.SequenceEngine.plot_widget`
    is set.

    This plugin has no configuration options beyond the instance name.

    Attributes:
        plot_clear (pyqtSignal):
            Emitted by :meth:`execute`.  Automatically connected to
            :meth:`~stoner_measurement.ui.plot_widget.PlotWidget.clear_all`
            when the plugin is attached to an engine with a plot widget.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command.plot_clear import PlotClearCommand
        >>> cmd = PlotClearCommand()
        >>> cmd.name
        'Plot Clear'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        False
    """

    #: Signal emitted by execute() — triggers clear_all() on the plot widget.
    plot_clear = pyqtSignal()

    def __init__(self, parent=None) -> None:
        """Initialise with default configuration."""
        super().__init__(parent)
        self._sequence_engine_ref: SequenceEngine | None = None

    # ------------------------------------------------------------------
    # sequence_engine property — auto-wires plot_clear signal
    # ------------------------------------------------------------------

    @property  # type: ignore[override]
    def sequence_engine(self) -> SequenceEngine | None:
        """Active sequence engine, or ``None`` when the plugin is detached.

        Overrides the class-level attribute from
        :class:`~stoner_measurement.plugins.base_plugin.BasePlugin` with a
        full property so that the setter can automatically connect the
        :attr:`plot_clear` signal to the engine's plot widget.

        Returns:
            (SequenceEngine | None):
                The owning engine, or ``None`` if not attached.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_clear import PlotClearCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> cmd = PlotClearCommand()
            >>> cmd.sequence_engine is None
            True
            >>> engine.add_plugin("plot_clear", cmd)
            >>> cmd.sequence_engine is engine
            True
            >>> engine.shutdown()
        """
        return self._sequence_engine_ref

    @sequence_engine.setter
    def sequence_engine(self, engine: SequenceEngine | None) -> None:
        """Set the owning engine, wiring :attr:`plot_clear` to its plot widget.

        Args:
            engine (SequenceEngine | None):
                New owning engine, or ``None`` to detach.
        """
        if self._sequence_engine_ref is not None:
            old_pw = getattr(self._sequence_engine_ref, "plot_widget", None)
            if old_pw is not None:
                _safe_disconnect(self.plot_clear, old_pw.clear_all)

        self._sequence_engine_ref = engine

        if engine is not None:
            new_pw = getattr(engine, "plot_widget", None)
            if new_pw is not None:
                self.plot_clear.connect(new_pw.clear_all)

    @property
    def name(self) -> str:
        """Unique identifier for the plot-clear command.

        Returns:
            (str):
                ``"Plot Clear"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_clear import PlotClearCommand
            >>> PlotClearCommand().name
            'Plot Clear'
        """
        return "Plot Clear"

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self) -> None:
        """Emit :attr:`plot_clear` to clear all traces from the plot window.

        Raises:
            RuntimeError:
                If the plugin is not attached to a sequence engine.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_clear import PlotClearCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> cmd = PlotClearCommand()
            >>> engine.add_plugin("plot_clear", cmd)
            >>> cleared = []
            >>> cmd.plot_clear.connect(lambda: cleared.append(True))
            >>> cmd.execute()
            >>> cleared
            [True]
            >>> engine.shutdown()
        """
        self.plot_clear.emit()
        self.log.debug("PlotClear: cleared all plot traces.")

    # ------------------------------------------------------------------
    # Configuration UI
    # ------------------------------------------------------------------

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a minimal settings widget for the plot-clear command.

        This plugin has no configurable parameters; the widget only displays
        an informational message.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The settings widget for the *PlotClear* configuration tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.plot_clear import PlotClearCommand
            >>> from PyQt6.QtWidgets import QWidget
            >>> isinstance(PlotClearCommand().config_widget(), QWidget)
            True
        """
        widget = QWidget(parent)
        label = QLabel(
            "<i>No configuration required.  When executed, all traces are "
            "removed from the plot window.</i>",
            widget,
        )
        label.setWordWrap(True)
        return widget
