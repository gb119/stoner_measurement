"""The host accepts portable displays without requiring Cartesian widget APIs."""

from threading import Thread

import pytest
from qtpy.QtCore import QObject, QThread
from qtpy.QtWidgets import QScrollArea, QWidget

from stoner_measurement.core.plotting.contracts import (
    AddMarker,
    AxisDescription,
    ClearPlot,
    CoordinateSystem,
    PlotCapabilities,
    PlotOperation,
    PlotRequest,
    Presentation,
    ResultStatus,
    SeriesDescription,
    SeriesUpdate,
)
from stoner_measurement.core.plotting.producers import xy_update
from stoner_measurement.core.plotting.service import LegacyCall
from stoner_measurement.plugins.command import PlotPointsCommand, PlotTraceCommand
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.main_window import MainWindow
from stoner_measurement.ui.plot_widget import PlotWidget
from stoner_measurement.ui.plotting.host import PlotDisplayHost
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry
from stoner_measurement.ui.plotting_bridge import LegacyPlotFacade

MINIMAL_CAPABILITIES = PlotCapabilities(
    frozenset({(CoordinateSystem.CARTESIAN, 2)}),
    frozenset({Presentation.LINE}),
    frozenset({PlotOperation.UPDATE_SERIES, PlotOperation.CLEAR}),
)


class MinimalDisplay(QObject):
    """Deliberately lacks append_point, set_trace, axis setters and pg_widget."""

    changed = pyqtSignal()
    capabilities = MINIMAL_CAPABILITIES

    def __init__(self, parent):
        super().__init__(parent)
        self.widget = QWidget(parent)
        self.updates = {}
        self.calls = []
        self.close_count = 0

    def validate(self, payload):
        if not isinstance(payload, (SeriesUpdate, ClearPlot)):
            raise ValueError("Unsupported operation")

    def apply(self, payload):
        self.calls.append((payload, QThread.currentThread()))
        if isinstance(payload, ClearPlot):
            self.updates.clear()
        else:
            self.updates[payload.series_id] = payload
        self.changed.emit()

    def descriptions(self):
        return (
            (AxisDescription("bottom", "x"), AxisDescription("left", "y")),
            tuple(
                SeriesDescription(name, name, update.binding)
                for name, update in self.updates.items()
            ),
        )

    def close(self):
        if not self.close_count:
            self.close_count += 1
            self.widget.close()


class MinimalFactory:
    factory_id = "minimal"
    name = "Minimal test display"
    contract_version = 1
    capabilities = MINIMAL_CAPABILITIES

    def create(self, parent):
        self.created = MinimalDisplay(parent)
        return self.created


def minimal_registry(factory=None):
    registry = PlotDisplayRegistry()
    registry.register(factory or MinimalFactory())
    return registry


def test_default_host_preserves_cartesian_access_and_owned_close(managed_qt_widget, monkeypatch):
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry()))
    assert isinstance(host.display_widget, PlotWidget)
    assert host.factory_id == "cartesian"
    closed = []
    original = host.display_widget.close

    def close():
        closed.append(True)
        return original()

    monkeypatch.setattr(host.display_widget, "close", close)
    ticket = host.service.submit(PlotRequest(xy_update("s", [1], [2])))
    host.close()
    host.close()
    assert closed == [True]
    assert ticket.wait(0).status == ResultStatus.CANCELLED


def test_minimal_display_accepts_worker_requests_and_optional_legacy_rejection(
    managed_qt_widget, qtbot
):
    host = managed_qt_widget(PlotDisplayHost(registry=minimal_registry(), factory_id="minimal"))
    tickets = []
    worker = Thread(
        target=lambda: tickets.append(host.service.submit(PlotRequest(xy_update("s", [1], [2]))))
    )
    worker.start()
    worker.join(timeout=2)
    qtbot.waitUntil(lambda: tickets[0].wait(0) is not None)
    assert tickets[0].wait(0).status == ResultStatus.APPLIED
    assert host.display.calls[0][1] == host.thread()
    assert not hasattr(host.display_widget, "set_trace")
    assert host.service.series()[0].series_id == "s"
    marker = host.service.apply_now(PlotRequest(AddMarker({"x": 1, "y": 2}))).wait(0)
    assert marker.status == ResultStatus.UNSUPPORTED
    legacy = host.service.invoke_legacy(LegacyCall("set_trace", ("s", [1], [2]), {})).wait(0)
    assert legacy.status == ResultStatus.UNSUPPORTED
    assert len(host.display.calls) == 1


def test_missing_factory_falls_back_with_diagnostic(managed_qt_widget):
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry(), factory_id="missing"))
    assert host.factory_id == "cartesian"
    assert "missing" in host.diagnostics[0] and "using Cartesian" in host.diagnostics[0]
    assert host.service.apply_now(PlotRequest(ClearPlot())).wait(0).status == ResultStatus.APPLIED


@pytest.mark.parametrize("failure", ["creation", "capabilities", "descriptions", "signal"])
def test_broken_factory_falls_back_and_closes_partial_widgets(managed_qt_widget, failure):
    closed = []

    class PartialWidget(QWidget):
        def closeEvent(self, event):
            closed.append(True)
            super().closeEvent(event)

    class BrokenFactory(MinimalFactory):
        def create(self, parent):
            if failure == "creation":
                self.partial = PartialWidget(parent)
                raise RuntimeError("creation failed")
            self.created = MinimalDisplay(parent)
            if failure == "capabilities":
                self.created.capabilities = None
            elif failure == "descriptions":
                self.created.descriptions = lambda: ([], [])
            else:
                self.created.changed = None
            return self.created

    factory = BrokenFactory()
    host = managed_qt_widget(
        PlotDisplayHost(registry=minimal_registry(factory), factory_id="minimal")
    )
    assert host.factory_id == "cartesian" and host.diagnostics
    if failure == "creation":
        assert closed == [True]
    else:
        assert factory.created.close_count == 1


def test_main_window_and_commands_need_only_portable_display_api(
    plugin_manager, engine, managed_qt_widget, qtbot
):
    window = managed_qt_widget(
        MainWindow(
            plugin_manager, display_registry=minimal_registry(), display_factory_id="minimal"
        )
    )
    host = window.plot_display_host
    assert window.plot_widget is host.display_widget
    assert window._splitter.widget(1) is host
    engine.plot_client = host.service
    engine.plot_widget = LegacyPlotFacade(host.service)
    trace = PlotTraceCommand()
    trace.advanced_mode = True
    trace.x_expr, trace.y_expr, trace.title_expr = "[1, 2]", "[3, 4]", "'Signal'"
    engine.add_plugin("plot_trace", trace)
    points = PlotPointsCommand()
    points.x_key = "p:x"
    points.y_entries = [{"key": "p:y", "label": "Point"}]
    engine.add_plugin("plot_points", points)
    engine._namespace["_values"] = {"p:x": "1.0", "p:y": "2.0"}
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script("plot_trace()\nplot_points()")
    assert set(host.display.updates) == {"Signal", "Point"}
    assert all(thread == host.thread() for _, thread in host.display.calls)
    assert host.diagnostics == ()
    window.close()
    assert host.display.close_count == 1


def test_host_construction_rejects_worker_threads(qapp):
    failures = []

    def construct():
        try:
            PlotDisplayHost(registry=PlotDisplayRegistry())
        except RuntimeError as exc:
            failures.append(str(exc))

    worker = Thread(target=construct)
    worker.start()
    worker.join(timeout=2)
    assert failures == ["Plot displays must be constructed on the GUI thread."]


def test_cartesian_configured_axes_and_label_edit_use_the_host_service(engine, managed_qt_widget):
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry()))
    engine.plot_client = host.service
    engine.plot_widget = LegacyPlotFacade(host.service)
    command = PlotPointsCommand()
    command.x_axis_name = "time"
    command.y_entries = [{"key": "p:y", "label": "Old", "y_axis": "voltage"}]
    engine.add_plugin("plot_points", command)
    assert {axis.name for axis in host.service.axes()} >= {"time", "voltage"}
    engine._namespace["_values"] = {"p:x": "1.0", "p:y": "2.0"}
    engine.plot_widget.append_point("Old", 1, 2)
    widget = managed_qt_widget(command.config_widget())
    grid = widget.findChild(QScrollArea).widget().layout()
    label = grid.itemAtPosition(2, 1).widget().lineEdit()
    observations = []
    command.plot_rename_trace.connect(lambda *args: observations.append(args))
    label.setText("New")
    label.editingFinished.emit()
    assert observations == [("Old", "New")]
    assert engine.plot_widget.trace_names == ["New"]
    assert host.service.data_snapshot("New").channels["x"].tolist() == [1]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
