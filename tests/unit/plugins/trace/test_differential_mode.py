"""Differential-mode behaviour shared by the Keithley trace plugins."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from qtpy.QtWidgets import QCheckBox

from stoner_measurement.plugins.trace._differential import (
    modulate_current_sweep,
    reduce_differential_readings,
)
from stoner_measurement.plugins.trace.k6221_2182a import Keithley6221_2182APlugin
from stoner_measurement.plugins.trace.keithley_2400 import (
    Keithley2400SweepPlugin,
    SweepSourceMode,
)
from stoner_measurement.ui.widgets import SISpinBox


def test_modulate_current_sweep_alternates_around_nominal_values():
    nominal = np.array([0.0, 1.0, 2.0, 3.0])

    actual = modulate_current_sweep(nominal, 0.1)

    np.testing.assert_allclose(actual, [0.1, 0.9, 2.1, 2.9])


def test_reduce_differential_readings_uses_requested_formulas():
    result = reduce_differential_readings(
        np.array([0.0, 1.0, 2.0, 3.0]),
        np.array([1.0, -1.0, 1.0, -1.0]),
        0.1,
        conductance=False,
    )

    np.testing.assert_allclose(result.current, [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_allclose(result.voltage, [0.0, 0.0, 0.0, 0.0])
    np.testing.assert_allclose(result.change_voltage, [1.0, 1.0, 1.0, 1.0])
    np.testing.assert_allclose(result.response, [10.0, 10.0, 10.0, 10.0])
    np.testing.assert_allclose(result.power, [0.1, 0.1, 0.1, 0.1])


def test_reduce_differential_readings_can_report_conductance():
    result = reduce_differential_readings(
        np.array([0.0, 1.0, 2.0]),
        np.array([1.0, -1.0, 1.0]),
        0.1,
        conductance=True,
    )

    np.testing.assert_allclose(result.response, [0.1, 0.1, 0.1])


def test_reduce_differential_readings_estimates_endpoint_voltages():
    result = reduce_differential_readings(
        np.array([0.0, 1.0, 2.0, 3.0]),
        np.array([11.0, 19.0, 31.0, 39.0]),
        0.1,
        conductance=False,
    )

    np.testing.assert_allclose(result.voltage, [10.0, 20.0, 30.0, 40.0])
    np.testing.assert_allclose(result.change_voltage, [1.0, 1.0, 1.0, 1.0])


@pytest.mark.parametrize(
    "plugin_class",
    [Keithley2400SweepPlugin, Keithley6221_2182APlugin],
)
def test_json_only_includes_differential_details_when_enabled(qapp, plugin_class):
    plugin = plugin_class()

    disabled = plugin.to_json()
    assert disabled["differential_mode"] is False
    assert "differential_conductance" not in disabled
    assert "delta_current" not in disabled

    plugin._differential_mode = True
    plugin._differential_conductance = True
    plugin._delta_current = 2e-6
    enabled = plugin.to_json()
    assert enabled["differential_conductance"] is True
    assert enabled["delta_current"] == pytest.approx(2e-6)

    restored = plugin_class()
    restored._restore_from_json(enabled)
    assert restored._differential_mode is True
    assert restored._differential_conductance is True
    assert restored._delta_current == pytest.approx(2e-6)


@pytest.mark.parametrize(
    "plugin_class",
    [Keithley2400SweepPlugin, Keithley6221_2182APlugin],
)
def test_configuration_page_exposes_differential_controls(
    qapp, managed_qt_widget, plugin_class
):
    plugin = plugin_class()
    widget = managed_qt_widget(plugin._plugin_config_tabs())

    enabled = widget.findChild(QCheckBox, "differential_mode")
    conductance = widget.findChild(QCheckBox, "differential_conductance")
    delta_current = widget.findChild(SISpinBox, "delta_current")

    assert enabled is not None
    assert conductance is not None and not conductance.isEnabled()
    assert delta_current is not None and not delta_current.isEnabled()
    enabled.setChecked(True)
    assert conductance.isEnabled()
    assert delta_current.isEnabled()


def test_6221_configure_programs_modulated_sweep(qapp):
    plugin = Keithley6221_2182APlugin()
    plugin._k6221 = MagicMock()
    plugin._k2182a = MagicMock()
    plugin.scan_generator = MagicMock()
    plugin.scan_generator.generate.return_value = np.array([0.0, 1.0, 2.0])
    plugin._differential_mode = True
    plugin._delta_current = 0.1

    plugin.configure()

    programmed = plugin._k6221.configure_custom_sweep.call_args.args[0]
    np.testing.assert_allclose(programmed, [0.1, 0.9, 2.1])
    np.testing.assert_allclose(plugin._nominal_sweep_values, [0.0, 1.0, 2.0])


def test_2400_configure_programs_modulated_sweep(qapp):
    plugin = Keithley2400SweepPlugin()
    plugin._smu = MagicMock()
    plugin.scan_generator = MagicMock()
    plugin.scan_generator.generate.return_value = [0.0, 1.0, 2.0]
    plugin._differential_mode = True
    plugin._delta_current = 0.1

    plugin.configure()

    config = plugin._smu.configure_source_sweep.call_args.args[0]
    np.testing.assert_allclose(config.values, [0.1, 0.9, 2.1])
    np.testing.assert_allclose(plugin._nominal_sweep_values, [0.0, 1.0, 2.0])


def test_2400_differential_mode_rejects_voltage_source_sweep(qapp):
    plugin = Keithley2400SweepPlugin()
    plugin._smu = MagicMock()
    plugin.scan_generator = MagicMock()
    plugin.scan_generator.generate.return_value = [0.0, 1.0, 2.0]
    plugin._source_mode = SweepSourceMode.VOLTAGE
    plugin._differential_mode = True

    with pytest.raises(ValueError, match="current-source sweep"):
        plugin.configure()


def test_6221_measure_reduces_primary_and_secondary_readings(qapp):
    plugin = Keithley6221_2182APlugin()
    plugin._differential_mode = True
    plugin._delta_current = 0.1
    plugin._nominal_sweep_values = np.array([0.0, 1.0, 2.0, 3.0])
    plugin._sweep_values = np.array([0.1, 0.9, 2.1, 2.9])
    plugin._secondary_enabled = True
    plugin._secondary_voltages = (2.0, -2.0, 2.0, -2.0)

    pairs = list(zip(plugin._sweep_values, (1.0, -1.0, 1.0, -1.0), strict=True))
    with patch.object(plugin, "_acquire_pairs", return_value=pairs):
        trace = plugin.measure({})["IV"]

    np.testing.assert_allclose(trace.x, [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_allclose(trace.df["R"], [10.0, 10.0, 10.0, 10.0])
    np.testing.assert_allclose(trace.df["P"], [0.1, 0.1, 0.1, 0.1])
    np.testing.assert_allclose(trace.df["secondary R"], [20.0, 20.0, 20.0, 20.0])
    np.testing.assert_allclose(trace.df["secondary P"], [0.2, 0.2, 0.2, 0.2])


def test_2400_measure_reports_differential_conductance(qapp):
    plugin = Keithley2400SweepPlugin()
    plugin._differential_mode = True
    plugin._differential_conductance = True
    plugin._delta_current = 0.1
    plugin._nominal_sweep_values = (0.0, 1.0, 2.0, 3.0)
    plugin._sweep_values = (0.1, 0.9, 2.1, 2.9)
    records = tuple(
        SimpleNamespace(voltage=v, current=i, resistance=None, time=t)
        for i, v, t in zip(
            plugin._sweep_values,
            (1.0, -1.0, 1.0, -1.0),
            (0.0, 1.0, 2.0, 3.0),
            strict=True,
        )
    )

    with patch.object(plugin, "_acquire_buffer_records", return_value=records):
        trace = plugin.measure({})["IV"]

    np.testing.assert_allclose(trace.x, [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_allclose(trace.df["Current"], [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_allclose(trace.df["Conductance"], [0.1, 0.1, 0.1, 0.1])
    assert trace.units["Conductance"] == "S"
    np.testing.assert_allclose(trace.df["Power"], [0.1, 0.1, 0.1, 0.1])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
