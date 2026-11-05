"""Pulse Delta trace persistence, acquisition, lifecycle and timing controls."""

from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QLabel

from stoner_measurement.instruments.keithley.k6221 import Keithley6221
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace import (
    Keithley6221PulseDeltaPlugin,
    SourceRangeMode,
    TraceStatus,
)
from stoner_measurement.plugins.trace.k6221_pulse_delta import _PulsePreview
from stoner_measurement.ui.widgets import SISpinBox


@pytest.fixture
def plugin(qapp):
    instance = Keithley6221PulseDeltaPlugin()
    instance._k6221 = MagicMock(spec=Keithley6221)
    instance._k6221.validate_pulse_delta_sweep.side_effect = Keithley6221.validate_pulse_delta_sweep
    instance.scan_generator = MagicMock()
    instance.scan_generator.generate.return_value = [0.001, -0.002, 0.0]
    instance._k6221.pulse_delta_buffer_count.return_value = 3
    instance._k6221.read_pulse_delta_buffer.return_value = (0.01, -0.04, 0.0)
    return instance


def test_round_trip_preserves_expressions_and_excludes_dc_settings(qapp):
    instance = Keithley6221PulseDeltaPlugin()
    instance._pulse_width = "pulse_width"
    instance._pulse_source_delay = 25e-6
    instance._pulse_period = "cycle_time"
    instance._low_measurements = 1
    instance._preview_mains_frequency = 60
    instance._source_range_mode = SourceRangeMode.FIXED
    data = instance.to_json()
    restored = BasePlugin.from_json(data)
    assert restored.to_json() == data
    assert restored._pulse_width == "pulse_width"
    assert restored._low_measurements == 1
    assert (
        not {"nplc", "secondary_nanovoltmeter", "connection_mode"}
        & data.keys()
    )


def test_configure_resolves_expressions_and_arms_native_mode(plugin):
    plugin.eval_float = lambda value: {"width": 500e-6}.get(value, value)
    plugin._pulse_width = "width"
    plugin.configure()
    source = plugin._k6221
    source.configure_pulse_delta_sweep.assert_called_once_with(
        (0.001, -0.002, 0.0),
        width=500e-6,
        source_delay=16e-6,
        period=0.1,
        low_measurements=2,
    )
    source.prepare_pulse_delta_buffer.assert_called_once_with(3)
    source.pulse_delta_arm.assert_called_once()
    source.sweep_arm.assert_not_called()
    assert plugin.status is TraceStatus.IDLE


def test_fixed_source_range_is_selected_for_the_pulse_sweep(plugin):
    plugin._source_range_mode = SourceRangeMode.FIXED
    plugin._source_range = 0.002
    plugin.configure()
    plugin._k6221.set_fixed_range.assert_called_once_with(0.002)
    plugin._k6221.set_sweep_range_mode.assert_called_once_with("FIXED")


def test_repeated_measurements_return_corrected_trace_and_rearm(plugin):
    plugin.configure()
    source = plugin._k6221
    for _ in range(2):
        trace = plugin.measure({})["IV"]
        np.testing.assert_allclose(trace.x, [0.001, -0.002, 0.0])
        np.testing.assert_allclose(trace.df["V"], [0.01, -0.04, 0.0])
        np.testing.assert_allclose(trace.df["R"], [10, 20, np.nan])
        np.testing.assert_allclose(trace.df["P"], [1e-5, 8e-5, 0])
    assert source.pulse_delta_arm.call_count == 2
    assert source.prepare_pulse_delta_buffer.call_count == 2
    assert source.sweep_abort.call_count == 3
    assert source.sweep_init.call_count == 2


def test_timeout_aborts_and_removes_previous_data(plugin, monkeypatch):
    plugin.configure()
    plugin.measure({})
    plugin._k6221.pulse_delta_buffer_count.return_value = 0
    times = iter([0, 100])
    monkeypatch.setattr(
        "stoner_measurement.plugins.trace.k6221_pulse_delta.time.monotonic", lambda: next(times)
    )
    with pytest.raises(TimeoutError):
        plugin.measure({})
    assert plugin.data == {}
    assert not plugin._pulse_armed
    assert plugin.status is TraceStatus.ERROR


@pytest.mark.parametrize("error", [ValueError("bad buffer"), KeyboardInterrupt()])
def test_read_failures_always_abort(plugin, error):
    plugin.configure()
    plugin._k6221.read_pulse_delta_buffer.side_effect = error
    with pytest.raises(type(error)):
        plugin.measure({})
    assert not plugin._pulse_armed
    assert plugin._k6221.sweep_abort.call_count == 2


def test_invalid_configuration_cannot_reuse_old_sweep(plugin):
    plugin.configure()
    plugin._pulse_width = 1e-6
    with pytest.raises(ValueError, match="Pulse width"):
        plugin.configure()
    with pytest.raises(RuntimeError, match="configure"):
        plugin.measure({})


@pytest.mark.parametrize("field", ["_secondary_enabled"])
def test_unsupported_modes_rejected_before_connection(qapp, field):
    instance = Keithley6221PulseDeltaPlugin()
    setattr(instance, field, True)
    with pytest.raises(ValueError, match="does not support"):
        instance.connect()


def test_disconnect_attempts_close_after_abort_failure_and_propagates(plugin):
    source = plugin._k6221
    source.sweep_abort.side_effect = RuntimeError("abort failed")
    with pytest.raises(RuntimeError, match="abort failed"):
        plugin.disconnect()
    source.disconnect.assert_called_once()
    source.enable_output.assert_called_once_with(False)
    assert plugin.status is TraceStatus.ERROR
    assert plugin._k6221 is None
    plugin.disconnect()


def test_stop_request_aborts_acquisition(plugin):
    plugin.configure()
    stopped = Event()
    stopped.set()
    plugin.sequence_engine = SimpleNamespace(_thread=SimpleNamespace(_stop_event=stopped))
    plugin._k6221.pulse_delta_buffer_count.return_value = 0
    with pytest.raises(RuntimeError, match="stopped"):
        plugin.measure({})
    assert not plugin._pulse_armed
    assert plugin.data == {}


def test_connection_retry_closes_owned_session(qapp, monkeypatch):
    from stoner_measurement.plugins.trace import k6221_pulse_delta as module

    source = MagicMock(spec=Keithley6221)
    transport = MagicMock()
    source.pulse_delta_present.return_value = True
    factory = MagicMock(return_value=transport)
    monkeypatch.setattr(module.GpibTransport, "from_resource_string", factory)
    monkeypatch.setattr(module, "Keithley6221", MagicMock(return_value=source))
    instance = module.Keithley6221PulseDeltaPlugin()
    instance.connect()
    instance.connect()
    source.disconnect.assert_called_once()
    assert factory.call_count == 2
    assert instance._k2182a is None
    instance.disconnect()


def test_missing_meter_closes_partial_connection(qapp, monkeypatch):
    from stoner_measurement.plugins.trace import k6221_pulse_delta as module

    transport = MagicMock()
    source = MagicMock(spec=Keithley6221)
    source.pulse_delta_present.return_value = False
    monkeypatch.setattr(
        module.GpibTransport, "from_resource_string", MagicMock(return_value=transport)
    )
    monkeypatch.setattr(module, "Keithley6221", MagicMock(return_value=source))
    instance = module.Keithley6221PulseDeltaPlugin()
    with pytest.raises(RuntimeError, match="compatible 2182A"):
        instance.connect()
    transport.close.assert_called_once()
    assert instance._k6221 is None
    assert instance.status is TraceStatus.ERROR


def test_settings_controls_preview_and_about(qapp, managed_plugin_config_tabs):
    instance = Keithley6221PulseDeltaPlugin()
    tabs = dict(managed_plugin_config_tabs(instance))
    settings = tabs["Settings"]
    assert set(tabs) == {"Scan", "Settings", "About"}
    width = settings.findChild(SISpinBox, "pulse_width")
    width.setValue(500e-6)
    assert instance._pulse_width == pytest.approx(500e-6)
    preview = settings.findChild(_PulsePreview)
    assert preview.cycle_timing().duty_cycle == pytest.approx(0.5)
    mains = settings.findChild(QComboBox, "preview_mains_frequency")
    mains.setCurrentIndex(mains.findData(60))
    assert preview.cycle_timing().before_high == pytest.approx(1 / 60)
    period = settings.findChild(SISpinBox, "pulse_period")
    period.setValue("cycle_time")
    assert instance._pulse_period == "cycle_time"
    low = settings.findChild(QComboBox, "low_measurements")
    low.setCurrentIndex(low.findData(1))
    assert instance._low_measurements == 1
    fixed_range = settings.findChild(SISpinBox, "source_range")
    assert not fixed_range.isEnabled()
    ranging = settings.findChild(QComboBox, "source_range_mode")
    ranging.setCurrentIndex(ranging.findData(SourceRangeMode.FIXED))
    assert fixed_range.isEnabled()
    differential = settings.findChild(QCheckBox, "differential_mode")
    delta = settings.findChild(SISpinBox, "delta_current")
    conductance = settings.findChild(QCheckBox, "differential_conductance")
    assert not delta.isEnabled()
    assert not conductance.isEnabled()
    differential.setChecked(True)
    assert delta.isEnabled() and conductance.isEnabled()
    delta.setValue("delta_i")
    conductance.setChecked(True)
    restored = BasePlugin.from_json(instance.to_json())
    assert restored._differential_mode
    assert restored._differential_conductance
    assert restored._delta_current == "delta_i"
    assert not preview.grab().isNull()
    assert "Pulse Delta" in instance._about_html()
    assert "secondary_nplc" not in {
        widget.objectName() for widget in settings.findChildren(SISpinBox)
    }


@pytest.mark.parametrize(
    "mains,before,after", [(50, 0.02, 0.0795), (60, 1 / 60, 0.0828333333333333)]
)
def test_cycle_feedback_includes_mains_delay_and_low_tail(
    qapp, managed_plugin_config_tabs, mains, before, after
):
    instance = Keithley6221PulseDeltaPlugin()
    instance._pulse_width = 500e-6
    instance._preview_mains_frequency = mains
    preview = dict(managed_plugin_config_tabs(instance))["Settings"].findChild(_PulsePreview)
    timing = preview.cycle_timing()
    assert timing.before_high == pytest.approx(before)
    assert timing.after_high == pytest.approx(after)
    assert timing.duty_cycle == pytest.approx(0.5)
    assert timing.falling_edge_to_v3 == pytest.approx(before + 16e-6 - 500e-6)
    instance._low_measurements = 1
    assert preview.cycle_timing() == timing  # Omitting V3 does not shorten the cycle.
    instance._pulse_period = 0.2
    assert preview.cycle_timing().duty_cycle == pytest.approx(0.25)
    assert preview.cycle_timing().after_high == pytest.approx(after + 0.1)


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("_pulse_period", 0.03, "Cycle too short"),
        ("_pulse_source_delay", 0.002, "must be shorter"),
        ("_pulse_width", 0.025, "50 us and 12 ms"),
        ("_pulse_period", "cycle_time", "expressions"),
        ("_pulse_width", float("nan"), "finite"),
    ],
)
def test_preview_reports_unavailable_or_invalid_timing(
    qapp, managed_plugin_config_tabs, field, value, message
):
    instance = Keithley6221PulseDeltaPlugin()
    setattr(instance, field, value)
    preview = dict(managed_plugin_config_tabs(instance))["Settings"].findChild(_PulsePreview)
    with pytest.raises(ValueError, match=message):
        preview.cycle_timing()
    assert not preview.grab().isNull()


@pytest.mark.parametrize("conductance", [False, True])
def test_differential_pulses_reduce_corrected_voltages(plugin, conductance):
    plugin.scan_generator.generate.return_value = [-0.002, -0.001, 0, 0.001, 0.002]
    plugin._differential_mode = True
    plugin._differential_conductance = conductance
    plugin._delta_current = "delta_i"
    plugin.eval_float = lambda value: 0.0001 if value == "delta_i" else float(value)
    plugin.configure()
    source = plugin._k6221
    np.testing.assert_allclose(
        source.configure_pulse_delta_sweep.call_args.args[0],
        [-0.0019, -0.0011, 0.0001, 0.0009, 0.0021],
    )
    source.pulse_delta_buffer_count.return_value = 5
    source.read_pulse_delta_buffer.return_value = [-0.019, -0.011, 0.001, 0.009, 0.021]
    for _ in range(2):
        trace = plugin.measure({})["IV"]
        np.testing.assert_allclose(trace.x, [-0.002, -0.001, 0, 0.001, 0.002])
        np.testing.assert_allclose(trace.df["V"], [-0.02, -0.01, 0, 0.01, 0.02], atol=1e-16)
        np.testing.assert_allclose(trace.df["G" if conductance else "R"], 0.1 if conductance else 10)
        np.testing.assert_allclose(trace.df["P"], 1e-7)


@pytest.mark.parametrize(
    "currents,delta",
    [
        ([0, 0.001], 1e-4),
        ([0, 0.001, 0.002], 0),
        ([0, 0.001, 0.002], float("nan")),
        ([0.105, 0, -0.1], 0.001),
    ],
)
def test_invalid_differential_list_is_rejected_before_programming(plugin, currents, delta):
    plugin._differential_mode = True
    plugin._delta_current = delta
    plugin.scan_generator.generate.return_value = currents
    with pytest.raises(ValueError):
        plugin.configure()
    plugin._k6221.configure_pulse_delta_sweep.assert_not_called()
    assert plugin._sweep_values is None


def test_old_pulse_settings_restore_without_differential_mode(qapp):
    instance = Keithley6221PulseDeltaPlugin()
    data = instance.to_json()
    for key in ("differential_mode", "differential_conductance", "delta_current"):
        data.pop(key)
    restored = BasePlugin.from_json(data)
    assert not restored._differential_mode


def test_timing_feedback_explains_invalid_delay_and_recovers(qapp, managed_plugin_config_tabs):
    instance = Keithley6221PulseDeltaPlugin()
    settings = dict(managed_plugin_config_tabs(instance))["Settings"]
    width = settings.findChild(SISpinBox, "pulse_width")
    delay = settings.findChild(SISpinBox, "pulse_source_delay")
    feedback = settings.findChild(QLabel, "pulse_timing_feedback")
    width.setValue(0.025)
    assert width.value() == pytest.approx(0.012)
    width.setValue(110e-6)
    delay.setValue(0.005)
    assert "Invalid pulse timing" in feedback.text()
    assert "5 ms" in feedback.text()
    assert "must be shorter" in feedback.text()
    width.setValue(0.012)
    assert "Invalid" not in feedback.text()
    assert settings.findChild(_PulsePreview).cycle_timing().delay == pytest.approx(0.005)
    width.setValue("pulse_width")
    assert "Preview unavailable" in feedback.text()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
