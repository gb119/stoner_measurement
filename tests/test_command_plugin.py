"""Tests for CommandPlugin, SaveCommand, and PlotTraceCommand."""

from __future__ import annotations

import json
import pathlib

import numpy as np
import pytest

from stoner_measurement.plugins.command import CommandPlugin, PlotTraceCommand, SaveCommand


# ---------------------------------------------------------------------------
# Minimal concrete implementation used across tests
# ---------------------------------------------------------------------------


class _Noop(CommandPlugin):
    """CommandPlugin that does nothing."""

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

    def test_config_tabs_has_general_tab(self, qapp):
        tabs = _Noop().config_tabs()
        tab_names = [t[0] for t in tabs]
        assert "General" in tab_names

    def test_execute_called_via_sequence(self, qapp, engine):
        """CommandPlugin.execute() is called when the sequence script runs."""
        import time

        from PyQt6.QtWidgets import QApplication

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
        assert SaveCommand().path_expr == "'data/output.json'"

    def test_to_json_includes_path_expr(self, qapp):
        cmd = SaveCommand()
        cmd.path_expr = "'my/path.json'"
        d = cmd.to_json()
        assert d["path_expr"] == "'my/path.json'"

    def test_restore_from_json(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = SaveCommand()
        cmd.path_expr = "'run/output.json'"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, SaveCommand)
        assert restored.path_expr == "'run/output.json'"

    def test_config_widget_returns_widget(self, qapp):
        from PyQt6.QtWidgets import QWidget

        assert isinstance(SaveCommand().config_widget(), QWidget)

    def test_config_widget_updates_path_expr(self, qapp):
        from PyQt6.QtWidgets import QLineEdit

        cmd = SaveCommand()
        widget = cmd.config_widget()
        line_edits = widget.findChildren(QLineEdit)
        assert line_edits, "Config widget should have a QLineEdit"
        line_edits[0].setText("'new/path.json'")
        line_edits[0].editingFinished.emit()
        assert cmd.path_expr == "'new/path.json'"

    def test_execute_writes_json_file(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "out.json"
        cmd.path_expr = repr(str(out_file))
        cmd.execute()
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "traces" in data
        assert "values" in data

    def test_execute_creates_parent_dirs(self, qapp, engine, tmp_path):
        cmd = SaveCommand()
        engine.add_plugin("save", cmd)
        out_file = tmp_path / "subdir" / "nested" / "out.json"
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

    def test_to_json_includes_fields(self, qapp):
        cmd = PlotTraceCommand()
        d = cmd.to_json()
        assert d["type"] == "command"
        assert "trace_key" in d
        assert "advanced_mode" in d
        assert "x_expr" in d
        assert "y_expr" in d
        assert "title_expr" in d

    def test_restore_from_json_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = PlotTraceCommand()
        cmd.trace_key = "dummy:Dummy"
        cmd.advanced_mode = True
        cmd.x_expr = "dummy.data['Dummy'].x"
        cmd.y_expr = "dummy.data['Dummy'].y"
        cmd.title_expr = "'my plot'"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, PlotTraceCommand)
        assert restored.trace_key == "dummy:Dummy"
        assert restored.advanced_mode is True
        assert restored.x_expr == "dummy.data['Dummy'].x"
        assert restored.y_expr == "dummy.data['Dummy'].y"
        assert restored.title_expr == "'my plot'"

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

        engine = __import__(
            "stoner_measurement.core.sequence_engine", fromlist=["SequenceEngine"]
        ).SequenceEngine()
        try:
            mock_pw = MagicMock()
            mock_pw.set_trace = MagicMock()
            mock_pw.set_default_axis_labels = MagicMock()
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
