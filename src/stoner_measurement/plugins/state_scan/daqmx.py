"""Point-by-point NI-DAQmx generation and oversampled acquisition."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Any

import numpy as np
from qtpy.QtWidgets import QWidget

from stoner_measurement.plugins.state_scan.base import StateScanPlugin
from stoner_measurement.plugins.trace.daqmx import (
    DaqmxTraceSettingsWidget,
    _build_output_trigger_values,
)
from stoner_measurement.plugins.trace.daqmx_runtime import (
    NidaqmxRuntime,
    validate_task_definition,
)
from stoner_measurement.ui.widgets import (
    DaqmxChannelFamily,
    DaqmxInputTrigger,
    DaqmxInputTriggerMode,
    DaqmxOutputTrigger,
    DaqmxSelectionMode,
    DaqmxTaskDefinition,
    DaqmxTaskKind,
)


class DaqmxPointScanSettingsWidget(DaqmxTraceSettingsWidget):
    """DAQmx settings adapted to one finite acquisition per scan point."""

    def __init__(self, plugin: DaqmxPointScanPlugin, parent: QWidget | None = None) -> None:
        super().__init__(plugin, parent, point_timing=True)


class DaqmxPointScanPlugin(StateScanPlugin):
    """Step through DAQmx output values and acquire statistics at every point.

    Use this state-scan plugin when DAQmx should provide a discrete sequence
    axis and other sequence steps may run between its points. The normal state
    scan generator defines the output values. At each point the plugin performs
    one finite, hardware-timed acquisition before nested steps run, making the
    latest input means and standard deviations available to those steps and to
    the state scan's data collector. Use
    :class:`~stoner_measurement.plugins.trace.daqmx.DaqmxTracePlugin` when the
    whole trace can run as one faster buffered operation, or
    :class:`~stoner_measurement.plugins.command.daqmx_set.DaqmxSetCommand` when
    only one value is required.

    The **Scan** tab selects the scan generator and its values. The **Data** tab
    controls which published values are collected at measurement points. On
    the **Settings** tab, the nested **General** page sets the acquisition
    sample rate, number of samples per point, acquisition task, and optional
    output task. It also displays the resulting point-acquisition time. Tasks
    may use direct physical channels, NI MAX global channels, or saved tasks.
    Acquisition and value-output tasks are restricted to analogue channels,
    with custom NI scales available for physical channels. Each physical input
    has its own symmetric range, defaulting to +/-10 V and populated from the
    device where possible. A common RSE, NRSE, or differential mode applies to
    all selected physical inputs. Counter channels are not supported.

    For every scan value, an enabled output task writes a constant buffer of
    **Samples per point** values. The input task acquires the same number of
    samples at the configured acquisition rate. The plugin then publishes the
    population mean and population standard deviation for each discovered
    input channel. These scalar values appear as ``<channel> Mean`` and
    ``<channel> Standard Deviation`` and can be selected on the **Data** tab or
    read by nested sequence commands. A directly selected physical analogue
    output gives the scan axis units of volts; other task definitions remain
    unitless because their engineering units cannot be inferred reliably.

    The **Advanced** page provides the same trigger controls as DAQmx Trace.
    Immediate, digital-edge, and analogue-edge input triggers are applied to
    the acquisition task. An optional one-line digital-output task generates
    one pulse per scan point. The pulse shares the acquisition sample clock
    and internal start event. Its phase is the normalized position through the
    current point's acquisition window, while delay, high time, low time, and
    idle polarity define its local shape. The pulse durations must be
    representable at the acquisition rate and must fit within the samples for
    one point.

    The acquisition task is always the timing master. Any value-output and
    trigger-output tasks are armed first, followed by the acquisition task, so
    an external input trigger starts all dependent work together. Tasks are
    configured once at the start of the state scan and restarted for each
    point. Automatic clock and start routing assumes compatible NI hardware;
    cross-device routes may require additional configuration outside the
    plugin.

    Attributes:
        scan_generator (BaseScanGenerator):
            Generator supplying the successive output values.
        _sample_rate_hz (float):
            Hardware acquisition rate in samples per second.
        _oversampling (int):
            Number of samples acquired and reduced at each point.
        _output_enabled (bool):
            Whether the current scan value is generated on an output task.
        _target_value (float):
            Most recently completed scan value.
        _means (dict[str, float]):
            Latest per-channel population means.
        _standard_deviations (dict[str, float]):
            Latest per-channel population standard deviations.
        _input_trigger (DaqmxInputTrigger):
            Start trigger applied to the acquisition task.
        _output_trigger (DaqmxOutputTrigger):
            Optional per-point synchronized digital pulse.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        To interleave a lock-in reading with DAQmx voltage points, configure an
        ``ao`` output, select the required ``ai`` inputs, and place the lock-in
        command beneath this scan. Each DAQmx point is generated and reduced
        first; the nested command can then use or collect that point's mean and
        standard-deviation outputs.
    """

    def __init__(
        self,
        parent=None,
        *,
        runtime_factory: Callable[[], Any] = NidaqmxRuntime,
    ) -> None:
        super().__init__(parent)
        self._acquisition_definition = DaqmxTaskDefinition(task_kind=DaqmxTaskKind.ACQUISITION)
        self._output_definition = DaqmxTaskDefinition(task_kind=DaqmxTaskKind.OUTPUT)
        self._output_enabled = False
        self._sample_rate_hz = 1000.0
        self._oversampling = 1
        self._input_trigger = DaqmxInputTrigger()
        self._output_trigger = DaqmxOutputTrigger()
        self._runtime_factory = runtime_factory
        self._runtime: Any | None = None
        self._input_task: Any | None = None
        self._output_task: Any | None = None
        self._trigger_output_task: Any | None = None
        self._input_channel_names: tuple[str, ...] = ()
        self._means: dict[str, float] = {}
        self._standard_deviations: dict[str, float] = {}
        self._target_value = 0.0
        self._configured = False
        self._apply_initial_config()

    @property
    def name(self) -> str:
        """Plugin catalogue name."""
        return "DAQmx Point Scan"

    @property
    def state_name(self) -> str:
        """Name of the optional generated output value."""
        return "Output value"

    @property
    def units(self) -> str:
        """Return volts for a selected physical analogue output, otherwise unitless."""
        definition = self._output_definition
        if (
            definition.selection_mode is DaqmxSelectionMode.PHYSICAL_CHANNELS
            and definition.physical_channels
            and definition.physical_channels[0].split("/", 1)[-1].casefold().startswith("ao")
        ):
            return "V"
        return ""

    def _validate_configuration(self) -> None:
        if self._acquisition_definition.task_kind is not DaqmxTaskKind.ACQUISITION:
            raise ValueError("The acquisition task definition has the wrong direction.")
        validate_task_definition(self._acquisition_definition, DaqmxChannelFamily.ANALOG)
        if self._output_enabled:
            if self._output_definition.task_kind is not DaqmxTaskKind.OUTPUT:
                raise ValueError("The output task definition has the wrong direction.")
            validate_task_definition(self._output_definition, DaqmxChannelFamily.ANALOG)
        if not np.isfinite(self._sample_rate_hz) or self._sample_rate_hz <= 0:
            raise ValueError("The acquisition sample rate must be positive.")
        if self._oversampling < 1:
            raise ValueError("Input oversampling must be at least one.")
        if self._input_trigger.mode is not DaqmxInputTriggerMode.IMMEDIATE:
            if not self._input_trigger.terminal:
                raise ValueError("Select an input trigger terminal.")
            if self._input_trigger.mode is DaqmxInputTriggerMode.ANALOG and not np.isfinite(
                self._input_trigger.analog_level
            ):
                raise ValueError("The analogue input trigger level must be finite.")
        if self._output_trigger.enabled:
            if not self._output_trigger.line:
                raise ValueError("Select a digital output trigger line.")
            if "/line" not in self._output_trigger.line.casefold():
                raise ValueError("The output trigger must select one digital output line.")
            timing_values = (
                self._output_trigger.phase_angle,
                self._output_trigger.delay,
                self._output_trigger.high_time,
                self._output_trigger.low_time,
            )
            if not all(np.isfinite(value) for value in timing_values):
                raise ValueError("Output trigger timing values must all be finite.")
            if not 0.0 <= self._output_trigger.phase_angle <= 360.0:
                raise ValueError("Output trigger phase must be between 0 and 360 degrees.")
            if self._output_trigger.delay < 0:
                raise ValueError("Output trigger delay cannot be negative.")
            if self._output_trigger.high_time <= 0 or self._output_trigger.low_time <= 0:
                raise ValueError("Output trigger high and low times must be positive.")

    def connect(self) -> None:
        """Create and verify all selected DAQmx tasks."""
        self.disconnect()
        runtime: Any | None = None
        input_task: Any | None = None
        output_task: Any | None = None
        trigger_output_task: Any | None = None
        try:
            self._validate_configuration()
            runtime = self._runtime_factory()
            input_task = runtime.create_task(self._acquisition_definition)
            runtime.verify_task(
                input_task, DaqmxTaskKind.ACQUISITION, DaqmxChannelFamily.ANALOG
            )
            if self._output_enabled:
                output_task = runtime.create_task(self._output_definition)
                runtime.verify_task(
                    output_task, DaqmxTaskKind.OUTPUT, DaqmxChannelFamily.ANALOG
                )
            if self._output_trigger.enabled:
                trigger_output_task = runtime.create_digital_output_task(self._output_trigger.line)
                runtime.verify_task(
                    trigger_output_task, DaqmxTaskKind.OUTPUT, DaqmxChannelFamily.DIGITAL
                )
        except Exception:
            if runtime is not None:
                for task in (trigger_output_task, output_task, input_task):
                    if task is not None:
                        with suppress(Exception):
                            runtime.close(task)
            raise
        self._runtime = runtime
        self._input_task = input_task
        self._output_task = output_task
        self._trigger_output_task = trigger_output_task

    def configure(self) -> None:
        """Configure one reusable finite acquisition window and its dependants."""
        if self._runtime is None or self._input_task is None:
            raise RuntimeError("Not connected - call connect() before configure().")
        self._configured = False
        try:
            self._validate_configuration()
            rate = self._sample_rate_hz
            samples = self._oversampling
            self._runtime.prepare_for_configuration(self._input_task)
            self._runtime.configure_finite_timing(self._input_task, rate, samples)
            self._runtime.configure_input_start_trigger(self._input_task, self._input_trigger)
            sample_clock_source = ""
            if self._output_task is not None or self._trigger_output_task is not None:
                sample_clock_source = self._runtime.input_sample_clock_source(self._input_task)
            if self._output_task is not None:
                self._runtime.prepare_for_configuration(self._output_task)
                self._runtime.configure_finite_timing(
                    self._output_task, rate, samples, source=sample_clock_source
                )
                self._runtime.configure_output_start_from_input(self._output_task, self._input_task)
                self._runtime.commit_task(self._output_task)
            if self._trigger_output_task is not None:
                values = _build_output_trigger_values(self._output_trigger, rate, samples)
                self._runtime.prepare_for_configuration(self._trigger_output_task)
                self._runtime.configure_finite_timing(
                    self._trigger_output_task,
                    rate,
                    samples,
                    source=sample_clock_source,
                )
                self._runtime.configure_output_start_from_input(
                    self._trigger_output_task, self._input_task
                )
                self._runtime.write_output(self._trigger_output_task, values)
                self._runtime.commit_task(self._trigger_output_task)
            self._runtime.commit_task(self._input_task)
            channel_names = self._runtime.channel_names(self._input_task)
            if not channel_names:
                raise ValueError("The acquisition task contains no input channels.")
            self._input_channel_names = channel_names
            self._means = {name: np.nan for name in channel_names}
            self._standard_deviations = {name: np.nan for name in channel_names}
            self._configured = True
            if self.sequence_engine is not None:
                self.sequence_engine.refresh_data_catalogs()
        except Exception:
            self._input_channel_names = ()
            self._means = {}
            self._standard_deviations = {}
            raise

    def set_state(self, value: float) -> None:
        """Generate one output point, acquire samples, and calculate statistics."""
        if not self._configured or self._runtime is None or self._input_task is None:
            raise RuntimeError("Plugin must be connected and configured before scanning.")
        target = float(value)
        if not np.isfinite(target):
            raise ValueError("DAQmx output values must be finite.")
        samples = self._oversampling
        timeout = max(10.0, (samples / self._sample_rate_hz) * 3.0 + 2.0)
        try:
            if self._output_task is not None:
                self._runtime.write_output(self._output_task, np.full(samples, target, dtype=float))
                self._runtime.start(self._output_task)
            if self._trigger_output_task is not None:
                self._runtime.start(self._trigger_output_task)
            self._runtime.start(self._input_task)
            raw = np.asarray(self._runtime.read(self._input_task, samples, timeout), dtype=float)
            if self._output_task is not None:
                self._runtime.wait_until_done(self._output_task, timeout)
            if self._trigger_output_task is not None:
                self._runtime.wait_until_done(self._trigger_output_task, timeout)
        finally:
            self._runtime.stop(self._input_task)
            if self._trigger_output_task is not None:
                self._runtime.stop(self._trigger_output_task)
            if self._output_task is not None:
                self._runtime.stop(self._output_task)
        if raw.ndim == 1:
            raw = raw[np.newaxis, :]
        expected_shape = (len(self._input_channel_names), samples)
        if raw.shape != expected_shape:
            raise ValueError(
                f"DAQmx returned acquisition shape {raw.shape}; expected {expected_shape}."
            )
        self._means = {
            name: float(np.mean(raw[index])) for index, name in enumerate(self._input_channel_names)
        }
        self._standard_deviations = {
            name: float(np.std(raw[index])) for index, name in enumerate(self._input_channel_names)
        }
        self._target_value = target
        self.state_changed.emit(target)

    def get_state(self) -> float:
        """Return the most recently completed output point."""
        return self._target_value

    def is_at_target(self) -> bool:
        """Return true because acquisition completes synchronously in ``set_state``."""
        return True

    def get_mean(self, channel: str) -> float | None:
        """Return the most recent mean for *channel*."""
        return self._means.get(channel)

    def get_standard_deviation(self, channel: str) -> float | None:
        """Return the most recent population standard deviation for *channel*."""
        return self._standard_deviations.get(channel)

    def _reported_channel_names(self) -> tuple[str, ...]:
        if self._input_channel_names:
            return self._input_channel_names
        definition = self._acquisition_definition
        if definition.selection_mode is DaqmxSelectionMode.PHYSICAL_CHANNELS:
            return definition.physical_channels
        if definition.selection_mode is DaqmxSelectionMode.GLOBAL_CHANNELS:
            return definition.global_channels
        return ()

    def reported_values(self) -> dict[str, str]:
        """Report a mean and standard deviation for every input channel."""
        values = super().reported_values()
        var = self.instance_name
        for channel in self._reported_channel_names():
            values[f"{var}:{channel} Mean"] = f"{var}.get_mean({channel!r})"
            values[f"{var}:{channel} Standard Deviation"] = (
                f"{var}.get_standard_deviation({channel!r})"
            )
        return values

    def reported_value_units(self) -> dict[str, str]:
        """Report input statistics without guessing DAQmx scale units."""
        units = super().reported_value_units()
        var = self.instance_name
        for channel in self._reported_channel_names():
            units[f"{var}:{channel} Mean"] = ""
            units[f"{var}:{channel} Standard Deviation"] = ""
        return units

    def disconnect(self) -> None:
        """Stop and close every task owned by this plugin."""
        runtime, self._runtime = self._runtime, None
        input_task, self._input_task = self._input_task, None
        output_task, self._output_task = self._output_task, None
        trigger_output_task, self._trigger_output_task = self._trigger_output_task, None
        self._configured = False
        self._input_channel_names = ()
        failures: list[Exception] = []
        if runtime is not None:
            for task in (trigger_output_task, output_task, input_task):
                if task is not None:
                    try:
                        runtime.stop(task)
                    except Exception as exc:
                        failures.append(exc)
                    try:
                        runtime.close(task)
                    except Exception as exc:
                        failures.append(exc)
        if failures:
            raise RuntimeError(
                "One or more DAQmx tasks could not be released cleanly."
            ) from failures[0]

    def to_json(self) -> dict[str, Any]:
        """Serialize task, timing, scan, and changed advanced settings."""
        data = super().to_json()
        data.update(self.daqmx_configuration_to_json())
        return data

    def daqmx_configuration_to_json(self) -> dict[str, Any]:
        """Return the reusable DAQmx configuration without plugin metadata."""
        data = {
            "acquisition_task": self._acquisition_definition.to_dict(),
            "output_enabled": self._output_enabled,
            "output_task": self._output_definition.to_dict(),
            "sample_rate_hz": self._sample_rate_hz,
            "oversampling": self._oversampling,
        }
        if self._input_trigger != DaqmxInputTrigger():
            data["input_trigger"] = self._input_trigger.to_dict()
        if self._output_trigger != DaqmxOutputTrigger():
            data["output_trigger"] = self._output_trigger.to_dict()
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        super()._restore_from_json(data)
        self.restore_daqmx_configuration(data)

    def restore_daqmx_configuration(self, data: dict[str, Any]) -> None:
        """Restore task, timing, and trigger settings from *data*."""
        if "acquisition_task" in data:
            self._acquisition_definition = DaqmxTaskDefinition.from_dict(data["acquisition_task"])
        if "output_task" in data:
            self._output_definition = DaqmxTaskDefinition.from_dict(data["output_task"])
        self._output_enabled = bool(data.get("output_enabled", self._output_enabled))
        self._sample_rate_hz = float(data.get("sample_rate_hz", self._sample_rate_hz))
        self._oversampling = max(1, int(data.get("oversampling", self._oversampling)))
        self._input_trigger = (
            DaqmxInputTrigger.from_dict(data["input_trigger"])
            if "input_trigger" in data
            else DaqmxInputTrigger()
        )
        self._output_trigger = (
            DaqmxOutputTrigger.from_dict(data["output_trigger"])
            if "output_trigger" in data
            else DaqmxOutputTrigger()
        )

    def _plugin_config_tabs(self) -> QWidget:
        """Return the shared General and Advanced DAQmx settings pages."""
        return DaqmxPointScanSettingsWidget(self)


__all__ = ["DaqmxPointScanPlugin", "DaqmxPointScanSettingsWidget"]
