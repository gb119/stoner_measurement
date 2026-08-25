"""Tests for the application settings dialog."""

from __future__ import annotations

from qtpy.QtWidgets import QDialog, QLineEdit, QMessageBox

from stoner_measurement.app_config import FEATURE_DEFINITIONS
from stoner_measurement.ui import settings_dialog as settings_module
from stoner_measurement.ui.settings_dialog import SettingsDialog


def _install_dialog_dependencies(
    monkeypatch,
    app_config: dict,
    toolbar_config: dict | None = None,
    plugin_catalogue_config: dict | None = None,
) -> list[dict]:
    """Patch persistent dependencies used by SettingsDialog construction."""
    saved_configs: list[dict] = []
    monkeypatch.setattr(settings_module, "load_app_config", lambda: app_config)
    monkeypatch.setattr(settings_module, "save_app_config", saved_configs.append)
    monkeypatch.setattr(settings_module, "load_toolbar_config", lambda: toolbar_config or {"buttons": []})
    monkeypatch.setattr(
        settings_module,
        "load_plugin_catalogue_config",
        lambda: plugin_catalogue_config or {"items": []},
    )
    return saved_configs


def _cell_line_edit(dialog: SettingsDialog, row: int, column: int) -> QLineEdit:
    cell = dialog._toolbar_table.cellWidget(row, column)
    assert cell is not None
    line_edit = cell.findChild(QLineEdit)
    assert line_edit is not None
    return line_edit


class TestSettingsDialogBasics:
    def test_xray_feature_is_registered_once(self):
        assert [item["key"] for item in FEATURE_DEFINITIONS].count("xray") == 1

    def test_creates_dialog_with_saved_settings(self, qapp, monkeypatch):
        app_config = {
            "app": {"default_data_directory": "C:/Data/Test", "rig": "Rig-A", "theme": "light"},
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
        assert dialog._rig_edit.text() == "Rig-A"
        assert dialog._theme_combo.currentText().lower() == "light"
        assert dialog._font_size_spin.value() == settings_module.font_size_setting(
            config=app_config
        )
        assert dialog._editor_font_size_spin.value() == 10
        assert dialog._console_font_size_spin.value() == 9
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
                    "xray": True,
                },
            },
        )
        dialog = SettingsDialog()

        dialog._data_dir_edit.setText(f"  {tmp_path / 'runs'}  ")
        dialog._rig_edit.setText("  Cryostat-2  ")
        dialog._theme_combo.setCurrentIndex(dialog._theme_combo.findText("Light"))
        dialog._font_size_spin.setValue(12)
        dialog._editor_font_size_spin.setValue(13)
        dialog._console_font_size_spin.setValue(11)
        dialog._feature_checkboxes["pressure"].setChecked(False)
        dialog._on_accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert saved == [
            {
                "app": {
                    "default_data_directory": str(tmp_path / "runs"),
                    "rig": "Cryostat-2",
                    "theme": "light",
                    "font_size": 12,
                    "editor_font_size": 13,
                    "console_font_size": 11,
                },
                "features": {
                    "temperature": True,
                    "magnetic_field": True,
                    "motor_position": True,
                    "pressure": False,
                    "xray": True,
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

    def test_browse_icon_installs_selection_and_stores_installed_name(
        self, qapp, monkeypatch, tmp_path
    ):
        _install_dialog_dependencies(monkeypatch, {"app": {}, "features": {}})
        dialog = SettingsDialog()
        line_edit = QLineEdit()
        selected = tmp_path / "R(T).png"
        selected.write_bytes(b"icon")
        installed = tmp_path / "resources" / selected.name
        selected_paths = []
        monkeypatch.setattr(
            settings_module.QFileDialog,
            "getOpenFileName",
            lambda *_args, **_kwargs: (str(selected), "Image Files"),
        )
        monkeypatch.setattr(
            settings_module,
            "install_toolbar_icon",
            lambda path: selected_paths.append(path) or installed,
        )

        dialog._browse_icon_for_row(line_edit)

        assert selected_paths == [str(selected)]
        assert line_edit.text() == "R(T).png"

    def test_browse_sequence_installs_selection_and_stores_installed_name(
        self, qapp, monkeypatch, tmp_path
    ):
        _install_dialog_dependencies(monkeypatch, {"app": {}, "features": {}})
        dialog = SettingsDialog()
        line_edit = QLineEdit()
        selected = tmp_path / "R(T).json"
        selected.write_text("{}", encoding="utf-8")
        installed = tmp_path / "sequences" / selected.name
        selected_paths = []
        monkeypatch.setattr(
            settings_module.QFileDialog,
            "getOpenFileName",
            lambda *_args, **_kwargs: (str(selected), "JSON Files"),
        )
        monkeypatch.setattr(
            settings_module,
            "install_predefined_sequence",
            lambda path: selected_paths.append(path) or installed,
        )

        dialog._browse_sequence_for_row(line_edit)

        assert selected_paths == [str(selected)]
        assert line_edit.text() == "R(T).json"

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


class TestSettingsDialogPluginCatalogue:
    def test_add_group_as_sibling_then_move_plugin_in_and_out(
        self, qapp, monkeypatch
    ):
        config = {
            "items": [
                {
                    "group": "Control",
                    "items": [
                        {"plugin": "first", "label": "First"},
                        {"plugin": "second", "label": "Second"},
                    ],
                }
            ]
        }
        _install_dialog_dependencies(
            monkeypatch,
            {"app": {}, "features": {}},
            plugin_catalogue_config=config,
        )
        dialog = SettingsDialog()
        tree = dialog._plugin_catalogue_tree
        control = tree.topLevelItem(0)

        tree.setCurrentItem(control.child(0))
        dialog._add_catalogue_group()

        nested_group = control.child(1)
        assert nested_group.text(0) == "New Group"
        assert control.child(2).text(0) == "second"

        tree.setCurrentItem(control.child(2))
        dialog._move_catalogue_item_in()

        assert nested_group.childCount() == 1
        assert nested_group.child(0).text(0) == "second"
        assert nested_group.isExpanded()
        assert dialog._collect_plugin_catalogue_from_ui() == {
            "items": [
                {
                    "group": "Control",
                    "items": [
                        {"plugin": "first", "label": "First"},
                        {
                            "group": "New Group",
                            "items": [
                                {"plugin": "second", "label": "Second"}
                            ],
                        },
                    ],
                }
            ]
        }

        dialog._move_catalogue_item_out()

        assert nested_group.childCount() == 0
        assert control.child(2).text(0) == "second"

    def test_moving_group_preserves_expanded_leaf_subtree(self, qapp, monkeypatch):
        config = {
            "items": [
                {
                    "group": "Magnet Control",
                    "items": [
                        {"plugin": "set_field", "label": "Set"},
                        {"plugin": "field_scan", "label": "Scan"},
                    ],
                },
                {
                    "group": "Temperature Control",
                    "items": [
                        {"plugin": "set_temperature", "label": "Set"},
                    ],
                },
            ]
        }
        _install_dialog_dependencies(
            monkeypatch,
            {"app": {}, "features": {}},
            plugin_catalogue_config=config,
        )
        dialog = SettingsDialog()
        tree = dialog._plugin_catalogue_tree
        magnet_group = tree.topLevelItem(0)
        assert magnet_group.isExpanded()

        tree.setCurrentItem(magnet_group)
        dialog._move_catalogue_item(1)

        moved_group = tree.topLevelItem(1)
        assert moved_group is magnet_group
        assert moved_group.isExpanded()
        assert [
            (moved_group.child(index).text(0), moved_group.child(index).text(1))
            for index in range(moved_group.childCount())
        ] == [("set_field", "Set"), ("field_scan", "Scan")]

        dialog._move_catalogue_item(-1)

        assert tree.topLevelItem(0) is magnet_group
        assert magnet_group.isExpanded()
        assert magnet_group.childCount() == 2

    def test_edits_group_order_labels_and_available_plugins(self, qapp, monkeypatch):
        config = {
            "items": [
                {
                    "group": "Magnet Control",
                    "items": [
                        {"plugin": "set_field", "label": "Set"},
                        {"plugin": "field_scan", "label": "Scan"},
                    ],
                }
            ]
        }
        _install_dialog_dependencies(
            monkeypatch,
            {"app": {}, "features": {}},
            plugin_catalogue_config=config,
        )
        plugins = {
            "set_field": _NamedPlugin("Set Field"),
            "field_scan": _NamedPlugin("Field Scan"),
            "extra": _NamedPlugin("Extra Plugin"),
        }

        dialog = SettingsDialog(available_plugins=plugins)
        group = dialog._plugin_catalogue_tree.topLevelItem(0)
        dialog._plugin_catalogue_tree.setCurrentItem(group.child(1))
        dialog._move_catalogue_item(-1)
        group.child(0).setText(1, "Field scan")

        assert dialog._plugin_catalogue_combo.count() == 1
        assert dialog._plugin_catalogue_combo.currentData() == "extra"
        assert dialog._collect_plugin_catalogue_from_ui() == {
            "items": [
                {
                    "group": "Magnet Control",
                    "items": [
                        {"plugin": "field_scan", "label": "Field scan"},
                        {"plugin": "set_field", "label": "Set"},
                    ],
                }
            ]
        }

    def test_accept_saves_dirty_plugin_catalogue(self, qapp, tmp_path, monkeypatch):
        _install_dialog_dependencies(
            monkeypatch,
            {"app": {}, "features": {}},
            plugin_catalogue_config={"items": []},
        )
        saved = []
        monkeypatch.setattr(
            settings_module,
            "save_plugin_catalogue_config",
            lambda config: saved.append(config) or (tmp_path / "plugin_catalogue.yaml"),
        )
        dialog = SettingsDialog()
        dialog._add_catalogue_group()

        dialog._on_accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        assert saved == [{"items": [{"group": "New Group", "items": []}]}]
        assert dialog.plugin_catalogue_saved is True


class _NamedPlugin:
    """Minimal plugin-like object for the catalogue preferences tests."""

    def __init__(self, name: str) -> None:
        self.name = name
