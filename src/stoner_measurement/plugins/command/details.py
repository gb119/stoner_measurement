"""DetailsCommand — built-in command plugin for recording measurement metadata.

:class:`DetailsCommand` is a concrete :class:`CommandPlugin` that stores
metadata about a measurement run (operator, sample, project, and free-form
notes).  Rather than emitting a ``{instance_name}()`` call, the generated
sequence code consists of attribute-assignment statements that attach the
configured values directly to the plugin instance in the engine namespace,
making them accessible to downstream sequence steps and data-saving plugins.

The *project* combo box is pre-populated with the top-level subdirectories of
the application default data directory, as configured in the application
settings (``app/default_data_directory``).  Falls back to the user's home
directory if no setting has been saved yet.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QWidget,
)

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.qt_compat import pyqtSignal


def _get_data_root() -> Path:
    """Return the configured default data directory, falling back to the home directory.

    Reads the ``app/default_data_directory`` key from the application settings
    (see :func:`~stoner_measurement.ui.settings_dialog.make_app_settings`).
    If the key is absent or the path is empty, :func:`pathlib.Path.home` is
    returned instead.

    Returns:
        (Path):
            The path to use as the root when listing project subdirectories.
    """
    from stoner_measurement.ui.settings_dialog import (
        KEY_DEFAULT_DATA_DIR,
        make_app_settings,
    )

    settings = make_app_settings()
    data_dir = settings.value(KEY_DEFAULT_DATA_DIR, "", type=str)
    if data_dir:
        return Path(data_dir)
    return Path.home()


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
    """Store user, sample, project, and notes information for a measurement.

    Use this command near the start of a sequence to record the basic details
    that identify a run: who is performing it, which sample is being measured,
    which project it belongs to, and any free-form notes. This information is
    intended to be filled in from the configuration panel and then reused by
    later steps such as saving or labelling data.

    In normal use, fill in **User**, **Sample**, and **Project** before
    running. These are treated as required fields. The **Project** field is
    pre-populated from top-level folders in the configured default data
    directory, but you can still type your own value. **Notes** can be used
    for anything that may help interpret the data later.

    For script-oriented use, this plugin behaves a little differently from
    most command plugins. The generated sequence code does **not** call
    ``{instance_name}()``. Instead it emits four attribute-assignment
    statements so that the values are set on the plugin instance in the engine
    namespace::

        details.user = "Alice"
        details.sample = "Nb_film_001"
        details.project = "NbSC"
        details.notes = "Cooled overnight; base pressure 5e-7 mbar."

    Attributes:
        user (str):
            Name of the person performing the measurement.
        sample (str):
            Identifier for the sample under test.
        project (str):
            Project name.  The configuration combo box is pre-populated with
            the top-level subdirectories of the application default data
            directory (as configured in the application settings).
        notes (str):
            Free-form notes about the measurement.

    This design allows later sequence steps and data-saving plugins to read
    the metadata directly from the instance, for example
    ``details.sample`` or ``details.project``.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
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

    show_validation_error = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        """Initialise with empty metadata fields."""
        super().__init__(parent)
        self.user: str = ""
        self.sample: str = ""
        self.project: str = ""
        self.notes: str = ""
        self.show_validation_error.connect(self._display_validation_error)

    def _display_validation_error(self, message: str) -> None:
        """Display a blocking validation warning dialog."""
        QMessageBox.warning(None, "Missing Details", message)

    @property
    def name(self) -> str:
        """Unique display name for the details command.

        Returns:
            (str):
                ``"Details"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.command.details import DetailsCommand
            >>> DetailsCommand().name
            'Details'
        """
        return "Details"

    def configure(self) -> None:
        """Validate the configured details fields used by generated scripts."""
        self.user = self.user.strip()
        self.sample = self.sample.strip()
        self.project = self.project.strip()

        missing_fields = []
        if not self.user:
            missing_fields.append("User")
        if not self.sample:
            missing_fields.append("Sample")
        if not self.project:
            missing_fields.append("Project")

        if missing_fields:
            field_text = ", ".join(missing_fields)
            message = f"The following Details fields must be filled in before continuing: {field_text}."
            self.show_validation_error.emit(message)
            raise ValueError(message)

    def execute(self) -> None:
        """Validate the stored metadata when the command is invoked directly."""
        self.configure()

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return attribute-assignment code lines for this plugin.

        Instead of a ``{instance_name}()`` call, emits four assignment
        statements that set the metadata attributes on the plugin instance in
        the engine namespace, followed by a ``configure()`` call and a blank
        separator line.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Ignored — :class:`DetailsCommand` is always a leaf node.
            render_sub_step (Callable):
                Ignored — :class:`DetailsCommand` is always a leaf node.

        Returns:
            (list[str]):
                Four assignment lines, one ``configure()`` call, and a
                trailing blank line.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
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
            'details.configure()'
            >>> lines[5]
            ''
        """
        prefix = "    " * indent
        inst = self.instance_name

        def _quoted(value: str) -> str:
            """Return *value* as a Python string literal, escaping backslashes and quotes.

            Args:
                value (str):
                    The raw string to encode.

            Returns:
                (str):
                    A double-quoted Python string literal with internal
                    backslashes and double-quotes escaped.
            """
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'

        lines = [
            f"{prefix}{inst}.user = {_quoted(self.user)}",
            f"{prefix}{inst}.sample = {_quoted(self.sample)}",
            f"{prefix}{inst}.project = {_quoted(self.project)}",
            f"{prefix}{inst}.notes = {_quoted(self.notes)}",
            f"{prefix}{inst}.configure()",
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
            >>> from qtpy.QtWidgets import QApplication
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
            """Copy the current text of *user_edit* to :attr:`user`."""
            self.user = user_edit.text()

        user_edit.editingFinished.connect(_apply_user)
        layout.addRow("User:", user_edit)

        # --- sample ---
        sample_edit = QLineEdit(self.sample, widget)
        sample_edit.setPlaceholderText("Sample identifier")

        def _apply_sample() -> None:
            """Copy the current text of *sample_edit* to :attr:`sample`."""
            self.sample = sample_edit.text()

        sample_edit.editingFinished.connect(_apply_sample)
        layout.addRow("Sample:", sample_edit)

        # --- project ---
        project_combo = QComboBox(widget)
        project_combo.setEditable(True)
        project_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for dir_name in _top_level_dirs(_get_data_root()):
            project_combo.addItem(dir_name)
        # Set current text to the stored project value
        project_combo.setCurrentText(self.project)

        def _apply_project() -> None:
            """Copy the current text of *project_combo* to :attr:`project`."""
            self.project = project_combo.currentText()

        project_combo.currentTextChanged.connect(_apply_project)
        layout.addRow("Project:", project_combo)

        # --- notes ---
        notes_edit = QPlainTextEdit(self.notes, widget)
        notes_edit.setPlaceholderText("Free-form notes about this measurement…")
        notes_edit.setMinimumHeight(80)

        def _apply_notes() -> None:
            """Copy the plain text of *notes_edit* to :attr:`notes`."""
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
            >>> from qtpy.QtWidgets import QApplication
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
