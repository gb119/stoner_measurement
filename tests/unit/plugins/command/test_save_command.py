"""Tests for SaveCommand."""

from __future__ import annotations

import pytest

from stoner_measurement.plugins.command import SaveCommand

# ---------------------------------------------------------------------------
# SaveCommand
# ---------------------------------------------------------------------------


class TestSaveCommand:
    def test_name(self, qapp):
        assert SaveCommand().name == "Save"

    def test_plugin_type(self, qapp):
        assert SaveCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert SaveCommand().has_lifecycle is False

    def test_default_path_expr(self, qapp):
        assert SaveCommand().path_expr == "'data/output.txt'"

    def test_to_json_includes_path_expr(self, qapp):
        cmd = SaveCommand()
        cmd.path_expr = "'my/path.txt'"
        d = cmd.to_json()
        assert d["path_expr"] == "'my/path.txt'"

    def test_restore_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = SaveCommand()
        cmd.path_expr = "'run/output.txt'"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, SaveCommand)
        assert restored.path_expr == "'run/output.txt'"

    def test_config_widget_returns_widget(self, qapp):
        from qtpy.QtWidgets import QWidget

        assert isinstance(SaveCommand().config_widget(), QWidget)

    def test_config_widget_updates_path_expr(self, qapp):
        from qtpy.QtWidgets import QLineEdit

        cmd = SaveCommand()
        widget = cmd.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        assert line_edits, "Config widget should have a QLineEdit"
        line_edits[0].setText("'new/path.txt'")
        line_edits[0].editingFinished.emit()
        assert cmd.path_expr == "'new/path.txt'"

    def test_execute_writes_tdi_file(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()
        assert out_file.exists()
        first_line = out_file.read_text().splitlines()[0]
        assert first_line.startswith("TDI Format 2.0")

    def test_execute_tdi_tab_delimited(self, qapp, engine, tmp_path):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        lines = out_file.read_text().splitlines()
        # All rows must be tab-separated with the same number of columns.
        assert all("\t" in line for line in lines if line)

    def test_execute_tdi_column_headers(self, qapp, engine, tmp_path):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        header = out_file.read_text().splitlines()[0].split("\t")
        # First cell is "TDI Format 2.0"; remaining cells are channel headers.
        assert header[0] == "TDI Format 2.0"
        # Headers use "{channel_name}:{axis_label} ({units})" format.
        # The instance_name prefix ("dummy:") is dropped; "Dummy" is the channel name.
        assert any("Dummy:" in h for h in header[1:])

    def test_execute_tdi_metadata_in_column_zero(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        lines = out_file.read_text().splitlines()
        # Rows after the header must have metadata entries in column 0.
        meta_cells = [line.split("\t")[0] for line in lines[1:] if line]
        assert any("{" in cell and "}" in cell and "=" in cell for cell in meta_cells)

    def test_execute_tdi_plugin_state_flattened(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        text = out_file.read_text()
        # The save plugin's instance_name should appear in flattened metadata.
        assert "save.instance_name{str}='save'" in text

    def test_execute_tdi_step_plugin_state_flattened(self, qapp, engine, tmp_path):
        """Only step plugins that are part of the sequence appear in metadata."""
        from stoner_measurement.plugins.trace import DummyPlugin

        in_sequence = DummyPlugin()
        in_sequence.instance_name = "step_in_seq"
        not_in_sequence = DummyPlugin()
        not_in_sequence.instance_name = "step_not_in_seq"
        engine.update_step_plugin_catalog([in_sequence, not_in_sequence])
        # Build a sequence that includes only in_sequence
        engine.generate_sequence_code([in_sequence], {"step_in_seq": in_sequence})
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        text = out_file.read_text()
        # Only the plugin that was part of the sequence should appear in metadata.
        assert "step_in_seq.instance_name" in text
        assert "step_not_in_seq.instance_name" not in text

    def test_execute_tdi_values_in_metadata(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        # Set a fake scalar value *after* add_plugin so _rebuild_data_catalogs
        # does not overwrite it.
        engine._namespace["_values"] = {"test:reading": "42.0"}  # noqa: SLF001
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        text = out_file.read_text()
        assert "test:reading" in text

    def test_execute_tdi_numerical_data_rows(self, qapp, engine, tmp_path):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        result = plugin.measure({})
        n_points = len(result["Dummy"].x)

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        lines = out_file.read_text().splitlines()
        data_rows = lines[1:]  # skip header
        # There must be at least as many rows as data points.
        assert len(data_rows) >= n_points

    def test_execute_creates_parent_dirs(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "subdir" / "nested" / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()
        assert out_file.exists()

    def test_execute_raises_when_detached(self, qapp):
        cmd = SaveCommand()
        with pytest.raises(RuntimeError):
            cmd.execute()

    def test_execute_raises_for_non_string_path(self, qapp, engine):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.path_expr = "42"  # evaluates to int, not str
        with pytest.raises(TypeError):
            cmd.execute()

    def test_generate_action_code(self, qapp):
        cmd = SaveCommand()
        lines = cmd.generate_action_code(1, [], lambda s, i: [])
        assert lines[0] == "    save()"

    # ------------------------------------------------------------------
    # New attributes and serialisation
    # ------------------------------------------------------------------

    def test_default_save_mode(self, qapp):
        assert SaveCommand().save_mode == "traces"

    def test_default_trace_selection_empty(self, qapp):
        assert SaveCommand().trace_selection == {}

    def test_default_data_source_empty(self, qapp):
        assert SaveCommand().data_source == ""

    def test_default_no_overwrite_true(self, qapp):
        assert SaveCommand().no_overwrite is True

    def test_default_incremental_save_false(self, qapp):
        assert SaveCommand().incremental_save is False

    def test_to_json_includes_new_fields(self, qapp):
        cmd = SaveCommand()
        cmd.save_mode = "data"
        cmd.data_source = "my_state"
        cmd.no_overwrite = False
        cmd.incremental_save = True
        d = cmd.to_json()
        assert d["save_mode"] == "data"
        assert d["data_source"] == "my_state"
        assert d["no_overwrite"] is False
        assert d["incremental_save"] is True
        assert "trace_selection" in d

    def test_restore_from_json_new_fields(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = SaveCommand()
        cmd.save_mode = "data"
        cmd.data_source = "ctrl"
        cmd.no_overwrite = False
        cmd.incremental_save = True
        cmd.trace_selection = {"dummy:Dummy": False}
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, SaveCommand)
        assert restored.save_mode == "data"
        assert restored.data_source == "ctrl"
        assert restored.no_overwrite is False
        assert restored.incremental_save is True
        assert restored.trace_selection == {"dummy:Dummy": False}

    # ------------------------------------------------------------------
    # No-overwrite behaviour
    # ------------------------------------------------------------------

    def test_no_overwrite_increments_filename(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.no_overwrite = True

        # First write: file created at original path.
        cmd.execute()
        assert out_file.exists()

        # Second write: should create out_001.txt instead of overwriting.
        cmd.execute()
        versioned = tmp_path / "out_001.txt"
        assert versioned.exists()

    def test_no_overwrite_false_overwrites(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.no_overwrite = False

        # Write an initial sentinel string to the file.
        out_file.write_text("sentinel content\n", encoding="utf-8")

        # Execute should overwrite with TDI content.
        cmd.execute()
        text = out_file.read_text(encoding="utf-8")
        assert "TDI Format 2.0" in text
        assert "sentinel" not in text

    # ------------------------------------------------------------------
    # Trace selection
    # ------------------------------------------------------------------

    def test_trace_selection_excludes_disabled_trace(self, qapp, engine, tmp_path):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        # Disable the 'dummy:Dummy' trace.
        cmd.trace_selection = {"dummy:Dummy": False}
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        header = out_file.read_text().splitlines()[0].split("\t")
        # No trace columns should be present.
        assert header == ["TDI Format 2.0"]

    def test_trace_selection_all_enabled_by_default(self, qapp, engine, tmp_path):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        cmd.trace_selection = {}  # empty dict → all enabled
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        header = out_file.read_text().splitlines()[0].split("\t")
        assert any("Dummy:" in h for h in header[1:])

    # ------------------------------------------------------------------
    # Trace column header format
    # ------------------------------------------------------------------

    def test_trace_column_header_uses_channel_name_not_instance_name(self, qapp, engine, tmp_path):
        """Column headers must use channel name only, not instance_name:channel_name."""
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        header = out_file.read_text().splitlines()[0].split("\t")
        # Headers must NOT start with the instance name "dummy:".
        assert not any(h.startswith("dummy:") for h in header[1:])
        # Headers must start with the channel name "Dummy:".
        assert any(h.startswith("Dummy:") for h in header[1:])

    # ------------------------------------------------------------------
    # Data mode
    # ------------------------------------------------------------------

    def test_execute_data_mode_saves_dataframe(self, qapp, engine, tmp_path):
        import pandas as pd

        from stoner_measurement.plugins.state_control import CounterPlugin

        counter = CounterPlugin()
        engine.add_plugin("counter", counter)
        # Inject some data directly.
        counter._data = pd.DataFrame(  # noqa: SLF001
            [{"value": 1.0, "x": 10.0}, {"value": 2.0, "x": 20.0}]
        )

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.save_mode = "data"
        cmd.data_source = "counter"
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        assert out_file.exists()
        lines = out_file.read_text().splitlines()
        header = lines[0].split("\t")
        assert header[0] == "TDI Format 2.0"
        # Column 0 is the TDI marker; column 1 is the first numerical data column.
        assert header[1] == "index"
        # DataFrame column names should be in the headers.
        assert any("value" in h for h in header[1:])
        assert any("x" in h for h in header[1:])
        assert lines[1].split("\t")[1] == "0.0"
        assert lines[2].split("\t")[1] == "1.0"

    def test_execute_data_mode_uses_named_index_header(self, qapp, engine, tmp_path):
        import pandas as pd

        from stoner_measurement.plugins.state_control import CounterPlugin

        counter = CounterPlugin()
        engine.add_plugin("counter", counter)
        counter._data = pd.DataFrame(  # noqa: SLF001
            [{"value": 1.0}, {"value": 2.0}],
            index=pd.Index([10, 20], name="step"),
        )

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.save_mode = "data"
        cmd.data_source = "counter"
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()

        lines = out_file.read_text().splitlines()
        header = lines[0].split("\t")
        assert header[1] == "step"
        assert lines[1].split("\t")[1] == "10.0"
        assert lines[2].split("\t")[1] == "20.0"

    def test_execute_data_mode_no_source_logs_warning(self, qapp, engine, tmp_path, caplog):
        import logging

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.save_mode = "data"
        cmd.data_source = ""
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))

        with caplog.at_level(logging.WARNING):
            cmd.execute()

        assert not out_file.exists()
        assert any("no data_source" in r.message for r in caplog.records)

    def test_execute_data_mode_missing_source_logs_warning(self, qapp, engine, tmp_path, caplog):
        import logging

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.save_mode = "data"
        cmd.data_source = "nonexistent_plugin"
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))

        with caplog.at_level(logging.WARNING):
            cmd.execute()

        assert not out_file.exists()
        assert any("not found" in r.message for r in caplog.records)

    def test_incremental_data_mode_appends_only_new_rows(self, qapp, engine, tmp_path):
        import pandas as pd

        from stoner_measurement.plugins.state_control import CounterPlugin

        counter = CounterPlugin()
        engine.add_plugin("counter", counter)
        counter._data = pd.DataFrame(  # noqa: SLF001
            [{"value": float(i)} for i in range(40)]
        )

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.save_mode = "data"
        cmd.data_source = "counter"
        cmd.incremental_save = True
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))

        cmd.execute()
        first_lines = out_file.read_text(encoding="utf-8").splitlines()

        counter._data = pd.DataFrame(  # noqa: SLF001
            [{"value": float(i)} for i in range(43)]
        )
        cmd.execute()

        second_lines = out_file.read_text(encoding="utf-8").splitlines()
        assert second_lines[: len(first_lines)] == first_lines
        assert len(second_lines) == len(first_lines) + 3
        assert [line.split("\t", maxsplit=1)[0] for line in second_lines[-3:]] == ["", "", ""]
        assert [line.split("\t")[1] for line in second_lines[-3:]] == ["40.0", "41.0", "42.0"]

    def test_incremental_data_mode_reuses_no_overwrite_filename(self, qapp, engine, tmp_path):
        import pandas as pd

        from stoner_measurement.plugins.state_control import CounterPlugin

        counter = CounterPlugin()
        engine.add_plugin("counter", counter)
        counter._data = pd.DataFrame(  # noqa: SLF001
            [{"value": float(i)} for i in range(40)]
        )

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.save_mode = "data"
        cmd.data_source = "counter"
        cmd.incremental_save = True
        cmd.no_overwrite = True
        out_file = tmp_path / "out.txt"
        out_file.write_text("sentinel\n", encoding="utf-8")
        cmd.path_expr = repr(str(out_file))

        cmd.execute()
        counter._data = pd.DataFrame(  # noqa: SLF001
            [{"value": float(i)} for i in range(41)]
        )
        cmd.execute()

        versioned = tmp_path / "out_001.txt"
        assert out_file.read_text(encoding="utf-8") == "sentinel\n"
        assert versioned.exists()
        assert not (tmp_path / "out_002.txt").exists()
        assert versioned.read_text(encoding="utf-8").splitlines()[-1].split("\t")[1] == "40.0"

    # ------------------------------------------------------------------
    # Config widget — new controls
    # ------------------------------------------------------------------

    def test_config_widget_has_no_overwrite_checkbox(self, qapp):
        from qtpy.QtWidgets import QCheckBox

        cmd = SaveCommand()
        widget = cmd.config_widget()
        checkboxes = widget.findChildren(QCheckBox)
        assert len(checkboxes) >= 1

    def test_config_widget_has_mode_combobox(self, qapp):
        from qtpy.QtWidgets import QComboBox

        cmd = SaveCommand()
        widget = cmd.config_widget()
        combos = widget.findChildren(QComboBox)
        # At least one combobox for mode selection.
        assert len(combos) >= 1

    def test_config_widget_has_browse_button(self, qapp):
        from qtpy.QtWidgets import QPushButton

        cmd = SaveCommand()
        widget = cmd.config_widget()
        buttons = widget.findChildren(QPushButton)
        assert any("Browse" in btn.text() for btn in buttons)

    def test_apply_path_wraps_unquoted_string(self, qapp):
        """Typing a plain path without quotes should auto-add single quotes."""
        from qtpy.QtWidgets import QLineEdit

        cmd = SaveCommand()
        widget = cmd.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        assert line_edits, "Config widget should have a QLineEdit"
        line_edits[0].setText("data/plain_path.txt")
        line_edits[0].editingFinished.emit()
        assert cmd.path_expr == repr("data/plain_path.txt")

    def test_apply_path_leaves_quoted_string_unchanged(self, qapp):
        """Text already starting with a quote should not be double-quoted."""
        from qtpy.QtWidgets import QLineEdit

        cmd = SaveCommand()
        widget = cmd.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        line_edits[0].setText("'data/output.txt'")
        line_edits[0].editingFinished.emit()
        assert cmd.path_expr == "'data/output.txt'"

    def test_apply_path_leaves_fstring_unchanged(self, qapp):
        """An f-string expression should not be modified."""
        from qtpy.QtWidgets import QLineEdit

        cmd = SaveCommand()
        widget = cmd.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        line_edits[0].setText("f'data/run_{index}.txt'")
        line_edits[0].editingFinished.emit()
        assert cmd.path_expr == "f'data/run_{index}.txt'"

    # ------------------------------------------------------------------
    # execute — default data directory resolution
    # ------------------------------------------------------------------

    def test_execute_resolves_relative_path_against_data_directory(
        self, qapp, engine, tmp_path
    ):
        """Relative path_expr should be resolved against KEY_DEFAULT_DATA_DIR."""
        from unittest.mock import patch

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.path_expr = "'subdir/out.txt'"

        data_dir = str(tmp_path)

        class _MockSettings:
            def value(self, key, default="", **_kwargs):
                return data_dir

        with patch(
            "stoner_measurement.ui.settings_dialog.make_app_settings",
            return_value=_MockSettings(),
        ):
            cmd.execute()

        expected = tmp_path / "subdir" / "out.txt"
        assert expected.exists()

    def test_execute_absolute_path_ignores_data_directory(self, qapp, engine, tmp_path):
        """An absolute path_expr must not be prefixed with the data directory."""
        from unittest.mock import patch

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "absolute_out.txt"
        cmd.path_expr = repr(str(out_file))

        # Even if data_dir is set, the absolute path should be used as-is.
        class _MockSettings:
            def value(self, key, default="", **_kwargs):
                return "/some/other/dir"

        with patch(
            "stoner_measurement.ui.settings_dialog.make_app_settings",
            return_value=_MockSettings(),
        ):
            cmd.execute()

        assert out_file.exists()

    # ------------------------------------------------------------------
    # execute / __call__ keyword parameter overrides
    # ------------------------------------------------------------------

    def test_execute_trace_kwarg_filters_to_single_trace(self, qapp, engine, tmp_path):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))

        # Pass the trace key explicitly; trace_selection is irrelevant.
        cmd.execute(trace="dummy:Dummy")
        header = out_file.read_text().splitlines()[0].split("\t")
        assert any("Dummy:" in h for h in header[1:])

    def test_execute_trace_kwarg_as_list(self, qapp, engine, tmp_path):
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))

        # List with a single valid trace key.
        cmd.execute(trace=["dummy:Dummy"])
        header = out_file.read_text().splitlines()[0].split("\t")
        assert any("Dummy:" in h for h in header[1:])

    def test_execute_trace_kwarg_excludes_unspecified_traces(self, qapp, engine, tmp_path):
        """When trace kwarg is given, only the listed traces should appear."""
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))

        # Pass an empty list — no traces should be saved.
        cmd.execute(trace=[])
        header = out_file.read_text().splitlines()[0].split("\t")
        assert header == ["TDI Format 2.0"]

    def test_execute_trace_kwarg_overrides_trace_selection(self, qapp, engine, tmp_path):
        """trace kwarg should override trace_selection config."""
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        # Config says: save NO traces.
        cmd.trace_selection = {"dummy:Dummy": False}
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))

        # But kwarg overrides the config and explicitly asks for dummy:Dummy.
        cmd.execute(trace="dummy:Dummy")
        header = out_file.read_text().splitlines()[0].split("\t")
        assert any("Dummy:" in h for h in header[1:])

    def test_execute_data_kwarg_overrides_data_source(self, qapp, engine, tmp_path):
        import pandas as pd

        from stoner_measurement.plugins.state_control import CounterPlugin

        counter = CounterPlugin()
        engine.add_plugin("counter", counter)
        counter._data = pd.DataFrame(  # noqa: SLF001
            [{"value": 1.0, "x": 10.0}, {"value": 2.0, "x": 20.0}]
        )

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        # Configured for trace mode with no data source.
        cmd.save_mode = "traces"
        cmd.data_source = ""
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))

        # kwarg should switch to data mode and use 'counter'.
        cmd.execute(data="counter")
        lines = out_file.read_text().splitlines()
        header = lines[0].split("\t")
        assert any("value" in h for h in header[1:])

    def test_execute_no_overwrite_kwarg_overrides_config(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        # Configured to overwrite.
        cmd.no_overwrite = False
        cmd.path_expr = repr(str(out_file))

        # Write sentinel content, then call with no_overwrite=True.
        out_file.write_text("sentinel\n", encoding="utf-8")
        cmd.execute(no_overwrite=True)

        # Original file should be intact; a versioned file should exist.
        assert out_file.read_text(encoding="utf-8") == "sentinel\n"
        versioned = tmp_path / "out_001.txt"
        assert versioned.exists()

    def test_execute_no_overwrite_false_kwarg_overrides_config(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.txt"
        # Configured to never overwrite.
        cmd.no_overwrite = True
        cmd.path_expr = repr(str(out_file))

        # Write sentinel, then call with no_overwrite=False → should overwrite.
        out_file.write_text("sentinel\n", encoding="utf-8")
        cmd.execute(no_overwrite=False)
        text = out_file.read_text(encoding="utf-8")
        assert "TDI Format 2.0" in text

    def test_execute_trace_and_data_kwarg_raises(self, qapp, engine):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        with pytest.raises(ValueError, match="mutually exclusive"):
            cmd.execute(trace="dummy:Dummy", data="counter")

    def test_call_trace_kwarg_forwarded(self, qapp, engine, tmp_path):
        """__call__ should forward kwargs to execute."""
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))

        cmd(trace="dummy:Dummy")
        header = out_file.read_text().splitlines()[0].split("\t")
        assert any("Dummy:" in h for h in header[1:])

    def test_call_no_args_uses_config(self, qapp, engine, tmp_path):
        """__call__() with no args should behave identically to execute()."""
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))
        cmd()
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8").startswith("TDI Format 2.0")

    def test_execute_trace_kwarg_does_not_mutate_trace_selection(self, qapp, engine, tmp_path):
        """Passing the trace kwarg must not modify self.trace_selection."""
        from stoner_measurement.plugins.trace import DummyPlugin
        from stoner_measurement.scan import SteppedScanGenerator

        plugin = DummyPlugin()
        plugin.scan_generator = SteppedScanGenerator(
            start=0.0, stages=[(0.4, 0.1, True)], parent=plugin
        )
        engine.add_plugin("dummy", plugin)
        engine.update_step_plugin_catalog([plugin])
        plugin.measure({})

        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        cmd.no_overwrite = False
        original_selection = {}
        cmd.trace_selection = original_selection
        out_file = tmp_path / "out.txt"
        cmd.path_expr = repr(str(out_file))

        cmd.execute(trace="dummy:Dummy")
        assert cmd.trace_selection is original_selection
        assert cmd.trace_selection == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))

