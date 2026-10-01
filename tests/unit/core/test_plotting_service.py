"""Plot service ordering, completion and GUI ownership contracts."""

from dataclasses import replace
from threading import Thread

import numpy as np
import pytest
from qtpy.QtCore import QThread

from stoner_measurement.core.plotting.contracts import (
    AddMarker,
    AxisDescription,
    ClearPlot,
    ConfigureAxes,
    CoordinateDescriptor,
    CoordinateSystem,
    ModifySeries,
    PlotRequest,
    ResultStatus,
)
from stoner_measurement.core.plotting.producers import xy_update
from stoner_measurement.core.plotting.service import CompletionTicket, PlotService
from stoner_measurement.ui.axis_mappings import AxisLabel
from stoner_measurement.ui.plot_widget import PlotWidget
from stoner_measurement.ui.plotting_bridge import CartesianPlotBridge, LegacyPlotFacade


@pytest.fixture
def display(managed_qt_widget):
    widget = managed_qt_widget(PlotWidget())
    service = PlotService(CartesianPlotBridge(widget))
    yield service, widget
    service.shutdown()


def test_worker_submission_captures_data_and_renders_on_gui(display, qtbot, monkeypatch):
    service, widget = display
    calls = []
    original = widget.set_trace_with_errors

    def record(*args, **kwargs):
        calls.append(QThread.currentThread())
        return original(*args, **kwargs)

    monkeypatch.setattr(widget, "set_trace_with_errors", record)
    source = np.array([1.0, 2.0])
    tickets = []

    def produce():
        tickets.append(service.submit(PlotRequest(xy_update("s", source, [3, 4]))))
        source[:] = 100

    worker = Thread(target=produce)
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    qtbot.waitUntil(lambda: tickets[0].wait(0) is not None)
    assert tickets[0].wait(0).status == ResultStatus.APPLIED
    assert calls == [service.thread()]
    np.testing.assert_array_equal(widget.x_data("s"), [1, 2])


def test_ordered_clear_and_update_acknowledge_once(display, qtbot):
    service, widget = display
    results = []
    service.result_ready.connect(results.append)
    requests = [
        PlotRequest(xy_update("old", [1], [2])),
        PlotRequest(ClearPlot()),
        PlotRequest(xy_update("new", [3], [4])),
    ]
    tickets = [service.submit(request) for request in requests]
    qtbot.waitUntil(lambda: len(results) == 3)
    assert [result.request_id for result in results] == [r.request_id for r in requests]
    assert widget.trace_names == ["new"]
    assert all(ticket.wait(0).status == ResultStatus.APPLIED for ticket in tickets)
    with pytest.raises(ValueError, match="reused"):
        service.submit(requests[0])
    assert len(results) == 3


def test_ack_includes_axis_labels_errors_style_and_title(display):
    service, widget = display
    snapshots = []
    service.result_ready.connect(
        lambda _: snapshots.append((widget.trace_style("s"), service.axes(), service.series()))
    )
    payload = replace(
        xy_update(
            "s",
            [1],
            [2],
            y_error=[0.2],
            x_label=AxisLabel("Time", "s"),
            y_label=AxisLabel("Voltage", "V"),
            y_axis="voltage",
            style={"colour": "red", "line_style": "dash"},
        ),
        title="Signal",
    )
    ticket = service.apply_now(PlotRequest(payload))
    assert ticket.wait(0).status == ResultStatus.APPLIED
    style, axes, series = snapshots[0]
    assert style["line"] == "dash"
    assert next(axis for axis in axes if axis.name == "voltage").label.unit == "V"
    assert series[0].title == "Signal" and series[0].series_id == "s"
    np.testing.assert_allclose(widget.trace_uncertainties("s")[1], [0.2])


def test_append_snapshot_and_schema_failure_preserve_data(display):
    service, widget = display
    for x in (1, 2, 3):
        assert (
            service.apply_now(PlotRequest(xy_update("s", [x], [x * 2], append=True))).wait(0).status
            == ResultStatus.APPLIED
        )
    np.testing.assert_array_equal(service.data_snapshot("s").channels["x"], [1, 2, 3])
    bad = service.apply_now(PlotRequest(xy_update("s", [4], [8], append=True, y_label="Changed")))
    assert bad.wait(0).status == ResultStatus.FAILED
    np.testing.assert_array_equal(widget.x_data("s"), [1, 2, 3])


@pytest.mark.parametrize(
    "payload",
    [
        xy_update("bad", [1], [2], style={"colour": "invalid colour"}),
        ConfigureAxes((AxisDescription("bottom", "x", scale="log", limits=(-1, 2)),)),
        ModifySeries("missing", visible=False),
    ],
)
def test_validation_failure_does_not_mutate_display(display, payload):
    service, widget = display
    before = service.axes()
    result = service.apply_now(PlotRequest(payload)).wait(0)
    assert result.status == ResultStatus.FAILED
    assert widget.trace_names == [] and service.axes() == before


def test_unsupported_coordinates_complete_without_rendering(display):
    service, widget = display
    update = replace(
        xy_update("polar", [1], [2]), coordinates=CoordinateDescriptor(CoordinateSystem.POLAR)
    )
    result = service.apply_now(PlotRequest(update)).wait(0)
    assert result.status == ResultStatus.UNSUPPORTED and result.message
    assert widget.trace_names == []


def test_renderer_failure_preserves_canonical_data_and_queue_recovers(display, monkeypatch):
    service, widget = display
    service.apply_now(PlotRequest(xy_update("s", [1], [2])))
    original = widget.set_trace_with_errors

    def fail(*args, **kwargs):
        raise RuntimeError("renderer broke")

    monkeypatch.setattr(widget, "set_trace_with_errors", fail)
    result = service.apply_now(PlotRequest(xy_update("s", [3], [4]))).wait(0)
    assert result.status == ResultStatus.FAILED and "renderer broke" in result.message
    np.testing.assert_array_equal(service.data_snapshot("s").channels["x"], [1])
    monkeypatch.setattr(widget, "set_trace_with_errors", original)
    assert service.apply_now(PlotRequest(ClearPlot())).wait(0).status == ResultStatus.APPLIED


def test_cancel_shutdown_and_bounded_queue(display, qtbot):
    service, widget = display
    service._max_pending = 1
    ticket = service.submit(PlotRequest(xy_update("s", [1], [2])))
    with pytest.raises(RuntimeError, match="full"):
        service.submit(PlotRequest(ClearPlot()))
    service.cancel(ticket)
    assert ticket.wait(0).status == ResultStatus.CANCELLED
    service.shutdown()
    assert service.submit(PlotRequest(ClearPlot())).wait(0).status == ResultStatus.CANCELLED
    qtbot.wait(1)
    assert widget.trace_names == []


def test_gui_cannot_block_on_pending_ticket(display):
    service, _ = display
    ticket = service.submit(PlotRequest(ClearPlot()))
    assert ticket.wait(0) is None
    with pytest.raises(RuntimeError, match="GUI callers"):
        ticket.wait(0.1)


def test_headless_service_completes(qapp):
    service = PlotService()
    try:
        result = service.apply_now(PlotRequest(xy_update("s", [1], [2]))).wait(0)
        assert result.status == ResultStatus.NO_DISPLAY and result.generation == 0
    finally:
        service.shutdown()


def test_standalone_ticket_timeout_is_not_completion():
    ticket = CompletionTicket("pending")
    assert ticket.wait(0.001) is None


def test_legacy_keywords_returns_and_state(display):
    service, widget = display
    facade = LegacyPlotFacade(service)
    facade.set_trace(trace_name="s", x_data=[1, 2], y_data=[3, 4])
    facade.append_point(trace_name="s", x=5, y=6)
    np.testing.assert_array_equal(service.data_snapshot("s").channels["x"], [1, 2, 5])
    marker = facade.add_data_marker(1, 3)
    assert marker > 0 and facade.remove_data_marker(marker) is True
    facade.rename_trace(old_name="s", new_name="renamed")
    assert facade.trace_names == ["renamed"]
    facade.remove_trace(trace_name="renamed")
    assert widget.trace_names == [] and service.series() == ()
    with pytest.raises(AttributeError):
        _ = facade._axis_orientations


def test_public_axis_and_visibility_changes_update_snapshots(display):
    service, widget = display
    service.apply_now(PlotRequest(xy_update("s", [1], [2])))
    widget.add_y_axis("extra", "Extra")
    assert "extra" in [axis.name for axis in service.axes()]
    widget.set_trace_visible("s", False)
    assert service.series()[0].visible is False
    marker = service.apply_now(PlotRequest(AddMarker({"x": 1, "y": 2}))).wait(0)
    assert marker.status == ResultStatus.APPLIED and marker.marker_id > 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
