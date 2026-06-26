"""Tests for the application settings dialog."""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import QSettings
from qtpy.QtWidgets import QDialog, QLineEdit, QMessageBox

from stoner_measurement.ui import settings_dialog as settings_module
from stoner_measurement.ui.settings_dialog import KEY_DEFAULT_DATA_DIR, KEY_THEME, SettingsDialog


def _temp_settings(path: Path) -> QSettings:
    """Return a QSettings object backed by a test-local INI file."""
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.clear()
    return settings


def _install_dialog_dependencies(monkeypatch, settings: QSettings, toolbar_config: dict | None = None) -> None:
    """Patch persistent dependencies used by SettingsDialog construction."""
    monkeypatch.setattr(settings_module, "make_app_settings", lambda: settings)
    monkeypatch.setattr(settings_module, "load_toolbar_config", lambda: toolbar_config or {"buttons": []})


def _cell_line_edit(dialog: SettingsDialog, row: int, column: int) -> QLineEdit:
    cell = dialog._toolbar_table.cellWidget(row, column)
    assert cell is not None
    line_edit = cell.findChild(QLineEdit)
    assert line_edit is not None
    return line_edit


class TestSettingsDialogBasics:
    def test_creates_dialog_with_saved_settings(self, qapp, tmp_path, monkeypatch):
        settings = _temp_settings(tmp_path / "settings.ini")
        settings.setValue(KEY_DEFAULT_DATA_DIR, str(tmp_path / "data"))
        settings.setValue(KEY_THEME, "light")
        _install_dialog_dependencies(monkeypatch, settings)

        dialog = SettingsDialog()

        assert dialog.windowTitle() == "Preferences"
        assert dialog._data_dir_edit.text() == str(tmp_path / "data")
        assert dialog._theme_combo.currentText().lower() == "light"

    def test_unknown_saved_theme_falls_back_to_first_available_theme(self, qapp, tmp_path, monkeypatch):
        settings = _temp_settings(tmp_path / "settings.ini")
        settings.setValue(KEY_THEME, "definitely-not-a-theme")
        _install_dialog_dependencies(monkeypatch, settings)

        dialog = SettingsDialog()

        assert dialog._theme_combo.currentText().lower() == settings_module.available_themes()[0]

    def test_accept_persists_data_directory_and_theme(self, qapp, tmp_path, monkeypatch):
        settings = _temp_settings(tmp_path / "settings.ini")
        _install_dialog_dependencies(monkeypatch, settings)
        dialog = SettingsDialog()

        dialog._data_dir_edit.setText(f"  {tmp_path / 'runs'}  ")
        dialog._theme_combo.setCurrentIndex(dialog._theme_combo.findText("Light"))
        dialog._on_accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert settings.value(KEY_DEFAULT_DATA_DIR, "", type=str) == str(tmp_path / "runs")
        assert settings.value(KEY_THEME, "", type=str) == "light"

    def test_reject_does_not_persist_changes(self, qapp, tmp_path, monkeypatch):
        settings = _temp_settings(tmp_path / "settings.ini")
        settings.setValue(KEY_DEFAULT_DATA_DIR, "before")
        settings.setValue(KEY_THEME, "dark")
        _install_dialog_dependencies(monkeypatch, settings)
        dialog = SettingsDialog()

        dialog._data_dir_edit.setText("after")
        dialog._theme_combo.setCurrentIndex(dialog._theme_combo.findText("Light"))
        dialog.reject()

        assert dialog.result() == QDialog.DialogCode.Rejected
        assert settings.value(KEY_DEFAULT_DATA_DIR, "", type=str) == "before"
        assert settings.value(KEY_THEME, "", type=str) == "dark"


class TestSettingsDialogToolbarRows:
    def test_loads_toolbar_buttons_and_separators(self, qapp, tmp_path, monkeypatch):
        settings = _temp_settings(tmp_path / "settings.ini")
        toolbar_config = {
            "buttons": [
                {
                    "name": "Run IV",
                    "sequence": "iv.json",
                    "image": "iv.png",
                    "tooltip": "Run an IV curve",
                },
                {"separator": True},
            ]
        }
        _install_dialog_dependencies(monkeypatch, settings, toolbar_config)

        dialog = SettingsDialog()

        assert dialog._toolbar_table.rowCount() == 2
        assert dialog._toolbar_table.item(0, 0).text() == "Run IV"
        assert _cell_line_edit(dialog, 0, 1).text() == "iv.json"
        assert _cell_line_edit(dialog, 0, 2).text() == "iv.png"
        assert dialog._toolbar_table.item(0, 3).text() == "Run an IV curve"
        assert dialog._row_is_separator(1)
        assert not _cell_line_edit(dialog, 1, 1).isEnabled()
        assert not _cell_line_edit(dialog, 1, 2).isEnabled()

    def test_collect_toolbar_config_uses_sequence_stem_for_blank_name(self, qapp, tmp_path, monkeypatch):
        settings = _temp_settings(tmp_path / "settings.ini")
        _install_dialog_dependencies(monkeypatch, settings)
        dialog = SettingsDialog()
        dialog._add_toolbar_row(name="", sequence="cool_scan.json", icon="", tooltip="")
        dialog._add_separator_row()

        assert dialog._collect_toolbar_config_from_ui() == {
            "buttons": [
                {"name": "cool_scan", "sequence": "cool_scan.json"},
                {"separator": True},
            ]
        }

    def test_validate_toolbar_rows_reports_actionable_warnings(self, qapp, tmp_path, monkeypatch):
        settings = _temp_settings(tmp_path / "settings.ini")
        _install_dialog_dependencies(monkeypatch, settings)
        dialog = SettingsDialog()
        dialog._add_toolbar_row(name="Duplicate", sequence="same.json", icon="", tooltip="")
        dialog._add_toolbar_row(name="Duplicate", sequence="same.json", icon="", tooltip="")
        dialog._add_toolbar_row(name="Missing Sequence", sequence="", icon="", tooltip="Has tooltip")

        warnings = dialog._validate_toolbar_rows()

        assert "Row 1: tooltip is empty." in warnings
        assert "Row 2: duplicate button name 'Duplicate'." in warnings
        assert "Row 2: duplicate sequence filename 'same.json'." in warnings
        assert "Row 3: button entries should specify a sequence filename." in warnings

    def test_remove_selected_toolbar_row(self, qapp, tmp_path, monkeypatch):
        settings = _temp_settings(tmp_path / "settings.ini")
        _install_dialog_dependencies(monkeypatch, settings)
        dialog = SettingsDialog()
        dialog._add_toolbar_row(name="One", sequence="one.json")
        dialog._add_toolbar_row(name="Two", sequence="two.json")

        dialog._toolbar_table.selectRow(0)
        dialog._remove_selected_toolbar_row()

        assert dialog._toolbar_table.rowCount() == 1
        assert dialog._toolbar_table.item(0, 0).text() == "Two"


class TestSettingsDialogToolbarSave:
    def test_save_toolbar_cancel_on_validation_warning_does_not_write(self, qapp, tmp_path, monkeypatch):
        settings = _temp_settings(tmp_path / "settings.ini")
        _install_dialog_dependencies(monkeypatch, settings)
        dialog = SettingsDialog()
        dialog._add_toolbar_row(name="Broken", sequence="")
        saved = []
        monkeypatch.setattr(settings_module, "save_toolbar_config", lambda config: saved.append(config))
        monkeypatch.setattr(
            settings_module.QMessageBox,
            "warning",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
        )

        dialog._save_toolbar_from_ui()

        assert saved == []
        assert dialog.toolbar_saved is False

    def test_save_toolbar_writes_valid_config(self, qapp, tmp_path, monkeypatch):
        settings = _temp_settings(tmp_path / "settings.ini")
        _install_dialog_dependencies(monkeypatch, settings)
        dialog = SettingsDialog()
        dialog._add_toolbar_row(name="Run", sequence="run.json", icon="run.png", tooltip="Run it")
        saved = []
        monkeypatch.setattr(
            settings_module,
            "save_toolbar_config",
            lambda config: saved.append(config) or (tmp_path / "toolbar.yaml"),
        )
        monkeypatch.setattr(settings_module.QMessageBox, "information", lambda *_args, **_kwargs: None)

        dialog._save_toolbar_from_ui()

        assert saved == [
            {"buttons": [{"name": "Run", "sequence": "run.json", "image": "run.png", "tooltip": "Run it"}]}
        ]
        assert dialog._toolbar_cfg == saved[0]
        assert dialog.toolbar_saved is True
