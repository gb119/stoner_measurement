"""Focused tests for the network-analyser trace plugin."""

from __future__ import annotations

import numpy as np
import pytest
from qtpy.QtWidgets import QComboBox, QWidget

from stoner_measurement.instruments import (
    NetworkAnalyserCapabilities,
    NetworkSweep,
    NetworkTraceData,
    SweepType,
    TraceFormat,
)
from stoner_measurement.plugins.trace import (
    NetworkAnalyserSweepVariable,
    NetworkAnalyserTracePlugin,
)
from stoner_measurement.scan import NetworkAnalyserScanGenerator, RampMode


class _FakeNetworkAnalyser:
    def __init__(self) -> None:
        self.configuration = None
        self.cw_frequency = None
        self.power_range = None
        self.averaging = None
        self.parameters: list[tuple[str, int, int]] = []

    def get_capabilities(self):
        return NetworkAnalyserCapabilities(
            port_count=2,
            max_channels=4,
            max_traces_per_channel=4,
            frequency_min_hz=1.0e5,
            frequency_max_hz=3.0e9,
            supported_sweep_types=(SweepType.LINEAR, SweepType.LOGARITHMIC, SweepType.POWER),
            supported_trace_formats=tuple(TraceFormat),
            has_power_sweep=True,
        )

    def set_sweep_configuration(self, configuration, channel):
        self.configuration = (configuration, channel)

    def set_cw_frequency(self, value, channel):
        self.cw_frequency = (value, channel)

    def set_power_sweep_range(self, start, stop, channel):
        self.power_range = (start, stop, channel)

    def set_averaging(self, enabled, count, channel):
        self.averaging = (enabled, count, channel)

    def set_measurement_parameter(self, parameter, channel, trace):
        self.parameters.append((parameter, channel, trace))

    def acquire(self, channel, traces, *, timeout, corrected):
        stimulus = np.array([1.0, 2.0, 3.0])
        results = tuple(
            NetworkTraceData(
                channel=channel,
                trace=trace,
                parameter=("S11", "S21")[index],
                stimulus=stimulus,
                values=np.array([1 + index * 1j, 2 + index * 1j, 3 + index * 1j]),
                corrected=corrected,
            )
            for index, trace in enumerate(traces)
        )
        assert timeout == pytest.approx(60.0)
        return NetworkSweep(results)


def _configured_plugin(qapp):
    plugin = NetworkAnalyserTracePlugin()
    plugin.scan_generator = NetworkAnalyserScanGenerator(
        start=1.0,
        end=3.0,
        num_points=3,
        parent=plugin,
    )
    analyser = _FakeNetworkAnalyser()
    plugin._analyser = analyser  # noqa: SLF001
    return plugin, analyser


def test_frequency_configuration_and_complex_trace_output(qapp):
    plugin, analyser = _configured_plugin(qapp)
    plugin.scan_generator.mode = RampMode.EXPONENTIAL

    plugin.configure()
    result = plugin.measure({})["S parameters"]

    configuration, channel = analyser.configuration
    assert channel == 1
    assert configuration.sweep_type is SweepType.LOGARITHMIC
    assert configuration.source_power_dbm == pytest.approx(-10.0)
    assert analyser.parameters == [("S11", 1, 1), ("S21", 1, 2)]
    assert list(result.df.columns) == ["x", "S11", "S21"]
    assert result.names["x"] == "Frequency"
    assert result.units["x"] == "Hz"
    np.testing.assert_allclose(
        result.df["S21"], 20 * np.log10(np.abs([1 + 1j, 2 + 1j, 3 + 1j]))
    )
    assert result.units["S21"] == "dB"


def test_phase_representation_returns_plottable_float_columns(qapp):
    plugin, _ = _configured_plugin(qapp)
    plugin._output_format = TraceFormat.PHASE  # noqa: SLF001

    plugin.configure()
    result = plugin.measure({})["S parameters"]

    assert result.df["S21"].dtype.kind == "f"
    np.testing.assert_allclose(result.df["S21"], [45.0, np.degrees(np.arctan(0.5)), np.degrees(np.arctan(1 / 3))])
    assert result.units["S21"] == "°"


def test_power_configuration_uses_fixed_frequency_and_linear_range(qapp):
    plugin, analyser = _configured_plugin(qapp)
    plugin._sweep_variable = NetworkAnalyserSweepVariable.POWER  # noqa: SLF001
    plugin._fixed_frequency_hz = 2.0e9  # noqa: SLF001
    plugin._sync_generator_mode()  # noqa: SLF001

    plugin.configure()

    configuration, _ = analyser.configuration
    assert configuration.sweep_type is SweepType.POWER
    assert analyser.cw_frequency == (2.0e9, 1)
    assert analyser.power_range == (1.0, 3.0, 1)
    assert plugin.scan_generator.mode is RampMode.LINEAR


def test_settings_toggle_complementary_fixed_control_and_scan_spacing(
    qapp, managed_qt_widget
):
    plugin = NetworkAnalyserTracePlugin()
    tabs = plugin.config_tabs()
    managed_qt_widget(tabs[0][1])
    settings = managed_qt_widget(tabs[1][1])
    variable = settings.findChild(QComboBox, "network_analyser_sweep_variable")
    fixed_power = settings.findChild(QWidget, "network_analyser_fixed_power")
    fixed_frequency = settings.findChild(QWidget, "network_analyser_fixed_frequency")
    spacing = tabs[0][1].findChild(QComboBox, "network_analyser_scan_spacing")

    assert fixed_power.isVisibleTo(settings)
    assert not fixed_frequency.isVisibleTo(settings)
    assert spacing.isEnabled()
    variable.setCurrentIndex(variable.findData(NetworkAnalyserSweepVariable.POWER))
    assert not fixed_power.isVisibleTo(settings)
    assert fixed_frequency.isVisibleTo(settings)
    assert not spacing.isEnabled()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
