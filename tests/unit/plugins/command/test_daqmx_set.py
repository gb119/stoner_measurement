"""Tests for the one-shot DAQmx set-and-acquire command."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command.daqmx_set import (
    DaqmxSetCommand,
    DaqmxSetSettingsWidget,
)
from stoner_measurement.ui.widgets import (
    DaqmxChannelFamily,
    DaqmxOutputTrigger,
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
    role: str


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_task(self, definition):
        role = "input" if definition.task_kind is DaqmxTaskKind.ACQUISITION else "output"
        names = (
            ("saved_ai",)
            if definition.selection_mode is DaqmxSelectionMode.SAVED_TASK
            else tuple(definition.physical_channels)
        )
        task = _Task(definition.task_kind, names, role)
        self.calls.append(("create", role))
        return task

    def verify_task(self, task, kind, channel_family=None):
        assert task.kind is kind
        assert channel_family is DaqmxChannelFamily.ANALOG

    def prepare_for_configuration(self, task):
        self.calls.append(("prepare", task.role))

    def configure_finite_timing(self, task, rate, samples, *, source=""):
        self.calls.append(("timing", task.role, rate, samples, source))

    def configure_input_start_trigger(self, task, trigger):
        self.calls.append(("input_trigger", task.role, trigger.mode))

    def input_sample_clock_source(self, task):
        return "/Dev1/ai/SampleClock"

    def configure_output_start_from_input(self, output_task, input_task):
        self.calls.append(("output_start", output_task.role))

    def commit_task(self, task):
        self.calls.append(("commit", task.role))

    def channel_names(self, task):
        return task.channel_names

    def write_output(self, task, values):
        self.calls.append(("write", task.role, tuple(values)))

    def start(self, task):
        self.calls.append(("start", task.role))

    def read(self, task, samples, timeout):
        self.calls.append(("read", task.role, samples, timeout))
        return np.array([[1.0, 3.0, 5.0, 7.0]])

    def wait_until_done(self, task, timeout):
        self.calls.append(("wait", task.role, timeout))

    def stop(self, task):
        self.calls.append(("stop", task.role))

    def close(self, task):
        self.calls.append(("close", task.role))


def _configured_command(runtime: _FakeRuntime) -> DaqmxSetCommand:
    command = DaqmxSetCommand(runtime_factory=lambda: runtime)
    point = command._point_plugin  # noqa: SLF001
    point._acquisition_definition = _physical_definition(  # noqa: SLF001
        DaqmxTaskKind.ACQUISITION, "Dev1/ai0"
    )
    point._output_definition = _physical_definition(  # noqa: SLF001
        DaqmxTaskKind.OUTPUT, "Dev1/ao0"
    )
    point._output_enabled = True  # noqa: SLF001
    point._sample_rate_hz = 2000.0  # noqa: SLF001
    point._oversampling = 4  # noqa: SLF001
    command._value = 2.5  # noqa: SLF001
    return command


def test_execute_performs_one_point_reports_statistics_and_releases_tasks(qapp):
    runtime = _FakeRuntime()
    command = _configured_command(runtime)

    command.execute()

    assert ("write", "output", (2.5, 2.5, 2.5, 2.5)) in runtime.calls
    assert [call for call in runtime.calls if call[0] == "start"] == [
        ("start", "output"),
        ("start", "input"),
    ]
    assert command.get_mean("Dev1/ai0") == pytest.approx(4.0)
    assert command.get_standard_deviation("Dev1/ai0") == pytest.approx(np.std([1.0, 3.0, 5.0, 7.0]))
    assert ("close", "output") in runtime.calls
    assert ("close", "input") in runtime.calls
    outputs = command.reported_values()
    assert outputs[f"{command.instance_name}:Output value"] == (
        f"{command.instance_name}._last_value"
    )
    assert f"{command.instance_name}:Dev1/ai0 Mean" in outputs


def test_settings_have_one_command_tab_and_no_scan_or_data_pages(qapp, managed_qt_widget):
    command = DaqmxSetCommand()
    tabs = command.config_tabs()
    combined = managed_qt_widget(tabs[0][1])
    combined.resize(900, 800)
    combined.show()
    qapp.processEvents()
    settings = combined.findChild(DaqmxSetSettingsWidget)
    value = combined.findChild(SISpinBox, "daqmx_set_value")

    titles = [title for title, _widget in tabs]
    assert titles[0] == "General"
    assert not any(title.endswith((" - Scan", " - Data")) for title in titles)
    assert settings is not None
    assert settings.tabText(0) == "General"
    assert settings.tabText(1) == "Advanced"
    assert value is not None
    assert not hasattr(command, "scan_generator")
    assert settings.output_enabled_check.isChecked()
    assert settings.output_group.isEnabled()
    assert settings.general_layout.itemAt(0).widget().title() == "Output point"
    assert settings.general_layout.itemAt(3).widget() is settings.output_enabled_check
    assert settings.general_layout.itemAt(4).widget() is settings.output_group
    assert settings.height() > settings.sizeHint().height()

    value.setValue("outer.output")
    assert command._value == "outer.output"  # noqa: SLF001


def test_json_reuses_point_configuration_and_omits_default_advanced_settings(qapp):
    command = DaqmxSetCommand()
    point = command._point_plugin  # noqa: SLF001
    command._value = 1.25  # noqa: SLF001
    point._acquisition_definition = _physical_definition(  # noqa: SLF001
        DaqmxTaskKind.ACQUISITION, "Dev1/ai0"
    )
    point._sample_rate_hz = 12_000.0  # noqa: SLF001
    point._oversampling = 16  # noqa: SLF001

    data = command.to_json()
    assert "scan_generator" not in data
    assert "input_trigger" not in data
    assert "output_trigger" not in data

    point._output_trigger = DaqmxOutputTrigger(  # noqa: SLF001
        enabled=True,
        line="Dev1/port0/line0",
        phase_angle=45.0,
    )
    restored = BasePlugin.from_json(command.to_json())

    assert isinstance(restored, DaqmxSetCommand)
    assert restored._value == pytest.approx(1.25)  # noqa: SLF001
    assert restored._point_plugin._acquisition_definition == (  # noqa: SLF001
        point._acquisition_definition  # noqa: SLF001
    )
    assert restored._point_plugin._sample_rate_hz == 12_000.0  # noqa: SLF001
    assert restored._point_plugin._oversampling == 16  # noqa: SLF001
    assert restored._point_plugin._output_trigger == point._output_trigger  # noqa: SLF001


def test_saved_task_channel_names_remain_reported_after_command_cleanup(qapp):
    runtime = _FakeRuntime()
    command = DaqmxSetCommand(runtime_factory=lambda: runtime)
    point = command._point_plugin  # noqa: SLF001
    point._acquisition_definition = DaqmxTaskDefinition(  # noqa: SLF001
        task_kind=DaqmxTaskKind.ACQUISITION,
        selection_mode=DaqmxSelectionMode.SAVED_TASK,
        saved_task="SavedInput",
    )
    point._output_enabled = False  # noqa: SLF001
    point._oversampling = 4  # noqa: SLF001

    command.execute()

    assert command.get_mean("saved_ai") == pytest.approx(4.0)
    assert f"{command.instance_name}:saved_ai Mean" in command.reported_values()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
