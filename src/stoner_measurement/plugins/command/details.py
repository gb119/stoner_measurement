"""DetailsCommand — built-in command plugin for recording measurement metadata.

:class:`DetailsCommand` is a concrete :class:`CommandPlugin` that stores
metadata about a measurement run (operator, sample, project, and free-form
notes).  Rather than emitting a ``{instance_name}()`` call, the generated
sequence code consists of attribute-assignment statements that attach the
configured values directly to the plugin instance in the engine namespace,
making them accessible to downstream sequence steps and data-saving plugins.

The *project* combo box is pre-populated with the top-level subdirectories of
the application default data directory (``Path.home()`` by default; this will
be overridden once the application ini file is introduced).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QWidget,
)

from stoner_measurement.plugins.command.base import CommandPlugin

#: Default data root used to populate the project combo box.
#: Will be replaced by a configurable ini-file setting in a future release.
_DEFAULT_DATA_ROOT = Path.home()


def _top_level_dirs(root: Path) -> list[str]:
    """Return sorted names of immediate subdirectories of *root*.

    Args:
        root (Path):
            Directory to inspect.

    Returns:
        (list[str]):
            Sorted list of subdirectory names, or an empty list if *root* does
            not exist or is not a directory.
    """
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


class DetailsCommand(CommandPlugin):
    """Command plugin that records measurement metadata in the sequence script.

    :class:`DetailsCommand` stores four metadata fields — *user*, *sample*,
    *project*, and *notes* — that describe who is performing the measurement,
    what is being measured, which project it belongs to, and any free-form
    comments.

    Unlike other command plugins, the generated sequence code does **not** call
    ``{instance_name}()``.  Instead it emits four attribute-assignment
    statements so that the values are set on the plugin instance in the engine
    namespace::

        details.user = "Alice"
        details.sample = "Nb_film_001"
        details.project = "NbSC"
        details.notes = "Cooled overnight; base pressure 5e-7 mbar."

    This allows subsequent sequence steps and data-saving plugins to read the
    metadata directly from the instance (e.g. ``details.sample``).

    Attributes:
        user (str):
            Name of the person performing the measurement.
        sample (str):
            Identifier for the sample under test.
        project (str):
            Project name.  The configuration combo box is pre-populated with
            the top-level subdirectories of the application default data
            directory.
        notes (str):
            Free-form notes about the measurement.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.command.details import DetailsCommand
        >>> cmd = DetailsCommand()
        >>> cmd.name
        'Details'
        >>> cmd.plugin_type
        'command'
        >>> cmd.has_lifecycle
        False
    """

    def __init__(self, parent=None) -> None:
        """Initialise with empty metadata fields."""
        super().__init__(parent)
        self.user: str = ""
        self.sample: str = ""
        self.project: str = ""
        self.notes: str = ""

    @property
    def name(self) -> str:
        """Unique display name for the details command.

        Returns:
            (str):
                ``"Details"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.details import DetailsCommand
            >>> DetailsCommand().name
            'Details'
        """
        return "Details"

    def execute(self) -> None:
        """Apply the stored metadata to the plugin instance.

        Sets :attr:`user`, :attr:`sample`, :attr:`project`, and :attr:`notes`
        on *self*.  This method is present to satisfy the abstract-method
        contract of :class:`~stoner_measurement.plugins.command.base.CommandPlugin`;
        the sequence engine generates attribute-assignment code rather than an
        ``execute()`` call, so this method is not invoked during normal
        sequence execution.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.details import DetailsCommand
            >>> cmd = DetailsCommand()
            >>> cmd.user = "Alice"
            >>> cmd.execute()
            >>> cmd.user
            'Alice'
        """
        # The attributes are already set; this is a no-op that satisfies the
        # abstract-method requirement and ensures execute() is idempotent.

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return attribute-assignment code lines for this plugin.

        Instead of a ``{instance_name}()`` call, emits four assignment
        statements that set the metadata attributes on the plugin instance in
        the engine namespace, followed by a blank separator line.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Ignored — :class:`DetailsCommand` is always a leaf node.
            render_sub_step (Callable):
                Ignored — :class:`DetailsCommand` is always a leaf node.

        Returns:
            (list[str]):
                Four assignment lines plus a trailing blank line.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.details import DetailsCommand
            >>> cmd = DetailsCommand()
            >>> cmd.user = "Alice"
            >>> cmd.sample = "Nb_001"
            >>> cmd.project = "NbSC"
            >>> cmd.notes = "Test run"
            >>> lines = cmd.generate_action_code(0, [], lambda s, i: [])
            >>> lines[0]
            'details.user = "Alice"'
            >>> lines[1]
            'details.sample = "Nb_001"'
            >>> lines[2]
            'details.project = "NbSC"'
            >>> lines[3]
            'details.notes = "Test run"'
            >>> lines[4]
            ''
        """
        prefix = "    " * indent
        inst = self.instance_name

        def _quoted(value: str) -> str:
            """Return *value* as a Python string literal, escaping backslashes and quotes."""
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'

        lines = [
            f"{prefix}{inst}.user = {_quoted(self.user)}",
            f"{prefix}{inst}.sample = {_quoted(self.sample)}",
            f"{prefix}{inst}.project = {_quoted(self.project)}",
            f"{prefix}{inst}.notes = {_quoted(self.notes)}",
            "",
        ]
        return lines

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a settings widget with user, sample, project, and notes fields.

        The widget contains a :class:`~PyQt6.QtWidgets.QFormLayout` with:

        * A :class:`~PyQt6.QtWidgets.QLineEdit` for the operator name.
        * A :class:`~PyQt6.QtWidgets.QLineEdit` for the sample identifier.
        * An editable :class:`~PyQt6.QtWidgets.QComboBox` for the project name,
          pre-populated with the top-level subdirectories of the application
          default data directory.
        * A :class:`~PyQt6.QtWidgets.QPlainTextEdit` for free-form notes.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The settings widget for the *Settings* tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.details import DetailsCommand
            >>> isinstance(DetailsCommand().config_widget(), QWidget)
            True
        """
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        # --- user ---
        user_edit = QLineEdit(self.user, widget)
        user_edit.setPlaceholderText("Operator name")

        def _apply_user() -> None:
            self.user = user_edit.text()

        user_edit.editingFinished.connect(_apply_user)
        layout.addRow("User:", user_edit)

        # --- sample ---
        sample_edit = QLineEdit(self.sample, widget)
        sample_edit.setPlaceholderText("Sample identifier")

        def _apply_sample() -> None:
            self.sample = sample_edit.text()

        sample_edit.editingFinished.connect(_apply_sample)
        layout.addRow("Sample:", sample_edit)

        # --- project ---
        project_combo = QComboBox(widget)
        project_combo.setEditable(True)
        project_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for dir_name in _top_level_dirs(_DEFAULT_DATA_ROOT):
            project_combo.addItem(dir_name)
        # Set current text to the stored project value
        project_combo.setCurrentText(self.project)

        def _apply_project() -> None:
            self.project = project_combo.currentText()

        project_combo.currentTextChanged.connect(_apply_project)
        layout.addRow("Project:", project_combo)

        # --- notes ---
        notes_edit = QPlainTextEdit(self.notes, widget)
        notes_edit.setPlaceholderText("Free-form notes about this measurement…")
        notes_edit.setMinimumHeight(80)

        def _apply_notes() -> None:
            self.notes = notes_edit.toPlainText()

        notes_edit.textChanged.connect(_apply_notes)
        layout.addRow("Notes:", notes_edit)

        widget.setLayout(layout)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise the details command configuration to a JSON-compatible dict.

        Returns:
            (dict[str, Any]):
                Base dict from
                :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                extended with ``"user"``, ``"sample"``, ``"project"``, and
                ``"notes"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.details import DetailsCommand
            >>> d = DetailsCommand().to_json()
            >>> d["type"]
            'command'
            >>> all(k in d for k in ("user", "sample", "project", "notes"))
            True
        """
        d = super().to_json()
        d["user"] = self.user
        d["sample"] = self.sample
        d["project"] = self.project
        d["notes"] = self.notes
        return d

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore metadata fields from a serialised dict.

        Args:
            data (dict[str, Any]):
                Serialised dict as produced by :meth:`to_json`.
        """
        if "user" in data:
            self.user = data["user"]
        if "sample" in data:
            self.sample = data["sample"]
        if "project" in data:
            self.project = data["project"]
        if "notes" in data:
            self.notes = data["notes"]
