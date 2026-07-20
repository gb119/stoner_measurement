"""Tests for the application settings dialog."""

from __future__ import annotations

from qtpy.QtWidgets import QDialog, QLineEdit, QMessageBox

from stoner_measurement.ui import settings_dialog as settings_module
from stoner_measurement.ui.settings_dialog import SettingsDialog


def _install_dialog_dependencies(monkeypatch, app_config: dict, toolbar_config: dict | None = None) -> list[dict]:
    """Patch persistent dependencies used by SettingsDialog construction."""
    saved_configs: list[dict] = []
    monkeypatch.setattr(settings_module, "load_app_config", lambda: app_config)
    monkeypatch.setattr(settings_module, "save_app_config", lambda config: saved_configs.append(config))
    monkeypatch.setattr(settings_module, "load_toolbar_config", lambda: toolbar_config or {"buttons": []})
    return saved_configs


def _cell_line_edit(dialog: SettingsDialog, row: int, column: int) -> QLineEdit:
    cell = dialog._toolbar_table.cellWidget(row, column)
    assert cell is not None
    line_edit = cell.findChild(QLineEdit)
    assert line_edit is not None
    return line_edit


class TestSettingsDialogBasics:
    def test_creates_dialog_with_saved_settings(self, qapp, monkeypatch):
        app_config = {
            "app": {"default_data_directory": "C:/Data/Test", "theme": "light"},
            "features": {
                "temperature": True,
                "magnetic_field": False,
                "motor_position": True,
                "pressure": True,
            },
        }
        _install_dialog_dependencies(monkeypatch, app_config)

        dialog = SettingsDialog()

        assert dialog.windowTitle() == "Preferences"
        assert dialog._data_dir_edit.text() == "C:/Data/Test"
        assert dialog._theme_combo.currentText().lower() == "light"
        assert dialog._feature_checkboxes["temperature"].isChecked() is True
        assert dialog._feature_checkboxes["magnetic_field"].isChecked() is False

    def test_unknown_saved_theme_falls_back_to_first_available_theme(self, qapp, monkeypatch):
        _install_dialog_dependencies(
            monkeypatch,
            {
                "app": {"default_data_directory": "", "theme": "definitely-not-a-theme"},
                "features": {},
            },
        )

        dialog = SettingsDialog()

        assert dialog._theme_combo.currentText().lower() == settings_module.available_themes()[0]

    def test_accept_persists_data_directory_theme_and_features(self, qapp, tmp_path, monkeypatch):
        saved = _install_dialog_dependencies(
            monkeypatch,
            {
                "app": {"default_data_directory": "", "theme": "dark"},
                "features": {
                    "temperature": True,
                    "magnetic_field": True,
                    "motor_position": True,
                    "pressure": True,
                },
            },
        )
        dialog = SettingsDialog()

        dialog._data_dir_edit.setText(f"  {tmp_path / 'runs'}  ")
        dialog._theme_combo.setCurrentIndex(dialog._theme_combo.findText("Light"))
        dialog._feature_checkboxes["pressure"].setChecked(False)
        dialog._on_accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert saved == [
            {
                "app": {
                    "default_data_directory": str(tmp_path / "runs"),
                    "theme": "light",
                },
                "features": {
                    "temperature": True,
                    "magnetic_field": True,
                    "motor_position": True,
                    "pressure": False,
                },
            }
        ]

    def test_reject_does_not_persist_changes(self, qapp, monkeypatch):
        saved = _install_dialog_dependencies(
            monkeypatch,
            {
                "app": {"default_data_directory": "before", "theme": "dark"},
                "features": {"temperature": True},
            },
        )
        dialog = SettingsDialog()

        dialog._data_dir_edit.setText("after")
        dialog.reject()

        assert dialog.result() == QDialog.DialogCode.Rejected
        assert saved == []


class TestSettingsDialogToolbarRows:
    def test_loads_toolbar_buttons_and_separators(self, qapp, monkeypatch):
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
        _install_dialog_dependencies(monkeypatch, {"app": {}, "features": {}}, toolbar_config)

        dialog = SettingsDialog()

        assert dialog._toolbar_table.rowCount() == 2
        assert dialog._toolbar_table.item(0, 0).text() == "Run IV"
        assert _cell_line_edit(dialog, 0, 1).text() == "iv.json"
        assert _cell_line_edit(dialog, 0, 2).text() == "iv.png"
        assert dialog._toolbar_table.item(0, 3).text() == "Run an IV curve"
        assert dialog._row_is_separator(1)
        assert not _cell_line_edit(dialog, 1, 1).isEnabled()
        assert not _cell_line_edit(dialog, 1, 2).isEnabled()

    def test_collect_toolbar_config_uses_sequence_stem_for_blank_name(self, qapp, monkeypatch):
        _install_dialog_dependencies(monkeypatch, {"app": {}, "features": {}})
        dialog = SettingsDialog()
        dialog._add_toolbar_row(name="", sequence="cool_scan.json", icon="", tooltip="")
        dialog._add_separator_row()

        assert dialog._collect_toolbar_config_from_ui() == {
            "buttons": [
                {"name": "cool_scan", "sequence": "cool_scan.json"},
                {"separator": True},
            ]
        }

    def test_validate_toolbar_rows_reports_actionable_warnings(self, qapp, monkeypatch):
        _install_dialog_dependencies(monkeypatch, {"app": {}, "features": {}})
        dialog = SettingsDialog()
        dialog._add_toolbar_row(name="Duplicate", sequence="same.json", icon="", tooltip="")
        dialog._add_toolbar_row(name="Duplicate", sequence="same.json", icon="", tooltip="")
        dialog._add_toolbar_row(name="Missing Sequence", sequence="", icon="", tooltip="Has tooltip")

        warnings = dialog._validate_toolbar_rows()

        assert "Row 1: tooltip is empty." in warnings
        assert "Row 2: duplicate button name 'Duplicate'." in warnings
        assert "Row 2: duplicate sequence filename 'same.json'." in warnings
        assert "Row 3: button entries should specify a sequence filename." in warnings

    def test_remove_selected_toolbar_row(self, qapp, monkeypatch):
        _install_dialog_dependencies(monkeypatch, {"app": {}, "features": {}})
        dialog = SettingsDialog()
        dialog._add_toolbar_row(name="One", sequence="one.json")
        dialog._add_toolbar_row(name="Two", sequence="two.json")

        dialog._toolbar_table.selectRow(0)
        dialog._remove_selected_toolbar_row()

        assert dialog._toolbar_table.rowCount() == 1
        assert dialog._toolbar_table.item(0, 0).text() == "Two"


class TestSettingsDialogToolbarSave:
    def test_save_toolbar_cancel_on_validation_warning_does_not_write(self, qapp, monkeypatch):
        _install_dialog_dependencies(monkeypatch, {"app": {}, "features": {}})
        dialog = SettingsDialog()
        dialog._add_toolbar_row(name="Broken", sequence="")
        saved = []
        monkeypatch.setattr(settings_module, "save_toolbar_config", saved.append)
        monkeypatch.setattr(
            settings_module.QMessageBox,
            "warning",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
        )

        dialog._save_toolbar_from_ui()

        assert saved == []
        assert dialog.toolbar_saved is False

    def test_save_toolbar_writes_valid_config(self, qapp, tmp_path, monkeypatch):
        _install_dialog_dependencies(monkeypatch, {"app": {}, "features": {}})
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
