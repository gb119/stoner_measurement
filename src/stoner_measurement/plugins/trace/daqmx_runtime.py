"""Lazy NI-DAQmx runtime boundary used by the DAQmx trace plugin."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import numpy as np

from stoner_measurement.ui.widgets import (
    DaqmxChannelFamily,
    DaqmxInputTrigger,
    DaqmxInputTriggerMode,
    DaqmxSelectionMode,
    DaqmxTaskDefinition,
    DaqmxTaskKind,
    DaqmxTerminalConfiguration,
)


class DaqmxRuntimeError(RuntimeError):
    """Raised for unsupported or inconsistent DAQmx task configurations."""


def validate_task_definition(
    definition: DaqmxTaskDefinition,
    channel_family: DaqmxChannelFamily | None = None,
) -> None:
    """Validate that *definition* selects exactly one usable task source."""
    if definition.selection_mode is DaqmxSelectionMode.PHYSICAL_CHANNELS:
        if not definition.device:
            raise ValueError("Select a DAQmx device.")
        if not definition.physical_channels:
            raise ValueError("Select at least one physical channel.")
        devices = {channel.split("/", 1)[0] for channel in definition.physical_channels}
        if devices != {definition.device}:
            raise ValueError("All physical channels must belong to the selected device.")
        families = {
            _physical_channel_family(channel, definition.task_kind)
            for channel in definition.physical_channels
        }
        if len(families) != 1:
            raise ValueError("A DAQmx task cannot mix physical channel types.")
        family = next(iter(families))
        expected = {DaqmxTaskKind.ACQUISITION: {"ai", "di"}, DaqmxTaskKind.OUTPUT: {"ao", "do"}}
        if family not in expected[definition.task_kind]:
            if family in {"ci", "co"}:
                raise ValueError(
                    "Counter channels need measurement-specific settings that are not yet "
                    "available in the DAQmx trace plugin."
                )
            raise ValueError(
                f"{family.upper()} channels are not valid for a {definition.task_kind.value} task."
            )
        actual_family = (
            DaqmxChannelFamily.ANALOG if family in {"ai", "ao"} else DaqmxChannelFamily.DIGITAL
        )
        if channel_family is not None and actual_family is not channel_family:
            raise ValueError(
                f"Select {channel_family.value} channels for this DAQmx plugin."
            )
        if definition.custom_scale and family not in {"ai", "ao"}:
            raise ValueError("Custom scales can only be used with analog channels.")
        if family == "ai":
            ranges = {item.channel: item for item in definition.input_ranges}
            for channel in definition.physical_channels:
                input_range = ranges.get(channel)
                if input_range is None:
                    continue
                if not np.isfinite(input_range.range):
                    raise ValueError(f"The input range for {channel} must be finite.")
                if input_range.range <= 0:
                    raise ValueError(f"The input range for {channel} must be positive.")
        return
    if definition.selection_mode is DaqmxSelectionMode.GLOBAL_CHANNELS:
        if not definition.global_channels:
            raise ValueError("Select at least one MAX global channel.")
        return
    if definition.selection_mode is DaqmxSelectionMode.SAVED_TASK and not definition.saved_task:
        raise ValueError("Select a MAX saved task.")


def _physical_channel_family(channel: str, task_kind: DaqmxTaskKind | None = None) -> str:
    """Return the DAQmx subsystem token embedded in a physical channel name."""
    suffix = channel.split("/", 1)[-1].lower()
    for family in ("ai", "ao", "di", "do", "ci", "co"):
        if suffix.startswith(family):
            return family
    if suffix.startswith("ctr"):
        return "co" if task_kind is DaqmxTaskKind.OUTPUT else "ci"
    if "/port" in channel.lower() or "/line" in channel.lower():
        return "do" if task_kind is DaqmxTaskKind.OUTPUT else "di"
    raise ValueError(f"Cannot determine the type of physical channel {channel!r}.")


class NidaqmxRuntime:
    """Small adapter around ``nidaqmx`` kept injectable for hardware-free tests."""

    def __init__(self) -> None:
        try:
            import nidaqmx  # type: ignore[import-not-found]
            from nidaqmx import (  # type: ignore[import-not-found]
                constants,
                system,
            )
        except (ImportError, OSError) as exc:
            raise DaqmxRuntimeError(
                "The DAQmx trace plugin requires the optional 'nidaqmx' package and "
                "an installed NI-DAQmx driver."
            ) from exc
        self._nidaqmx = nidaqmx
        self._constants = constants
        self._system = system.System.local()

    def create_task(self, definition: DaqmxTaskDefinition) -> Any:
        """Create or load a task described by *definition*."""
        validate_task_definition(definition)
        if definition.selection_mode is DaqmxSelectionMode.SAVED_TASK:
            return self._system.tasks[definition.saved_task].load()

        task = self._nidaqmx.Task()
        try:
            if definition.selection_mode is DaqmxSelectionMode.GLOBAL_CHANNELS:
                channels = [
                    self._system.global_channels[name] for name in definition.global_channels
                ]
                task.add_global_channels(channels)
            else:
                self._add_physical_channels(task, definition)
        except Exception:
            task.close()
            raise
        return task

    def create_digital_output_task(self, line: str) -> Any:
        """Create a one-line digital output task for an exported trigger pulse."""
        task = self._nidaqmx.Task()
        try:
            task.do_channels.add_do_chan(
                line,
                line_grouping=self._constants.LineGrouping.CHAN_PER_LINE,
            )
            if int(task.number_of_channels) != 1:
                raise DaqmxRuntimeError(
                    "The output trigger must select exactly one digital output line."
                )
        except Exception:
            task.close()
            raise
        return task

    def _add_physical_channels(self, task: Any, definition: DaqmxTaskDefinition) -> None:
        family = _physical_channel_family(definition.physical_channels[0], definition.task_kind)
        input_ranges = {item.channel: item for item in definition.input_ranges}
        for channel in definition.physical_channels:
            if family == "ai":
                input_range = input_ranges.get(channel)
                range_limit = 10.0 if input_range is None else input_range.range
                kwargs: dict[str, Any] = {
                    "min_val": -range_limit,
                    "max_val": range_limit,
                }
                if definition.terminal_configuration is not DaqmxTerminalConfiguration.DEFAULT:
                    terminal_name = {
                        DaqmxTerminalConfiguration.RSE: "RSE",
                        DaqmxTerminalConfiguration.NRSE: "NRSE",
                        DaqmxTerminalConfiguration.DIFFERENTIAL: "DIFF",
                    }[definition.terminal_configuration]
                    kwargs["terminal_config"] = getattr(
                        self._constants.TerminalConfiguration, terminal_name
                    )
                if definition.custom_scale:
                    kwargs.update(
                        units=self._constants.VoltageUnits.FROM_CUSTOM_SCALE,
                        custom_scale_name=definition.custom_scale,
                    )
                task.ai_channels.add_ai_voltage_chan(channel, **kwargs)
            elif family == "ao":
                kwargs = {}
                if definition.custom_scale:
                    kwargs.update(
                        units=self._constants.VoltageUnits.FROM_CUSTOM_SCALE,
                        custom_scale_name=definition.custom_scale,
                    )
                task.ao_channels.add_ao_voltage_chan(channel, **kwargs)
            elif family == "di":
                task.di_channels.add_di_chan(channel)
            elif family == "do":
                task.do_channels.add_do_chan(channel)

    def verify_task(
        self,
        task: Any,
        expected_kind: DaqmxTaskKind,
        channel_family: DaqmxChannelFamily | None = None,
    ) -> None:
        """Verify task resources and its acquisition/output direction."""
        actual = getattr(task.channels.chan_type, "name", str(task.channels.chan_type)).upper()
        allowed = {
            DaqmxTaskKind.ACQUISITION: {"ANALOG_INPUT", "DIGITAL_INPUT"},
            DaqmxTaskKind.OUTPUT: {"ANALOG_OUTPUT", "DIGITAL_OUTPUT"},
        }
        if actual not in allowed[expected_kind]:
            raise DaqmxRuntimeError(
                f"DAQmx task contains {actual.replace('_', ' ').lower()} channels; expected "
                f"an {expected_kind.value} task."
            )
        actual_family = {
            "ANALOG_INPUT": DaqmxChannelFamily.ANALOG,
            "ANALOG_OUTPUT": DaqmxChannelFamily.ANALOG,
            "DIGITAL_INPUT": DaqmxChannelFamily.DIGITAL,
            "DIGITAL_OUTPUT": DaqmxChannelFamily.DIGITAL,
        }[actual]
        if channel_family is not None and actual_family is not channel_family:
            raise DaqmxRuntimeError(
                f"DAQmx task contains {actual_family.value} channels; expected "
                f"{channel_family.value} channels."
            )
        task.control(self._constants.TaskMode.TASK_VERIFY)

    def prepare_for_configuration(self, task: Any) -> None:
        """Stop and unreserve an existing task before changing timing."""
        with suppress(Exception):
            task.stop()
        task.control(self._constants.TaskMode.TASK_UNRESERVE)

    def configure_finite_timing(
        self, task: Any, rate: float, samples: int, *, source: str = ""
    ) -> None:
        """Configure finite sampling from the onboard or supplied clock source."""
        task.timing.cfg_samp_clk_timing(
            rate,
            source=source,
            sample_mode=self._constants.AcquisitionType.FINITE,
            samps_per_chan=samples,
        )

    def configure_input_start_trigger(self, task: Any, trigger: DaqmxInputTrigger) -> None:
        """Configure or disable the acquisition task's external start trigger."""
        if trigger.mode is DaqmxInputTriggerMode.IMMEDIATE:
            task.triggers.start_trigger.disable_start_trig()
            return
        if trigger.mode is DaqmxInputTriggerMode.DIGITAL:
            task.triggers.start_trigger.cfg_dig_edge_start_trig(
                trigger.terminal,
                trigger_edge=getattr(self._constants.Edge, trigger.edge.name),
            )
            return
        task.triggers.start_trigger.cfg_anlg_edge_start_trig(
            trigger_source=trigger.terminal,
            trigger_slope=getattr(self._constants.Slope, trigger.edge.name),
            trigger_level=trigger.analog_level,
        )

    @staticmethod
    def input_sample_clock_source(input_task: Any) -> str:
        """Return the acquisition subsystem's internal sample-clock terminal."""
        devices = list(input_task.devices)
        if len(devices) != 1:
            raise DaqmxRuntimeError(
                "Automatic sample-clock routing requires the acquisition task to use one device."
            )
        channel_type = getattr(
            input_task.channels.chan_type, "name", str(input_task.channels.chan_type)
        ).upper()
        subsystem = {"ANALOG_INPUT": "ai", "DIGITAL_INPUT": "di"}.get(channel_type)
        if subsystem is None:
            raise DaqmxRuntimeError("The acquisition task has no supported sample clock.")
        return f"/{devices[0].name}/{subsystem}/SampleClock"

    def configure_output_start_from_input(self, output_task: Any, input_task: Any) -> str:
        """Arm output from the acquisition subsystem's internal start event."""
        devices = list(input_task.devices)
        if len(devices) != 1:
            raise DaqmxRuntimeError(
                "Automatic start-trigger routing requires the acquisition task to use one device."
            )
        channel_type = getattr(
            input_task.channels.chan_type, "name", str(input_task.channels.chan_type)
        ).upper()
        subsystem = {"ANALOG_INPUT": "ai", "DIGITAL_INPUT": "di"}.get(channel_type)
        if subsystem is None:
            raise DaqmxRuntimeError("The acquisition task has no supported start event.")
        source = f"/{devices[0].name}/{subsystem}/StartTrigger"
        output_task.triggers.start_trigger.cfg_dig_edge_start_trig(source)
        return source

    def commit_task(self, task: Any) -> None:
        """Reserve resources and commit the configured task."""
        task.control(self._constants.TaskMode.TASK_COMMIT)

    @staticmethod
    def channel_names(task: Any) -> tuple[str, ...]:
        """Return task virtual-channel names."""
        return tuple(str(name) for name in task.channel_names)

    @staticmethod
    def write_output(task: Any, values: np.ndarray) -> None:
        """Preload one finite output buffer without implicitly starting it."""
        count = int(task.number_of_channels)
        channel_type = getattr(
            task.channels.chan_type, "name", str(task.channels.chan_type)
        ).upper()
        prepared = values != 0 if channel_type == "DIGITAL_OUTPUT" else values
        data: Any = prepared.tolist() if count == 1 else np.tile(prepared, (count, 1)).tolist()
        task.write(data, auto_start=False)

    @staticmethod
    def start(task: Any) -> None:
        """Start or arm a task."""
        task.start()

    @staticmethod
    def read(task: Any, samples: int, timeout: float) -> np.ndarray:
        """Read exactly *samples* per channel and normalize to channel-first shape."""
        raw = task.read(number_of_samples_per_channel=samples, timeout=timeout)
        values = np.asarray(raw)
        if values.ndim == 1:
            values = values[np.newaxis, :]
        return values

    @staticmethod
    def wait_until_done(task: Any, timeout: float) -> None:
        """Wait for finite generation to complete."""
        task.wait_until_done(timeout)

    @staticmethod
    def stop(task: Any) -> None:
        """Disarm a task, tolerating a task that is already stopped."""
        with suppress(Exception):
            task.stop()

    @staticmethod
    def close(task: Any) -> None:
        """Clear a task and release all DAQmx resources."""
        task.close()


__all__ = ["DaqmxRuntimeError", "NidaqmxRuntime", "validate_task_definition"]
