"""Focused tests for direct network-analyser point scans."""

from __future__ import annotations

import numpy as np
import pytest
from qtpy.QtWidgets import QCheckBox, QComboBox, QGroupBox

from stoner_measurement.instruments import (
    NetworkAnalyserCapabilities,
    NetworkSweep,
    NetworkTraceData,
    SweepType,
    TraceFormat,
)
from stoner_measurement.plugins._network_analyser_support import (
    NetworkAnalyserModel,
    NetworkAnalyserSweepVariable,
)
from stoner_measurement.plugins.state_scan import NetworkAnalyserPointScanPlugin
from stoner_measurement.ui.widgets import SISpinBox


class _FakeNetworkAnalyser:
    def __init__(self) -> None:
        self.cw_frequencies: list[tuple[float, int]] = []
        self.powers: list[tuple[float, int, int | None]] = []
        self.pulse_states: list[tuple[bool, int, int]] = []
        self.disconnected = False

    def get_capabilities(self):
        return NetworkAnalyserCapabilities(
            port_count=2,
            max_channels=4,
            max_traces_per_channel=4,
            frequency_min_hz=3.0e5,
            frequency_max_hz=26.5e9,
            supported_sweep_types=(SweepType.CW,),
            supported_trace_formats=tuple(TraceFormat),
        )

    def set_cw_frequency(self, value, channel):
        self.cw_frequencies.append((value, channel))

    def set_source_power(self, value, channel, port=None):
        self.powers.append((value, channel, port))

    def acquire(self, channel, traces, *, timeout, corrected):
        assert timeout == pytest.approx(60.0)
        assert corrected
        return NetworkSweep(
            tuple(
                NetworkTraceData(
                    channel=channel,
                    trace=trace,
                    parameter=("S11", "S21")[index],
                    stimulus=np.array([1.0, 1.0]),
                    values=np.array([1.0 + index * 1.0j, 3.0 + index * 1.0j]),
                    corrected=corrected,
                )
                for index, trace in enumerate(traces)
            )
        )

    def set_external_pulse_modulation(self, enabled, channel, port):
        self.pulse_states.append((enabled, channel, port))

    def disconnect(self):
        self.disconnected = True


def test_frequency_point_reevaluates_fixed_power_expression(monkeypatch, qapp):
    plugin = NetworkAnalyserPointScanPlugin()
    analyser = _FakeNetworkAnalyser()
    plugin._analyser = analyser  # noqa: SLF001
    plugin._fixed_power_dbm = "outer.power"  # noqa: SLF001
    outer = {"power": -20.0}

    def evaluate(_plugin, value):
        return outer["power"] if value == "outer.power" else float(value)

    monkeypatch.setattr(NetworkAnalyserPointScanPlugin, "eval_float", evaluate)

    plugin.set_state(1.0e9)
    outer["power"] = -15.0
    plugin.set_state(2.0e9)

    assert analyser.cw_frequencies == [(1.0e9, 1), (2.0e9, 1)]
    assert analyser.powers == [(-20.0, 1, None), (-15.0, 1, None)]
    assert plugin.get_s_parameter("S11") == pytest.approx(20 * np.log10(2.0))
    assert plugin.get_s_parameter("S21") == pytest.approx(20 * np.log10(abs(2 + 1j)))
    assert plugin.reported_value_units()[f"{plugin.instance_name}:Source power"] == "dBm"


def test_power_point_reevaluates_fixed_frequency_expression(monkeypatch, qapp):
    plugin = NetworkAnalyserPointScanPlugin()
    analyser = _FakeNetworkAnalyser()
    plugin._analyser = analyser  # noqa: SLF001
    plugin._scan_variable = NetworkAnalyserSweepVariable.POWER  # noqa: SLF001
    plugin._fixed_frequency_hz = "outer.frequency"  # noqa: SLF001
    outer = {"frequency": 1.0e9}

    def evaluate(_plugin, value):
        return outer["frequency"] if value == "outer.frequency" else float(value)

    monkeypatch.setattr(NetworkAnalyserPointScanPlugin, "eval_float", evaluate)

    plugin.set_state(-20.0)
    outer["frequency"] = 2.0e9
    plugin.set_state(-10.0)

    assert analyser.powers == [(-20.0, 1, None), (-10.0, 1, None)]
    assert analyser.cw_frequencies == [(1.0e9, 1), (2.0e9, 1)]


def test_disconnect_restores_gate_before_releasing_transport(qapp):
    plugin = NetworkAnalyserPointScanPlugin()
    analyser = _FakeNetworkAnalyser()
    plugin._model = NetworkAnalyserModel.N5222A  # noqa: SLF001
    plugin._external_pulse_modulation = True  # noqa: SLF001
    plugin._pulse_source_port = 2  # noqa: SLF001
    plugin._analyser = analyser  # noqa: SLF001

    plugin.disconnect()

    assert analyser.pulse_states == [(False, 1, 2)]
    assert analyser.disconnected


def test_settings_use_expression_fixed_value_and_model_gated_modulation(
    qapp, managed_qt_widget
):
    plugin = NetworkAnalyserPointScanPlugin()
    settings = managed_qt_widget(plugin.config_tabs()[2][1])
    fixed = settings.findChild(SISpinBox, "network_analyser_state_fixed_value")
    variable = settings.findChild(QComboBox, "network_analyser_state_variable")
    model = settings.findChild(QComboBox, "network_analyser_state_model")
    modulation = settings.findChild(QGroupBox, "network_analyser_state_modulation")
    pulse = settings.findChild(
        QCheckBox, "network_analyser_state_external_pulse"
    )

    fixed.setValue("outer.power")
    assert fixed.value() == "outer.power"
    assert plugin._fixed_power_dbm == "outer.power"  # noqa: SLF001
    assert fixed.opts["suffix"] == "dBm"
    assert not modulation.isEnabled()

    variable.setCurrentIndex(variable.findData(NetworkAnalyserSweepVariable.POWER))
    assert fixed.opts["suffix"] == "Hz"
    model.setCurrentIndex(model.findData(NetworkAnalyserModel.N5222A))
    assert modulation.isEnabled()
    assert "TTL" in pulse.toolTip()
    assert "not analogue" in pulse.toolTip()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
