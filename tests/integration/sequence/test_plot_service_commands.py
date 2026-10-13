"""Real engine-worker plotting with the fixed Cartesian service."""

from threading import Event, Thread

import numpy as np
import pytest
from qtpy.QtCore import QThread

from stoner_measurement.core.plotting.contracts import ClearPlot, PlotRequest, ResultStatus
from stoner_measurement.core.plotting.service import PlotService, submit_from_plugin
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import (
    AddPlotMarkerCommand,
    PlotClearCommand,
    PlotPointsCommand,
    PlotTraceCommand,
    RemovePlotMarkersCommand,
)
from stoner_measurement.ui.plot_widget import PlotWidget
from stoner_measurement.ui.plotting_bridge import CartesianPlotBridge, LegacyPlotFacade


@pytest.fixture
def routed(engine, managed_qt_widget):
    widget = managed_qt_widget(PlotWidget())
    engine.plot_widget = widget
    service = PlotService(CartesianPlotBridge(widget))
    engine.plot_client = service
    engine.plot_widget = LegacyPlotFacade(service)
    yield engine, service, widget
    service.shutdown()


def trace_command(engine):
    command = PlotTraceCommand()
    command.advanced_mode = True
    command.x_expr, command.y_expr, command.title_expr = "[1, 2]", "[3, 4]", "'Signal'"
    engine.add_plugin("plot_trace", command)
    return command


def test_actual_engine_worker_uses_gui_and_observable_signals(routed, qtbot, monkeypatch):
    engine, service, widget = routed
    command = trace_command(engine)
    observations, threads = [], []
    command.plot_trace.connect(lambda *args: observations.append(args))
    original = widget.set_trace_with_errors

    def record(*args, **kwargs):
        threads.append(QThread.currentThread())
        return original(*args, **kwargs)

    monkeypatch.setattr(widget, "set_trace_with_errors", record)
    engine._namespace["plot_command"] = command
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script("plot_command.execute()")
    assert threads == [service.thread()]
    assert len(observations) == 1
    np.testing.assert_array_equal(widget.y_data("Signal"), [3, 4])


def test_worker_renderer_failure_is_reported(routed, qtbot, monkeypatch):
    engine, _, widget = routed
    command = trace_command(engine)
    errors = []
    engine.error_output.connect(errors.append)

    def fail(*args, **kwargs):
        raise RuntimeError("display failure")

    monkeypatch.setattr(widget, "set_trace_with_errors", fail)
    engine._namespace["plot_command"] = command
    engine.run_script("plot_command.execute()")
    qtbot.waitUntil(lambda: any("display failure" in error for error in errors), timeout=5000)


def test_attach_existing_producer_does_not_render_twice(
    engine, managed_qt_widget, qtbot, monkeypatch
):
    widget = managed_qt_widget(PlotWidget())
    engine.plot_widget = widget
    command = trace_command(engine)
    service = PlotService(CartesianPlotBridge(widget))
    try:
        calls = []
        original = widget.set_trace_with_errors

        def record(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(widget, "set_trace_with_errors", record)
        engine.plot_client = service
        engine.plot_client = service
        command.execute()
        qtbot.wait(1)
        assert calls == [1]
        engine.plot_client = None
        command.execute()
        engine.plot_client = service
        command.execute()
        assert calls == [1, 1]
    finally:
        engine.plot_client = None
        service.shutdown()


def test_stop_wakes_worker_and_prevents_queued_render(routed):
    engine, service, widget = routed
    ticket = service.submit(PlotRequest(ClearPlot()))
    ready, done = Event(), Event()
    results = []

    def wait():
        ready.set()
        results.append(engine.wait_for_plot_ticket(ticket))
        done.set()

    worker = Thread(target=wait)
    worker.start()
    assert ready.wait(2)
    engine.stop()
    assert done.wait(2)
    worker.join(timeout=2)
    assert results == [None]
    assert ticket.wait(0).status == ResultStatus.CANCELLED
    assert widget.trace_names == []


def test_pause_holds_completed_ticket_until_resume(routed):
    engine, service, _ = routed
    ticket = service.apply_now(PlotRequest(ClearPlot()))
    engine._thread._pause_event.clear()
    ready, done = Event(), Event()

    def wait():
        ready.set()
        engine.wait_for_plot_ticket(ticket)
        done.set()

    worker = Thread(target=wait)
    worker.start()
    try:
        assert ready.wait(2)
        assert not done.wait(0.03)
        engine.resume()
        assert done.wait(2)
    finally:
        engine.resume()
        worker.join(timeout=2)


def test_worker_timeout_leaves_request_pending(routed):
    engine, service, _ = routed
    ticket = service.submit(PlotRequest(ClearPlot()))
    errors = []

    def wait():
        try:
            engine.wait_for_plot_ticket(ticket, timeout=0.01)
        except TimeoutError as exc:
            errors.append(exc)

    worker = Thread(target=wait)
    worker.start()
    worker.join(timeout=2)
    assert errors and ticket.wait(0) is None
    service.cancel(ticket)


def test_optional_annotation_failure_preserves_execution(routed, monkeypatch):
    engine, service, _ = routed
    command = trace_command(engine)

    def fail(*args, **kwargs):
        raise TimeoutError("annotation timeout")

    monkeypatch.setattr(service, "apply_now", fail)
    assert submit_from_plugin(command, ClearPlot(), required=False)
    with pytest.raises(TimeoutError):
        submit_from_plugin(command, ClearPlot())


def test_saved_point_command_generated_actions_and_markers(routed, qtbot):
    engine, service, widget = routed
    configured = PlotPointsCommand()
    configured.x_key = "p:x"
    configured.y_entries = [{"key": "p:y", "label": "Voltage", "colour": "red"}]
    points = BasePlugin.from_json(configured.to_json())
    engine.add_plugin("plot_points", points)
    marker = AddPlotMarkerCommand()
    marker.x_expr, marker.y_expr = "1.0", "2.0"
    remove = RemovePlotMarkersCommand()
    clear = PlotClearCommand()
    for name, command in (
        ("add_plot_marker", marker),
        ("remove_plot_markers", remove),
        ("plot_clear", clear),
    ):
        engine.add_plugin(name, command)
    engine._namespace["_values"] = {"p:x": "1.0", "p:y": "2.0"}
    observations, results = [], []
    points.plot_point.connect(lambda *args: observations.append(args))
    service.result_ready.connect(results.append)
    code = "\n".join(points.generate_action_code(0, [], lambda *args: []))
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script(code + "\n" + code + "\nadd_plot_marker()\nremove_plot_markers()")
    assert len(observations) == 2 and len(results) == 4
    np.testing.assert_array_equal(widget.y_data("Voltage"), [2, 2])
    assert all(result.status == ResultStatus.APPLIED for result in results)
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script("plot_clear()")
    assert widget.trace_names == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
