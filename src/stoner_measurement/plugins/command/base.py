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

from PyQt6.QtCore import QObject, pyqtSignal

from stoner_measurement.plugins.base_plugin import BasePlugin, _ABCQObjectMeta


class CommandPlugin(QObject, BasePlugin, metaclass=_ABCQObjectMeta):
    """Abstract base class for sequence-engine command plugins.

    A :class:`CommandPlugin` performs a single action (e.g. saving data,
    sending data to a plot) during the sequence without connecting to or
    configuring any hardware.  The generated sequence script calls only
    :meth:`execute`; no ``connect()``, ``configure()``, or ``disconnect()``
    calls are emitted for command plugins.

    Subclasses must implement :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.name`
    and :meth:`execute`.  They may optionally override
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_widget` or
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_tabs` to
    provide a settings UI, and :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
    / :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin._restore_from_json`
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
