"""Settings dialogue for the Stoner Measurement application.

Provides :class:`SettingsDialog` for editing persistent application preferences,
and :func:`make_app_settings` for obtaining the shared :class:`~PyQt6.QtCore.QSettings`
instance backed by an INI file.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

#: Settings key for the default data directory.
KEY_DEFAULT_DATA_DIR = "app/default_data_directory"
#: Settings key for the default sequence template path.
KEY_DEFAULT_SEQUENCE_TEMPLATE = "app/default_sequence_template"


def make_app_settings() -> QSettings:
    """Return a :class:`~PyQt6.QtCore.QSettings` instance backed by an INI file.

    The file is placed in the platform-appropriate user-configuration directory:

    * **Windows** — ``%APPDATA%\\University of Leeds\\Stoner Measurement.ini``
    * **Linux / Unix** — ``~/.config/University of Leeds/Stoner Measurement.ini``
    * **macOS** — ``~/Library/Preferences/University of Leeds/Stoner Measurement.ini``

    Returns:
        (QSettings):
            The application-settings object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> s = make_app_settings()
        >>> isinstance(s, QSettings)
        True
    """
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "University of Leeds",
        "Stoner Measurement",
    )


class SettingsDialog(QDialog):
    """Modal preferences dialogue for editing persistent application settings.

    Presents a form with two fields:

    * **Default data directory** — the directory used as the starting point for
      file-open and file-save dialogues (sequences, scripts, and data files).
    * **Default sequence template** — path to a JSON sequence file that is
      loaded whenever a new sequence is created or the application starts.  If
      the path is empty or the file does not exist an empty sequence is used.

    Changes are written to the INI-format settings file returned by
    :func:`make_app_settings` when the user clicks *OK*.

    Args:
        parent (QWidget | None):
            Optional parent widget.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> dlg = SettingsDialog()
        >>> dlg.windowTitle()
        'Preferences'
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(520)

        settings = make_app_settings()

        # ── Form ──────────────────────────────────────────────────────────
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Default data directory row
        self._data_dir_edit = QLineEdit(self)
        self._data_dir_edit.setPlaceholderText("(none — use current working directory)")
        self._data_dir_edit.setText(settings.value(KEY_DEFAULT_DATA_DIR, "", type=str))

        data_dir_browse = QPushButton("Browse…", self)
        data_dir_browse.setFixedWidth(80)
        data_dir_browse.clicked.connect(self._browse_data_dir)

        data_dir_row = QHBoxLayout()
        data_dir_row.setContentsMargins(0, 0, 0, 0)
        data_dir_row.addWidget(self._data_dir_edit)
        data_dir_row.addWidget(data_dir_browse)
        form.addRow("Default data directory:", data_dir_row)

        # Default sequence template row
        self._template_edit = QLineEdit(self)
        self._template_edit.setPlaceholderText("(none — start with empty sequence)")
        self._template_edit.setText(settings.value(KEY_DEFAULT_SEQUENCE_TEMPLATE, "", type=str))

        template_browse = QPushButton("Browse…", self)
        template_browse.setFixedWidth(80)
        template_browse.clicked.connect(self._browse_template)

        template_row = QHBoxLayout()
        template_row.setContentsMargins(0, 0, 0, 0)
        template_row.addWidget(self._template_edit)
        template_row.addWidget(template_browse)
        form.addRow("Default sequence template:", template_row)

        # ── Button box ────────────────────────────────────────────────────
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(button_box)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _browse_data_dir(self) -> None:
        """Open a directory-chooser and populate the data-directory field."""
        current = self._data_dir_edit.text().strip()
        start = current if Path(current).is_dir() else ""
        path = QFileDialog.getExistingDirectory(
            self, "Select Default Data Directory", start
        )
        if path:
            self._data_dir_edit.setText(path)

    def _browse_template(self) -> None:
        """Open a file-chooser and populate the sequence-template field."""
        current = self._template_edit.text().strip()
        start_dir = str(Path(current).parent) if current else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Default Sequence Template",
            start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self._template_edit.setText(path)

    def _on_accept(self) -> None:
        """Write the current field values to the INI settings file."""
        settings = make_app_settings()
        settings.setValue(KEY_DEFAULT_DATA_DIR, self._data_dir_edit.text().strip())
        settings.setValue(KEY_DEFAULT_SEQUENCE_TEMPLATE, self._template_edit.text().strip())
        settings.sync()
        self.accept()
