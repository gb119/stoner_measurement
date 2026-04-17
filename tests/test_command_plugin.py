"""Tests for CommandPlugin, SaveCommand, PlotTraceCommand, WaitCommand,
StatusCommand, AlertCommand, PlotPointsCommand, and PlotClearCommand."""

from __future__ import annotations

import numpy as np
import pytest

from stoner_measurement.plugins.command import (
    AlertCommand,
    CommandPlugin,
    PlotClearCommand,
    PlotPointsCommand,
    PlotTraceCommand,
    SaveCommand,
    StatusCommand,
    WaitCommand,
)

# ---------------------------------------------------------------------------
# Minimal concrete implementation used across tests
# ---------------------------------------------------------------------------


class _Noop(CommandPlugin):
    # No docstring — test helper only.

    executed: list[int]

    @property
    def name(self) -> str:
        return "Noop"

    def execute(self) -> None:
        try:
            self.executed.append(1)
        except AttributeError:
            self.executed = [1]


# ---------------------------------------------------------------------------
# CommandPlugin abstract contract
# ---------------------------------------------------------------------------


class TestCommandPlugin:
    def test_plugin_type(self, qapp):
        assert _Noop().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert _Noop().has_lifecycle is False

    def test_instance_name_defaults_to_name(self, qapp):
        assert _Noop().instance_name == "noop"

    def test_instance_name_changed_signal(self, qapp):
        p = _Noop()
        received: list[tuple[str, str]] = []
        p.instance_name_changed.connect(lambda o, n: received.append((o, n)))
        p.instance_name = "my_noop"
        assert received == [("noop", "my_noop")]

    def test_reported_traces_empty(self, qapp):
        assert _Noop().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert _Noop().reported_values() == {}

    def test_generate_action_code_execute_call(self, qapp):
        p = _Noop()
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert lines[0] == "    noop()"

    def test_call_delegates_to_execute(self, qapp):
        p = _Noop()
        p.executed = []
        p()
        assert p.executed == [1]

    def test_generate_action_code_blank_separator(self, qapp):
        p = _Noop()
        lines = p.generate_action_code(1, [], lambda s, i: [])
        assert lines[-1] == ""

    def test_generate_action_code_indentation(self, qapp):
        p = _Noop()
        lines = p.generate_action_code(2, [], lambda s, i: [])
        assert lines[0].startswith("        ")

    def test_to_json_type_field(self, qapp):
        d = _Noop().to_json()
        assert d["type"] == "command"

    def test_to_json_class_field(self, qapp):
        d = _Noop().to_json()
        assert "class" in d

    def test_from_json_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        p = _Noop()
        p.instance_name = "my_noop"
        restored = BasePlugin.from_json(p.to_json())
        assert restored.instance_name == "my_noop"
        assert restored.plugin_type == "command"

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        assert isinstance(_Noop().config_widget(), QWidget)

    def test_config_tabs_single_tab(self, qapp):
        tabs = _Noop().config_tabs()
        assert len(tabs) == 1
        assert tabs[0][0] == "Noop"

    def test_execute_called_via_sequence(self, qapp, engine):
        """CommandPlugin.execute() is called when the sequence script runs."""
        p = _Noop()
        p.executed = []
        engine.add_plugin("noop", p)
        code = engine.generate_sequence_code(["noop"], {"noop": p})
        # Should NOT contain connect/configure/disconnect for command plugin
        assert "noop.connect()" not in code
        assert "noop.configure()" not in code
        assert "noop.disconnect()" not in code
        # Should contain a callable invocation
        assert "noop()" in code

    def test_no_lifecycle_in_generated_code(self, qapp, engine):
        p = _Noop()
        engine.add_plugin("noop", p)
        code = engine.generate_sequence_code(["noop"], {"noop": p})
        assert "noop.connect()" not in code
        assert "noop.configure()" not in code
        assert "noop.disconnect()" not in code


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
        from PyQt6.QtWidgets import QWidget

        assert isinstance(SaveCommand().config_widget(), QWidget)

    def test_config_widget_updates_path_expr(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

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

    def test_to_json_includes_new_fields(self, qapp):
        cmd = SaveCommand()
        cmd.save_mode = "data"
        cmd.data_source = "my_state"
        cmd.no_overwrite = False
        d = cmd.to_json()
        assert d["save_mode"] == "data"
        assert d["data_source"] == "my_state"
        assert d["no_overwrite"] is False
        assert "trace_selection" in d

    def test_restore_from_json_new_fields(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = SaveCommand()
        cmd.save_mode = "data"
        cmd.data_source = "ctrl"
        cmd.no_overwrite = False
        cmd.trace_selection = {"dummy:Dummy": False}
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, SaveCommand)
        assert restored.save_mode == "data"
        assert restored.data_source == "ctrl"
        assert restored.no_overwrite is False
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

    # ------------------------------------------------------------------
    # Config widget — new controls
    # ------------------------------------------------------------------

    def test_config_widget_has_no_overwrite_checkbox(self, qapp):
        from PyQt6.QtWidgets import QCheckBox

        cmd = SaveCommand()
        widget = cmd.config_widget()
        checkboxes = widget.findChildren(QCheckBox)
        assert len(checkboxes) >= 1

    def test_config_widget_has_mode_combobox(self, qapp):
        from PyQt6.QtWidgets import QComboBox

        cmd = SaveCommand()
        widget = cmd.config_widget()
        combos = widget.findChildren(QComboBox)
        # At least one combobox for mode selection.
        assert len(combos) >= 1

    def test_config_widget_has_browse_button(self, qapp):
        from PyQt6.QtWidgets import QPushButton

        cmd = SaveCommand()
        widget = cmd.config_widget()
        buttons = widget.findChildren(QPushButton)
        assert any("Browse" in btn.text() for btn in buttons)

    def test_apply_path_wraps_unquoted_string(self, qapp):
        """Typing a plain path without quotes should auto-add single quotes."""
        from PyQt6.QtWidgets import QLineEdit

        cmd = SaveCommand()
        widget = cmd.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        assert line_edits, "Config widget should have a QLineEdit"
        line_edits[0].setText("data/plain_path.txt")
        line_edits[0].editingFinished.emit()
        assert cmd.path_expr == repr("data/plain_path.txt")

    def test_apply_path_leaves_quoted_string_unchanged(self, qapp):
        """Text already starting with a quote should not be double-quoted."""
        from PyQt6.QtWidgets import QLineEdit

        cmd = SaveCommand()
        widget = cmd.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        line_edits[0].setText("'data/output.txt'")
        line_edits[0].editingFinished.emit()
        assert cmd.path_expr == "'data/output.txt'"

    def test_apply_path_leaves_fstring_unchanged(self, qapp):
        """An f-string expression should not be modified."""
        from PyQt6.QtWidgets import QLineEdit

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


# ---------------------------------------------------------------------------
# PlotTraceCommand
# ---------------------------------------------------------------------------


class TestPlotTraceCommand:
    def test_name(self, qapp):
        assert PlotTraceCommand().name == "Plot Trace"

    def test_plugin_type(self, qapp):
        assert PlotTraceCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert PlotTraceCommand().has_lifecycle is False

    def test_default_attributes(self, qapp):
        cmd = PlotTraceCommand()
        assert cmd.trace_key == ""
        assert cmd.advanced_mode is False
        assert cmd.x_expr == ""
        assert cmd.y_expr == ""
        assert cmd.title_expr == "'plot'"
        assert cmd.x_axis_name == "bottom"
        assert cmd.y_axis_name == "left"

    def test_to_json_includes_fields(self, qapp):
        cmd = PlotTraceCommand()
        d = cmd.to_json()
        assert d["type"] == "command"
        assert "trace_key" in d
        assert "advanced_mode" in d
        assert "x_expr" in d
        assert "y_expr" in d
        assert "title_expr" in d
        assert "x_axis_name" in d
        assert "y_axis_name" in d

    def test_restore_from_json_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = PlotTraceCommand()
        cmd.trace_key = "dummy:Dummy"
        cmd.advanced_mode = True
        cmd.x_expr = "dummy.data['Dummy'].x"
        cmd.y_expr = "dummy.data['Dummy'].y"
        cmd.title_expr = "'my plot'"
        cmd.x_axis_name = "freq"
        cmd.y_axis_name = "temp"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, PlotTraceCommand)
        assert restored.trace_key == "dummy:Dummy"
        assert restored.advanced_mode is True
        assert restored.x_expr == "dummy.data['Dummy'].x"
        assert restored.y_expr == "dummy.data['Dummy'].y"
        assert restored.title_expr == "'my plot'"
        assert restored.x_axis_name == "freq"
        assert restored.y_axis_name == "temp"

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        assert isinstance(PlotTraceCommand().config_widget(), QWidget)

    def test_config_widget_has_trace_combo(self, qapp):
        from PyQt6.QtWidgets import QComboBox

        widget = PlotTraceCommand().config_widget()
        combos = widget.findChildren(QComboBox)
        assert len(combos) >= 1

    def test_config_widget_has_advanced_checkbox(self, qapp):
        from PyQt6.QtWidgets import QCheckBox

        widget = PlotTraceCommand().config_widget()
        checkboxes = widget.findChildren(QCheckBox)
        assert len(checkboxes) == 1

    def test_config_widget_has_title_lineedit(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        widget = PlotTraceCommand().config_widget()
        edits = widget.findChildren(QLineEdit)
        assert len(edits) == 1

    def test_config_advanced_checkbox_toggles_advanced_mode(self, qapp):
        from PyQt6.QtWidgets import QCheckBox

        cmd = PlotTraceCommand()
        cmd.advanced_mode = False
        widget = cmd.config_widget()
        checkbox = widget.findChildren(QCheckBox)[0]
        checkbox.setChecked(True)
        assert cmd.advanced_mode is True
        checkbox.setChecked(False)
        assert cmd.advanced_mode is False

    def test_config_title_edit_updates_title_expr(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        cmd = PlotTraceCommand()
        widget = cmd.config_widget()
        edit = widget.findChildren(QLineEdit)[0]
        edit.setText("'new title'")
        edit.editingFinished.emit()
        assert cmd.title_expr == "'new title'"

    def test_execute_advanced_mode_emits_plot_trace(self, qapp, engine):
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["my_x"] = np.array([1.0, 2.0, 3.0])
        engine._namespace["my_y"] = np.array([4.0, 5.0, 6.0])
        cmd.advanced_mode = True
        cmd.x_expr = "my_x"
        cmd.y_expr = "my_y"
        cmd.title_expr = "'test trace'"

        received: list[tuple] = []
        cmd.plot_trace.connect(lambda t, x, y: received.append((t, x, y)))
        cmd.execute()

        assert len(received) == 1
        title, x_data, y_data = received[0]
        assert title == "test trace"
        np.testing.assert_array_equal(x_data, [1.0, 2.0, 3.0])
        np.testing.assert_array_equal(y_data, [4.0, 5.0, 6.0])

    def test_execute_advanced_mode_missing_expr_logs_warning(self, qapp, engine):
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        cmd.advanced_mode = True
        cmd.x_expr = ""  # empty — should warn and not emit
        cmd.y_expr = "some_y"

        received: list = []
        cmd.plot_trace.connect(lambda t, x, y: received.append(1))
        cmd.execute()

        assert received == []

    def test_execute_simple_mode_missing_trace_key_logs_warning(self, qapp, engine):
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        cmd.advanced_mode = False
        cmd.trace_key = "nonexistent:channel"

        received: list = []
        cmd.plot_trace.connect(lambda t, x, y: received.append(1))
        cmd.execute()

        assert received == []

    def test_execute_raises_when_detached(self, qapp):
        cmd = PlotTraceCommand()
        cmd.advanced_mode = True
        cmd.x_expr = "x"
        cmd.y_expr = "y"
        cmd.title_expr = "'t'"
        with pytest.raises(RuntimeError):
            cmd.execute()

    def test_generate_action_code(self, qapp):
        cmd = PlotTraceCommand()
        lines = cmd.generate_action_code(1, [], lambda s, i: [])
        assert lines[0] == "    plot_trace()"

    def test_reported_traces_empty(self, qapp):
        assert PlotTraceCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert PlotTraceCommand().reported_values() == {}

    def test_config_widget_initialises_trace_key_from_first_available_trace(self, qapp, engine):
        """config_widget() must sync trace_key to the combo's default item.

        When trace_key is empty and there is at least one trace in the engine
        catalogue, opening the config widget (without the user touching the
        combo) should update trace_key to the first available trace key so that
        the subsequent code generation is not left with an empty trace_key.
        """
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["_traces"] = {
            "dummy:Dummy": "dummy.data['Dummy']",
        }
        assert cmd.trace_key == ""
        cmd.config_widget()
        assert cmd.trace_key == "dummy:Dummy"

    def test_config_widget_preserves_existing_trace_key(self, qapp, engine):
        """config_widget() must not overwrite a trace_key that is already valid."""
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["_traces"] = {
            "dummy:Dummy": "dummy.data['Dummy']",
            "other:Chan": "other.data['Chan']",
        }
        cmd.trace_key = "other:Chan"
        cmd.config_widget()
        assert cmd.trace_key == "other:Chan"

    def test_config_widget_initialises_x_expr_from_first_available_channel(self, qapp, engine):
        """config_widget() must sync x_expr to the first channel when x_expr is empty."""
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["_traces"] = {
            "dummy:Dummy": "dummy.data['Dummy']",
        }
        assert cmd.x_expr == ""
        cmd.config_widget()
        assert cmd.x_expr in ("dummy.data['Dummy'].x", "dummy.data['Dummy'].y")

    def test_config_widget_initialises_y_expr_from_first_available_channel(self, qapp, engine):
        """config_widget() must sync y_expr to the first channel when y_expr is empty."""
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["_traces"] = {
            "dummy:Dummy": "dummy.data['Dummy']",
        }
        assert cmd.y_expr == ""
        cmd.config_widget()
        assert cmd.y_expr in ("dummy.data['Dummy'].x", "dummy.data['Dummy'].y")

    # ------------------------------------------------------------------
    # sequence_engine property — auto-connection tests
    # ------------------------------------------------------------------

    def test_sequence_engine_property_returns_none_initially(self, qapp):
        """sequence_engine is None before attaching to an engine."""
        cmd = PlotTraceCommand()
        assert cmd.sequence_engine is None

    def test_sequence_engine_property_set_via_add_plugin(self, qapp, engine):
        """add_plugin() must cause sequence_engine to point at the engine."""
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        assert cmd.sequence_engine is engine

    def test_sequence_engine_cleared_via_remove_plugin(self, qapp, engine):
        """remove_plugin() must clear sequence_engine back to None."""
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine.remove_plugin("plot_trace")
        assert cmd.sequence_engine is None

    def test_plot_trace_auto_connects_when_engine_has_plot_widget(self, qapp):
        """plot_trace signal is auto-connected to plot_widget.set_trace when engine is attached."""
        from unittest.mock import MagicMock

        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        try:
            mock_pw = MagicMock()
            mock_pw.set_trace = MagicMock()
            mock_pw.set_default_axis_labels = MagicMock()
            mock_pw.assign_trace_axes = MagicMock()
            engine.plot_widget = mock_pw

            cmd = PlotTraceCommand()
            engine.add_plugin("plot_trace", cmd)

            # plot_trace should now be connected to mock_pw.set_trace
            received: list[tuple] = []
            cmd.plot_trace.connect(lambda t, x, y: received.append((t, x, y)))
            engine._namespace["px"] = np.array([1.0, 2.0])
            engine._namespace["py"] = np.array([3.0, 4.0])
            cmd.advanced_mode = True
            cmd.x_expr = "px"
            cmd.y_expr = "py"
            cmd.title_expr = "'auto'"
            cmd.execute()

            assert len(received) == 1
            assert received[0][0] == "auto"
            # The mock slot is called from the same thread so call_count > 0
            assert mock_pw.set_trace.call_count == 1
            assert mock_pw.assign_trace_axes.call_count == 1
        finally:
            engine.shutdown()

    def test_plot_trace_disconnects_on_engine_change(self, qapp):
        """plot_trace signal is disconnected from old plot_widget when engine changes."""
        from unittest.mock import MagicMock

        from stoner_measurement.core.sequence_engine import SequenceEngine

        engine = SequenceEngine()
        try:
            mock_pw = MagicMock()
            mock_pw.set_trace = MagicMock()
            mock_pw.set_default_axis_labels = MagicMock()
            mock_pw.assign_trace_axes = MagicMock()
            engine.plot_widget = mock_pw

            cmd = PlotTraceCommand()
            engine.add_plugin("plot_trace", cmd)
            # Now detach
            engine.remove_plugin("plot_trace")
            assert cmd.sequence_engine is None
            # The plot_trace signal should no longer call mock_pw.set_trace
            engine._namespace["px"] = np.array([1.0])
            engine._namespace["py"] = np.array([2.0])
        finally:
            engine.shutdown()

    def test_plot_axis_labels_emitted_in_simple_mode(self, qapp, engine):
        """execute() emits plot_axis_labels in simple mode with TraceData metadata."""
        from stoner_measurement.plugins.trace.base import TraceData

        td = TraceData(
            x=np.array([0.0, 1.0]),
            y=np.array([2.0, 3.0]),
            names={"x": "Current", "y": "Voltage", "d": "", "e": ""},
            units={"x": "A", "y": "V", "d": "", "e": ""},
        )

        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"dummy:Ch": "td"}
        cmd.trace_key = "dummy:Ch"

        labels: list[tuple[str, str]] = []
        cmd.plot_axis_labels.connect(lambda x, y: labels.append((x, y)))
        cmd.execute()

        assert len(labels) == 1
        assert labels[0] == ("Current (A)", "Voltage (V)")

    def test_plot_axis_labels_not_emitted_in_advanced_mode(self, qapp, engine):
        """execute() does not emit plot_axis_labels in advanced mode."""
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["px"] = np.array([1.0])
        engine._namespace["py"] = np.array([2.0])
        cmd.advanced_mode = True
        cmd.x_expr = "px"
        cmd.y_expr = "py"

        labels: list = []
        cmd.plot_axis_labels.connect(lambda x, y: labels.append((x, y)))
        cmd.execute()

        assert labels == []

    def test_plot_axis_labels_not_emitted_when_names_empty(self, qapp, engine):
        """execute() does not emit plot_axis_labels when TraceData has no names."""
        from stoner_measurement.plugins.trace.base import TraceData

        td = TraceData(x=np.array([0.0]), y=np.array([1.0]))
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"dummy:Ch": "td"}
        cmd.trace_key = "dummy:Ch"

        labels: list = []
        cmd.plot_axis_labels.connect(lambda x, y: labels.append((x, y)))
        cmd.execute()

        assert labels == []

    def test_execute_assigns_trace_to_configured_axes(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        pw.add_x_axis("freq", "Frequency (Hz)")
        pw.add_y_axis("temp", "Temperature (K)")
        engine.plot_widget = pw

        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["my_x"] = np.array([1.0, 2.0])
        engine._namespace["my_y"] = np.array([4.0, 5.0])
        cmd.advanced_mode = True
        cmd.x_expr = "my_x"
        cmd.y_expr = "my_y"
        cmd.title_expr = "'test trace'"
        cmd.x_axis_name = "freq"
        cmd.y_axis_name = "temp"

        cmd.execute()

        assert pw._trace_axes["test trace"] == ("freq", "temp")

    def test_execute_creates_missing_axes_when_configured_axis_missing(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        engine.plot_widget = pw

        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["my_x"] = np.array([1.0, 2.0])
        engine._namespace["my_y"] = np.array([4.0, 5.0])
        cmd.advanced_mode = True
        cmd.x_expr = "my_x"
        cmd.y_expr = "my_y"
        cmd.title_expr = "'test trace'"
        cmd.x_axis_name = "missing_x_axis"
        cmd.y_axis_name = "missing_y_axis"

        cmd.execute()

        assert "missing_x_axis" in pw.axis_names
        assert "missing_y_axis" in pw.axis_names
        assert pw._trace_axes["test trace"] == ("missing_x_axis", "missing_y_axis")


# ---------------------------------------------------------------------------
# WaitCommand
# ---------------------------------------------------------------------------


class TestWaitCommand:
    def test_name(self, qapp):
        assert WaitCommand().name == "Wait"

    def test_plugin_type(self, qapp):
        assert WaitCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert WaitCommand().has_lifecycle is False

    def test_default_delay_expr(self, qapp):
        assert WaitCommand().delay_expr == "1.0"

    def test_to_json_includes_delay_expr(self, qapp):
        cmd = WaitCommand()
        cmd.delay_expr = "0.5"
        d = cmd.to_json()
        assert d["delay_expr"] == "0.5"

    def test_restore_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = WaitCommand()
        cmd.delay_expr = "2.5"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, WaitCommand)
        assert restored.delay_expr == "2.5"

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        assert isinstance(WaitCommand().config_widget(), QWidget)

    def test_config_widget_has_lineedit(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        widget = WaitCommand().config_widget()
        edits = widget.findChildren(QLineEdit)
        assert len(edits) >= 1

    def test_config_widget_updates_delay_expr(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        cmd = WaitCommand()
        widget = cmd.config_widget()
        edit = widget.findChildren(QLineEdit)[0]
        edit.setText("3.0")
        edit.editingFinished.emit()
        assert cmd.delay_expr == "3.0"

    def test_execute_with_explicit_delay_sleeps(self, qapp):
        import time

        cmd = WaitCommand()
        t0 = time.monotonic()
        cmd.execute(delay=0.01)
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.01

    def test_call_with_explicit_delay_sleeps(self, qapp):
        import time

        cmd = WaitCommand()
        t0 = time.monotonic()
        cmd(delay=0.01)
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.01

    def test_execute_uses_delay_expr_when_attached(self, qapp, engine):
        import time

        cmd = WaitCommand()
        cmd.delay_expr = "0.01"
        engine.add_plugin("wait", cmd)
        t0 = time.monotonic()
        cmd.execute()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.01

    def test_execute_raises_when_detached_and_no_kwarg(self, qapp):
        cmd = WaitCommand()
        with pytest.raises(RuntimeError):
            cmd.execute()

    def test_generate_action_code(self, qapp):
        cmd = WaitCommand()
        lines = cmd.generate_action_code(1, [], lambda s, i: [])
        assert lines[0] == "    wait()"

    def test_reported_traces_empty(self, qapp):
        assert WaitCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert WaitCommand().reported_values() == {}


# ---------------------------------------------------------------------------
# StatusCommand
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_name(self, qapp):
        assert StatusCommand().name == "Status"

    def test_plugin_type(self, qapp):
        assert StatusCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert StatusCommand().has_lifecycle is False

    def test_default_status_expr(self, qapp):
        assert StatusCommand().status_expr == "'Ready'"

    def test_to_json_includes_status_expr(self, qapp):
        cmd = StatusCommand()
        cmd.status_expr = "'Running step 1'"
        d = cmd.to_json()
        assert d["status_expr"] == "'Running step 1'"

    def test_restore_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = StatusCommand()
        cmd.status_expr = "'Done'"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, StatusCommand)
        assert restored.status_expr == "'Done'"

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        assert isinstance(StatusCommand().config_widget(), QWidget)

    def test_config_widget_has_lineedit(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        widget = StatusCommand().config_widget()
        edits = widget.findChildren(QLineEdit)
        assert len(edits) >= 1

    def test_config_widget_updates_status_expr(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        cmd = StatusCommand()
        widget = cmd.config_widget()
        edit = widget.findChildren(QLineEdit)[0]
        edit.setText("'new status'")
        edit.editingFinished.emit()
        assert cmd.status_expr == "'new status'"

    def test_execute_with_explicit_status_emits_signal(self, qapp):
        cmd = StatusCommand()
        received: list[str] = []
        cmd.status_message.connect(received.append)
        cmd.execute(status="hello")
        assert received == ["hello"]

    def test_call_with_explicit_status_emits_signal(self, qapp):
        cmd = StatusCommand()
        received: list[str] = []
        cmd.status_message.connect(received.append)
        cmd(status="world")
        assert received == ["world"]

    def test_execute_uses_status_expr_when_attached(self, qapp, engine):
        cmd = StatusCommand()
        cmd.status_expr = "'engine ready'"
        engine.add_plugin("status", cmd)
        received: list[str] = []
        cmd.status_message.connect(received.append)
        cmd.execute()
        assert received == ["engine ready"]

    def test_execute_raises_when_detached_and_no_kwarg(self, qapp):
        cmd = StatusCommand()
        with pytest.raises(RuntimeError):
            cmd.execute()

    def test_status_message_forwarded_to_engine_status_changed(self, qapp, engine):
        cmd = StatusCommand()
        engine.add_plugin("status", cmd)
        engine_statuses: list[str] = []
        engine.status_changed.connect(engine_statuses.append)
        cmd.execute(status="custom message")
        assert "custom message" in engine_statuses

    def test_sequence_engine_property_none_initially(self, qapp):
        assert StatusCommand().sequence_engine is None

    def test_sequence_engine_set_via_add_plugin(self, qapp, engine):
        cmd = StatusCommand()
        engine.add_plugin("status", cmd)
        assert cmd.sequence_engine is engine

    def test_sequence_engine_cleared_via_remove_plugin(self, qapp, engine):
        cmd = StatusCommand()
        engine.add_plugin("status", cmd)
        engine.remove_plugin("status")
        assert cmd.sequence_engine is None

    def test_generate_action_code(self, qapp):
        cmd = StatusCommand()
        lines = cmd.generate_action_code(1, [], lambda s, i: [])
        assert lines[0] == "    status()"

    def test_reported_traces_empty(self, qapp):
        assert StatusCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert StatusCommand().reported_values() == {}


# ---------------------------------------------------------------------------
# AlertCommand
# ---------------------------------------------------------------------------


class TestAlertCommand:
    def test_name(self, qapp):
        assert AlertCommand().name == "Alert"

    def test_plugin_type(self, qapp):
        assert AlertCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert AlertCommand().has_lifecycle is False

    def test_default_message_expr(self, qapp):
        assert AlertCommand().message_expr == "'Alert'"

    def test_to_json_includes_message_expr(self, qapp):
        cmd = AlertCommand()
        cmd.message_expr = "'Check instrument'"
        d = cmd.to_json()
        assert d["message_expr"] == "'Check instrument'"

    def test_restore_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = AlertCommand()
        cmd.message_expr = "'Step complete'"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, AlertCommand)
        assert restored.message_expr == "'Step complete'"

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        assert isinstance(AlertCommand().config_widget(), QWidget)

    def test_config_widget_has_lineedit(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        widget = AlertCommand().config_widget()
        edits = widget.findChildren(QLineEdit)
        assert len(edits) >= 1

    def test_config_widget_updates_message_expr(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        cmd = AlertCommand()
        widget = cmd.config_widget()
        edit = widget.findChildren(QLineEdit)[0]
        edit.setText("'new message'")
        edit.editingFinished.emit()
        assert cmd.message_expr == "'new message'"

    def test_execute_raises_when_detached_and_no_kwarg(self, qapp):
        cmd = AlertCommand()
        with pytest.raises(RuntimeError):
            cmd.execute()

    def test_execute_with_explicit_message_emits_signal(self, qapp, monkeypatch):
        """execute(message=...) emits show_alert with the provided message."""
        from unittest.mock import patch

        cmd = AlertCommand()
        received: list[str] = []

        # Disconnect the BlockingQueuedConnection so we can test without
        # a running event loop in the main thread blocking the test.
        cmd.show_alert.disconnect(cmd._display_alert)
        cmd.show_alert.connect(received.append)

        with patch.object(cmd, "_display_alert", lambda msg: None):
            cmd.execute(message="test msg")

        assert received == ["test msg"]

    def test_call_with_explicit_message_emits_signal(self, qapp):
        """__call__(message=...) delegates to execute(message=...)."""
        cmd = AlertCommand()
        received: list[str] = []

        cmd.show_alert.disconnect(cmd._display_alert)
        cmd.show_alert.connect(received.append)

        cmd(message="call test")
        assert received == ["call test"]

    def test_execute_uses_message_expr_when_attached(self, qapp, engine):
        cmd = AlertCommand()
        cmd.message_expr = "'engine alert'"
        engine.add_plugin("alert", cmd)
        received: list[str] = []

        cmd.show_alert.disconnect(cmd._display_alert)
        cmd.show_alert.connect(received.append)

        cmd.execute()
        assert received == ["engine alert"]

    def test_generate_action_code(self, qapp):
        cmd = AlertCommand()
        lines = cmd.generate_action_code(1, [], lambda s, i: [])
        assert lines[0] == "    alert()"

    def test_reported_traces_empty(self, qapp):
        assert AlertCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert AlertCommand().reported_values() == {}


# ---------------------------------------------------------------------------
# DetailsCommand
# ---------------------------------------------------------------------------


class TestDetailsCommand:
    def test_name(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        assert DetailsCommand().name == "Details"

    def test_plugin_type(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        assert DetailsCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        assert DetailsCommand().has_lifecycle is False

    def test_default_fields_empty(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        assert cmd.user == ""
        assert cmd.sample == ""
        assert cmd.project == ""
        assert cmd.notes == ""

    def test_generate_action_code_assignments(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        cmd.user = "Alice"
        cmd.sample = "Nb_001"
        cmd.project = "NbSC"
        cmd.notes = "Cooled overnight"
        lines = cmd.generate_action_code(0, [], lambda s, i: [])
        assert lines[0] == 'details.user = "Alice"'
        assert lines[1] == 'details.sample = "Nb_001"'
        assert lines[2] == 'details.project = "NbSC"'
        assert lines[3] == 'details.notes = "Cooled overnight"'
        assert lines[4] == ""

    def test_generate_action_code_indentation(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        lines = cmd.generate_action_code(2, [], lambda s, i: [])
        for line in lines[:-1]:
            assert line.startswith("        ")

    def test_generate_action_code_no_execute_call(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        lines = cmd.generate_action_code(0, [], lambda s, i: [])
        assert not any("()" in line for line in lines)

    def test_generate_action_code_escapes_special_chars(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        cmd.user = 'Bob "The Builder"'
        lines = cmd.generate_action_code(0, [], lambda s, i: [])
        assert '\\"' in lines[0]

    def test_to_json_fields(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        cmd.user = "Alice"
        cmd.sample = "S1"
        cmd.project = "P1"
        cmd.notes = "notes"
        d = cmd.to_json()
        assert d["type"] == "command"
        assert d["user"] == "Alice"
        assert d["sample"] == "S1"
        assert d["project"] == "P1"
        assert d["notes"] == "notes"

    def test_restore_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin
        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        cmd.user = "Alice"
        cmd.sample = "S1"
        cmd.project = "P1"
        cmd.notes = "notes text"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, DetailsCommand)
        assert restored.user == "Alice"
        assert restored.sample == "S1"
        assert restored.project == "P1"
        assert restored.notes == "notes text"

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        from stoner_measurement.plugins.command.details import DetailsCommand

        assert isinstance(DetailsCommand().config_widget(), QWidget)

    def test_config_widget_user_field(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        cmd.user = "Alice"
        widget = cmd.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        assert any(le.text() == "Alice" for le in line_edits)

    def test_config_widget_updates_user(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        widget = cmd.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        user_edit = line_edits[0]
        user_edit.setText("Bob")
        user_edit.editingFinished.emit()
        assert cmd.user == "Bob"

    def test_config_widget_project_combobox(self, qapp):
        from PyQt6.QtWidgets import QComboBox

        from stoner_measurement.plugins.command.details import DetailsCommand

        widget = DetailsCommand().config_widget()
        combos = widget.findChildren(QComboBox)
        assert len(combos) == 1

    def test_config_widget_project_populated_from_settings(self, qapp, tmp_path):
        """Project combo box should list top-level subdirs of the settings data directory."""
        from PyQt6.QtWidgets import QComboBox

        from stoner_measurement.plugins.command.details import DetailsCommand
        from stoner_measurement.ui.settings_dialog import KEY_DEFAULT_DATA_DIR, make_app_settings

        # Create subdirectories that should appear in the combo box.
        (tmp_path / "ProjectAlpha").mkdir()
        (tmp_path / "ProjectBeta").mkdir()
        (tmp_path / "ProjectGamma").mkdir()
        # A file should NOT appear.
        (tmp_path / "not_a_dir.txt").write_text("ignored")

        # Point the settings at tmp_path.
        settings = make_app_settings()
        original = settings.value(KEY_DEFAULT_DATA_DIR, "", type=str)
        settings.setValue(KEY_DEFAULT_DATA_DIR, str(tmp_path))
        settings.sync()

        try:
            widget = DetailsCommand().config_widget()
            combo = widget.findChildren(QComboBox)[0]
            items = [combo.itemText(i) for i in range(combo.count())]
            # _top_level_dirs returns a sorted list; verify items match sorted subdirectory names.
            assert items == sorted(["ProjectAlpha", "ProjectBeta", "ProjectGamma"])
        finally:
            settings.setValue(KEY_DEFAULT_DATA_DIR, original)
            settings.sync()

    def test_config_widget_notes_updates(self, qapp):
        from PyQt6.QtWidgets import QPlainTextEdit

        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        widget = cmd.config_widget()
        notes_edit = widget.findChildren(QPlainTextEdit)[0]
        notes_edit.setPlainText("new notes")
        assert cmd.notes == "new notes"

    def test_execute_is_noop(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        cmd = DetailsCommand()
        cmd.user = "Alice"
        cmd.execute()
        assert cmd.user == "Alice"

    def test_reported_traces_empty(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        assert DetailsCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        from stoner_measurement.plugins.command.details import DetailsCommand

        assert DetailsCommand().reported_values() == {}


# ---------------------------------------------------------------------------
# PlotClearCommand
# ---------------------------------------------------------------------------


class TestPlotClearCommand:
    def test_name(self, qapp):
        assert PlotClearCommand().name == "Plot Clear"

    def test_plugin_type(self, qapp):
        assert PlotClearCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert PlotClearCommand().has_lifecycle is False

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        assert isinstance(PlotClearCommand().config_widget(), QWidget)

    def test_execute_emits_plot_clear_signal(self, qapp, engine):
        cmd = PlotClearCommand()
        engine.add_plugin("plot_clear", cmd)
        cleared = []
        cmd.plot_clear.connect(lambda: cleared.append(True))
        cmd.execute()
        assert cleared == [True]

    def test_execute_emits_once_per_call(self, qapp, engine):
        cmd = PlotClearCommand()
        engine.add_plugin("plot_clear", cmd)
        count = []
        cmd.plot_clear.connect(lambda: count.append(1))
        cmd.execute()
        cmd.execute()
        assert len(count) == 2

    def test_generate_action_code(self, qapp):
        cmd = PlotClearCommand()
        lines = cmd.generate_action_code(1, [], lambda s, i: [])
        assert lines[0] == "    plot_clear()"

    def test_reported_traces_empty(self, qapp):
        assert PlotClearCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert PlotClearCommand().reported_values() == {}

    def test_to_json_type_field(self, qapp):
        d = PlotClearCommand().to_json()
        assert d["type"] == "command"

    def test_restore_from_json_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = PlotClearCommand()
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, PlotClearCommand)

    def test_sequence_engine_wires_to_plot_widget(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        engine.plot_widget = pw
        cmd = PlotClearCommand()
        engine.add_plugin("plot_clear", cmd)
        # After attach, signal should be connected — appending then clearing
        # should result in no traces.
        pw.append_point("trace_a", 1.0, 2.0)
        assert "trace_a" in pw.trace_names
        cmd.execute()
        assert pw.trace_names == []

    def test_sequence_engine_disconnects_on_detach(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        engine.plot_widget = pw
        cmd = PlotClearCommand()
        engine.add_plugin("plot_clear", cmd)
        # Detach
        cmd.sequence_engine = None
        # Now execute should not reach the plot widget
        pw.append_point("trace_b", 1.0, 2.0)
        cmd.execute()  # should not raise; plot_clear emitted but not connected to pw
        assert "trace_b" in pw.trace_names


# ---------------------------------------------------------------------------
# PlotPointsCommand
# ---------------------------------------------------------------------------


class TestPlotPointsCommand:
    def test_name(self, qapp):
        assert PlotPointsCommand().name == "Plot Points"

    def test_plugin_type(self, qapp):
        assert PlotPointsCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert PlotPointsCommand().has_lifecycle is False

    def test_default_attributes(self, qapp):
        cmd = PlotPointsCommand()
        assert cmd.x_key == ""
        assert cmd.y_entries == []
        assert cmd.x_axis_name == "bottom"

    def test_to_json_includes_fields(self, qapp):
        cmd = PlotPointsCommand()
        cmd.x_key = "p:x"
        cmd.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "left"}]
        d = cmd.to_json()
        assert d["type"] == "command"
        assert d["x_key"] == "p:x"
        assert d["x_axis_name"] == "bottom"
        assert d["y_entries"] == [{"key": "p:y", "label": "My Y", "y_axis": "left"}]

    def test_restore_from_json_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = PlotPointsCommand()
        cmd.x_key = "sensor:temp"
        cmd.y_entries = [{"key": "sensor:voltage", "label": "Voltage (V)", "y_axis": "temp"}]
        cmd.x_axis_name = "freq"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, PlotPointsCommand)
        assert restored.x_key == "sensor:temp"
        assert restored.x_axis_name == "freq"
        assert restored.y_entries == [
            {"key": "sensor:voltage", "label": "Voltage (V)", "y_axis": "temp"}
        ]

    def test_restore_from_json_backward_compat_global_y_axis(self, qapp):
        """Old JSON with a global 'y_axis_name' migrates to per-entry 'y_axis'."""
        from stoner_measurement.plugins.base_plugin import BasePlugin

        old_json = {
            "type": "command",
            "class": "stoner_measurement.plugins.command.plot_points:PlotPointsCommand",
            "instance_name": "plot_points",
            "x_key": "p:x",
            "x_axis_name": "bottom",
            "y_axis_name": "temp",
            "y_entries": [{"key": "p:y", "label": "Y"}],
        }
        restored = BasePlugin.from_json(old_json)
        assert isinstance(restored, PlotPointsCommand)
        # per-entry y_axis should be migrated from legacy global
        assert restored.y_entries[0]["y_axis"] == "temp"

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        assert isinstance(PlotPointsCommand().config_widget(), QWidget)

    def test_config_widget_has_x_combo(self, qapp, engine):
        from PyQt6.QtWidgets import QComboBox

        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        widget = cmd.config_widget()
        combos = widget.findChildren(QComboBox)
        assert len(combos) >= 1

    def test_execute_emits_plot_point_for_each_y_series(self, qapp, engine):
        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "p_x_val", "p:y0": "p_y0_val", "p:y1": "p_y1_val"}
        engine._namespace["p_x_val"] = 3.0
        engine._namespace["p_y0_val"] = 10.0
        engine._namespace["p_y1_val"] = 20.0
        cmd.x_key = "p:x"
        cmd.y_entries = [
            {"key": "p:y0", "label": "Series 0"},
            {"key": "p:y1", "label": "Series 1"},
        ]
        received: list[tuple] = []
        cmd.plot_point.connect(lambda lbl, x, y: received.append((lbl, x, y)))
        cmd.execute()
        assert len(received) == 2
        assert received[0] == ("Series 0", 3.0, 10.0)
        assert received[1] == ("Series 1", 3.0, 20.0)

    def test_execute_emits_axis_signals_for_each_y_series(self, qapp, engine):
        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "p_x_val", "p:y0": "p_y0_val", "p:y1": "p_y1_val"}
        engine._namespace["p_x_val"] = 3.0
        engine._namespace["p_y0_val"] = 10.0
        engine._namespace["p_y1_val"] = 20.0
        cmd.x_key = "p:x"
        cmd.x_axis_name = "freq"
        cmd.y_entries = [
            {"key": "p:y0", "label": "Series 0", "y_axis": "left"},
            {"key": "p:y1", "label": "Series 1", "y_axis": "temp"},
        ]

        ensured_axes: list[tuple[str, str]] = []
        assigned_trace_axes: list[tuple[str, str, str]] = []
        cmd.plot_ensure_y_axis.connect(lambda axis, label: ensured_axes.append((axis, label)))
        cmd.plot_trace_axes.connect(
            lambda trace, x_axis, y_axis: assigned_trace_axes.append((trace, x_axis, y_axis))
        )

        cmd.execute()

        assert ensured_axes == [("left", "left"), ("temp", "temp")]
        assert assigned_trace_axes == [("Series 0", "freq", "left"), ("Series 1", "freq", "temp")]

    def test_execute_skips_missing_x_key(self, qapp, engine):
        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {}
        cmd.x_key = "missing:x"
        cmd.y_entries = [{"key": "p:y", "label": "Y"}]
        received: list = []
        cmd.plot_point.connect(lambda _l, _x, _y: received.append(1))
        cmd.execute()
        assert received == []

    def test_execute_skips_when_x_key_empty(self, qapp, engine):
        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "1.0"}
        cmd.x_key = ""
        received: list = []
        cmd.plot_point.connect(lambda _l, _x, _y: received.append(1))
        cmd.execute()
        assert received == []

    def test_execute_skips_when_no_y_entries(self, qapp, engine):
        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "1.0"}
        engine._namespace["1.0"] = 1.0
        cmd.x_key = "p:x"
        cmd.y_entries = []
        received: list = []
        cmd.plot_point.connect(lambda _l, _x, _y: received.append(1))
        cmd.execute()
        assert received == []

    def test_execute_skips_missing_y_key(self, qapp, engine):
        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "p_x_val"}
        engine._namespace["p_x_val"] = 1.0
        cmd.x_key = "p:x"
        cmd.y_entries = [{"key": "p:y_missing", "label": "Y"}]
        received: list = []
        cmd.plot_point.connect(lambda _l, _x, _y: received.append(1))
        cmd.execute()
        assert received == []

    def test_execute_skips_when_detached_no_values(self, qapp):
        cmd = PlotPointsCommand()
        cmd.x_key = "p:x"
        cmd.y_entries = [{"key": "p:y", "label": "Y"}]
        # When detached, engine_namespace returns {} so _values is empty
        received: list = []
        cmd.plot_point.connect(lambda _l, _x, _y: received.append(1))
        cmd.execute()
        assert received == []

    def test_generate_action_code(self, qapp):
        cmd = PlotPointsCommand()
        lines = cmd.generate_action_code(1, [], lambda s, i: [])
        assert lines[0] == "    plot_points()"

    def test_reported_traces_empty(self, qapp):
        assert PlotPointsCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert PlotPointsCommand().reported_values() == {}

    def test_sequence_engine_wires_to_plot_widget(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        engine.plot_widget = pw
        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        cmd.x_key = "p:x"
        cmd.y_entries = [{"key": "p:y", "label": "My Y"}]
        cmd.execute()
        assert pw.x_data("My Y") == [1.0]
        assert pw.y_data("My Y") == [5.0]
        assert pw.is_busy_for_data() is False

    def test_sequence_engine_disconnects_on_detach(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        engine.plot_widget = pw
        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        cmd.x_key = "p:x"
        cmd.y_entries = [{"key": "p:y", "label": "My Y"}]
        # Detach
        cmd.sequence_engine = None
        cmd.execute()  # should not raise; plot_point emitted but not connected to pw
        assert pw.trace_names == []

    def test_execute_assigns_points_to_configured_axes(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        pw.add_x_axis("freq", "Frequency (Hz)")
        pw.add_y_axis("temp", "Temperature (K)")
        engine.plot_widget = pw

        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        cmd.x_key = "p:x"
        cmd.x_axis_name = "freq"
        cmd.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "temp"}]

        cmd.execute()

        assert pw._trace_axes["My Y"] == ("freq", "temp")

    def test_execute_different_series_on_different_y_axes(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        pw.add_y_axis("temp", "Temperature (K)")
        engine.plot_widget = pw

        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {
            "p:x": "p_x",
            "p:v": "p_v",
            "p:t": "p_t",
        }
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_v"] = 5.0
        engine._namespace["p_t"] = 300.0
        cmd.x_key = "p:x"
        cmd.y_entries = [
            {"key": "p:v", "label": "Voltage", "y_axis": "left"},
            {"key": "p:t", "label": "Temp", "y_axis": "temp"},
        ]

        cmd.execute()

        assert pw._trace_axes["Voltage"] == ("bottom", "left")
        assert pw._trace_axes["Temp"] == ("bottom", "temp")

    def test_execute_auto_creates_missing_y_axis(self, qapp, engine):
        """execute() creates a new y-axis on the plot widget if it doesn't exist."""
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        engine.plot_widget = pw

        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        cmd.x_key = "p:x"
        cmd.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "brand_new_axis"}]

        assert "brand_new_axis" not in pw.axis_names
        cmd.execute()
        assert "brand_new_axis" in pw.axis_names
        assert pw._trace_axes["My Y"] == ("bottom", "brand_new_axis")

    def test_execute_auto_creates_missing_x_axis(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        engine.plot_widget = pw

        cmd = PlotPointsCommand()
        engine.add_plugin("plot_points", cmd)
        engine._namespace["_values"] = {"p:x": "p_x", "p:y": "p_y"}
        engine._namespace["p_x"] = 1.0
        engine._namespace["p_y"] = 5.0
        cmd.x_key = "p:x"
        cmd.x_axis_name = "brand_new_x_axis"
        cmd.y_entries = [{"key": "p:y", "label": "My Y", "y_axis": "left"}]

        assert "brand_new_x_axis" not in pw.axis_names
        cmd.execute()
        assert "brand_new_x_axis" in pw.axis_names
        assert pw._trace_axes["My Y"] == ("brand_new_x_axis", "left")
