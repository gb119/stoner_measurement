"""Motor-angle dependent signals through real workers and the polar display."""

from types import SimpleNamespace

import numpy as np
import pytest
from qtpy.QtCore import QSettings
from qtpy.QtWidgets import QCheckBox, QComboBox, QScrollArea

from stoner_measurement.core.plotting.contracts import PlotRequest
from stoner_measurement.core.plotting.producers import xy_update
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command import PlotPointsCommand, PlotTraceCommand
from stoner_measurement.ui.plotting.host import PlotDisplayHost
from stoner_measurement.ui.plotting.polar import PolarDisplayFactory
from stoner_measurement.ui.plotting.registry import PlotDisplayRegistry
from stoner_measurement.ui.plotting_bridge import LegacyPlotFacade


@pytest.fixture
def host(engine, managed_qt_widget):
    host = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry(), factory_id="polar"))
    engine.plot_client = host.service
    yield host
    engine.shutdown()
    engine.plot_client = None
    host.service.shutdown()


@pytest.mark.parametrize("command_type", [PlotTraceCommand, PlotPointsCommand])
def test_attach_xy_command_to_polar_retains_settings_without_creating_xy_axes(
    host, engine, managed_plugin_config_tabs, command_type
):
    engine.plot_widget = LegacyPlotFacade(host.service)
    command = command_type()
    command.x_axis_name = "motor_axis"
    if command_type is PlotTraceCommand:
        command.y_axis_name = "response_axis"
    else:
        command.y_entries = [{"key": "signal", "y_axis": "response_axis"}]
    original = command.to_json()
    command = BasePlugin.from_json(original)
    axes_before = host.service.axes()
    engine.add_plugin("plot", command)
    assert command.sequence_engine is engine
    assert host.service.axes() == axes_before
    assert command.x_axis_name == "motor_axis"
    assert command.plot_form == "xy"
    page = dict(managed_plugin_config_tabs(command))["General"]
    forms = page.findChild(QComboBox, "plot_form")
    assert "unsupported" in forms.currentText()
    forms.setCurrentIndex(forms.findData("polar"))
    assert command.plot_form == "polar"
    assert command.x_axis_name == "motor_axis"
    assert host.service.axes() == axes_before


@pytest.mark.parametrize("command_type", [PlotTraceCommand, PlotPointsCommand])
def test_generated_worker_commands_use_angle_as_independent_variable(
    host, engine, qtbot, command_type
):
    command = command_type()
    command.plot_form = "polar"
    command.polar_angle_expr = "angles" if command_type is PlotTraceCommand else "motor.position"
    command.polar_radius_expr = (
        "response" if command_type is PlotTraceCommand else "2 + motor.position / 90"
    )
    engine.add_plugin("plot", command)
    engine._namespace.update(
        angles=np.array([0, 90, 180]),
        response=np.array([2, 3, 4]),
        motor=SimpleNamespace(position=0),
    )
    errors = []
    engine.error_output.connect(errors.append)
    code = "\n".join(command.generate_action_code(0, [], lambda *args: []))
    if command_type is PlotPointsCommand:
        code = "for motor.position in (0, 90, 180):\n" + "\n".join(
            "    " + line for line in code.splitlines()
        )
    finished = []
    engine.script_finished.connect(lambda: finished.append(True))
    engine.run_script(code)
    qtbot.waitUntil(lambda: bool(finished or errors), timeout=5000)
    assert not errors
    series = host.export_state().series[0].update
    assert series.binding.x == "angle" and series.binding.y == "radius"
    np.testing.assert_array_equal(series.data.channels["angle"], [0, 90, 180])
    np.testing.assert_array_equal(series.data.channels["radius"], [2, 3, 4])
    x, y = host.display._curves[series.series_id].getData()
    np.testing.assert_allclose(x, [0, 3, 0], atol=1e-14)
    np.testing.assert_allclose(y, [2, 0, -4], atol=1e-14)
    assert series.coordinates.clockwise
    assert series.coordinates.angular_origin == 90


@pytest.mark.parametrize("command_type", [PlotTraceCommand, PlotPointsCommand])
def test_form_controls_persistence_and_unsupported_switch(
    host, engine, managed_plugin_config_tabs, command_type
):
    command = command_type()
    command.plot_form = "polar"
    command.polar_angle_expr, command.polar_radius_expr = "motor.position", "signal"
    engine.add_plugin("plot", command)
    page = dict(managed_plugin_config_tabs(command))["General"]
    forms = page.findChild(QComboBox, "plot_form")
    assert forms.currentText() == "Polar (angle, radius)"
    units = page.findChild(QComboBox, "polar_angular_unit")
    assert units.currentText() == "degrees"
    assert page.findChild(QCheckBox, "polar_clockwise").isChecked()
    units.setCurrentText("radians")
    loaded = BasePlugin.from_json(command.to_json())
    assert loaded.polar_settings == {
        "angular_unit": "radians",
        "angular_origin": np.pi / 2,
        "clockwise": True,
    }
    units.setCurrentText("degrees")
    assert command.polar_settings["angular_origin"] == 90
    assert loaded.polar_angle_expr == "motor.position"
    assert loaded.polar_id_expr == command.polar_id_expr
    assert host.switch_display("cartesian", reset=True)
    assert "unsupported" in forms.currentText()
    assert command.polar_radius_expr == "signal"
    assert host.switch_display("polar", reset=True)
    assert forms.currentText() == "Polar (angle, radius)"


@pytest.mark.parametrize("command_type", [PlotTraceCommand, PlotPointsCommand])
def test_polar_scroll_uses_available_height_without_spreading_controls(
    host, engine, managed_plugin_config_tabs, qapp, command_type
):
    command = command_type()
    command.plot_form = "polar"
    engine.add_plugin("plot", command)
    page = dict(managed_plugin_config_tabs(command))["General"]
    page.resize(520, 700)
    page.show()
    qapp.processEvents()
    scroll = page.findChild(QScrollArea, "polar_options")
    angle = scroll.widget().findChild(QComboBox, "polar_angle_expr")
    radius = scroll.widget().findChild(QComboBox, "polar_radius_expr")
    initial_height = scroll.height()
    initial_spacing = radius.y() - angle.y()
    page.resize(520, 1100)
    qapp.processEvents()
    assert scroll.height() >= initial_height + 350
    assert radius.y() - angle.y() == initial_spacing
    assert angle.y() < 25
    assert scroll.verticalScrollBar().maximum() == 0
    forms = page.findChild(QComboBox, "plot_form")
    forms.setCurrentIndex(forms.findData("xy"))
    qapp.processEvents()
    assert scroll.isHidden()


def test_host_replay_and_incompatible_switch_are_transactional(host):
    from dataclasses import replace

    from stoner_measurement.core.plotting.contracts import (
        AngularUnit,
        CoordinateDescriptor,
        CoordinateSystem,
    )

    # No coordinate conversion is inferred when choosing a different display.
    request = replace(
        xy_update("signal", [0], [2]),
        axes={},
        coordinates=CoordinateDescriptor(CoordinateSystem.POLAR, AngularUnit.DEGREES),
    )
    host.service.apply_now(PlotRequest(request))
    original = host.display
    assert not host.switch_display("cartesian")
    assert host.switch_requires_reset and host.display is original
    clone = PolarDisplayFactory()
    clone.factory_id = "polar_clone"
    host.registry.register(clone)
    assert host.switch_display("polar_clone")
    np.testing.assert_array_equal(host.service.data_snapshot("signal").channels["x"], [0])
    assert host.switch_display("cartesian", reset=True)
    assert not host.export_state().series


def test_polar_factory_and_label_units_persist_on_restart(tmp_path, managed_qt_widget):
    settings = QSettings(str(tmp_path / "polar.ini"), QSettings.Format.IniFormat)
    original = managed_qt_widget(
        PlotDisplayHost(registry=PlotDisplayRegistry(), factory_id="polar", settings=settings)
    )
    original.display.angle_units.setCurrentText("radians")
    original.save_preferences()
    restored = managed_qt_widget(PlotDisplayHost(registry=PlotDisplayRegistry(), settings=settings))
    assert restored.factory_id == "polar"
    assert restored.display.angle_units.currentText() == "radians"
    assert not restored.export_state().series


@pytest.mark.parametrize(
    "command_type,angles,radii",
    [
        (PlotTraceCommand, "[0, 90]", "[1]"),
        (PlotTraceCommand, "0", "1"),
        (PlotPointsCommand, "[0]", "1"),
        (PlotPointsCommand, "0", "[1]"),
    ],
)
def test_invalid_polar_shapes_leave_the_plot_empty(host, engine, command_type, angles, radii):
    command = command_type()
    command.plot_form = "polar"
    command.polar_angle_expr, command.polar_radius_expr = angles, radii
    engine.add_plugin("plot", command)
    with pytest.raises(ValueError, match="arrays.*scalars"):
        command.execute()
    assert not host.export_state().series


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
