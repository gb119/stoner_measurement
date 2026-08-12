"""DetailsCommand — built-in command plugin for recording measurement metadata.

:class:`DetailsCommand` is a concrete :class:`CommandPlugin` that stores
metadata about a measurement run (operator, sample, project, and free-form
notes).  Rather than emitting a ``{instance_name}()`` call, the generated
sequence code consists of attribute-assignment statements that attach the
configured values directly to the plugin instance in the engine namespace,
making them accessible to downstream sequence steps and data-saving plugins.

The *project* combo box is pre-populated with the top-level subdirectories of
the configured application default data directory. Falls back to the user's
home directory if no setting has been saved yet.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from qtpy.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.theme import colour


def _get_data_root() -> Path:
    """Return the configured default data directory, falling back to the home directory.

    If the configured path is empty, :func:`pathlib.Path.home` is returned
    instead.

    Returns:
        (Path):
            The path to use as the root when listing project subdirectories.
    """
    from stoner_measurement.app_config import default_data_directory

    data_dir = default_data_directory()
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

    The :attr:`date`, :attr:`time`, and :attr:`rig` attributes are read-only
    runtime properties rather than configuration fields. ``date`` and ``time``
    return the current local date and time when accessed, while ``rig`` reads
    the local rig name from the application configuration.

    Additional metadata can be configured on the **Metadata** tab as a name
    and Python value expression. Generated sequence code evaluates those
    expressions in the engine namespace and assigns the results as attributes
    on this instance. For example, a metadata row named ``temperature`` can be
    read by later sequence steps as ``details.temperature`` (or through the
    configured :attr:`instance_name`). The configured rows themselves are
    available through :attr:`metadata_expressions`.

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
        date (str):
            Read-only current local date in ``YYYYMMDD`` form.
        time (str):
            Read-only current local time in ``HHmmss`` form.
        rig (str):
            Read-only rig name from the local application configuration.
        metadata_expressions (list[dict[str, str]]):
            Additional attribute names and value expressions. Each entry has
            ``"name"`` and ``"expression"`` keys; generated code exposes the
            evaluated value as an attribute named by ``"name"``.

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
        self._metadata_reserved_names = frozenset(dir(self))
        self.metadata_expressions: list[dict[str, str]] = []
        self.show_validation_error.connect(self._display_validation_error)

    @property
    def date(self) -> str:
        """Current local date formatted as ``YYYYMMDD``."""
        return datetime.now().strftime("%Y%m%d")

    @property
    def time(self) -> str:
        """Current local time formatted as ``HHmmss`` at access time."""
        return datetime.now().strftime("%H%M%S")

    @property
    def rig(self) -> str:
        """Return the rig name from this machine's application configuration."""
        from stoner_measurement.app_config import rig_setting

        return rig_setting()

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

    def eval_metadata(self, expression: str) -> Any:
        """Evaluate a metadata value, treating unknown identifiers as literal text.

        Metadata is deliberately more forgiving than other runtime expression
        fields. A bare unquoted string is valid Python syntax, so the shared
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval` path
        raises :class:`NameError` rather than using its syntax-error fallback.
        For metadata only, warn and retry the original text as a quoted string.
        The retry still uses the shared evaluator, preserving runtime f-string
        interpolation for replacement fields.

        Args:
            expression (str):
                Stored metadata expression or free-form literal text.

        Returns:
            (Any):
                Evaluated expression or literal-string fallback.
        """
        try:
            return self.eval(expression)
        except NameError as exc:
            self.log.warning(
                "Metadata value %r referenced an unknown identifier (%s); "
                "treating it as literal text.",
                expression,
                exc,
            )
            return self.eval(repr(expression))

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return attribute-assignment code lines for this plugin.

        Instead of a ``{instance_name}()`` call, emits four assignment
        statements that set the metadata attributes on the plugin instance in
        the engine namespace. Additional metadata values are assigned through
        :meth:`eval_metadata`, which delegates to the shared runtime evaluator
        so genuine Python expressions use the live engine namespace while
        syntactically invalid text follows the quoted-string and runtime
        f-string fallback. Metadata also treats an unknown identifier as
        likely unquoted literal text after logging a warning. A ``configure()``
        call and blank separator line follow the assignments.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Ignored — :class:`DetailsCommand` is always a leaf node.
            render_sub_step (Callable):
                Ignored — :class:`DetailsCommand` is always a leaf node.

        Returns:
            (list[str]):
                Four fixed-detail assignments, any evaluated metadata
                assignments, one ``configure()`` call, and a trailing blank
                line.

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
        ]
        seen: set[str] = set()
        for item in self.metadata_expressions:
            name = item["name"].strip()
            expression = item["expression"].strip()
            error = self._metadata_name_error(name)
            if name in seen:
                error = f"Duplicate metadata name: {name!r}."
            if not expression:
                error = "A value expression is required."
            if error:
                raise ValueError(error)
            seen.add(name)
            lines.append(f"{prefix}{inst}.{name} = {inst}.eval_metadata({expression!r})")
        lines.extend((f"{prefix}{inst}.configure()", ""))
        return lines

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return General, Metadata, and standard optional About tabs."""

        def _build_tabs() -> list[tuple[str, QWidget]]:
            tabs = [
                ("General", self._general_details_config_widget(parent=parent)),
                ("Metadata", self._metadata_config_widget(parent=parent)),
            ]
            about_tab = self._make_about_tab()
            if about_tab is not None:
                tabs.append(about_tab)
            return tabs

        return self._get_cached_config_tabs(_build_tabs)

    def _general_details_config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Build the top-packed General tab with identity and fixed detail fields."""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._general_config_widget(parent=widget))

        separator = QFrame(widget)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        layout.addWidget(self.config_widget(parent=widget))
        layout.addStretch(1)
        return widget

    def _metadata_name_error(self, name: str) -> str | None:
        """Return a validation message for an invalid custom attribute name."""
        if not name.isidentifier() or name.startswith("_"):
            return "Names must be valid Python identifiers and must not start with an underscore."
        configured_names = {item["name"] for item in self.metadata_expressions}
        if name in self._metadata_reserved_names or (
            hasattr(self, name) and name not in configured_names
        ):
            return f"{name!r} clashes with an existing Details attribute."
        return None

    def _metadata_config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Build the table used to configure runtime metadata expressions."""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        table = QTableWidget(0, 2, widget)
        table.setObjectName("detailsMetadataTable")
        table.setHorizontalHeaderLabels(["Name", "Value expression"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(True)
        selected_background = colour("tab_selected_background")
        selected_border = colour("tab_selected_border")
        text_colour = colour("text")
        table.setStyleSheet(
            "QTableWidget::item:selected {"
            f"background-color: {selected_background}; color: {text_colour};"
            "}"
            "QTableWidget QLineEdit {"
            f"background-color: {selected_background}; color: {text_colour};"
            f"border: 1px solid {selected_border};"
            "}"
        )
        visible_rows = 6
        table_height = (
            table.horizontalHeader().sizeHint().height()
            + table.verticalHeader().defaultSectionSize() * visible_rows
            + 2 * table.frameWidth()
        )
        table.setFixedHeight(table_height)
        layout.addWidget(table)

        def sync() -> None:
            entries: list[dict[str, str]] = []
            seen: set[str] = set()
            for row in range(table.rowCount()):
                name_item = table.item(row, 0)
                expr_item = table.item(row, 1)
                name = name_item.text().strip() if name_item else ""
                expression = expr_item.text().strip() if expr_item else ""
                error = self._metadata_name_error(name) if name else "Name is required."
                if name in seen:
                    error = f"Duplicate metadata name: {name!r}."
                if not expression:
                    error = "A value expression is required."
                if error:
                    if name_item is not None:
                        name_item.setToolTip(error)
                    continue
                name_item.setToolTip("")
                seen.add(name)
                entries.append({"name": name, "expression": expression})
            self.metadata_expressions = entries

        def add_row(name: str = "", expression: str = "") -> int:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(expression))
            return row

        table.blockSignals(True)
        for entry in self.metadata_expressions:
            add_row(entry["name"], entry["expression"])
        table.blockSignals(False)

        buttons = QHBoxLayout()
        add_button = QPushButton("Add", widget)
        add_button.setObjectName("detailsMetadataAddButton")
        remove_button = QPushButton("Remove", widget)
        remove_button.setObjectName("detailsMetadataRemoveButton")
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

        def remove_selected() -> None:
            row = table.currentRow()
            if row >= 0:
                table.removeRow(row)
                sync()

        def add_empty_row() -> None:
            row = add_row()
            name_item = table.item(row, 0)
            table.setCurrentCell(row, 0)
            table.scrollToItem(name_item)
            table.editItem(name_item)

        add_button.clicked.connect(add_empty_row)
        remove_button.clicked.connect(remove_selected)
        table.itemChanged.connect(lambda _item: sync())
        return widget

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
        user_edit.setObjectName("detailsUserEdit")
        user_edit.setPlaceholderText("Operator name")

        def _apply_user() -> None:
            """Copy the current text of *user_edit* to :attr:`user`."""
            self.user = user_edit.text()

        user_edit.editingFinished.connect(_apply_user)
        layout.addRow("User:", user_edit)

        # --- sample ---
        sample_edit = QLineEdit(self.sample, widget)
        sample_edit.setObjectName("detailsSampleEdit")
        sample_edit.setPlaceholderText("Sample identifier")

        def _apply_sample() -> None:
            """Copy the current text of *sample_edit* to :attr:`sample`."""
            self.sample = sample_edit.text()

        sample_edit.editingFinished.connect(_apply_sample)
        layout.addRow("Sample:", sample_edit)

        # --- project ---
        project_combo = QComboBox(widget)
        project_combo.setObjectName("detailsProjectCombo")
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
        notes_edit.setObjectName("detailsNotesEdit")
        notes_edit.setPlaceholderText("Free-form notes about this measurement…")
        notes_height = (
            notes_edit.fontMetrics().lineSpacing() * 8
            + 2 * round(notes_edit.document().documentMargin())
            + 2 * notes_edit.frameWidth()
        )
        notes_edit.setFixedHeight(notes_height)

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
        d["metadata_expressions"] = [dict(item) for item in self.metadata_expressions]
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
        if "metadata_expressions" in data:
            self.metadata_expressions = [
                {"name": str(item["name"]), "expression": str(item["expression"])}
                for item in data["metadata_expressions"]
                if isinstance(item, dict) and "name" in item and "expression" in item
            ]
