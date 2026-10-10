"""Real plot commands, native displays and cached configuration pages."""

import numpy as np
import pytest
from qtpy.QtWidgets import QComboBox

from stoner_measurement.core.plotting.contracts import ClearPlot, PlotRequest, ResultStatus
from stoner_measurement.plugins.command import PlotPointsCommand, PlotTraceCommand
from stoner_measurement.ui.plotting.host import PlotDisplayHost
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry
from stoner_measurement.ui.plotting.surface_displays import (
    Cartesian3DDisplayFactory,
    IntensityDisplayFactory,
)
from stoner_measurement.ui.plotting_bridge import LegacyPlotFacade


@pytest.fixture(params=[("cartesian_3d", "xyz"), ("intensity", "xy_intensity")])
def native_host(request, engine, managed_qt_widget):
    display_id, form = request.param
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry(), factory_id=display_id))
    engine.plot_client = host.service
    engine.plot_widget = LegacyPlotFacade(host.service)
    yield host, form
    engine.plot_client = None
    engine.plot_widget = None
    host.service.shutdown()


@pytest.mark.parametrize("command_type", [PlotTraceCommand, PlotPointsCommand])
def test_worker_acquisition_reaches_native_graphics(native_host, engine, qtbot, command_type):
    host, form = native_host
    command = command_type()
    command.plot_form = form
    if command_type is PlotTraceCommand:
        command.new_x_expr, command.fixed_y_expr, command.z_expr = "[0, 2]", "T", "[T, T+2]"
        command.new_x_expr = "[0, 2] if T == 1 else [0.1, 1.9]"
        command.surface_id_expr = "'scan'"
        script = "for T in (1, 3):\n    command.execute()"
    else:
        command.new_x_expr, command.coordinate_y_expr = "H", "T"
        command.z_entries = [{"expr": "H+T", "label": "Signal", "surface_id_expr": "'scan'"}]
        script = "for T in (1, 3):\n    for H in ((0, 2) if T == 1 else (2, 0)):\n        command.execute()"
    engine.add_plugin("plot", command)
    engine._namespace["command"] = command
    errors, results = [], []
    engine.error_output.connect(errors.append)
    host.service.result_ready.connect(results.append)
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script(script)
    assert not errors
    assert all(result.status == ResultStatus.APPLIED for result in results)
    np.testing.assert_array_equal(host.service.data_snapshot("scan").channels["z"], [1, 3, 3, 5])
    host.display.refresh()
    assert len(host.display.export_state().series[0].update.data.channels["z"]) == 4
    if form == "xyz":
        assert any(
            isinstance(item, host.display.canvas.gl.GLScatterPlotItem)
            for item in host.display.canvas.view.items
        )
    else:
        assert len(host.display.canvas.plot.items) == 1


@pytest.mark.parametrize("command_type", [PlotTraceCommand, PlotPointsCommand])
def test_switch_refreshes_existing_config_page_and_retains_saved_bindings(
    engine,
    managed_qt_widget,
    managed_plugin_config_tabs,
    command_type,
):
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry()))
    engine.plot_client = host.service
    engine.plot_widget = LegacyPlotFacade(host.service)
    try:
        command = command_type()
        engine.add_plugin("plot", command)
        pages = dict(managed_plugin_config_tabs(command))
        page = pages["General"]
        combo = page.findChild(QComboBox, "plot_form")
        assert combo.itemData(combo.currentIndex()) == "xy"
        assert host.switch_display("cartesian_3d")
        assert {combo.itemData(i) for i in range(combo.count())} == {"xy", "xyz", "xyz_value"}
        combo.setCurrentIndex(combo.findData("xyz"))
        command.new_x_expr = "H"
        assert host.switch_display("intensity")
        assert combo.currentText() == "XYZ (unsupported)"
        assert command.new_x_expr == "H"
        assert "xy_intensity" in {combo.itemData(i) for i in range(combo.count())}
        assert host.switch_display("cartesian_3d")
        assert combo.currentText() == "XYZ"
        assert dict(command.config_tabs())["General"] is page
    finally:
        engine.plot_client = None
        engine.plot_widget = None
        host.service.shutdown()


def test_idle_replay_and_incompatible_switch_are_transactional(native_host, engine, qtbot):
    host, form = native_host
    factory_type = Cartesian3DDisplayFactory if form == "xyz" else IntensityDisplayFactory
    clone = factory_type()
    clone.factory_id = "compatible"
    host.registry.register(clone)
    command = PlotTraceCommand()
    command.plot_form = form
    command.new_x_expr, command.fixed_y_expr, command.z_expr = "[0, 2]", "T", "[T, T+2]"
    command.surface_id_expr = "'scan'"
    engine.add_plugin("plot", command)
    engine._namespace["command"] = command
    with qtbot.waitSignal(engine.script_finished, timeout=5000):
        engine.run_script("for T in (1, 3):\n    command.execute()")
    original = host.display
    assert host.switch_display("compatible")
    assert host.display is not original
    np.testing.assert_array_equal(
        host.display.export_state().series[0].update.data.channels["z"], [1, 3, 3, 5]
    )
    compatible = host.display
    assert not host.switch_display("cartesian")
    assert host.display is compatible
    assert host.service.apply_now(PlotRequest(ClearPlot())).wait(0).status == ResultStatus.APPLIED
    assert host.switch_display("cartesian")


def test_switch_back_restores_factory_colour_and_view_preferences(native_host):
    host, form = native_host
    factory_id = host.factory_id
    view = (
        {"distance": 8, "azimuth": 70}
        if form == "xyz"
        else {"ranges": [[-3, 3], [-4, 4]], "auto": [False, False]}
    )
    host.display.import_settings({"palette": "inferno", "colour_limits": [-2, 20], "view": view})
    expected = host.display.export_settings()
    assert host.switch_display("cartesian")
    assert host.switch_display(factory_id)
    assert host.display.export_settings() == expected
