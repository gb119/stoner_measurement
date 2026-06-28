"""Tests for DetailsCommand."""

from __future__ import annotations

import pytest
from qtpy.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit, QWidget

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command.details import DetailsCommand
from stoner_measurement.ui.settings_dialog import KEY_DEFAULT_DATA_DIR, make_app_settings


class TestDetailsCommand:
    def test_name(self, qapp):
        assert DetailsCommand().name == "Details"

    def test_plugin_type(self, qapp):
        assert DetailsCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert DetailsCommand().has_lifecycle is False

    def test_default_fields_empty(self, qapp):
        command = DetailsCommand()
        assert command.user == ""
        assert command.sample == ""
        assert command.project == ""
        assert command.notes == ""

    def test_generate_action_code_assignments(self, qapp):
        command = DetailsCommand()
        command.user = "Alice"
        command.sample = "Nb_001"
        command.project = "NbSC"
        command.notes = "Cooled overnight"
        lines = command.generate_action_code(0, [], lambda source, indent: [])
        assert lines[0] == 'details.user = "Alice"'
        assert lines[1] == 'details.sample = "Nb_001"'
        assert lines[2] == 'details.project = "NbSC"'
        assert lines[3] == 'details.notes = "Cooled overnight"'
        assert lines[4] == "details.configure()"
        assert lines[5] == ""

    def test_generate_action_code_indentation(self, qapp):
        command = DetailsCommand()
        lines = command.generate_action_code(2, [], lambda source, indent: [])
        for line in lines[:-1]:
            assert line.startswith("        ")

    def test_generate_action_code_no_execute_call(self, qapp):
        command = DetailsCommand()
        lines = command.generate_action_code(0, [], lambda source, indent: [])
        assert "details.configure()" in lines
        assert not any(line.strip() == "details()" for line in lines)

    def test_generate_action_code_escapes_special_chars(self, qapp):
        command = DetailsCommand()
        command.user = 'Bob "The Builder"'
        lines = command.generate_action_code(0, [], lambda source, indent: [])
        assert '\\"' in lines[0]

    def test_to_json_fields(self, qapp):
        command = DetailsCommand()
        command.user = "Alice"
        command.sample = "S1"
        command.project = "P1"
        command.notes = "notes"
        data = command.to_json()
        assert data["type"] == "command"
        assert data["user"] == "Alice"
        assert data["sample"] == "S1"
        assert data["project"] == "P1"
        assert data["notes"] == "notes"

    def test_restore_from_json(self, qapp):
        command = DetailsCommand()
        command.user = "Alice"
        command.sample = "S1"
        command.project = "P1"
        command.notes = "notes text"
        restored = BasePlugin.from_json(command.to_json())
        assert isinstance(restored, DetailsCommand)
        assert restored.user == "Alice"
        assert restored.sample == "S1"
        assert restored.project == "P1"
        assert restored.notes == "notes text"

    def test_config_widget_returns_widget(self, qapp):
        assert isinstance(DetailsCommand().config_widget(), QWidget)

    def test_execute_raises_and_shows_warning_for_missing_required_fields(self, qapp, monkeypatch):
        command = DetailsCommand()
        warnings: list[str] = []

        monkeypatch.setattr(
            "stoner_measurement.plugins.command.details.QMessageBox.warning",
            lambda *args, **kwargs: None,
        )
        command.show_validation_error.disconnect(command._display_validation_error)
        command.show_validation_error.connect(warnings.append)

        with pytest.raises(ValueError, match="User.*Sample.*Project"):
            command.execute()

        assert warnings
        assert "User" in warnings[0]
        assert "Sample" in warnings[0]
        assert "Project" in warnings[0]

    def test_execute_allows_blank_notes(self, qapp):
        command = DetailsCommand()
        command.user = "Alice"
        command.sample = "S1"
        command.project = "P1"
        command.execute()

    def test_configure_raises_and_shows_warning_for_missing_required_fields(self, qapp, monkeypatch):
        command = DetailsCommand()
        warnings: list[str] = []

        monkeypatch.setattr(
            "stoner_measurement.plugins.command.details.QMessageBox.warning",
            lambda *args, **kwargs: None,
        )
        command.show_validation_error.disconnect(command._display_validation_error)
        command.show_validation_error.connect(warnings.append)

        with pytest.raises(ValueError, match="User.*Sample.*Project"):
            command.configure()

        assert warnings

    def test_configure_strips_required_fields(self, qapp):
        command = DetailsCommand()
        command.user = " Alice "
        command.sample = " S1 "
        command.project = " P1 "

        command.configure()

        assert command.user == "Alice"
        assert command.sample == "S1"
        assert command.project == "P1"

    def test_config_widget_user_field(self, qapp):
        command = DetailsCommand()
        command.user = "Alice"
        widget = command.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        assert any(line_edit.text() == "Alice" for line_edit in line_edits)

    def test_config_widget_updates_user(self, qapp):
        command = DetailsCommand()
        widget = command.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        user_edit = line_edits[0]
        user_edit.setText("Bob")
        user_edit.editingFinished.emit()
        assert command.user == "Bob"

    def test_config_widget_project_combobox(self, qapp):
        widget = DetailsCommand().config_widget()
        combos = widget.findChildren(QComboBox)
        assert len(combos) == 1

    def test_config_widget_project_populated_from_settings(self, qapp, tmp_path):
        """Project combo box should list top-level subdirs of the settings data directory."""
        (tmp_path / "ProjectAlpha").mkdir()
        (tmp_path / "ProjectBeta").mkdir()
        (tmp_path / "ProjectGamma").mkdir()
        (tmp_path / "not_a_dir.txt").write_text("ignored")

        settings = make_app_settings()
        original = settings.value(KEY_DEFAULT_DATA_DIR, "", type=str)
        settings.setValue(KEY_DEFAULT_DATA_DIR, str(tmp_path))
        settings.sync()

        try:
            widget = DetailsCommand().config_widget()
            combo = widget.findChildren(QComboBox)[0]
            items = [combo.itemText(index) for index in range(combo.count())]
            assert items == sorted(["ProjectAlpha", "ProjectBeta", "ProjectGamma"])
        finally:
            settings.setValue(KEY_DEFAULT_DATA_DIR, original)
            settings.sync()

    def test_config_widget_notes_updates(self, qapp):
        command = DetailsCommand()
        widget = command.config_widget()
        notes_edit = widget.findChildren(QPlainTextEdit)[0]
        notes_edit.setPlainText("new notes")
        assert command.notes == "new notes"

    def test_execute_passes_when_required_fields_are_present(self, qapp):
        command = DetailsCommand()
        command.user = "Alice"
        command.sample = "S1"
        command.project = "P1"
        command.execute()
        assert command.user == "Alice"
        assert command.sample == "S1"

    def test_reported_traces_empty(self, qapp):
        assert DetailsCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert DetailsCommand().reported_values() == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
