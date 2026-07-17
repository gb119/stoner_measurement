"""Settings dialogue for the Stoner Measurement application."""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import QSettings
from qtpy.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.app_config import (
    FEATURE_DEFINITIONS,
    KEY_DEFAULT_DATA_DIR,
    KEY_THEME,
    default_data_directory,
    load_app_config,
    save_app_config,
    set_app_config_value,
    theme_setting,
)
from stoner_measurement.resources import (
    load_toolbar_config,
    save_toolbar_config,
    user_config_root,
)
from stoner_measurement.ui.theme import DEFAULT_THEME, available_themes

_ROW_TYPE_SEPARATOR = "__separator__"


def make_app_settings() -> QSettings:
    """Return the QSettings store used for non-YAML UI state such as geometry."""
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "University of Leeds",
        "Stoner Measurement",
    )


class SettingsDialog(QDialog):
    """Modal preferences dialogue for editing persistent application settings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(620)

        self.toolbar_saved = False
        self._toolbar_cfg = load_toolbar_config()
        self._feature_checkboxes: dict[str, QCheckBox] = {}
        app_config = load_app_config()

        tabs = QTabWidget(self)
        tabs.addTab(self._build_general_tab(app_config), "General")
        tabs.addTab(self._build_features_tab(app_config), "Features")
        tabs.addTab(self._build_toolbar_tab(), "Toolbar")

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(tabs)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def _build_general_tab(self, app_config: dict) -> QWidget:
        tab = QWidget(self)
        form = QFormLayout(tab)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self._data_dir_edit = QLineEdit(tab)
        self._data_dir_edit.setPlaceholderText("(none - use current working directory)")
        self._data_dir_edit.setText(default_data_directory(config=app_config))

        data_dir_browse = QPushButton("Browse...", tab)
        data_dir_browse.setFixedWidth(80)
        data_dir_browse.clicked.connect(self._browse_data_dir)

        data_dir_row = QHBoxLayout()
        data_dir_row.setContentsMargins(0, 0, 0, 0)
        data_dir_row.addWidget(self._data_dir_edit)
        data_dir_row.addWidget(data_dir_browse)
        form.addRow("Default data directory:", data_dir_row)

        self._theme_combo = QComboBox(tab)
        self._theme_combo.addItems([name.capitalize() for name in available_themes()])
        saved_theme = theme_setting(config=app_config) or DEFAULT_THEME
        index = max(0, available_themes().index(saved_theme) if saved_theme in available_themes() else 0)
        self._theme_combo.setCurrentIndex(index)
        form.addRow("Theme:", self._theme_combo)
        return tab

    def _build_features_tab(self, app_config: dict) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        help_label = QLabel(
            "Disable a controller feature to hide its menu, toolbar, panel, status "
            "indicator, and any plugins that declare they depend on that controller.",
            tab,
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        for entry in FEATURE_DEFINITIONS:
            checkbox = QCheckBox(f"Enable {entry['label']}", tab)
            checkbox.setChecked(bool(app_config.get("features", {}).get(entry["key"], True)))
            self._feature_checkboxes[entry["key"]] = checkbox
            form.addRow(f"{entry['label']}:", checkbox)

        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _build_toolbar_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        self._toolbar_table = QTableWidget(0, 4, tab)
        self._toolbar_table.setHorizontalHeaderLabels(["Button name / separator", "Sequence", "Icon", "Tooltip"])
        self._toolbar_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._toolbar_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._toolbar_table.verticalHeader().setVisible(False)
        header = self._toolbar_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._toolbar_table.setMinimumHeight(220)
        self._load_toolbar_rows()
        layout.addWidget(self._toolbar_table)

        toolbar_help = QLabel(
            "Sequences are looked up by filename in the user and bundled sequences "
            "folders. Icons are looked up by filename in the user and bundled "
            "resources folders. Saving always writes a user toolbar.yaml override.",
            tab,
        )
        toolbar_help.setWordWrap(True)
        layout.addWidget(toolbar_help)

        toolbar_buttons_row = QHBoxLayout()
        toolbar_buttons_row.setContentsMargins(0, 0, 0, 0)
        add_toolbar_button = QPushButton("Add Button", tab)
        add_toolbar_button.clicked.connect(self._add_toolbar_row)
        add_separator_button = QPushButton("Add Separator", tab)
        add_separator_button.clicked.connect(self._add_separator_row)
        remove_toolbar_button = QPushButton("Remove Selected", tab)
        remove_toolbar_button.clicked.connect(self._remove_selected_toolbar_row)
        save_toolbar_button = QPushButton("Save Toolbar", tab)
        save_toolbar_button.clicked.connect(self._save_toolbar_from_ui)
        toolbar_buttons_row.addWidget(add_toolbar_button)
        toolbar_buttons_row.addWidget(add_separator_button)
        toolbar_buttons_row.addWidget(remove_toolbar_button)
        toolbar_buttons_row.addStretch(1)
        toolbar_buttons_row.addWidget(save_toolbar_button)
        layout.addLayout(toolbar_buttons_row)
        return tab

    def _load_toolbar_rows(self) -> None:
        """Populate the toolbar table from the effective toolbar configuration."""
        for button in self._toolbar_cfg.get("buttons", []):
            if button.get("separator"):
                self._add_separator_row()
                continue
            self._add_toolbar_row(
                name=button.get("name", ""),
                sequence=button.get("sequence", ""),
                icon=button.get("image", ""),
                tooltip=button.get("tooltip", ""),
            )

    def _make_file_picker_cell(
        self,
        value: str,
        browse_callback,
        placeholder: str = "",
        enabled: bool = True,
    ) -> QWidget:
        """Create a line-edit plus browse-button cell widget."""
        cell = QWidget(self)
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(value, cell)
        if placeholder:
            edit.setPlaceholderText(placeholder)
        edit.setEnabled(enabled)
        browse = QPushButton("...", cell)
        browse.setFixedWidth(32)
        browse.setEnabled(enabled)
        browse.clicked.connect(lambda: browse_callback(edit))
        layout.addWidget(edit)
        layout.addWidget(browse)
        return cell

    def _set_separator_row_state(self, row: int, is_separator: bool) -> None:
        """Update a row to behave as either a button row or separator row."""
        name_item = self._toolbar_table.item(row, 0)
        if name_item is None:
            name_item = QTableWidgetItem()
            self._toolbar_table.setItem(row, 0, name_item)
        if is_separator:
            name_item.setText("--- separator ---")
            name_item.setData(0x0100, _ROW_TYPE_SEPARATOR)
            for col in (1, 2, 3):
                item = self._toolbar_table.item(row, col)
                if item is not None:
                    item.setText("")
                cell_widget = self._toolbar_table.cellWidget(row, col)
                if cell_widget is not None:
                    cell_widget.setEnabled(False)
        else:
            if name_item.text() == "--- separator ---":
                name_item.setText("")
            name_item.setData(0x0100, None)
            for col in (1, 2, 3):
                cell_widget = self._toolbar_table.cellWidget(row, col)
                if cell_widget is not None:
                    cell_widget.setEnabled(True)

    def _add_toolbar_row(
        self,
        checked: bool = False,
        name: str = "",
        sequence: str = "",
        icon: str = "",
        tooltip: str = "",
    ) -> None:
        """Add one editable toolbar-button row to the table."""
        del checked
        row = self._toolbar_table.rowCount()
        self._toolbar_table.insertRow(row)
        self._toolbar_table.setItem(row, 0, QTableWidgetItem(name))
        self._toolbar_table.setItem(row, 3, QTableWidgetItem(tooltip))

        sequence_cell = self._make_file_picker_cell(
            sequence,
            self._browse_sequence_for_row,
            placeholder="sequence JSON filename",
        )
        self._toolbar_table.setCellWidget(row, 1, sequence_cell)

        icon_cell = self._make_file_picker_cell(
            icon,
            self._browse_icon_for_row,
            placeholder="icon filename",
        )
        self._toolbar_table.setCellWidget(row, 2, icon_cell)

    def _add_separator_row(self, checked: bool = False) -> None:
        """Add one toolbar separator row to the table."""
        del checked
        row = self._toolbar_table.rowCount()
        self._toolbar_table.insertRow(row)
        self._toolbar_table.setItem(row, 0, QTableWidgetItem())
        self._toolbar_table.setItem(row, 3, QTableWidgetItem(""))
        sequence_cell = self._make_file_picker_cell("", self._browse_sequence_for_row, enabled=False)
        icon_cell = self._make_file_picker_cell("", self._browse_icon_for_row, enabled=False)
        self._toolbar_table.setCellWidget(row, 1, sequence_cell)
        self._toolbar_table.setCellWidget(row, 2, icon_cell)
        self._set_separator_row_state(row, True)

    def _row_is_separator(self, row: int) -> bool:
        """Return True if the given table row represents a separator."""
        item = self._toolbar_table.item(row, 0)
        return bool(item and item.data(0x0100) == _ROW_TYPE_SEPARATOR)

    def _remove_selected_toolbar_row(self) -> None:
        """Remove the currently selected toolbar row, if any."""
        row = self._toolbar_table.currentRow()
        if row >= 0:
            self._toolbar_table.removeRow(row)

    def _browse_icon_for_row(self, line_edit: QLineEdit) -> None:
        """Choose an icon file and store its basename in the row editor."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Toolbar Icon",
            "",
            "Image Files (*.png *.svg *.ico *.jpg *.jpeg);;All Files (*)",
        )
        if path:
            line_edit.setText(Path(path).name)

    def _browse_sequence_for_row(self, line_edit: QLineEdit) -> None:
        """Choose a sequence file and store its basename in the row editor."""
        start_dir = str(user_config_root() / "sequences")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Toolbar Sequence",
            start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            line_edit.setText(Path(path).name)

    def _browse_data_dir(self) -> None:
        """Open a directory chooser and populate the data-directory field."""
        current = self._data_dir_edit.text().strip()
        start = current if Path(current).is_dir() else ""
        path = QFileDialog.getExistingDirectory(self, "Select Default Data Directory", start)
        if path:
            self._data_dir_edit.setText(path)

    def _validate_toolbar_rows(self) -> list[str]:
        """Return human-readable validation warnings for the toolbar table."""
        warnings = []
        seen_sequences: set[str] = set()
        seen_names: set[str] = set()
        for row in range(self._toolbar_table.rowCount()):
            if self._row_is_separator(row):
                continue
            name_item = self._toolbar_table.item(row, 0)
            tooltip_item = self._toolbar_table.item(row, 3)
            sequence_cell = self._toolbar_table.cellWidget(row, 1)
            sequence_edit = sequence_cell.findChild(QLineEdit) if sequence_cell is not None else None
            name = name_item.text().strip() if name_item is not None else ""
            sequence = sequence_edit.text().strip() if sequence_edit is not None else ""
            if not sequence:
                warnings.append(f"Row {row + 1}: button entries should specify a sequence filename.")
                continue
            effective_name = name or Path(sequence).stem
            if effective_name in seen_names:
                warnings.append(f"Row {row + 1}: duplicate button name '{effective_name}'.")
            else:
                seen_names.add(effective_name)
            if sequence in seen_sequences:
                warnings.append(f"Row {row + 1}: duplicate sequence filename '{sequence}'.")
            else:
                seen_sequences.add(sequence)
            if tooltip_item is not None and not tooltip_item.text().strip():
                warnings.append(f"Row {row + 1}: tooltip is empty.")
        return warnings

    def _collect_toolbar_config_from_ui(self) -> dict:
        """Build a toolbar configuration mapping from the table contents."""
        buttons = []
        for row in range(self._toolbar_table.rowCount()):
            name_item = self._toolbar_table.item(row, 0)
            tooltip_item = self._toolbar_table.item(row, 3)
            sequence_cell = self._toolbar_table.cellWidget(row, 1)
            icon_cell = self._toolbar_table.cellWidget(row, 2)
            sequence_edit = sequence_cell.findChild(QLineEdit) if sequence_cell is not None else None
            icon_edit = icon_cell.findChild(QLineEdit) if icon_cell is not None else None

            if self._row_is_separator(row):
                buttons.append({"separator": True})
                continue

            name = name_item.text().strip() if name_item is not None else ""
            sequence = sequence_edit.text().strip() if sequence_edit is not None else ""
            tooltip = tooltip_item.text().strip() if tooltip_item is not None else ""
            image = icon_edit.text().strip() if icon_edit is not None else ""

            if not sequence:
                continue
            entry = {"name": name or Path(sequence).stem, "sequence": sequence}
            if image:
                entry["image"] = image
            if tooltip:
                entry["tooltip"] = tooltip
            buttons.append(entry)
        return {"buttons": buttons}

    def _save_toolbar_from_ui(self) -> None:
        """Save the toolbar table contents to the user toolbar.yaml file."""
        warnings = self._validate_toolbar_rows()
        if warnings:
            message = "Toolbar configuration has some issues:\n\n- " + "\n- ".join(warnings)
            result = QMessageBox.warning(
                self,
                "Toolbar Validation Warnings",
                message,
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if result != QMessageBox.StandardButton.Save:
                return
        config = self._collect_toolbar_config_from_ui()
        path = save_toolbar_config(config)
        QMessageBox.information(self, "Toolbar Saved", f"Toolbar configuration saved to:\n{path}")
        self._toolbar_cfg = config
        self.toolbar_saved = True

    def _on_accept(self) -> None:
        """Write the current field values to the user application config."""
        config = load_app_config()
        set_app_config_value(config, KEY_DEFAULT_DATA_DIR, self._data_dir_edit.text().strip())
        set_app_config_value(config, KEY_THEME, self._theme_combo.currentText().strip().lower())
        for entry in FEATURE_DEFINITIONS:
            set_app_config_value(
                config,
                entry["config_key"],
                self._feature_checkboxes[entry["key"]].isChecked(),
            )
        save_app_config(config)
        self.accept()
