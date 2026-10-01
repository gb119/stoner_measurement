"""Transactional display replacement, explicit state replay and persistence."""

import json
from dataclasses import replace
from threading import Event

import numpy as np
import pytest
from qtpy.QtCore import QObject, QSettings
from qtpy.QtWidgets import QWidget

from stoner_measurement.core.plotting.contracts import (
    AddMarker,
    ChannelMetadata,
    ClearPlot,
    CoordinateBinding,
    CoordinateDescriptor,
    CoordinateSystem,
    ModifySeries,
    PlotCapabilities,
    PlotData,
    PlotRequest,
    ResultStatus,
    SeriesDescription,
    SeriesUpdate,
)
from stoner_measurement.core.plotting.producers import xy_update
from stoner_measurement.core.plotting.state import DisplayState, SeriesState, settings_dict
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.ui.plotting.cartesian import CartesianDisplayFactory
from stoner_measurement.ui.plotting.host import PlotDisplayHost
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry
from stoner_measurement.ui.plotting_bridge import LegacyPlotFacade


class MemoryDisplay(QObject):
    """Portable, non-PyQtGraph adapter retaining an explicit snapshot."""

    changed = pyqtSignal()
    capabilities = CartesianDisplayFactory.capabilities

    def __init__(self, parent):
        super().__init__(parent)
        self.widget = QWidget(parent)
        self.state = DisplayState()
        self.closed = 0

    def validate(self, payload):
        pass

    def apply(self, payload):
        if isinstance(payload, ClearPlot):
            self.state = replace(self.state, series=(), markers=())
        elif isinstance(payload, SeriesUpdate):
            entries = {entry.update.series_id: entry for entry in self.state.series}
            entries[payload.series_id] = SeriesState(payload)
            self.state = replace(self.state, series=tuple(entries.values()))
        self.changed.emit()

    def descriptions(self):
        return self.state.axes, tuple(
            SeriesDescription(
                entry.update.series_id,
                entry.update.title or entry.update.series_id,
                entry.update.binding,
                entry.update.coordinates,
                entry.visible,
            )
            for entry in self.state.series
        )

    def export_state(self):
        return self.state

    def import_state(self, state):
        self.state = state
        self.changed.emit()

    def export_settings(self):
        return {"version": 1, "background": "black"}

    def import_settings(self, settings):
        if settings.get("version") != 1:
            raise ValueError("bad preferences")

    def close(self):
        if not self.closed:
            self.closed += 1
            self.widget.close()


class MemoryFactory:
    factory_id = "memory"
    name = "Memory display"
    contract_version = 1
    capabilities = CartesianDisplayFactory.capabilities
    display_class = MemoryDisplay

    def create(self, parent):
        self.created = self.display_class(parent)
        return self.created


@pytest.fixture
def hosted(managed_qt_widget):
    registry = PlotDisplayRegistry()
    factory = MemoryFactory()
    registry.register(factory)
    host = managed_qt_widget(PlotDisplayHost(registry=registry))
    return host, factory


def populate(host):
    facade = LegacyPlotFacade(host.service)
    facade.add_x_axis("time", "Time (s)")
    facade.add_y_axis("voltage", "Voltage (V)")
    update = xy_update(
        "s",
        [1.0, 2.0],
        [3.0, 4.0],
        x_error=[0.1, 0.2],
        y_error=[0.3, 0.4],
        x_axis="time",
        y_axis="voltage",
        x_label="Time",
        y_label="Voltage",
        style={
            "colour": "red",
            "line_style": "dash",
            "point_style": "diamond",
            "line_width": 4.0,
            "point_size": 9.0,
        },
    )
    host.service.apply_now(PlotRequest(update))
    # User controls must override presentation originally submitted by the producer.
    widget = host.display_widget
    widget.set_trace_style("s", colour="blue", line_width=6.0)
    widget.set_trace_title("s", "User title")
    widget.set_trace_visible("s", False)
    widget.set_axis_scale("time", "log")
    widget.set_axis_range("time", 1.0, 10.0)
    widget.set_axis_range("voltage", -2.0, 5.0)
    widget.set_axis_mouse_active("bottom", False)
    widget.set_axis_mouse_active("left", False)
    widget.set_axis_mouse_active("time", True)
    widget.set_axis_mouse_active("voltage", True)
    widget.set_axis_grid("voltage", True)
    widget.set_axis_visible("left", False)
    marker = host.service.apply_now(PlotRequest(AddMarker({"x": 1.5, "y": 3.5}))).wait(0).marker_id
    return marker


def test_round_trip_preserves_data_ui_state_marker_identity_and_generation(hosted, qapp):
    host, factory = hosted
    marker_id = populate(host)
    host.resize(900, 650)
    host.show()
    qapp.processEvents()
    host.display_widget._plot_splitter.setSizes([190, 450])
    host.display_widget._on_plot_splitter_moved(190, 1)
    original_widget = host.display_widget
    before = host.export_state()
    service = host.service
    old_result = service.apply_now(PlotRequest(ModifySeries("s", visible=False))).wait(0)
    assert host.switch_display("memory"), host.diagnostics
    assert host.service is service and factory.created.state.markers[0].marker_id == marker_id
    assert host.switch_display("cartesian"), host.diagnostics
    after = host.export_state()
    assert after.renderer_settings["legend_sizes"][0] == before.renderer_settings["legend_sizes"][0]
    assert after.axes == before.axes
    assert after.markers == before.markers
    assert after.series[0].update.title == "User title"
    assert after.series[0].visible is False
    assert after.series[0].update.style == before.series[0].update.style
    np.testing.assert_array_equal(after.series[0].update.data.channels["x"], [1, 2])
    np.testing.assert_array_equal(after.series[0].update.data.uncertainties["y"], [0.3, 0.4])
    assert host.display_widget is not original_widget and factory.created.closed == 1
    assert LegacyPlotFacade(service).remove_data_marker(marker_id) is True
    result = service.apply_now(PlotRequest(ClearPlot())).wait(0)
    assert result.generation == old_result.generation + 2
    assert old_result.status == ResultStatus.APPLIED


@pytest.mark.parametrize("failure", ["hydrate", "description", "capability"])
def test_failed_candidate_keeps_current_display_and_generation(hosted, failure):
    host, factory = hosted
    populate(host)
    original = host.display_widget
    before = host.export_state()
    if failure == "capability":
        factory.capabilities = PlotCapabilities(
            frozenset({(CoordinateSystem.POLAR, 2)}),
            factory.capabilities.presentations,
            factory.capabilities.operations,
        )

        class Incompatible(MemoryDisplay):
            capabilities = factory.capabilities

        factory.display_class = Incompatible
    else:

        class Broken(MemoryDisplay):
            def import_state(self, state):
                if failure == "hydrate":
                    raise RuntimeError("hydration failed")
                self.state = state
                self.descriptions = lambda: ([], [])

        factory.display_class = Broken
    assert host.switch_display("memory") is False
    assert host.display_widget is original and host.factory_id == "cartesian"
    assert host.export_state().axes == before.axes
    assert factory.created.closed == 1
    result = host.service.apply_now(PlotRequest(ModifySeries("s", visible=False))).wait(0)
    assert result.generation == 1 and result.status == ResultStatus.APPLIED


def test_busy_requests_and_execution_refuse_switch_before_creation(hosted, engine, qtbot):
    host, factory = hosted
    host.idle_check = lambda: engine.is_plot_idle
    pending = host.service.submit(PlotRequest(ClearPlot()))
    assert host.switch_display("memory") is False
    assert not hasattr(factory, "created")
    host.service.cancel(pending)
    release = Event()
    engine._namespace["hold"] = release
    engine.execute_command("hold.wait(2)")
    assert host.switch_display("memory") is False
    release.set()
    qtbot.waitUntil(lambda: engine.is_plot_idle)
    assert host.switch_display("memory") is True


def test_pending_submission_during_hydration_is_rejected(hosted):
    host, factory = hosted

    class Reentrant(MemoryDisplay):
        def import_state(self, state):
            with pytest.raises(RuntimeError, match="replacement is in progress"):
                host.service.submit(PlotRequest(ClearPlot()))
            super().import_state(state)

    factory.display_class = Reentrant
    assert host.switch_display("memory")


def test_unsupported_styles_survive_switching_back_with_feedback(hosted):
    host, factory = hosted
    populate(host)

    class Limited(MemoryDisplay):
        supported_styles = {"colour"}

    factory.display_class = Limited
    assert host.switch_display("memory")
    assert set(factory.created.state.series[0].update.style) == {"colour"}
    assert any("unsupported styles" in message for message in host.diagnostics)
    assert host.switch_display("cartesian")
    assert host.export_state().series[0].update.style["line_width"] == 6.0


def test_preferences_restore_factory_and_renderer_settings_without_arrays(
    managed_qt_widget, tmp_path
):
    settings = QSettings(str(tmp_path / "display.ini"), QSettings.Format.IniFormat)
    registry = PlotDisplayRegistry()
    registry.register(MemoryFactory())
    first = managed_qt_widget(PlotDisplayHost(registry=registry, settings=settings))
    populate(first)
    first.display_widget.resize(800, 600)
    first.display_widget._plot_splitter.setSizes([180, 410])
    first.display_widget._on_plot_splitter_moved(180, 1)
    assert first.switch_display("memory")
    first.close()
    saved = json.loads(settings.value("plotDisplay/preferences"))
    assert saved["factory_id"] == "memory" and "series" not in saved["renderers"]["cartesian"]
    second = managed_qt_widget(PlotDisplayHost(registry=registry, settings=settings))
    assert second.factory_id == "memory"
    assert second.switch_display("cartesian")
    # Startup has no acquisition arrays, but Cartesian preferences remain available.
    assert second.service.series() == ()
    assert second.display_widget.export_plot_settings()["legend_resized"] is True
    assert second.display_widget.export_plot_settings()["next_marker_id"] > 1


def test_missing_saved_factory_and_invalid_settings_fall_back(managed_qt_widget, tmp_path):
    settings = QSettings(str(tmp_path / "display.ini"), QSettings.Format.IniFormat)
    settings.setValue(
        "plotDisplay/preferences",
        json.dumps({"version": 1, "factory_id": "missing", "renderers": {}}),
    )
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry(), settings=settings))
    assert host.factory_id == "cartesian" and host.diagnostics
    settings.setValue(
        "plotDisplay/preferences",
        json.dumps({"version": 99, "factory_id": "cartesian", "renderers": {}}),
    )
    other = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry(), settings=settings))
    assert other.factory_id == "cartesian" and other.diagnostics


def test_canonical_source_binding_and_metadata_survive_replay(hosted):
    host, _ = hosted
    update = SeriesUpdate(
        "bound",
        PlotData(
            {"t": [1], "v": [2], "aux": [3]},
            {"t": ChannelMetadata("Time", "s"), "v": ChannelMetadata("Voltage", "V")},
        ),
        CoordinateBinding("t", "v"),
        CoordinateDescriptor(),
    )
    host.service.apply_now(PlotRequest(update))
    assert host.switch_display("memory") and host.switch_display("cartesian")
    replayed = host.export_state().series[0].update
    assert replayed.binding == update.binding
    assert host.service.series()[0].binding == update.binding
    assert replayed.data.metadata == update.data.metadata
    assert replayed.data.channels["aux"].tolist() == [3]


def test_state_preferences_reject_measurement_arrays():
    with pytest.raises(ValueError, match="not arrays"):
        DisplayState(renderer_settings={"bad": np.array([1])})
    source = {"version": 1, "nested": [1, 2]}
    state = DisplayState(renderer_settings=source)
    source["nested"].append(3)
    assert settings_dict(state.renderer_settings)["nested"] == [1, 2]


def test_invalid_cartesian_preferences_restore_safe_defaults(managed_qt_widget, tmp_path):
    settings = QSettings(str(tmp_path / "bad.ini"), QSettings.Format.IniFormat)
    settings.setValue(
        "plotDisplay/preferences",
        json.dumps(
            {"version": 1, "factory_id": "cartesian", "renderers": {"cartesian": {"version": 99}}}
        ),
    )
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry(), settings=settings))
    assert host.factory_id == "cartesian" and host.diagnostics
    assert host.service.apply_now(PlotRequest(ClearPlot())).wait(0).status == ResultStatus.APPLIED


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
