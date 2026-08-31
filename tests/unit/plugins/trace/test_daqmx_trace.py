"""Behaviour tests for the hardware-timed DAQmx trace plugin."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
from qtpy.QtWidgets import QGroupBox, QScrollArea

from stoner_measurement.core import COLUMN_ROLE_X, COLUMN_ROLE_Y, COLUMN_ROLE_Z
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace.daqmx import (
    DaqmxTracePlugin,
    DaqmxTraceSettingsWidget,
    _build_output_trigger_values,
)
from stoner_measurement.plugins.trace.daqmx_runtime import validate_task_definition
from stoner_measurement.scan import ListScanGenerator
from stoner_measurement.ui.widgets import (
    DaqmxDeviceInfo,
    DaqmxInputTrigger,
    DaqmxInputTriggerMode,
    DaqmxOutputTrigger,
    DaqmxSelectionMode,
    DaqmxSystemInfo,
    DaqmxTaskDefinition,
    DaqmxTaskKind,
    DaqmxTriggerEdge,
    DaqmxTriggerIdleState,
    SISpinBox,
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
        self.read_values = np.array(
            [[0.0, 2.0, 10.0, 12.0, 20.0, 22.0], [4.0, 6.0, 14.0, 16.0, 24.0, 26.0]]
        )

    def create_task(self, definition):
        names = definition.physical_channels or definition.global_channels
        role = (
            "acquisition"
            if definition.task_kind is DaqmxTaskKind.ACQUISITION
            else "waveform_output"
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
        assert task.role == "acquisition"
        self.calls.append(
            (
                "input_trigger",
                trigger.mode,
                trigger.terminal,
                trigger.edge,
                trigger.analog_level,
            )
        )

    def input_sample_clock_source(self, task):
        assert task.kind is DaqmxTaskKind.ACQUISITION
        return "/Dev1/ai/SampleClock"

    def configure_output_start_from_input(self, output_task, input_task):
        assert output_task.kind is DaqmxTaskKind.OUTPUT
        assert input_task.kind is DaqmxTaskKind.ACQUISITION
        self.calls.append(("output_start", output_task.role))
        return "/Dev1/ai/StartTrigger"

    def write_output(self, task, values):
        self.calls.append(("write", task.role, tuple(values)))

    def commit_task(self, task):
        self.calls.append(("commit", task.role))

    def channel_names(self, task):
        assert task.kind is DaqmxTaskKind.ACQUISITION
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


def _configured_plugin(runtime: _FakeRuntime) -> DaqmxTracePlugin:
    plugin = DaqmxTracePlugin(runtime_factory=lambda: runtime)
    plugin._acquisition_definition = _physical_definition(
        DaqmxTaskKind.ACQUISITION, "Dev1/ai0", "Dev1/ai1"
    )
    plugin._output_definition = _physical_definition(DaqmxTaskKind.OUTPUT, "Dev1/ao0")
    plugin._output_enabled = True
    plugin._sample_rate_hz = 100.0
    plugin._oversampling = 2
    plugin.scan_generator = ListScanGenerator(
        stages=[(0.0, True), (1.0, True), (2.0, True)], parent=plugin
    )
    return plugin


def test_lifecycle_configures_triggered_generation_and_averages_windows(qapp):
    runtime = _FakeRuntime()
    plugin = _configured_plugin(runtime)

    plugin.connect()
    plugin.configure()
    result = plugin.measure({})

    assert ("timing", "acquisition", 200.0, 6, "") in runtime.calls
    assert (
        "timing",
        "waveform_output",
        200.0,
        6,
        "/Dev1/ai/SampleClock",
    ) in runtime.calls
    assert ("output_start", "waveform_output") in runtime.calls
    assert (
        "write",
        "waveform_output",
        (0.0, 0.0, 1.0, 1.0, 2.0, 2.0),
    ) in runtime.calls
    starts = [call for call in runtime.calls if call[0] == "start"]
    assert starts == [
        ("start", "waveform_output"),
        ("start", "acquisition"),
    ]

    trace = result["DAQmx Trace"]
    assert trace.df["x"].tolist() == [0.0, 1.0, 2.0]
    assert trace.df["Dev1/ai0"].tolist() == [1.0, 11.0, 21.0]
    assert trace.df["Dev1/ai1"].tolist() == [5.0, 15.0, 25.0]
    assert trace.get_columns_by_role(COLUMN_ROLE_X) == ["x"]
    assert trace.get_columns_by_role(COLUMN_ROLE_Y) == ["Dev1/ai0"]
    assert trace.get_columns_by_role(COLUMN_ROLE_Z) == ["Dev1/ai1"]

    plugin.measure({})
    assert len([call for call in runtime.calls if call[0] == "timing"]) == 2
    assert len([call for call in runtime.calls if call[0] == "start"]) == 4


@pytest.mark.parametrize(
    ("mode", "edge", "level"),
    [
        (DaqmxInputTriggerMode.DIGITAL, DaqmxTriggerEdge.FALLING, 0.0),
        (DaqmxInputTriggerMode.ANALOG, DaqmxTriggerEdge.RISING, 0.25),
    ],
)
def test_external_input_trigger_is_applied_to_acquisition_task(mode, edge, level, qapp):
    runtime = _FakeRuntime()
    plugin = _configured_plugin(runtime)
    plugin._output_enabled = False
    plugin._input_trigger = DaqmxInputTrigger(
        mode=mode,
        edge=edge,
        terminal="/Dev1/PFI0",
        analog_level=level,
    )

    plugin.connect()
    plugin.configure()

    assert ("input_trigger", mode, "/Dev1/PFI0", edge, level) in runtime.calls


def test_output_trigger_uses_synchronized_hardware_timed_digital_task(qapp):
    runtime = _FakeRuntime()
    plugin = _configured_plugin(runtime)
    plugin._input_trigger = DaqmxInputTrigger(
        mode=DaqmxInputTriggerMode.DIGITAL,
        terminal="/Dev1/PFI0",
    )
    plugin._output_trigger = DaqmxOutputTrigger(
        enabled=True,
        line="Dev1/port0/line0",
        phase_angle=120.0,
        delay=0.0,
        high_time=0.005,
        low_time=0.005,
    )

    plugin.connect()
    plugin.configure()
    plugin.measure({})

    assert ("create", "trigger_output", "Dev1/port0/line0") in runtime.calls
    assert (
        "input_trigger",
        DaqmxInputTriggerMode.DIGITAL,
        "/Dev1/PFI0",
        DaqmxTriggerEdge.RISING,
        0.0,
    ) in runtime.calls
    assert (
        "timing",
        "trigger_output",
        200.0,
        6,
        "/Dev1/ai/SampleClock",
    ) in runtime.calls
    assert ("output_start", "trigger_output") in runtime.calls
    assert (
        "write",
        "trigger_output",
        (False, False, True, False, False, False),
    ) in runtime.calls
    starts = [call for call in runtime.calls if call[0] == "start"]
    assert starts == [
        ("start", "waveform_output"),
        ("start", "trigger_output"),
        ("start", "acquisition"),
    ]
    assert any(call[:2] == ("wait", "trigger_output") for call in runtime.calls)

    plugin.disconnect()
    assert ("close", "trigger_output") in runtime.calls


def test_output_trigger_waveform_uses_idle_polarity_and_validates_resolution():
    trigger = DaqmxOutputTrigger(
        enabled=True,
        line="Dev1/port0/line0",
        idle_state=DaqmxTriggerIdleState.HIGH,
        phase_angle=0.0,
        delay=0.002,
        high_time=0.003,
        low_time=0.002,
    )

    values = _build_output_trigger_values(trigger, rate=1000.0, sample_count=10)

    assert values.tolist() == [True, True, False, False, True, True, True, True, True, True]

    with pytest.raises(ValueError, match="shorter than the hardware sample period"):
        _build_output_trigger_values(
            DaqmxOutputTrigger(
                enabled=True,
                line="Dev1/port0/line0",
                high_time=10e-9,
                low_time=0.001,
            ),
            rate=1000.0,
            sample_count=10,
        )


def test_output_trigger_rejects_a_whole_digital_port(qapp):
    plugin = DaqmxTracePlugin()
    plugin._acquisition_definition = _physical_definition(DaqmxTaskKind.ACQUISITION, "Dev1/ai0")
    plugin._output_trigger = DaqmxOutputTrigger(
        enabled=True,
        line="Dev1/port0",
    )

    with pytest.raises(ValueError, match="one digital output line"):
        plugin.connect()


def test_output_task_is_optional(qapp):
    runtime = _FakeRuntime()
    runtime.read_values = runtime.read_values[:1]
    plugin = _configured_plugin(runtime)
    plugin._acquisition_definition = _physical_definition(DaqmxTaskKind.ACQUISITION, "Dev1/ai0")
    plugin._output_enabled = False

    plugin.connect()
    plugin.configure()
    plugin.measure({})

    assert not any(call[0] in {"output_start", "write", "wait"} for call in runtime.calls)
    assert ("start", "acquisition") in runtime.calls


def test_disconnect_stops_and_closes_owned_tasks(qapp):
    runtime = _FakeRuntime()
    plugin = _configured_plugin(runtime)
    plugin.connect()

    plugin.disconnect()

    assert ("close", "waveform_output") in runtime.calls
    assert ("close", "acquisition") in runtime.calls
    with pytest.raises(RuntimeError, match="connected and configured"):
        plugin.measure({})


def test_disconnect_attempts_every_close_after_cleanup_failure(qapp):
    class _FailingStopRuntime(_FakeRuntime):
        def stop(self, task):
            super().stop(task)
            if task.role == "waveform_output":
                raise RuntimeError("stop failed")

    runtime = _FailingStopRuntime()
    plugin = _configured_plugin(runtime)
    plugin.connect()

    with pytest.raises(RuntimeError, match="could not be released"):
        plugin.disconnect()

    assert ("close", "waveform_output") in runtime.calls
    assert ("close", "acquisition") in runtime.calls


def test_trigger_output_connect_failure_closes_every_created_task(qapp):
    class _FailingVerifyRuntime(_FakeRuntime):
        def verify_task(self, task, kind):
            super().verify_task(task, kind)
            if task.role == "trigger_output":
                raise RuntimeError("trigger output verification failed")

    runtime = _FailingVerifyRuntime()
    plugin = _configured_plugin(runtime)
    plugin._output_trigger = DaqmxOutputTrigger(
        enabled=True,
        line="Dev1/port0/line0",
    )

    with pytest.raises(RuntimeError, match="verification failed"):
        plugin.connect()

    assert ("close", "trigger_output") in runtime.calls
    assert ("close", "waveform_output") in runtime.calls
    assert ("close", "acquisition") in runtime.calls


def test_task_validation_rejects_mixed_and_counter_physical_channels():
    with pytest.raises(ValueError, match="cannot mix"):
        validate_task_definition(
            _physical_definition(DaqmxTaskKind.ACQUISITION, "Dev1/ai0", "Dev1/port0")
        )
    with pytest.raises(ValueError, match="Counter channels"):
        validate_task_definition(_physical_definition(DaqmxTaskKind.ACQUISITION, "Dev1/ctr0"))


def test_settings_fix_direction_and_disable_optional_output(managed_qt_widget):
    plugin = DaqmxTracePlugin()
    settings = managed_qt_widget(DaqmxTraceSettingsWidget(plugin))

    assert settings.acquisition_widget.task_kind() is DaqmxTaskKind.ACQUISITION
    assert settings.output_widget.task_kind() is DaqmxTaskKind.OUTPUT
    assert isinstance(settings.widget(0), QScrollArea)
    assert isinstance(settings.sample_rate_spin, SISpinBox)
    first_group = settings.general_layout.itemAt(0).widget()
    assert isinstance(first_group, QGroupBox)
    assert first_group.title() == "Hardware timing"
    assert not settings.output_group.isEnabled()

    settings.output_enabled_check.setChecked(True)
    settings.sample_rate_spin.setValue(250.0)
    settings.oversampling_spin.setValue(4)

    assert settings.output_group.isEnabled()
    assert plugin._output_enabled is True
    assert plugin._sample_rate_hz == 250.0
    assert plugin._oversampling == 4
    assert settings.input_rate_label.text() == "1000 Hz"
    assert settings.tabText(1) == "Advanced"
    assert isinstance(settings.widget(1), QScrollArea)

    settings.input_trigger_widget.mode_combo.setCurrentIndex(
        settings.input_trigger_widget.mode_combo.findData(DaqmxInputTriggerMode.DIGITAL.value)
    )
    settings.output_trigger_widget.enabled_check.setChecked(True)
    settings.output_trigger_widget.phase_angle_spin.setValue(90.0)

    assert plugin._input_trigger.mode is DaqmxInputTriggerMode.DIGITAL
    assert plugin._output_trigger.enabled is True
    assert plugin._output_trigger.phase_angle == 90.0

    settings.acquisition_widget.set_snapshot(
        DaqmxSystemInfo(
            devices=(
                DaqmxDeviceInfo(
                    "Dev1",
                    terminals=("/Dev1/PFI0",),
                    digital_outputs=(
                        "Dev1/port0",
                        "Dev1/port0/line0",
                    ),
                ),
            )
        )
    )

    assert settings.input_trigger_widget.terminal_combo.itemText(0) == "/Dev1/PFI0"
    assert settings.output_trigger_widget.line_combo.itemText(0) == "Dev1/port0/line0"


def test_configuration_round_trip(qapp):
    plugin = DaqmxTracePlugin()
    plugin._acquisition_definition = _physical_definition(DaqmxTaskKind.ACQUISITION, "Dev1/ai0")
    plugin._output_definition = _physical_definition(DaqmxTaskKind.OUTPUT, "Dev1/ao0")
    plugin._output_enabled = True
    plugin._sample_rate_hz = 12_345.0
    plugin._oversampling = 8
    plugin._input_trigger = DaqmxInputTrigger(
        mode=DaqmxInputTriggerMode.DIGITAL, terminal="/Dev1/PFI0"
    )
    plugin._output_trigger = DaqmxOutputTrigger(
        enabled=True, line="Dev1/port0/line0", phase_angle=45.0
    )

    restored = BasePlugin.from_json(plugin.to_json())

    assert isinstance(restored, DaqmxTracePlugin)
    assert restored._acquisition_definition == plugin._acquisition_definition
    assert restored._output_definition == plugin._output_definition
    assert restored._output_enabled is True
    assert restored._sample_rate_hz == 12_345.0
    assert restored._oversampling == 8
    assert restored._input_trigger == plugin._input_trigger
    assert restored._output_trigger == plugin._output_trigger


def test_default_advanced_trigger_settings_are_omitted_from_json(qapp):
    plugin = DaqmxTracePlugin()

    data = plugin.to_json()

    assert "input_trigger" not in data
    assert "output_trigger" not in data

    plugin._input_trigger = DaqmxInputTrigger(
        mode=DaqmxInputTriggerMode.DIGITAL, terminal="/Dev1/PFI0"
    )
    data = plugin.to_json()

    assert data["input_trigger"] == plugin._input_trigger.to_dict()
    assert "output_trigger" not in data

    restored = BasePlugin.from_json(data)
    assert restored._input_trigger == plugin._input_trigger
    assert restored._output_trigger == DaqmxOutputTrigger()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
