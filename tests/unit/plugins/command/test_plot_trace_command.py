"""Tests for PlotTraceCommand."""

from __future__ import annotations

import numpy as np
import pytest

from stoner_measurement.plugins.command import (
    PlotTraceCommand,
)


def _make_plot_widget(qtbot, qapp, request):
    """Create a PlotWidget and close it explicitly before pytest-qt teardown."""
    from stoner_measurement.ui.plot_widget import PlotWidget

    widget = PlotWidget()
    qtbot.addWidget(widget)

    def _cleanup() -> None:
        widget.close()
        qapp.processEvents()
        widget.deleteLater()
        qapp.processEvents()

    request.addfinalizer(_cleanup)
    return widget


class _NeverAckPlotWidget:
    """Test double that tracks queued updates but never acknowledges processing."""

    def __init__(self) -> None:
        self._pending = 0

    def mark_data_update_queued(self) -> None:
        self._pending += 1

    def is_busy_for_data(self) -> bool:
        return self._pending > 0

    def set_trace(self, _trace_name: str, _x_data: object, _y_data: object) -> None:
        pass

    def append_point(self, _trace_name: str, _x: float, _y: float) -> None:
        pass

    def ensure_x_axis(self, _name: str, _label: str) -> None:
        pass

    def ensure_y_axis(self, _name: str, _label: str) -> None:
        pass

    def assign_trace_axes(self, _trace_name: str, _x_axis: str, _y_axis: str) -> None:
        pass


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
        assert cmd.column_key == ""
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
        assert "column_key" in d
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
        cmd.column_key = "z"
        cmd.advanced_mode = True
        cmd.x_expr = "dummy.data['Dummy'].x"
        cmd.y_expr = "dummy.data['Dummy'].y"
        cmd.title_expr = "'my plot'"
        cmd.x_axis_name = "freq"
        cmd.y_axis_name = "temp"
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, PlotTraceCommand)
        assert restored.trace_key == "dummy:Dummy"
        assert restored.column_key == "z"
        assert restored.advanced_mode is True
        assert restored.x_expr == "dummy.data['Dummy'].x"
        assert restored.y_expr == "dummy.data['Dummy'].y"
        assert restored.title_expr == "'my plot'"
        assert restored.x_axis_name == "freq"
        assert restored.y_axis_name == "temp"

    def test_config_widget_returns_widget(self, qapp):
        from qtpy.QtWidgets import QWidget

        assert isinstance(PlotTraceCommand().config_widget(), QWidget)

    def test_config_widget_has_trace_combo(self, qapp):
        from qtpy.QtWidgets import QComboBox

        widget = PlotTraceCommand().config_widget()
        combos = widget.findChildren(QComboBox)
        assert len(combos) >= 1

    def test_config_widget_has_advanced_checkbox(self, qapp):
        from qtpy.QtWidgets import QCheckBox

        widget = PlotTraceCommand().config_widget()
        checkboxes = widget.findChildren(QCheckBox)
        assert len(checkboxes) >= 2


    def test_config_advanced_checkbox_toggles_advanced_mode(self, qapp):
        from qtpy.QtWidgets import QCheckBox

        cmd = PlotTraceCommand()
        cmd.advanced_mode = False
        widget = cmd.config_widget()
        checkboxes = widget.findChildren(QCheckBox)

        advanced_checkbox = next(cb for cb in checkboxes if cb.isChecked() == cmd.advanced_mode)
        # If both start False, prefer the non-transpose one by excluding the first checkbox.
        if advanced_checkbox is checkboxes[0] and len(checkboxes) > 1:
            advanced_checkbox = checkboxes[1]

        advanced_checkbox.setChecked(True)
        assert cmd.advanced_mode is True
        advanced_checkbox.setChecked(False)
        assert cmd.advanced_mode is False

    def test_config_widget_has_title_lineedit(self, qapp):
        from qtpy.QtWidgets import QLineEdit

        widget = PlotTraceCommand().config_widget()
        edits = widget.findChildren(QLineEdit)
        # title_expr edit + internal spin box edits
        assert len(edits) >= 2

    def test_config_widget_has_colour_button(self, qapp):
        from qtpy.QtWidgets import QPushButton

        cmd = PlotTraceCommand()
        widget = cmd.config_widget()
        buttons = widget.findChildren(QPushButton)
        assert any(btn.text() == "(auto)" for btn in buttons)

    def test_config_title_edit_updates_title_expr(self, qapp):
        from qtpy.QtWidgets import QLineEdit

        cmd = PlotTraceCommand()
        cmd.title_expr = "'original'"
        widget = cmd.config_widget()
        edits = widget.findChildren(QLineEdit)
        # Find the title edit by its current text (title_expr value).
        title_edit = next((e for e in edits if e.text() == "'original'"), None)
        assert title_edit is not None
        title_edit.setText("'new title'")
        title_edit.editingFinished.emit()
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

    def test_execute_advanced_mode_waits_when_plot_widget_busy(self, qapp, engine):
        import threading
        import time

        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        pw.mark_data_update_queued()
        engine.plot_widget = pw

        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["my_x"] = np.array([1.0, 2.0])
        engine._namespace["my_y"] = np.array([4.0, 5.0])
        cmd.advanced_mode = True
        cmd.x_expr = "my_x"
        cmd.y_expr = "my_y"
        cmd.title_expr = "'busy-trace'"

        received: list[tuple] = []
        cmd.plot_trace.connect(lambda t, x, y: received.append((t, x, y)))

        def _release_plot_busy_flag() -> None:
            time.sleep(0.02)
            pw._mark_data_update_processed()

        release_thread = threading.Thread(target=_release_plot_busy_flag, daemon=True)
        release_thread.start()
        started = time.monotonic()
        cmd.execute()
        elapsed = time.monotonic() - started
        release_thread.join(timeout=1.0)

        assert len(received) == 1
        assert received[0][0] == "busy-trace"
        # Verify waiting occurred; exact timing is platform and scheduler dependent.
        assert elapsed >= 0.01
        assert pw.is_busy_for_data() is False

    def test_execute_advanced_mode_raises_when_plot_response_times_out(self, qapp, engine, monkeypatch):
        import stoner_measurement.plugins.command.base as command_base

        monkeypatch.setattr(command_base, "_DEFAULT_PLOT_READY_TIMEOUT_SECONDS", 0.01)
        engine.plot_widget = _NeverAckPlotWidget()

        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["my_x"] = np.array([1.0, 2.0])
        engine._namespace["my_y"] = np.array([4.0, 5.0])
        cmd.advanced_mode = True
        cmd.x_expr = "my_x"
        cmd.y_expr = "my_y"
        cmd.title_expr = "'timeout-trace'"

        with pytest.raises(TimeoutError, match="plot response"):
            cmd.execute()

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
            mock_pw.is_busy_for_data = MagicMock(return_value=False)
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

    def test_sequence_engine_attachment_creates_configured_axes(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        engine.plot_widget = pw
        cmd = PlotTraceCommand()
        cmd.x_axis_name = "loaded_x"
        cmd.y_axis_name = "loaded_y"

        assert "loaded_x" not in pw.axis_names
        assert "loaded_y" not in pw.axis_names
        engine.add_plugin("plot_trace", cmd)

        assert "loaded_x" in pw.axis_names
        assert "loaded_y" in pw.axis_names

    def test_execute_simple_mode_uses_column_key(self, qapp, engine):
        """execute() uses column_key to select a specific DataFrame column."""
        import pandas as pd

        from stoner_measurement.plugins.trace.base import (
            COLUMN_ROLE_Y,
            COLUMN_ROLE_Z,
            TraceData,
        )

        df = pd.DataFrame(
            {"y": [1.0, 2.0], "z": [3.0, 4.0]},
            index=pd.Index([0.0, 1.0], name="x"),
        )
        td = TraceData(df=df, column_roles={"y": COLUMN_ROLE_Y, "z": COLUMN_ROLE_Z})
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"dummy:Ch": "td"}
        cmd.trace_key = "dummy:Ch"
        cmd.column_key = "z"

        received: list[tuple] = []
        cmd.plot_trace_with_errors.connect(lambda t, x, y, xe, ye: received.append((t, x, y, xe, ye)))
        cmd.execute()

        assert len(received) == 1
        np.testing.assert_array_equal(received[0][2], [3.0, 4.0])

    def test_execute_simple_mode_falls_back_to_y_when_column_key_empty(self, qapp, engine):
        """execute() falls back to .y when column_key is empty."""
        from stoner_measurement.plugins.trace.base import TraceData

        td = TraceData(x=np.array([0.0, 1.0]), y=np.array([10.0, 20.0]))
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"dummy:Ch": "td"}
        cmd.trace_key = "dummy:Ch"
        cmd.column_key = ""  # empty → use .y

        received: list[tuple] = []
        cmd.plot_trace_with_errors.connect(lambda t, x, y, xe, ye: received.append((t, x, y, xe, ye)))
        cmd.execute()

        assert len(received) == 1
        np.testing.assert_array_equal(received[0][2], [10.0, 20.0])

    def test_execute_simple_mode_falls_back_to_y_for_unknown_column_key(self, qapp, engine):
        """execute() falls back to .y when column_key names a non-existent column."""
        from stoner_measurement.plugins.trace.base import TraceData

        td = TraceData(x=np.array([0.0, 1.0]), y=np.array([5.0, 6.0]))
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"dummy:Ch": "td"}
        cmd.trace_key = "dummy:Ch"
        cmd.column_key = "nonexistent"

        received: list[tuple] = []
        cmd.plot_trace_with_errors.connect(lambda t, x, y, xe, ye: received.append((t, x, y, xe, ye)))
        cmd.execute()

        assert len(received) == 1
        np.testing.assert_array_equal(received[0][2], [5.0, 6.0])

    def test_axis_labels_use_column_key_name_and_unit(self, qapp, engine):
        """_emit_trace_axis_labels uses the column_key to look up name/unit."""
        import pandas as pd

        from stoner_measurement.plugins.trace.base import (
            COLUMN_ROLE_Y,
            COLUMN_ROLE_Z,
            TraceData,
        )

        df = pd.DataFrame(
            {"y": [1.0], "z": [2.0]},
            index=pd.Index([0.0], name="x"),
        )
        td = TraceData(
            df=df,
            column_roles={"y": COLUMN_ROLE_Y, "z": COLUMN_ROLE_Z},
            names={"x": "Current", "y": "Voltage", "z": "Height"},
            units={"x": "A", "y": "V", "z": "m"},
        )
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"dummy:Ch": "td"}
        cmd.trace_key = "dummy:Ch"
        cmd.column_key = "z"

        labels: list[tuple[str, str]] = []
        cmd.plot_axis_labels.connect(lambda x, y: labels.append((x, y)))
        cmd.execute()

        assert len(labels) == 1
        assert labels[0] == ("Current (A)", "Height (m)")

    def test_axis_labels_fallback_to_resolved_y_column_when_column_key_invalid(self, qapp, engine):
        """Axis label y metadata should come from the actual plotted y column."""
        import pandas as pd

        from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData

        df = pd.DataFrame({"V": [1.0], "R": [2.0]}, index=pd.Index([0.0], name="x"))
        td = TraceData(
            df=df,
            column_roles={"V": COLUMN_ROLE_Y, "R": COLUMN_ROLE_Y},
            names={"x": "Current", "V": "Voltage", "R": "Resistance"},
            units={"x": "A", "V": "V", "R": "ohm"},
        )
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"dummy:Ch": "td"}
        cmd.trace_key = "dummy:Ch"
        cmd.column_key = "missing"

        labels: list[tuple[str, str]] = []
        cmd.plot_axis_labels.connect(lambda x, y: labels.append((x, y)))
        cmd.execute()

        assert len(labels) == 1
        assert labels[0] == ("Current (A)", "Voltage (V)")

    def test_config_widget_has_column_combo(self, qapp, engine):
        """config_widget() must include a Column combo box.

        At minimum there should be two combo boxes: the trace combo and the
        column combo.  In practice there are more (x/y data and x/y axis), but
        we only assert the minimum here to keep the test robust.
        """
        from qtpy.QtWidgets import QComboBox

        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        widget = cmd.config_widget()
        combos = widget.findChildren(QComboBox)
        assert len(combos) >= 2

    def test_config_widget_column_combo_repopulates_on_trace_change(self, qapp, engine):
        import pandas as pd
        from qtpy.QtWidgets import QComboBox

        from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData

        t1 = TraceData(
            df=pd.DataFrame({"A": [1.0]}, index=pd.Index([0.0], name="x")),
            column_roles={"A": COLUMN_ROLE_Y},
        )
        t2 = TraceData(
            df=pd.DataFrame({"B": [2.0]}, index=pd.Index([0.0], name="x")),
            column_roles={"B": COLUMN_ROLE_Y},
        )
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        cmd.engine_namespace["t1"] = t1
        cmd.engine_namespace["t2"] = t2
        cmd.engine_namespace["_traces"] = {"src:t1": "t1", "src:t2": "t2"}
        cmd.trace_key = "src:t1"
        cmd.column_key = ""
        widget = cmd.config_widget()
        combos = widget.findChildren(QComboBox)

        trace_combo = next(c for c in combos if c.findText("src:t1") >= 0 and c.findText("src:t2") >= 0)
        column_combo = next(c for c in combos if c.findText("(default)") >= 0)
        assert column_combo.findText("A") >= 0
        assert column_combo.findText("B") == -1

        trace_combo.setCurrentText("src:t2")

        assert column_combo.findText("(default)") >= 0
        assert column_combo.findText("B") >= 0
        assert column_combo.findText("A") == -1

    # ------------------------------------------------------------------
    # Multicolumn and error-bar behaviour
    # ------------------------------------------------------------------

    def test_execute_multicolumn_emits_one_trace_per_y_column(self, qapp, engine):
        """execute() emits plot_trace_with_errors once per COLUMN_ROLE_Y column."""
        import pandas as pd

        from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData

        df = pd.DataFrame(
            {"V": [1.0, 2.0], "R": [10.0, 20.0]},
            index=pd.Index([0.0, 1.0], name="x"),
        )
        td = TraceData(df=df, column_roles={"V": COLUMN_ROLE_Y, "R": COLUMN_ROLE_Y})
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"src:ch": "td"}
        cmd.trace_key = "src:ch"
        cmd.column_key = ""

        received: list[tuple] = []
        cmd.plot_trace_with_errors.connect(lambda t, x, y, xe, ye: received.append((t, list(y))))
        cmd.execute()

        assert len(received) == 2
        titles = {r[0] for r in received}
        assert "src:ch:V" in titles
        assert "src:ch:R" in titles
        v_row = next(r for r in received if r[0] == "src:ch:V")
        r_row = next(r for r in received if r[0] == "src:ch:R")
        assert v_row[1] == [1.0, 2.0]
        assert r_row[1] == [10.0, 20.0]

    def test_execute_multicolumn_does_not_emit_plot_trace(self, qapp, engine):
        """execute() must NOT emit plot_trace (advanced-mode signal) in simple mode."""
        import pandas as pd

        from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData

        df = pd.DataFrame(
            {"V": [1.0], "R": [10.0]},
            index=pd.Index([0.0], name="x"),
        )
        td = TraceData(df=df, column_roles={"V": COLUMN_ROLE_Y, "R": COLUMN_ROLE_Y})
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"src:ch": "td"}
        cmd.trace_key = "src:ch"
        cmd.column_key = ""

        legacy: list = []
        cmd.plot_trace.connect(lambda t, x, y: legacy.append(1))
        cmd.execute()

        assert legacy == []

    def test_execute_single_column_with_y_error_bars(self, qapp, engine):
        """execute() passes y-error bars from COLUMN_ROLE_E to plot_trace_with_errors."""
        import pandas as pd

        from stoner_measurement.plugins.trace.base import (
            COLUMN_ROLE_E,
            COLUMN_ROLE_Y,
            TraceData,
        )

        df = pd.DataFrame(
            {"V": [1.0, 2.0], "e_V": [0.1, 0.2]},
            index=pd.Index([0.0, 1.0], name="x"),
        )
        td = TraceData(
            df=df,
            column_roles={"V": COLUMN_ROLE_Y, "e_V": COLUMN_ROLE_E},
        )
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"src:ch": "td"}
        cmd.trace_key = "src:ch"
        cmd.column_key = ""

        received: list[tuple] = []
        cmd.plot_trace_with_errors.connect(lambda t, x, y, xe, ye: received.append((t, xe, list(ye))))
        cmd.execute()

        assert len(received) == 1
        assert received[0][1] is None  # no x errors
        np.testing.assert_allclose(received[0][2], [0.1, 0.2])

    def test_execute_multicolumn_y_error_positional_match(self, qapp, engine):
        """execute() matches e-columns positionally to y-columns."""
        import pandas as pd

        from stoner_measurement.plugins.trace.base import (
            COLUMN_ROLE_E,
            COLUMN_ROLE_Y,
            TraceData,
        )

        df = pd.DataFrame(
            {"V": [1.0, 2.0], "R": [10.0, 20.0], "e_V": [0.1, 0.2], "e_R": [1.0, 2.0]},
            index=pd.Index([0.0, 1.0], name="x"),
        )
        td = TraceData(
            df=df,
            column_roles={
                "V": COLUMN_ROLE_Y,
                "R": COLUMN_ROLE_Y,
                "e_V": COLUMN_ROLE_E,
                "e_R": COLUMN_ROLE_E,
            },
        )
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"src:ch": "td"}
        cmd.trace_key = "src:ch"
        cmd.column_key = ""

        received: dict[str, list] = {}
        cmd.plot_trace_with_errors.connect(
            lambda t, x, y, xe, ye: received.update({t: list(ye)})
        )
        cmd.execute()

        assert "src:ch:V" in received
        assert "src:ch:R" in received
        np.testing.assert_allclose(received["src:ch:V"], [0.1, 0.2])
        np.testing.assert_allclose(received["src:ch:R"], [1.0, 2.0])

    def test_execute_multicolumn_shared_x_error(self, qapp, engine):
        """execute() shares COLUMN_ROLE_D x-error across all y-columns."""
        import pandas as pd

        from stoner_measurement.plugins.trace.base import (
            COLUMN_ROLE_D,
            COLUMN_ROLE_Y,
            TraceData,
        )

        df = pd.DataFrame(
            {"V": [1.0, 2.0], "R": [10.0, 20.0], "d_I": [0.01, 0.01]},
            index=pd.Index([0.0, 1.0], name="x"),
        )
        td = TraceData(
            df=df,
            column_roles={"V": COLUMN_ROLE_Y, "R": COLUMN_ROLE_Y, "d_I": COLUMN_ROLE_D},
        )
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["td"] = td
        engine._namespace["_traces"] = {"src:ch": "td"}
        cmd.trace_key = "src:ch"
        cmd.column_key = ""

        received: dict[str, list] = {}
        cmd.plot_trace_with_errors.connect(
            lambda t, x, y, xe, ye: received.update({t: list(xe)})
        )
        cmd.execute()

        assert "src:ch:V" in received
        assert "src:ch:R" in received
        np.testing.assert_allclose(received["src:ch:V"], [0.01, 0.01])
        np.testing.assert_allclose(received["src:ch:R"], [0.01, 0.01])

    def test_set_trace_with_errors_updates_plot_widget(self, qtbot, qapp, request):
        """PlotWidget.set_trace_with_errors updates trace data and creates error bars."""

        widget = _make_plot_widget(qtbot, qapp, request)
        widget.set_trace_with_errors(
            "sig",
            [0.0, 1.0, 2.0],
            [1.0, 2.0, 3.0],
            None,
            [0.1, 0.1, 0.1],
        )
        assert widget.y_data("sig") == [1.0, 2.0, 3.0]
        assert "sig" in widget._error_bar_items

    def test_set_trace_with_errors_no_errors_no_error_bar_item(self, qtbot, qapp, request):
        """PlotWidget.set_trace_with_errors with no errors should not create an ErrorBarItem."""

        widget = _make_plot_widget(qtbot, qapp, request)
        widget.set_trace_with_errors("sig", [0.0, 1.0], [2.0, 3.0], None, None)
        assert widget.y_data("sig") == [2.0, 3.0]
        assert "sig" not in widget._error_bar_items

    def test_set_trace_with_errors_waits_for_error_bar_work_before_marking_processed(self, qtbot, qapp, request, monkeypatch):
        """Pending update must stay busy until error-bar update completes."""

        widget = _make_plot_widget(qtbot, qapp, request)
        widget.set_trace_with_errors("sig", [0.0, 1.0], [2.0, 3.0], None, [0.1, 0.2])
        error_bar_item = widget._error_bar_items["sig"]
        original_set_data = error_bar_item.setData
        observed_busy_states: list[bool] = []

        def _wrapped_set_data(*args, **kwargs):
            observed_busy_states.append(widget.is_busy_for_data())
            return original_set_data(*args, **kwargs)

        monkeypatch.setattr(error_bar_item, "setData", _wrapped_set_data)
        widget.mark_data_update_queued()
        widget.set_trace_with_errors("sig", [0.0, 1.0], [2.5, 3.5], None, [0.1, 0.2])

        assert observed_busy_states == [True]
        assert widget.is_busy_for_data() is False

    def test_remove_trace_cleans_up_error_bar_item(self, qtbot, qapp, request):
        """remove_trace() must also remove the associated ErrorBarItem."""

        widget = _make_plot_widget(qtbot, qapp, request)
        widget.set_trace_with_errors("sig", [0.0, 1.0], [2.0, 3.0], None, [0.1, 0.2])
        assert "sig" in widget._error_bar_items
        widget.remove_trace("sig")
        assert "sig" not in widget._error_bar_items
        assert "sig" not in widget.trace_names

    # ------------------------------------------------------------------
    # Format / style attribute tests
    # ------------------------------------------------------------------

    def test_default_format_attributes(self, qapp):
        cmd = PlotTraceCommand()
        assert cmd.colour == ""
        assert cmd.line_style == ""
        assert cmd.point_style == ""
        assert cmd.line_width == 0.0
        assert cmd.point_size == 0.0

    def test_to_json_includes_format_fields(self, qapp):
        cmd = PlotTraceCommand()
        d = cmd.to_json()
        assert "colour" in d
        assert "line_style" in d
        assert "point_style" in d
        assert "line_width" in d
        assert "point_size" in d

    def test_restore_from_json_round_trip_includes_format(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        cmd = PlotTraceCommand()
        cmd.colour = "red"
        cmd.line_style = "dash"
        cmd.point_style = "circle"
        cmd.line_width = 3.0
        cmd.point_size = 10.0
        restored = BasePlugin.from_json(cmd.to_json())
        assert isinstance(restored, PlotTraceCommand)
        assert restored.colour == "red"
        assert restored.line_style == "dash"
        assert restored.point_style == "circle"
        assert restored.line_width == 3.0
        assert restored.point_size == 10.0

    def test_restore_from_json_format_defaults_when_absent(self, qapp):
        """Old JSON with no format fields restores with empty defaults."""
        from stoner_measurement.plugins.base_plugin import BasePlugin

        old_json = {
            "type": "command",
            "class": "stoner_measurement.plugins.command.plot_trace:PlotTraceCommand",
            "instance_name": "plot_trace",
            "trace_key": "",
            "column_key": "",
            "transpose": False,
            "advanced_mode": False,
            "x_expr": "",
            "y_expr": "",
            "title_expr": "'plot'",
            "x_axis_name": "bottom",
            "y_axis_name": "left",
        }
        restored = BasePlugin.from_json(old_json)
        assert isinstance(restored, PlotTraceCommand)
        assert restored.colour == ""
        assert restored.line_style == ""
        assert restored.point_style == ""
        assert restored.line_width == 0.0
        assert restored.point_size == 0.0

    def test_execute_advanced_mode_emits_style_signal(self, qapp, engine):
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["my_x"] = np.array([1.0, 2.0])
        engine._namespace["my_y"] = np.array([3.0, 4.0])
        cmd.advanced_mode = True
        cmd.x_expr = "my_x"
        cmd.y_expr = "my_y"
        cmd.title_expr = "'styled'"
        cmd.colour = "red"
        cmd.line_style = "dash"
        cmd.point_style = "circle"
        cmd.line_width = 3.0
        cmd.point_size = 10.0

        style_signals: list[tuple] = []
        cmd.plot_trace_style.connect(lambda name, style: style_signals.append((name, style)))
        cmd.execute()

        assert len(style_signals) == 1
        name, style = style_signals[0]
        assert name == "styled"
        assert style["colour"] == "red"
        assert style["line_style"] == "dash"
        assert style["point_style"] == "circle"
        assert style["line_width"] == 3.0
        assert style["point_size"] == 10.0

    def test_execute_advanced_mode_no_style_signal_when_defaults(self, qapp, engine):
        """No style signal emitted when all format attributes are at their defaults."""
        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["my_x"] = np.array([1.0])
        engine._namespace["my_y"] = np.array([2.0])
        cmd.advanced_mode = True
        cmd.x_expr = "my_x"
        cmd.y_expr = "my_y"
        cmd.title_expr = "'t'"

        style_signals: list = []
        cmd.plot_trace_style.connect(lambda n, s: style_signals.append(s))
        cmd.execute()

        assert style_signals == []

    def test_config_widget_has_colour_button_with_initial_value(self, qapp):
        from qtpy.QtWidgets import QPushButton

        cmd = PlotTraceCommand()
        cmd.colour = "blue"
        widget = cmd.config_widget()
        buttons = widget.findChildren(QPushButton)
        colour_button = next((b for b in buttons if b.text() == "#0000ff"), None)
        assert colour_button is not None

    def test_config_colour_button_updates_colour(self, qapp, monkeypatch):
        from qtpy.QtWidgets import QPushButton

        cmd = PlotTraceCommand()
        cmd.colour = "blue"
        monkeypatch.setattr(cmd, "_choose_colour", lambda current, title: "#008000")
        widget = cmd.config_widget()
        buttons = widget.findChildren(QPushButton)
        colour_button = next((b for b in buttons if b.text() == "#0000ff"), None)
        assert colour_button is not None
        colour_button.click()
        assert cmd.colour == "#008000"

    def test_plot_widget_set_trace_style_from_dict(self, qtbot, qapp, request):
        widget = _make_plot_widget(qtbot, qapp, request)
        widget.append_point("sig", 0.0, 1.0)
        widget.set_trace_style_from_dict("sig", {"colour": "red", "line_style": "dash"})
        assert widget._trace_style["sig"]["line"] == "dash"

    def test_plot_widget_set_trace_style_from_dict_empty_is_noop(self, qtbot, qapp, request):
        widget = _make_plot_widget(qtbot, qapp, request)
        widget.append_point("sig", 0.0, 1.0)
        original_style = dict(widget._trace_style["sig"])
        widget.set_trace_style_from_dict("sig", {})
        assert widget._trace_style["sig"] == original_style

    def test_plot_trace_style_signal_wired_to_plot_widget(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        pw = PlotWidget()
        engine.plot_widget = pw

        cmd = PlotTraceCommand()
        engine.add_plugin("plot_trace", cmd)
        engine._namespace["my_x"] = np.array([1.0])
        engine._namespace["my_y"] = np.array([2.0])
        cmd.advanced_mode = True
        cmd.x_expr = "my_x"
        cmd.y_expr = "my_y"
        cmd.title_expr = "'t'"
        cmd.colour = "red"
        cmd.line_style = "dash"
        cmd.execute()

        # The plot widget should now have the style applied.
        assert pw._trace_style.get("t", {}).get("line") == "dash"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))

