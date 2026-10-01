"""The published external factory integrates without application changes."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from stoner_measurement.core.plotting.contracts import AddMarker, PlotRequest, ResultStatus
from stoner_measurement.core.plotting.producers import xy_update
from stoner_measurement.plugins.command import PlotPointsCommand, PlotTraceCommand
from stoner_measurement.ui.main_window import MainWindow
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry
from stoner_measurement.ui.plotting_bridge import LegacyPlotFacade


@pytest.fixture
def example_registry(monkeypatch):
    path = Path(__file__).resolve().parents[3] / "docs/examples/summary_display.py"
    spec = spec_from_file_location("documented_summary_display", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    entry = SimpleNamespace(
        name="summary",
        value="your_package.summary_display:SummaryDisplayFactory",
        load=lambda: module.SummaryDisplayFactory,
    )
    monkeypatch.setattr("importlib.metadata.entry_points", lambda **kwargs: [entry])
    registry = PlotDisplayRegistry()
    registry.discover()
    assert registry.diagnostics == ()
    return registry


def test_documented_factory_runs_existing_worker_and_replays(
    example_registry, engine, plugin_manager, qtbot, managed_qt_widget
):
    window = managed_qt_widget(
        MainWindow(plugin_manager, display_registry=example_registry, display_factory_id="summary")
    )
    host = window.plot_display_host
    engine.plot_client = host.service
    engine.plot_widget = LegacyPlotFacade(host.service)
    command = PlotTraceCommand()
    command.advanced_mode = True
    command.x_expr, command.y_expr, command.title_expr = "[1, 2]", "[3, 4]", "'Signal'"
    engine.add_plugin("plot_trace", command)
    points = PlotPointsCommand()
    points.x_key = "p:x"
    points.y_entries = [{"key": "p:y", "label": "Point"}]
    engine.add_plugin("plot_points", points)
    engine._namespace["_values"] = {"p:x": "1.0", "p:y": "2.0"}
    errors = []
    engine.error_output.connect(errors.append)
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script("plot_trace()\nplot_points()")
    assert not errors
    assert "Signal: 2 samples" in host.display.label.text()
    assert "Point: 1 samples" in host.display.label.text()
    append = xy_update("Signal", [5], [6], append=True)
    assert host.service.apply_now(PlotRequest(append)).wait(0).status == ResultStatus.APPLIED
    assert "Signal: 3 samples" in host.display.label.text()
    assert host.switch_display("cartesian")
    np.testing.assert_array_equal(window.plot_widget.y_data("Signal"), [3, 4, 6])
    assert host.switch_display("summary")
    assert "Signal: 3 samples" in host.display.label.text()


def test_documented_factory_refuses_markers_and_retains_original(
    example_registry, plugin_manager, managed_qt_widget
):
    window = managed_qt_widget(MainWindow(plugin_manager, display_registry=example_registry))
    host = window.plot_display_host
    host.service.apply_now(PlotRequest(AddMarker({"x": 1, "y": 2})))
    original = host.display
    assert not host.switch_display("summary")
    assert host.display is original


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
