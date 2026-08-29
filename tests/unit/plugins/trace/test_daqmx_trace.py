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
)
from stoner_measurement.plugins.trace.daqmx_runtime import validate_task_definition
from stoner_measurement.scan import ListScanGenerator
from stoner_measurement.ui.widgets import (
    DaqmxSelectionMode,
    DaqmxTaskDefinition,
    DaqmxTaskKind,
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


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.read_values = np.array(
            [[0.0, 2.0, 10.0, 12.0, 20.0, 22.0], [4.0, 6.0, 14.0, 16.0, 24.0, 26.0]]
        )

    def create_task(self, definition):
        names = definition.physical_channels or definition.global_channels
        task = _Task(definition.task_kind, tuple(names))
        self.calls.append(("create", definition.task_kind))
        return task

    def verify_task(self, task, kind):
        assert task.kind is kind
        self.calls.append(("verify", kind))

    def prepare_for_configuration(self, task):
        self.calls.append(("prepare", task.kind))

    def configure_finite_timing(self, task, rate, samples, *, source=""):
        self.calls.append(("timing", task.kind, rate, samples, source))

    def input_sample_clock_source(self, task):
        assert task.kind is DaqmxTaskKind.ACQUISITION
        return "/Dev1/ai/SampleClock"

    def configure_output_start_from_input(self, output_task, input_task):
        assert output_task.kind is DaqmxTaskKind.OUTPUT
        assert input_task.kind is DaqmxTaskKind.ACQUISITION
        self.calls.append(("trigger",))
        return "/Dev1/ai/StartTrigger"

    def write_output(self, task, values):
        self.calls.append(("write", task.kind, tuple(values)))

    def commit_task(self, task):
        self.calls.append(("commit", task.kind))

    def channel_names(self, task):
        assert task.kind is DaqmxTaskKind.ACQUISITION
        return task.channel_names

    def start(self, task):
        self.calls.append(("start", task.kind))

    def read(self, task, samples, timeout):
        self.calls.append(("read", task.kind, samples, timeout))
        return self.read_values.copy()

    def wait_until_done(self, task, timeout):
        self.calls.append(("wait", task.kind, timeout))

    def stop(self, task):
        self.calls.append(("stop", task.kind))

    def close(self, task):
        self.calls.append(("close", task.kind))


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

    assert ("timing", DaqmxTaskKind.ACQUISITION, 200.0, 6, "") in runtime.calls
    assert (
        "timing",
        DaqmxTaskKind.OUTPUT,
        200.0,
        6,
        "/Dev1/ai/SampleClock",
    ) in runtime.calls
    assert ("trigger",) in runtime.calls
    assert (
        "write",
        DaqmxTaskKind.OUTPUT,
        (0.0, 0.0, 1.0, 1.0, 2.0, 2.0),
    ) in runtime.calls
    starts = [call for call in runtime.calls if call[0] == "start"]
    assert starts == [
        ("start", DaqmxTaskKind.OUTPUT),
        ("start", DaqmxTaskKind.ACQUISITION),
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


def test_output_task_is_optional(qapp):
    runtime = _FakeRuntime()
    runtime.read_values = runtime.read_values[:1]
    plugin = _configured_plugin(runtime)
    plugin._acquisition_definition = _physical_definition(
        DaqmxTaskKind.ACQUISITION, "Dev1/ai0"
    )
    plugin._output_enabled = False

    plugin.connect()
    plugin.configure()
    plugin.measure({})

    assert not any(call[0] in {"trigger", "write", "wait"} for call in runtime.calls)
    assert ("start", DaqmxTaskKind.ACQUISITION) in runtime.calls


def test_disconnect_stops_and_closes_owned_tasks(qapp):
    runtime = _FakeRuntime()
    plugin = _configured_plugin(runtime)
    plugin.connect()

    plugin.disconnect()

    assert ("close", DaqmxTaskKind.OUTPUT) in runtime.calls
    assert ("close", DaqmxTaskKind.ACQUISITION) in runtime.calls
    with pytest.raises(RuntimeError, match="connected and configured"):
        plugin.measure({})


def test_disconnect_attempts_every_close_after_cleanup_failure(qapp):
    class _FailingStopRuntime(_FakeRuntime):
        def stop(self, task):
            super().stop(task)
            if task.kind is DaqmxTaskKind.OUTPUT:
                raise RuntimeError("stop failed")

    runtime = _FailingStopRuntime()
    plugin = _configured_plugin(runtime)
    plugin.connect()

    with pytest.raises(RuntimeError, match="could not be released"):
        plugin.disconnect()

    assert ("close", DaqmxTaskKind.OUTPUT) in runtime.calls
    assert ("close", DaqmxTaskKind.ACQUISITION) in runtime.calls


def test_task_validation_rejects_mixed_and_counter_physical_channels():
    with pytest.raises(ValueError, match="cannot mix"):
        validate_task_definition(
            _physical_definition(DaqmxTaskKind.ACQUISITION, "Dev1/ai0", "Dev1/port0")
        )
    with pytest.raises(ValueError, match="Counter channels"):
        validate_task_definition(
            _physical_definition(DaqmxTaskKind.ACQUISITION, "Dev1/ctr0")
        )


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


def test_configuration_round_trip(qapp):
    plugin = DaqmxTracePlugin()
    plugin._acquisition_definition = _physical_definition(
        DaqmxTaskKind.ACQUISITION, "Dev1/ai0"
    )
    plugin._output_definition = _physical_definition(DaqmxTaskKind.OUTPUT, "Dev1/ao0")
    plugin._output_enabled = True
    plugin._sample_rate_hz = 12_345.0
    plugin._oversampling = 8

    restored = BasePlugin.from_json(plugin.to_json())

    assert isinstance(restored, DaqmxTracePlugin)
    assert restored._acquisition_definition == plugin._acquisition_definition
    assert restored._output_definition == plugin._output_definition
    assert restored._output_enabled is True
    assert restored._sample_rate_hz == 12_345.0
    assert restored._oversampling == 8


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
