"""Real command/worker loops and live display replacement for surface bindings."""

from dataclasses import replace

import numpy as np
import pytest
from qtpy.QtCore import QObject, QThread
from qtpy.QtWidgets import QComboBox, QWidget

from stoner_measurement.core.plotting.contracts import (
    AxisDescription,
    ChannelMetadata,
    ClearPlot,
    ConfigureAxes,
    PlotCapabilities,
    PlotOperation,
    PlotRequest,
    Presentation,
    ResultStatus,
    SeriesDescription,
    SeriesUpdate,
)
from stoner_measurement.core.plotting.state import DisplayState, SeriesState
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import PlotPointsCommand, PlotTraceCommand
from stoner_measurement.plugins.command.plot_forms import PlotFormPanel
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.scan import FunctionScanGenerator
from stoner_measurement.ui.plotting.host import PlotDisplayHost
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry
from stoner_measurement.ui.plotting_bridge import LegacyPlotFacade

CAPABILITIES = PlotCapabilities(
    frozenset(
        {("cartesian", 2), ("cartesian", 3), ("polar", 2), ("cylindrical", 3), ("spherical", 3)}
    ),
    frozenset(Presentation),
    frozenset(PlotOperation),
    uncertainties=True,
    named_axes=True,
    value_channel=True,
    surface_versions=frozenset({1}),
)


class SurfaceDisplay(QObject):
    """GUI test adapter independently retaining cells and incoming transactions."""

    changed = pyqtSignal()
    capabilities = CAPABILITIES

    def __init__(self, parent):
        super().__init__(parent)
        self.widget = QWidget(parent)
        self.state = DisplayState()
        self.cells = {}
        self.acquisitions = {}
        self.requests = []
        self.threads = []
        self.fail = False

    def validate(self, payload):
        if self.fail:
            raise ValueError("adapter refused update")

    def apply(self, payload):
        self.threads.append(QThread.currentThread())
        self.requests.append(payload)
        if isinstance(payload, ClearPlot):
            self.cells.clear()
            self.acquisitions.clear()
            self.state = replace(self.state, series=())
        elif isinstance(payload, ConfigureAxes):
            self.state = replace(self.state, axes=payload.axes)
        elif isinstance(payload, SeriesUpdate):
            if payload.surface:
                surface = payload.surface
                if (
                    self.acquisitions.get(payload.series_id) != surface.acquisition_id
                    or surface.kind == "snapshot"
                ):
                    self.cells[payload.series_id] = {}
                self.acquisitions[payload.series_id] = surface.acquisition_id
                for index, (x, y) in enumerate(
                    zip(payload.data.channels["x"], payload.data.channels["y"], strict=True)
                ):
                    self.cells[payload.series_id][(float(x), float(y))] = payload.data.channels[
                        "z"
                    ][index]
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
            )
            for entry in self.state.series
        )

    def export_state(self):
        return self.state

    def import_state(self, state):
        self.state = replace(state, series=())
        for entry in state.series:
            self.apply(entry.update)
        self.changed.emit()

    def export_settings(self):
        return {}

    def close(self):
        self.widget.close()


class SurfaceFactory:
    name = "Surface test display"
    contract_version = 1
    capabilities = CAPABILITIES

    def __init__(self, factory_id):
        self.factory_id = factory_id

    def create(self, parent):
        return SurfaceDisplay(parent)


@pytest.fixture
def surface_host(engine, managed_qt_widget):
    registry = PlotDisplayRegistry()
    registry.register(SurfaceFactory("surface-one"))
    registry.register(SurfaceFactory("surface-two"))
    host = managed_qt_widget(PlotDisplayHost(registry=registry, factory_id="surface-one"))
    engine.plot_client = host.service
    engine.plot_widget = LegacyPlotFacade(host.service)
    yield host
    engine.plot_client = None
    engine.plot_widget = None
    host.service.shutdown()


def trace_command(engine, form="xyz"):
    command = PlotTraceCommand()
    command.plot_form = form
    command.new_x_expr, command.z_expr, command.fixed_y_expr = "[0, 1]", "[T, T+1]", "T"
    command.surface_id_expr = "'trace-grid'"
    engine.add_plugin("plot_trace", command)
    return command


def points_command(engine, form="xyz"):
    command = PlotPointsCommand()
    command.plot_form = form
    command.new_x_expr, command.coordinate_y_expr = "H", "T"
    command.z_entries = [{"expr": "H + T", "label": "Signal", "surface_id_expr": "'point-grid'"}]
    engine.add_plugin("plot_points", command)
    return command


@pytest.mark.parametrize("form", ["xyz", "xy_intensity", "xyz_value"])
def test_real_worker_trace_loop_retains_every_slice_and_iteration_coordinate(
    surface_host, engine, qtbot, form
):
    command = trace_command(engine, form)
    command.value_expr = "[T*2, T*3]"
    errors, results = [], []
    engine.error_output.connect(errors.append)
    surface_host.service.result_ready.connect(results.append)
    engine._namespace["command"] = command
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script("for T in (10, 20):\n    command.execute()")
    assert not errors
    assert len(surface_host.display.cells["trace-grid"]) == 4
    data = surface_host.service.data_snapshot("trace-grid")
    np.testing.assert_array_equal(data.channels["y"], [10, 10, 20, 20])
    np.testing.assert_array_equal(data.channels["z"], [10, 11, 20, 21])
    assert len(results) == 2 and all(result.status == ResultStatus.APPLIED for result in results)
    assert all(thread == surface_host.service.thread() for thread in surface_host.display.threads)
    binding = surface_host.service.series()[0].binding
    assert (binding.value == "z") == (form == "xy_intensity")
    assert (binding.z == "z") == (form != "xy_intensity")


@pytest.mark.parametrize("identity", [None, "", "   "])
def test_saved_blank_surface_identity_is_stable_unique_and_persisted(
    surface_host, engine, qtbot, identity
):
    saved = trace_command(engine).to_json()
    if identity is None:
        saved.pop("surface_id_expr")
    else:
        saved["surface_id_expr"] = identity
    command = BasePlugin.from_json(saved)
    other = BasePlugin.from_json(saved)
    assert command.surface_id_expr != other.surface_id_expr
    engine.add_plugin("saved_plot", command)
    expression = command.surface_id_expr
    engine._namespace["command"] = command
    errors = []
    engine.error_output.connect(errors.append)
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script("for T in (10, 20):\n    command.execute()")
    assert not errors
    surface_id = command.eval(expression)
    data = surface_host.service.data_snapshot(surface_id)
    np.testing.assert_array_equal(data.channels["y"], [10, 10, 20, 20])
    assert command.surface_id_expr == expression
    restored = BasePlugin.from_json(command.to_json())
    assert restored.surface_id_expr == expression


def test_clearing_surface_identity_after_load_keeps_subsequent_slices_together(
    surface_host, engine
):
    command = trace_command(engine)
    command.surface_id_expr = " "
    engine._namespace["T"] = 10
    command.execute()
    expression = command.surface_id_expr
    engine._namespace["T"] = 20
    command.execute()
    assert command.to_json()["surface_id_expr"] == expression
    data = surface_host.service.data_snapshot(command.eval(expression))
    np.testing.assert_array_equal(data.channels["y"], [10, 10, 20, 20])


@pytest.mark.parametrize("form", ["xyz", "xy_intensity", "xyz_value"])
def test_triangle_iv_is_regridded_without_custom_expressions(surface_host, engine, form):
    command = trace_command(engine, form)
    currents = FunctionScanGenerator(
        waveform="Triangle", amplitude=0.001, exponent=2, num_points=501
    ).generate()
    engine._namespace.update(T=0, currents=currents, voltages=currents * 0.005)
    command.new_x_expr, command.z_expr = "currents", "voltages"
    command.value_expr = "voltages * 2"
    for y in (0, 1):
        engine._namespace["T"] = y
        command.execute()
    data = surface_host.service.data_snapshot("trace-grid")
    assert len(data.channels["z"]) == 502
    assert set(data.channels["y"]) == {0, 1}
    np.testing.assert_allclose(data.channels["z"], data.channels["x"] * 0.005, atol=1e-18)
    if form == "xyz_value":
        np.testing.assert_allclose(data.channels["value"], data.channels["z"] * 2, atol=1e-18)
    np.testing.assert_array_equal(engine._namespace["currents"], currents)


def test_regridding_uses_live_grid_after_replay_clear_and_run_reset(surface_host, engine):
    command = trace_command(engine)
    engine._namespace["T"] = 0
    command.new_x_expr, command.z_expr = "[0, 1, 2]", "[0, 2, 4]"
    command.execute()
    assert surface_host.service.surface_x_grid("trace-grid", "default") == (0, 1, 2)
    assert surface_host.switch_display("surface-two")
    engine._namespace["T"] = 1
    command.new_x_expr, command.z_expr = "[0.1, 0.9, 1.9]", "[0.2, 1.8, 3.8]"
    command.execute()
    data = surface_host.service.data_snapshot("trace-grid")
    np.testing.assert_allclose(data.channels["x"], [0, 1, 2, 0, 1, 2])
    np.testing.assert_allclose(data.channels["z"], [0, 2, 4, 0.2, 2, 3.8])
    command.acquisition_id_expr, command.reset_on_change = "'new-run'", True
    command.execute()
    assert surface_host.service.surface_x_grid("trace-grid", "default") is None
    assert surface_host.service.surface_x_grid("trace-grid", "new-run") == (0.1, 0.9, 1.9)
    surface_host.service.apply_now(PlotRequest(ClearPlot()))
    assert surface_host.service.surface_x_grid("trace-grid", "new-run") is None
    command.new_x_expr, command.z_expr = "[3, 4]", "[6, 8]"
    command.execute()
    assert surface_host.service.surface_x_grid("trace-grid", "new-run") == (3, 4)


def test_strict_surface_grids_still_reject_triangle_samples(surface_host, engine):
    command = trace_command(engine)
    command.regrid_policy = "strict"
    command.new_x_expr, command.z_expr = "[0, 1, 0]", "[2, 3, 4]"
    engine._namespace["T"] = 0
    with pytest.raises(ValueError, match="distinct, nonempty grid cells"):
        command.execute()
    assert surface_host.display.requests == []


def test_regrid_controls_edit_and_round_trip_without_array_expressions(
    surface_host, engine, managed_plugin_config_tabs
):
    command = trace_command(engine)
    page = dict(managed_plugin_config_tabs(command))["General"]
    policy = page.findChild(QComboBox, "regrid_policy")
    bounds = page.findChild(QComboBox, "regrid_bounds")
    assert policy.currentData() == "mean"
    assert bounds.currentData() == "nearest"
    policy.setCurrentIndex(policy.findData("last"))
    bounds.setCurrentIndex(bounds.findData("missing"))
    restored = BasePlugin.from_json(command.to_json())
    assert restored.regrid_policy == "last"
    assert restored.regrid_bounds == "missing"
    saved = command.to_json()
    saved.pop("regrid_policy")
    saved.pop("regrid_bounds")
    restored = BasePlugin.from_json(saved)
    assert restored.regrid_policy == "mean" and restored.regrid_bounds == "nearest"


@pytest.mark.parametrize("form", ["xyz", "xy_intensity", "xyz_value"])
def test_nested_worker_points_are_serpentine_order_independent_and_multiple_channels(
    surface_host, engine, qtbot, form
):
    command = points_command(engine, form)
    command.value_expr = "H * T"
    command.z_entries.append({"expr": "H - T", "label": "Other", "surface_id_expr": "'other-grid'"})
    engine._namespace["command"] = command
    errors = []
    engine.error_output.connect(errors.append)
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script(
            "for T in (1, 2):\n    for H in ((0, 1) if T == 1 else (1, 0)):\n        command.execute()"
        )
    assert not errors
    for name in ("point-grid", "other-grid"):
        data = surface_host.service.data_snapshot(name)
        np.testing.assert_array_equal(data.channels["x"], [0, 1, 0, 1])
        np.testing.assert_array_equal(data.channels["y"], [1, 1, 2, 2])
        assert len(surface_host.display.cells[name]) == 4
    np.testing.assert_array_equal(
        surface_host.service.data_snapshot("point-grid").channels["z"], [1, 2, 2, 3]
    )


def test_idle_replacement_replays_cells_slices_and_duplicate_policy(surface_host, engine):
    command = trace_command(engine)
    command.duplicate_policy = "replace"
    for y in (10, 20):
        engine._namespace["T"] = y
        command.execute()
    assert surface_host.switch_display("surface-two")
    assert len(surface_host.display.cells["trace-grid"]) == 4
    command.z_expr = "[8, 9]"
    engine._namespace["T"] = 10
    command.execute()
    np.testing.assert_array_equal(
        surface_host.service.data_snapshot("trace-grid").channels["z"], [8, 9, 20, 21]
    )
    assert not surface_host.switch_display("cartesian")
    assert surface_host.factory_id == "surface-two"
    assert len(surface_host.display.cells["trace-grid"]) == 4


def test_points_replay_then_append_and_explicit_run_reset(surface_host, engine):
    command = points_command(engine)
    engine._namespace.update(H=0, T=1)
    command.execute()
    assert surface_host.switch_display("surface-two")
    engine._namespace["H"] = 1
    command.execute()
    assert len(surface_host.service.data_snapshot("point-grid").channels["z"]) == 2
    command.acquisition_id_expr = "'next'"
    command.reset_on_change = True
    command.execute()
    assert len(surface_host.service.data_snapshot("point-grid").channels["z"]) == 1
    assert len(surface_host.display.cells["point-grid"]) == 1


@pytest.mark.parametrize("command_type", [PlotTraceCommand, PlotPointsCommand])
def test_cached_config_changes_forms_axes_and_retains_unsupported_selection(
    surface_host,
    engine,
    command_type,
    managed_plugin_config_tabs,
):
    command = command_type()
    engine.add_plugin("plot", command)
    page = dict(managed_plugin_config_tabs(command))["General"]
    combo = page.findChild(QComboBox, "plot_form")
    assert {combo.itemData(i) for i in range(combo.count())} == {
        "xy",
        "xyz",
        "xy_intensity",
        "xyz_value",
    }
    combo.setCurrentIndex(combo.findData("xyz"))
    command.new_x_expr = "custom_binding"
    assert surface_host.switch_display("cartesian")
    assert command.plot_form == "xyz" and command.new_x_expr == "custom_binding"
    assert combo.currentText() == "XYZ (unsupported)"
    assert {combo.itemData(i) for i in range(combo.count())} == {"xy", "xyz"}
    assert surface_host.switch_display("surface-two")
    assert combo.currentText() == "XYZ"
    axes = (
        AxisDescription("field", "x", ChannelMetadata("Field")),
        AxisDescription("temperature", "y", ChannelMetadata("Temperature")),
        AxisDescription("height", "z", ChannelMetadata("Height")),
    )
    surface_host.service.apply_now(PlotRequest(ConfigureAxes(axes)))
    x_axis = page.findChild(QComboBox, "plot_x_axis")
    assert "field" in [x_axis.itemText(i) for i in range(x_axis.count())]
    assert command.x_axis_name == "bottom"
    assert dict(command.config_tabs())["General"] is page


def test_data_updates_do_not_rebuild_configuration(
    surface_host, engine, managed_plugin_config_tabs, monkeypatch
):
    command = points_command(engine)
    page = dict(managed_plugin_config_tabs(command))["General"]
    panel = page.findChild(PlotFormPanel)
    calls = []
    monkeypatch.setattr(panel.binding, "callback", lambda: calls.append(1))
    for x in range(3):
        engine._namespace.update(H=x, T=1)
        command.execute()
    assert calls == []


@pytest.mark.parametrize(
    "kind", ["shape", "fixed", "identity", "blank_identity", "duplicates", "failure"]
)
def test_bad_request_never_mutates_canonical_or_display_state(surface_host, engine, kind):
    command = trace_command(engine)
    engine._namespace["T"] = 10
    command.execute()
    before = len(surface_host.display.requests)
    if kind == "shape":
        command.z_expr = "[1]"
    elif kind == "fixed":
        command.fixed_y_expr = "[10]"
    elif kind == "identity":
        command.surface_id_expr = "42"
    elif kind == "blank_identity":
        command.surface_id_expr = "'   '"
    elif kind == "failure":
        engine._namespace["T"] = 20
        surface_host.display.fail = True
    with pytest.raises((ValueError, RuntimeError)):
        command.execute()
    assert len(surface_host.display.requests) == before
    np.testing.assert_array_equal(
        surface_host.service.data_snapshot("trace-grid").channels["z"], [10, 11]
    )


def test_headless_execution_preserves_no_display_semantics(engine):
    command = trace_command(engine)
    engine._namespace["T"] = 10
    command.execute()


@pytest.mark.parametrize("command_type", [PlotTraceCommand, PlotPointsCommand])
def test_saved_generated_actions_evaluate_each_live_iteration(
    surface_host, engine, qtbot, command_type
):
    configured = (
        trace_command(engine) if command_type is PlotTraceCommand else points_command(engine)
    )
    restored = BasePlugin.from_json(configured.to_json())
    engine.add_plugin("saved_plot", restored)
    action = "\n".join(restored.generate_action_code(1, [], lambda *args: []))
    errors = []
    engine.error_output.connect(errors.append)
    engine._namespace["H"] = 0
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script("for T in (5, 6):\n" + action)
    assert not errors
    name = "trace-grid" if command_type is PlotTraceCommand else "point-grid"
    data = surface_host.service.data_snapshot(name)
    assert set(data.channels["y"]) == {5, 6}


def test_point_expressions_are_evaluated_once_per_execution_for_multiple_z(surface_host, engine):
    command = points_command(engine, "xyz_value")
    counts = {"x": 0, "y": 0, "z": 0, "value": 0}

    def sample(name):
        counts[name] += 1
        return counts[name]

    engine._namespace["sample"] = sample
    command.new_x_expr, command.coordinate_y_expr = "sample('x')", "sample('y')"
    command.value_expr = "sample('value')"
    command.z_entries[0]["expr"] = "sample('z')"
    command.z_entries.append({"expr": "9", "surface_id_expr": "'second'"})
    command.execute()
    assert counts == {"x": 1, "y": 1, "z": 1, "value": 1}
    for name in ("point-grid", "second"):
        data = surface_host.service.data_snapshot(name)
        assert data.channels["x"].tolist() == [1] and data.channels["value"].tolist() == [1]


def test_source_catalog_refresh_retains_custom_expression_and_new_choices(
    surface_host,
    engine,
    managed_plugin_config_tabs,
):
    command = points_command(engine)
    command.new_x_expr = "custom(H)"
    page = dict(managed_plugin_config_tabs(command))["General"]
    source = page.findChild(QComboBox, "new_x_expr")
    engine.values_catalog_changed.emit({"field:Value": "H", "temperature:Value": "T"})
    assert source.currentText() == "custom(H)" and command.new_x_expr == "custom(H)"
    assert "field:Value" in [source.itemText(i) for i in range(source.count())]
    source.setCurrentText("field:Value")
    assert command.new_x_expr == "H"


def test_clear_removes_surface_history_and_allows_default_acquisition_again(surface_host, engine):
    command = trace_command(engine)
    engine._namespace["T"] = 10
    command.execute()
    surface_host.service.apply_now(PlotRequest(ClearPlot()))
    command.execute()
    assert len(surface_host.service.data_snapshot("trace-grid").channels["z"]) == 2


def test_identity_collisions_are_rejected_before_any_measured_channel_submission(
    surface_host, engine
):
    command = points_command(engine)
    engine._namespace.update(H=1, T=2)
    command.z_entries.append(dict(command.z_entries[0]))
    with pytest.raises(ValueError, match="distinct surface identities"):
        command.execute()
    assert surface_host.display.requests == []


@pytest.mark.parametrize("command_type", [PlotTraceCommand, PlotPointsCommand])
def test_optional_fields_round_trip_and_old_json_remains_xy(qapp, command_type):
    command = command_type()
    command.plot_form = "xyz_value"
    command.new_x_expr, command.z_expr, command.value_expr = "source_x", "source_z", "source_value"
    command.coordinate_settings = {"system": "cylindrical", "angular_unit": "degrees"}
    command.z_entries = [{"expr": "signal", "surface_id_expr": "'identity'", "label": "Z"}]
    command.duplicate_policy, command.reset_on_change = "replace", True
    command.regrid_policy, command.regrid_bounds = "last", "missing"
    data = command.to_json()
    restored = command_type()
    restored._restore_from_json(data)
    assert restored.to_json() == data
    data["z_entries"][0]["expr"] = "changed"
    assert command.z_entries[0]["expr"] == "signal"
    restored._restore_from_json({})
    assert restored.plot_form == "xy"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
