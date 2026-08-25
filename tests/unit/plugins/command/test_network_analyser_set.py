"""Focused tests for the one-off network-analyser set command."""

from __future__ import annotations

import numpy as np
import pytest
from qtpy.QtWidgets import QComboBox

from stoner_measurement.instruments import (
    NetworkAnalyserCapabilities,
    NetworkSweep,
    NetworkTraceData,
    SweepType,
    TraceFormat,
)
from stoner_measurement.plugins.command import NetworkAnalyserSetCommand
from stoner_measurement.ui.widgets import SISpinBox


class _FakeNetworkAnalyser:
    def __init__(self) -> None:
        self.configuration = None
        self.frequency = None
        self.power = None
        self.averaging = None
        self.parameters: list[tuple[str, int, int]] = []
        self.disconnected = False

    def get_capabilities(self):
        return NetworkAnalyserCapabilities(
            port_count=2,
            max_channels=4,
            max_traces_per_channel=4,
            frequency_min_hz=3.0e5,
            frequency_max_hz=3.0e9,
            supported_sweep_types=(SweepType.CW,),
            supported_trace_formats=tuple(TraceFormat),
        )

    def set_sweep_configuration(self, configuration, channel):
        self.configuration = (configuration, channel)

    def set_averaging(self, enabled, count, channel):
        self.averaging = (enabled, count, channel)

    def set_measurement_parameter(self, parameter, channel, trace):
        self.parameters.append((parameter, channel, trace))

    def set_cw_frequency(self, value, channel):
        self.frequency = (value, channel)

    def set_source_power(self, value, channel, port=None):
        self.power = (value, channel, port)

    def acquire(self, channel, traces, *, timeout, corrected):
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

    def disconnect(self):
        self.disconnected = True


def test_execute_evaluates_all_stimulus_expressions_and_publishes_outputs(
    monkeypatch, qapp
):
    plugin = NetworkAnalyserSetCommand()
    analyser = _FakeNetworkAnalyser()
    plugin._frequency_hz = "outer.frequency"  # noqa: SLF001
    plugin._power_dbm = "outer.power"  # noqa: SLF001
    plugin._if_bandwidth_hz = "settings.bandwidth"  # noqa: SLF001
    values = {
        "outer.frequency": 2.0e9,
        "outer.power": -15.0,
        "settings.bandwidth": 250.0,
    }

    def evaluate(_plugin, value):
        return values[value] if value in values else float(value)

    monkeypatch.setattr(
        NetworkAnalyserSetCommand,
        "eval_float",
        evaluate,
    )
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.network_analyser_set.connect_point_analyser",
        lambda owner: setattr(owner, "_analyser", analyser),
    )

    plugin.execute()

    configuration, channel = analyser.configuration
    assert channel == 1
    assert configuration.sweep_type is SweepType.CW
    assert configuration.start_hz == pytest.approx(2.0e9)
    assert configuration.if_bandwidth_hz == pytest.approx(250.0)
    assert analyser.frequency == (2.0e9, 1)
    assert analyser.power == (-15.0, 1, None)
    assert analyser.parameters == [("S11", 1, 1), ("S21", 1, 2)]
    assert analyser.disconnected
    assert plugin.get_s_parameter("S11") == pytest.approx(20 * np.log10(2.0))
    assert plugin.reported_value_units()[f"{plugin.instance_name}:S21"] == "dB"


def test_disconnect_runs_when_configuration_fails(monkeypatch, qapp):
    plugin = NetworkAnalyserSetCommand()
    analyser = _FakeNetworkAnalyser()
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.network_analyser_set.connect_point_analyser",
        lambda owner: setattr(owner, "_analyser", analyser),
    )
    monkeypatch.setattr(
        "stoner_measurement.plugins.command.network_analyser_set.configure_point_analyser",
        lambda *_args: (_ for _ in ()).throw(ValueError("bad setup")),
    )

    with pytest.raises(ValueError, match="bad setup"):
        plugin.execute()

    assert analyser.disconnected


def test_configuration_has_expression_inputs_but_no_scan_selector(
    qapp, managed_qt_widget
):
    plugin = NetworkAnalyserSetCommand()
    widget = managed_qt_widget(plugin.config_tabs()[0][1])
    frequency = widget.findChild(SISpinBox, "network_analyser_set_frequency")
    power = widget.findChild(SISpinBox, "network_analyser_set_power")
    bandwidth = widget.findChild(
        SISpinBox, "network_analyser_set_if_bandwidth"
    )

    frequency.setValue("outer.frequency")
    power.setValue("outer.power")
    bandwidth.setValue("settings.bandwidth")

    assert plugin._frequency_hz == "outer.frequency"  # noqa: SLF001
    assert plugin._power_dbm == "outer.power"  # noqa: SLF001
    assert plugin._if_bandwidth_hz == "settings.bandwidth"  # noqa: SLF001
    assert widget.findChild(QComboBox, "network_analyser_state_variable") is None


def test_settings_round_trip_preserves_expressions(qapp):
    plugin = NetworkAnalyserSetCommand()
    plugin._frequency_hz = "outer.frequency"  # noqa: SLF001
    plugin._power_dbm = "outer.power"  # noqa: SLF001
    plugin._if_bandwidth_hz = "settings.bandwidth"  # noqa: SLF001

    restored = NetworkAnalyserSetCommand.from_json(plugin.to_json())

    assert restored._frequency_hz == "outer.frequency"  # noqa: SLF001
    assert restored._power_dbm == "outer.power"  # noqa: SLF001
    assert restored._if_bandwidth_hz == "settings.bandwidth"  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
