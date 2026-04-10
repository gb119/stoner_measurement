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
this module serves as a worked example.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

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
        """

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return the action code line for this command plugin.

        Emits a single ``{instance_name}.execute()`` call at the requested
        indentation level, followed by a blank separator line.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Ignored — :class:`CommandPlugin` is always a leaf node.
            render_sub_step (Callable):
                Ignored — :class:`CommandPlugin` is always a leaf node.

        Returns:
            (list[str]):
                A single ``execute()`` call line followed by a blank line.

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
            '    noop.execute()'
            >>> lines[1]
            ''
        """
        prefix = "    " * indent
        return [f"{prefix}{self.instance_name}.execute()", ""]

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


class SaveCommand(CommandPlugin):
    """Command plugin that saves current trace and configuration data to disc.

    The save path is given as a Python expression string (``path_expr``) that
    is evaluated against the sequence engine namespace at runtime using
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`.  This
    allows the path to incorporate namespace variables such as loop counters,
    timestamps, or instrument settings::

        "f'data/run_{run_index:03d}.json'"

    The ``_traces`` and ``_values`` dicts from the engine namespace are
    serialised to JSON and written to the evaluated path.  If a parent
    directory does not exist it is created automatically.

    Attributes:
        path_expr (str):
            Python expression string that evaluates to the file path.
            Defaults to ``"'data/output.json'"``.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command import SaveCommand
        >>> cmd = SaveCommand()
        >>> cmd.name
        'Save'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        False
    """

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise with a default path expression."""
        super().__init__(parent)
        self.path_expr: str = "'data/output.json'"

    @property
    def name(self) -> str:
        """Unique identifier for the save command.

        Returns:
            (str):
                ``"Save"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> SaveCommand().name
            'Save'
        """
        return "Save"

    def execute(self) -> None:
        """Evaluate :attr:`path_expr` and write trace and value data to disc.

        Evaluates :attr:`path_expr` in the sequence engine namespace to obtain
        the output file path, creates any required parent directories, and
        writes a JSON file containing the current ``_traces`` and ``_values``
        catalogs from the namespace.

        Raises:
            RuntimeError:
                If the plugin is not attached to a sequence engine.
            TypeError:
                If :attr:`path_expr` does not evaluate to a string.
            OSError:
                If the file cannot be written (e.g. due to permissions).

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> import tempfile, os, json
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> cmd = SaveCommand()
            >>> engine.add_plugin("save", cmd)
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     path = os.path.join(tmp, "out.json")
            ...     cmd.path_expr = repr(path)
            ...     cmd.execute()
            ...     with open(path) as fh:
            ...         data = json.load(fh)
            >>> sorted(data.keys())
            ['traces', 'values']
            >>> engine.shutdown()
        """
        import json
        import pathlib

        path_val = self.eval(self.path_expr)
        if not isinstance(path_val, str):
            raise TypeError(
                f"SaveCommand.path_expr must evaluate to a str, got {type(path_val).__name__!r}"
            )
        dest = pathlib.Path(path_val)
        dest.parent.mkdir(parents=True, exist_ok=True)
        ns = self.engine_namespace
        payload: dict[str, Any] = {
            "traces": dict(ns.get("_traces", {})),
            "values": dict(ns.get("_values", {})),
        }
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.log.info("Data saved to %s", dest)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a settings widget with a path-expression editor.

        Displays a :class:`~PyQt6.QtWidgets.QFormLayout` containing a
        :class:`~PyQt6.QtWidgets.QLineEdit` that accepts a Python expression
        string for the output file path, and a brief description label.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The settings widget for the *Settings* tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> from PyQt6.QtWidgets import QWidget
            >>> isinstance(SaveCommand().config_widget(), QWidget)
            True
        """
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        path_edit = QLineEdit(self.path_expr, widget)
        path_edit.setToolTip(
            "Python expression evaluated in the sequence engine namespace. "
            "Must produce a string file path. "
            "Example: f'data/run_{run_index:03d}.json'"
        )

        def _apply() -> None:
            self.path_expr = path_edit.text().strip()

        path_edit.editingFinished.connect(_apply)
        layout.addRow("Path expression:", path_edit)
        layout.addRow(
            QLabel(
                "<i>Expression is evaluated at runtime in the sequence "
                "engine namespace.</i>",
                widget,
            )
        )
        widget.setLayout(layout)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise the save command configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict from :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                extended with ``"path_expr"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command import SaveCommand
            >>> d = SaveCommand().to_json()
            >>> d["type"]
            'command'
            >>> "path_expr" in d
            True
        """
        d = super().to_json()
        d["path_expr"] = self.path_expr
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore :attr:`path_expr` from a serialised dict.

        Args:
            data (dict[str, Any]):
                Serialised dict as produced by :meth:`to_json`.
        """
        if "path_expr" in data:
            self.path_expr = data["path_expr"]
