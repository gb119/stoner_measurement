"""Tests for DetailsCommand."""

from __future__ import annotations

import pytest
from qtpy.QtWidgets import (
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command.details import DetailsCommand
from stoner_measurement.ui.theme import colour


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
        assert command.metadata_expressions == []

    def test_dynamic_date_and_time_formats(self, qapp):
        command = DetailsCommand()
        assert len(command.date) == 8 and command.date.isdigit()
        assert len(command.time) == 6 and command.time.isdigit()

    def test_rig_reads_local_application_setting(self, qapp, monkeypatch):
        monkeypatch.setattr("stoner_measurement.app_config.rig_setting", lambda: "Rig-A")
        assert DetailsCommand().rig == "Rig-A"

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

    def test_generate_action_code_includes_runtime_metadata_expressions(self, qapp):
        command = DetailsCommand()
        command.metadata_expressions = [
            {"name": "run_label", "expression": "f'{details.date}-{index}'"}
        ]
        lines = command.generate_action_code(0, [], lambda source, indent: [])
        assignment = 'details.run_label = details.eval_metadata("f\'{details.date}-{index}\'")'
        assert assignment in lines
        assert lines.index(assignment) < lines.index("details.configure()")

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("2 + 3", 5),
            ("Run {index:03d}", "Run 007"),
            ("'Sample {sample}'", "Sample A"),
            ("unquoted_label", "unquoted_label"),
        ],
    )
    def test_metadata_values_follow_shared_runtime_evaluation(
        self, qapp, qtbot, engine, expression, expected
    ):
        command = DetailsCommand()
        command.user = "Alice"
        command.sample = "S1"
        command.project = "P1"
        engine.add_plugin("details", command)
        engine._namespace.update(index=7, sample="A")

        assert command.eval_metadata(expression) == expected

        command.metadata_expressions = [{"name": "result", "expression": expression}]
        lines = command.generate_action_code(0, [], lambda source, indent: [])
        assert f"details.result = details.eval_metadata({expression!r})" in lines

        errors: list[str] = []
        engine.error_output.connect(errors.append)
        with qtbot.waitSignal(engine.script_finished, timeout=5000):
            engine.run_script("\n".join(lines), customised=False)

        assert errors == []
        assert getattr(command, "result") == expected

    def test_metadata_unknown_identifier_warns_before_literal_fallback(
        self, qapp, engine, caplog
    ):
        command = DetailsCommand()
        engine.add_plugin("details", command)

        with caplog.at_level("WARNING"):
            result = command.eval_metadata("missing_runtime_name")

        assert result == "missing_runtime_name"
        assert "unknown identifier" in caplog.text
        assert "treating it as literal text" in caplog.text

    def test_metadata_does_not_hide_non_name_runtime_errors(self, qapp, engine):
        command = DetailsCommand()
        engine.add_plugin("details", command)

        with pytest.raises(ZeroDivisionError):
            command.eval_metadata("1 / 0")

    def test_generate_action_code_rejects_invalid_metadata_name(self, qapp):
        command = DetailsCommand()
        command.metadata_expressions = [{"name": "date", "expression": "123"}]
        with pytest.raises(ValueError, match="clashes"):
            command.generate_action_code(0, [], lambda source, indent: [])

    def test_to_json_fields(self, qapp):
        command = DetailsCommand()
        command.user = "Alice"
        command.sample = "S1"
        command.project = "P1"
        command.notes = "notes"
        command.metadata_expressions = [{"name": "field", "expression": "magnet.field"}]
        data = command.to_json()
        assert data["type"] == "command"
        assert data["user"] == "Alice"
        assert data["sample"] == "S1"
        assert data["project"] == "P1"
        assert data["notes"] == "notes"
        assert data["metadata_expressions"] == [
            {"name": "field", "expression": "magnet.field"}
        ]

    def test_restore_from_json(self, qapp):
        command = DetailsCommand()
        command.user = "Alice"
        command.sample = "S1"
        command.project = "P1"
        command.notes = "notes text"
        command.metadata_expressions = [{"name": "temperature", "expression": "4.2"}]
        restored = BasePlugin.from_json(command.to_json())
        assert isinstance(restored, DetailsCommand)
        assert restored.user == "Alice"
        assert restored.sample == "S1"
        assert restored.project == "P1"
        assert restored.notes == "notes text"
        assert restored.metadata_expressions == [
            {"name": "temperature", "expression": "4.2"}
        ]

    def test_config_tabs_have_general_metadata_and_standard_about_tabs(
        self, qapp, managed_qt_widget
    ):
        command = DetailsCommand()
        tabs = command.config_tabs()
        for _title, widget in tabs:
            managed_qt_widget(widget)
        assert [title for title, _widget in tabs] == [
            "General",
            "Metadata",
            "About",
        ]
        assert tabs[1][1].findChild(QTableWidget, "detailsMetadataTable") is not None

    def test_general_tab_combines_identity_and_fixed_details_at_top(
        self, qapp, managed_qt_widget
    ):
        command = DetailsCommand()
        general = managed_qt_widget(command.config_tabs()[0][1])

        assert general.findChild(QLineEdit, "detailsUserEdit") is not None
        assert general.findChild(QLineEdit, "detailsSampleEdit") is not None
        assert general.findChild(QComboBox, "detailsProjectCombo") is not None
        notes = general.findChild(QPlainTextEdit, "detailsNotesEdit")
        assert notes is not None
        assert notes.minimumHeight() == notes.maximumHeight()
        assert notes.height() >= notes.fontMetrics().lineSpacing() * 8

        layout = general.layout()
        assert isinstance(layout, QVBoxLayout)
        assert layout.itemAt(layout.count() - 1).spacerItem() is not None

    def test_metadata_tab_has_fixed_six_row_table_buttons_and_top_packing(
        self, qapp, managed_qt_widget
    ):
        command = DetailsCommand()
        metadata = managed_qt_widget(command.config_tabs()[1][1])
        table = metadata.findChild(QTableWidget, "detailsMetadataTable")
        assert table is not None
        assert table.verticalHeader().isHidden() is False
        assert table.minimumHeight() == table.maximumHeight()
        expected_height = (
            table.horizontalHeader().sizeHint().height()
            + table.verticalHeader().defaultSectionSize() * 6
            + 2 * table.frameWidth()
        )
        assert table.height() == expected_height
        assert metadata.findChild(QPushButton, "detailsMetadataAddButton") is not None
        assert metadata.findChild(QPushButton, "detailsMetadataRemoveButton") is not None

        layout = metadata.layout()
        assert isinstance(layout, QVBoxLayout)
        assert layout.itemAt(layout.count() - 1).spacerItem() is not None

    def test_metadata_table_uses_subtle_row_selection_during_editing(
        self, qapp, managed_qt_widget
    ):
        command = DetailsCommand()
        metadata = managed_qt_widget(command.config_tabs()[1][1])
        table = metadata.findChild(QTableWidget, "detailsMetadataTable")
        add_button = metadata.findChild(QPushButton, "detailsMetadataAddButton")
        assert table is not None
        assert add_button is not None

        add_button.click()
        qapp.processEvents()

        assert table.rowCount() == 1
        assert table.currentRow() == 0
        assert {index.row() for index in table.selectedIndexes()} == {0}
        assert table.findChild(QLineEdit) is not None
        assert colour("tab_selected_background") in table.styleSheet()
        assert colour("text") in table.styleSheet()

    def test_metadata_table_restores_all_configured_rows(self, qapp):
        command = DetailsCommand()
        command.metadata_expressions = [
            {"name": "wafer", "expression": "'A1'"},
            {"name": "run_number", "expression": "index"},
        ]
        table = command.config_tabs()[1][1].findChild(QTableWidget, "detailsMetadataTable")
        assert table is not None
        assert table.rowCount() == 2

    @pytest.mark.parametrize("name", ["not valid", "_private", "date", "time", "rig", "user"])
    def test_metadata_rejects_invalid_or_reserved_names(self, qapp, name):
        command = DetailsCommand()
        assert command._metadata_name_error(name) is not None

    def test_metadata_accepts_new_python_attribute_name(self, qapp):
        assert DetailsCommand()._metadata_name_error("wafer_number") is None

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
        from unittest.mock import patch

        with patch("stoner_measurement.app_config.default_data_directory", return_value=str(tmp_path)):
            widget = DetailsCommand().config_widget()
            combo = widget.findChildren(QComboBox)[0]
            items = [combo.itemText(index) for index in range(combo.count())]
            assert items == sorted(["ProjectAlpha", "ProjectBeta", "ProjectGamma"])

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
