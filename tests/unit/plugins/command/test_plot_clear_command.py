"""Tests for PlotClearCommand."""

from __future__ import annotations

from stoner_measurement.plugins.command import PlotClearCommand


class TestPlotClearCommand:
    def test_name(self, qapp):
        assert PlotClearCommand().name == "Plot Clear"

    def test_plugin_type(self, qapp):
        assert PlotClearCommand().plugin_type == "command"

    def test_has_lifecycle_false(self, qapp):
        assert PlotClearCommand().has_lifecycle is False

    def test_config_widget_returns_widget(self, qapp):
        from qtpy.QtWidgets import QWidget

        assert isinstance(PlotClearCommand().config_widget(), QWidget)

    def test_execute_emits_plot_clear_signal(self, qapp, engine):
        command = PlotClearCommand()
        engine.add_plugin("plot_clear", command)
        cleared = []
        command.plot_clear.connect(lambda: cleared.append(True))
        command.execute()
        assert cleared == [True]

    def test_execute_emits_once_per_call(self, qapp, engine):
        command = PlotClearCommand()
        engine.add_plugin("plot_clear", command)
        count = []
        command.plot_clear.connect(lambda: count.append(1))
        command.execute()
        command.execute()
        assert len(count) == 2

    def test_generate_action_code(self, qapp):
        command = PlotClearCommand()
        lines = command.generate_action_code(1, [], lambda source, indent: [])
        assert lines[0] == "    plot_clear()"

    def test_reported_traces_empty(self, qapp):
        assert PlotClearCommand().reported_traces() == {}

    def test_reported_values_empty(self, qapp):
        assert PlotClearCommand().reported_values() == {}

    def test_to_json_type_field(self, qapp):
        data = PlotClearCommand().to_json()
        assert data["type"] == "command"

    def test_restore_from_json_round_trip(self, qapp):
        from stoner_measurement.plugins.base_plugin import BasePlugin

        command = PlotClearCommand()
        restored = BasePlugin.from_json(command.to_json())
        assert isinstance(restored, PlotClearCommand)

    def test_sequence_engine_wires_to_plot_widget(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        plot_widget = PlotWidget()
        engine.plot_widget = plot_widget
        command = PlotClearCommand()
        engine.add_plugin("plot_clear", command)
        plot_widget.append_point("trace_a", 1.0, 2.0)
        assert "trace_a" in plot_widget.trace_names
        command.execute()
        assert plot_widget.trace_names == []

    def test_sequence_engine_disconnects_on_detach(self, qapp, engine):
        from stoner_measurement.ui.plot_widget import PlotWidget

        plot_widget = PlotWidget()
        engine.plot_widget = plot_widget
        command = PlotClearCommand()
        engine.add_plugin("plot_clear", command)
        command.sequence_engine = None
        plot_widget.append_point("trace_b", 1.0, 2.0)
        command.execute()
        assert "trace_b" in plot_widget.trace_names


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "--pdb"]))
