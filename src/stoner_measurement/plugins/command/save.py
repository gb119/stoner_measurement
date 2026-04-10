"""SaveCommand — built-in command plugin for writing data to disc.

:class:`SaveCommand` is a concrete :class:`CommandPlugin` that evaluates a
Python expression to obtain a file path and then writes the current trace and
scalar value catalogs from the sequence engine namespace to a JSON file.

This module is part of the :mod:`stoner_measurement.plugins.command` sub-package.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin


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

    def __init__(self, parent=None) -> None:
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
