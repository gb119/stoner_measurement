"""Behaviour tests for point-by-point DAQmx scans."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.state_scan.daqmx import (
    DaqmxPointScanPlugin,
    DaqmxPointScanSettingsWidget,
)
from stoner_measurement.ui.widgets import (
    DaqmxInputTrigger,
    DaqmxInputTriggerMode,
    DaqmxOutputTrigger,
    DaqmxSelectionMode,
    DaqmxTaskDefinition,
    DaqmxTaskKind,
)


def _physical_definition(kind: DaqmxTaskKind, *channels: str) -> DaqmxTaskDefinition:
    return DaqmxTaskDefinition(
        task_kind=kind,
        selection_mode=DaqmxSelectionMode.PHYSICAL_CHANNELS,
        device="Dev1",
        physical_channels=channels,
    )


@dataclass
class _Task:
    kind: DaqmxTaskKind
    channel_names: tuple[str, ...]
    role: str


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.read_values = np.array([[1.0, 3.0, 5.0, 7.0], [10.0, 12.0, 14.0, 16.0]])

    def create_task(self, definition):
        names = definition.physical_channels or definition.global_channels
        role = (
            "acquisition" if definition.task_kind is DaqmxTaskKind.ACQUISITION else "point_output"
        )
        task = _Task(definition.task_kind, tuple(names), role)
        self.calls.append(("create", role))
        return task

    def create_digital_output_task(self, line):
        task = _Task(DaqmxTaskKind.OUTPUT, (line,), "trigger_output")
        self.calls.append(("create", "trigger_output", line))
        return task

    def verify_task(self, task, kind):
        assert task.kind is kind
        self.calls.append(("verify", task.role))

    def prepare_for_configuration(self, task):
        self.calls.append(("prepare", task.role))

    def configure_finite_timing(self, task, rate, samples, *, source=""):
        self.calls.append(("timing", task.role, rate, samples, source))

    def configure_input_start_trigger(self, task, trigger):
        self.calls.append(("input_trigger", task.role, trigger.mode, trigger.terminal))

    def input_sample_clock_source(self, task):
        assert task.role == "acquisition"
        return "/Dev1/ai/SampleClock"

    def configure_output_start_from_input(self, output_task, input_task):
        assert input_task.role == "acquisition"
        self.calls.append(("output_start", output_task.role))
        return "/Dev1/ai/StartTrigger"

    def write_output(self, task, values):
        self.calls.append(("write", task.role, tuple(values)))

    def commit_task(self, task):
        self.calls.append(("commit", task.role))

    def channel_names(self, task):
        return task.channel_names

    def start(self, task):
        self.calls.append(("start", task.role))

    def read(self, task, samples, timeout):
        self.calls.append(("read", task.role, samples, timeout))
        return self.read_values.copy()

    def wait_until_done(self, task, timeout):
        self.calls.append(("wait", task.role, timeout))

    def stop(self, task):
        self.calls.append(("stop", task.role))

    def close(self, task):
        self.calls.append(("close", task.role))


def _configured_plugin(runtime: _FakeRuntime) -> DaqmxPointScanPlugin:
    plugin = DaqmxPointScanPlugin(runtime_factory=lambda: runtime)
    plugin._acquisition_definition = _physical_definition(  # noqa: SLF001
        DaqmxTaskKind.ACQUISITION, "Dev1/ai0", "Dev1/ai1"
    )
    plugin._output_definition = _physical_definition(  # noqa: SLF001
        DaqmxTaskKind.OUTPUT, "Dev1/ao0"
    )
    plugin._output_enabled = True  # noqa: SLF001
    plugin._sample_rate_hz = 2000.0  # noqa: SLF001
    plugin._oversampling = 4  # noqa: SLF001
    plugin._input_trigger = DaqmxInputTrigger(  # noqa: SLF001
        mode=DaqmxInputTriggerMode.DIGITAL, terminal="/Dev1/PFI0"
    )
    plugin._output_trigger = DaqmxOutputTrigger(  # noqa: SLF001
        enabled=True,
        line="Dev1/port0/line0",
        phase_angle=0.0,
        delay=0.0,
        high_time=0.0005,
        low_time=0.0005,
    )
    return plugin


def test_each_point_generates_once_and_reports_mean_and_standard_deviation(qapp):
    runtime = _FakeRuntime()
    plugin = _configured_plugin(runtime)

    plugin.connect()
    plugin.configure()
    plugin.set_state(2.5)

    assert ("timing", "acquisition", 2000.0, 4, "") in runtime.calls
    assert (
        "timing",
        "point_output",
        2000.0,
        4,
        "/Dev1/ai/SampleClock",
    ) in runtime.calls
    assert (
        "write",
        "point_output",
        (2.5, 2.5, 2.5, 2.5),
    ) in runtime.calls
    assert ("write", "trigger_output", (True, False, False, False)) in runtime.calls
    starts = [call for call in runtime.calls if call[0] == "start"]
    assert starts == [
        ("start", "point_output"),
        ("start", "trigger_output"),
        ("start", "acquisition"),
    ]
    assert plugin.get_state() == pytest.approx(2.5)
    assert plugin.get_mean("Dev1/ai0") == pytest.approx(4.0)
    assert plugin.get_mean("Dev1/ai1") == pytest.approx(13.0)
    assert plugin.get_standard_deviation("Dev1/ai0") == pytest.approx(np.std([1.0, 3.0, 5.0, 7.0]))
    values = plugin.reported_values()
    assert values[f"{plugin.instance_name}:Dev1/ai0 Mean"] == (
        f"{plugin.instance_name}.get_mean('Dev1/ai0')"
    )
    assert f"{plugin.instance_name}:Dev1/ai0 Standard Deviation" in values

    plugin.set_state(-1.0)
    assert len([call for call in runtime.calls if call[0] == "timing"]) == 3
    assert len([call for call in runtime.calls if call[:2] == ("start", "trigger_output")]) == 2


def test_point_acquisition_works_without_either_output(qapp):
    runtime = _FakeRuntime()
    runtime.read_values = runtime.read_values[:1]
    plugin = _configured_plugin(runtime)
    plugin._acquisition_definition = _physical_definition(  # noqa: SLF001
        DaqmxTaskKind.ACQUISITION, "Dev1/ai0"
    )
    plugin._output_enabled = False  # noqa: SLF001
    plugin._output_trigger = DaqmxOutputTrigger()  # noqa: SLF001

    plugin.connect()
    plugin.configure()
    plugin.set_state(3.0)

    assert not any(call[0] in {"output_start", "write", "wait"} for call in runtime.calls)
    assert ("start", "acquisition") in runtime.calls
    assert plugin.get_mean("Dev1/ai0") == pytest.approx(4.0)


def test_point_settings_show_acquisition_rate_and_duration(managed_qt_widget):
    plugin = DaqmxPointScanPlugin()
    settings = managed_qt_widget(DaqmxPointScanSettingsWidget(plugin))

    settings.sample_rate_spin.setValue(2000.0)
    settings.oversampling_spin.setValue(4)

    assert settings.input_rate_label.text() == "0.002 s"
    assert settings.general_layout.itemAt(settings.general_layout.count() - 1).spacerItem()


def test_point_configuration_round_trip_and_compact_advanced_json(qapp):
    plugin = DaqmxPointScanPlugin()
    plugin._acquisition_definition = _physical_definition(  # noqa: SLF001
        DaqmxTaskKind.ACQUISITION, "Dev1/ai0"
    )
    plugin._output_definition = _physical_definition(  # noqa: SLF001
        DaqmxTaskKind.OUTPUT, "Dev1/ao0"
    )
    plugin._output_enabled = True  # noqa: SLF001
    plugin._sample_rate_hz = 12_345.0  # noqa: SLF001
    plugin._oversampling = 8  # noqa: SLF001

    data = plugin.to_json()
    assert "input_trigger" not in data
    assert "output_trigger" not in data

    plugin._output_trigger = DaqmxOutputTrigger(  # noqa: SLF001
        enabled=True, line="Dev1/port0/line0", phase_angle=45.0
    )
    restored = BasePlugin.from_json(plugin.to_json())

    assert isinstance(restored, DaqmxPointScanPlugin)
    assert restored._acquisition_definition == plugin._acquisition_definition  # noqa: SLF001
    assert restored._output_definition == plugin._output_definition  # noqa: SLF001
    assert restored._sample_rate_hz == 12_345.0  # noqa: SLF001
    assert restored._oversampling == 8  # noqa: SLF001
    assert restored._output_trigger == plugin._output_trigger  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
