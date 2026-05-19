"""CommandPlugin — abstract base class for single-action sequence commands.

Command plugins execute a single action during a measurement sequence without
any instrument lifecycle steps (no connect, configure, or disconnect calls).
Examples include saving collected data to disc, sending trace data to a plot
window, or emitting a point to a live scatter graph.

A :class:`CommandPlugin` has access to the full sequence engine namespace
(including all registered plugin instances and numpy functions) but produces
no output data of its own.

Unlike the instrument-oriented plugin sub-types, command plugins do **not**
require a scan generator and are always leaf nodes in the sequence tree.

Concrete implementations must subclass :class:`CommandPlugin` and implement
:meth:`~CommandPlugin.execute`.  The :class:`SaveCommand` class provided in
:mod:`stoner_measurement.plugins.command.save` serves as a worked example.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import Protocol

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QWidget

from stoner_measurement.plugins.base_plugin import BasePlugin, _ABCQObjectMeta

_DEFAULT_PLOT_RESPONSE_TIMEOUT_SECONDS = 0.25


class _SignalEmitter(Protocol):
    """Protocol for Qt-like signal objects exposing an ``emit()`` method."""

    def emit(self) -> None:
        """Emit the signal."""


class CommandPlugin(QObject, BasePlugin, metaclass=_ABCQObjectMeta):
    """Abstract base class for sequence-engine command plugins.

    A :class:`CommandPlugin` performs a single action (e.g. saving data,
    sending data to a plot) during the sequence without connecting to or
    configuring any hardware.  The generated sequence script calls only
    :meth:`execute`; no ``connect()``, ``configure()``, or ``disconnect()``
    calls are emitted for command plugins.

    Subclasses must implement :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name`
    and :meth:`execute`.  They may optionally override
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_widget` to provide
    a settings UI — the instance-name editor and plugin-type label are added automatically
    at the top of the single configuration tab.  They may also override
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json` and
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin._restore_from_json`
    to persist configuration across sessions.

    Attributes:
        instance_name_changed (pyqtSignal[str, str]):
            Emitted when :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.instance_name`
            is reassigned, carrying the old and new names.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command import CommandPlugin
        >>> class _Noop(CommandPlugin):
        ...     @property
        ...     def name(self): return "Noop"
        ...     def execute(self): pass
        >>> p = _Noop()
        >>> p.plugin_type
        'command'
        >>> p.has_lifecycle
        False
    """

    instance_name_changed = pyqtSignal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy."""
        super().__init__(parent)

    def _on_instance_name_changed(self, old_name: str, new_name: str) -> None:
        """Emit :attr:`instance_name_changed` when the instance name changes."""
        self.instance_name_changed.emit(old_name, new_name)

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a command.

        Returns:
            (str):
                Always ``"command"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import CommandPlugin
            >>> class _Noop(CommandPlugin):
            ...     @property
            ...     def name(self): return "Noop"
            ...     def execute(self): pass
            >>> _Noop().plugin_type
            'command'
        """
        return "command"

    @property
    def has_lifecycle(self) -> bool:
        """Command plugins have no instrument lifecycle.

        Returns:
            (bool):
                Always ``False``.  The sequence engine therefore omits
                ``connect()``, ``configure()``, and ``disconnect()`` calls
                for this plugin when generating sequence code.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import CommandPlugin
            >>> class _Noop(CommandPlugin):
            ...     @property
            ...     def name(self): return "Noop"
            ...     def execute(self): pass
            >>> _Noop().has_lifecycle
            False
        """
        return False

    @abstractmethod
    def execute(self) -> None:
        """Perform the command action.

        Called by the generated sequence script once per sequence step
        occurrence.  The method has access to the full sequence engine
        namespace via
        :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.engine_namespace`
        and can evaluate Python expressions against it using
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`.

        The plugin instance is also callable — invoking ``plugin()`` is
        equivalent to calling ``plugin.execute()``.

        Raises:
            Exception:
                Any exception raised here propagates to the sequence engine
                and is reported as a script error attributed to this plugin.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import CommandPlugin
            >>> class _Log(CommandPlugin):
            ...     @property
            ...     def name(self): return "Logger"
            ...     def execute(self):
            ...         self.log.info("sequence step reached")
            >>> p = _Log()
            >>> p.execute()  # no error when detached (uses fallback logger)
            >>> p()          # equivalent — __call__ delegates to execute()
        """

    def __call__(self) -> None:
        """Call :meth:`execute`, allowing the plugin to be invoked as ``plugin()``.

        The generated sequence script emits ``{instance_name}()`` rather than
        ``{instance_name}.execute()``, so this method is what actually runs
        during a sequence step.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import CommandPlugin
            >>> class _Noop(CommandPlugin):
            ...     @property
            ...     def name(self): return "Noop"
            ...     def execute(self): pass
            >>> p = _Noop()
            >>> p()  # calls execute()
        """
        self.execute()

    def _wait_for_plot_ready(self, timeout: float | None = None) -> bool:
        """Wait until the attached plot widget can accept another data update."""
        engine = self.sequence_engine
        if engine is None:
            return True
        wait_for_plot_ready = getattr(engine, "wait_for_plot_ready", None)
        if not callable(wait_for_plot_ready):
            return True
        return bool(wait_for_plot_ready(timeout=timeout))

    def _queue_plot_update_request(self, fallback_signal: _SignalEmitter | None = None) -> None:
        """Register one pending plot update before emitting data signals.

        Keyword Parameters:
            fallback_signal (_SignalEmitter | None):
                Optional Qt signal to emit when the plot widget does not expose
                ``mark_data_update_queued``.
        """
        engine = self.sequence_engine
        if engine is None:
            if fallback_signal is not None:
                fallback_signal.emit()
            return
        plot_widget = getattr(engine, "plot_widget", None)
        mark_data_update_queued = getattr(plot_widget, "mark_data_update_queued", None)
        if callable(mark_data_update_queued):
            mark_data_update_queued()
            return
        if fallback_signal is not None:
            fallback_signal.emit()

    def _wait_for_plot_response_or_raise(
        self,
        request_name: str,
        timeout: float | None = None,
    ) -> None:
        """Wait for one queued plot update to complete, or raise on timeout.

        Args:
            request_name (str):
                Human-readable label for the pending plot request.

        Keyword Parameters:
            timeout (float | None):
                Maximum wait time in seconds for the plot widget
                acknowledgement. If ``None``, uses the module default.

        Raises:
            TimeoutError:
                If the plot request is not acknowledged before *timeout*.
        """
        timeout_value = _DEFAULT_PLOT_RESPONSE_TIMEOUT_SECONDS if timeout is None else timeout
        if self._wait_for_plot_ready(timeout=timeout_value):
            return
        engine = self.sequence_engine
        thread = getattr(engine, "_thread", None)
        stop_event = getattr(thread, "_stop_event", None) if thread is not None else None
        if stop_event is not None and stop_event.is_set():
            self.log.debug("Plot update request %r interrupted by stop request.", request_name)
            return
        raise TimeoutError(
            f"Timed out after {timeout_value:g} s waiting for plot response for {request_name!r}."
        )

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return configuration tabs combining general and plugin-specific settings.

        Overrides the base-class implementation so that command plugins present
        a single tab rather than separate *General* and plugin-specific tabs.
        The tab shows the instance-name editor and plugin-type label at the top
        (from :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin._general_config_widget`),
        followed by a horizontal separator and then the plugin-specific widget
        returned by :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_widget`.
        An optional *About* tab is appended when
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin._about_html` returns
        non-``None`` content.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (list[tuple[str, QWidget]]):
                A list containing ``(self.name, combined_widget)`` and
                optionally an *About* tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import CommandPlugin
            >>> class _Noop(CommandPlugin):
            ...     @property
            ...     def name(self): return "Noop"
            ...     def execute(self): pass
            >>> tabs = _Noop().config_tabs()
            >>> len(tabs)
            1
            >>> tabs[0][0]
            'Noop'
        """
        combined = QWidget(parent)
        layout = QVBoxLayout(combined)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._general_config_widget())
        separator = QFrame(combined)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)
        layout.addWidget(self.config_widget())
        layout.addStretch()
        combined.setLayout(layout)
        tabs = [(self.name, combined)]
        about_tab = self._make_about_tab()
        if about_tab is not None:
            tabs.append(about_tab)
        return tabs

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return the action code line for this command plugin.

        Emits a single ``{instance_name}()`` call at the requested
        indentation level, followed by a blank separator line.  The generated
        call invokes :meth:`__call__`, which in turn delegates to
        :meth:`execute`.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Ignored — :class:`CommandPlugin` is always a leaf node.
            render_sub_step (Callable):
                Ignored — :class:`CommandPlugin` is always a leaf node.

        Returns:
            (list[str]):
                A single ``()`` call line followed by a blank line.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import CommandPlugin
            >>> class _Noop(CommandPlugin):
            ...     @property
            ...     def name(self): return "Noop"
            ...     def execute(self): pass
            >>> p = _Noop()
            >>> lines = p.generate_action_code(1, [], lambda s, i: [])
            >>> lines[0]
            '    noop()'
            >>> lines[1]
            ''
        """
        prefix = "    " * indent
        return [f"{prefix}{self.instance_name}()", ""]

    def reported_traces(self) -> dict[str, str]:
        """Command plugins produce no trace data.

        Returns:
            (dict[str, str]):
                Always an empty dict.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import CommandPlugin
            >>> class _Noop(CommandPlugin):
            ...     @property
            ...     def name(self): return "Noop"
            ...     def execute(self): pass
            >>> _Noop().reported_traces()
            {}
        """
        return {}

    def reported_values(self) -> dict[str, str]:
        """Command plugins produce no scalar data values.

        Returns:
            (dict[str, str]):
                Always an empty dict.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import CommandPlugin
            >>> class _Noop(CommandPlugin):
            ...     @property
            ...     def name(self): return "Noop"
            ...     def execute(self): pass
            >>> _Noop().reported_values()
            {}
        """
        return {}
