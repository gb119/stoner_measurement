"""Hardware-timed NI-DAQmx acquisition and generation trace plugin."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from qtpy.QtCore import Qt  # type: ignore[attr-defined]
from qtpy.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.trace_data import COLUMN_ROLE_Y, COLUMN_ROLE_Z, TraceData
from stoner_measurement.plugins.trace.base import TracePlugin, TraceStatus
from stoner_measurement.plugins.trace.daqmx_runtime import (
    NidaqmxRuntime,
    validate_task_definition,
)
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.widgets import (
    DaqmxInputTrigger,
    DaqmxInputTriggerMode,
    DaqmxInputTriggerWidget,
    DaqmxOutputTrigger,
    DaqmxOutputTriggerWidget,
    DaqmxSystemInfo,
    DaqmxTaskDefinition,
    DaqmxTaskDefinitionWidget,
    DaqmxTaskKind,
    DaqmxTriggerIdleState,
    SISpinBox,
)


def _duration_in_samples(name: str, duration: float, rate: float) -> int:
    """Convert a positive pulse duration to representable hardware samples."""
    samples = int(round(duration * rate))
    if samples < 1:
        raise ValueError(
            f"Output trigger {name} ({duration:g} s) is shorter than the "
            f"hardware sample period ({1.0 / rate:g} s)."
        )
    return samples


def _build_output_trigger_values(
    trigger: DaqmxOutputTrigger, rate: float, sample_count: int
) -> np.ndarray:
    """Build one finite digital pulse synchronized to the generated scan."""
    high_samples = _duration_in_samples("high time", trigger.high_time, rate)
    low_samples = _duration_in_samples("low time", trigger.low_time, rate)
    delay_samples = 0
    if trigger.delay > 0:
        delay_samples = _duration_in_samples("delay", trigger.delay, rate)
    phase_sample = int(round((trigger.phase_angle / 360.0) * sample_count))
    active_samples, trailing_samples = (
        (high_samples, low_samples)
        if trigger.idle_state is DaqmxTriggerIdleState.LOW
        else (low_samples, high_samples)
    )
    active_start = phase_sample + delay_samples
    required_samples = active_start + active_samples + trailing_samples
    if required_samples > sample_count:
        raise ValueError(
            "The output trigger phase, delay, pulse, and trailing idle time do not "
            "fit within the generated scan."
        )
    idle = trigger.idle_state is DaqmxTriggerIdleState.HIGH
    values = np.full(sample_count, idle, dtype=bool)
    values[active_start : active_start + active_samples] = not idle
    return values


class DaqmxTraceSettingsWidget(FontAwareTabWidget):
    """General DAQmx task/timing controls and reusable trigger configuration."""

    def __init__(
        self,
        plugin: DaqmxTracePlugin,
        parent: QWidget | None = None,
        *,
        point_timing: bool = False,
    ) -> None:
        super().__init__(parent)
        self._plugin = plugin
        self._point_timing = point_timing
        self.addTab(self._build_general_page(), "General")
        self.addTab(self._build_advanced_page(), "Advanced")

    def _build_general_page(self) -> QScrollArea:
        self.general_scroll = QScrollArea(self)
        self.general_scroll.setWidgetResizable(True)
        self.general_scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget(self.general_scroll)
        self.general_page = page
        layout = QVBoxLayout(page)
        self.general_layout = layout
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        timing_group = QGroupBox("Hardware timing", page)
        timing_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        timing_form = QFormLayout(timing_group)
        self.sample_rate_spin = SISpinBox(
            timing_group,
            value=self._plugin._sample_rate_hz,
            suffix="Hz",
            siPrefix=True,
        )
        self.sample_rate_spin.setMinimum(0.001)
        self.sample_rate_spin.setMaximum(10_000_000.0)
        rate_label = "Acquisition sample rate" if self._point_timing else "Scan point rate"
        timing_form.addRow(rate_label, self.sample_rate_spin)
        self.oversampling_spin = QSpinBox(timing_group)
        self.oversampling_spin.setRange(1, 100_000)
        self.oversampling_spin.setValue(self._plugin._oversampling)
        oversampling_label = "Samples per point" if self._point_timing else "Input oversampling"
        timing_form.addRow(oversampling_label, self.oversampling_spin)
        self.input_rate_label = QLabel(timing_group)
        derived_label = "Point acquisition time" if self._point_timing else "Hardware sample rate"
        timing_form.addRow(derived_label, self.input_rate_label)
        self.sample_rate_spin.valueChanged.connect(self._set_sample_rate)
        self.oversampling_spin.valueChanged.connect(self._set_oversampling)
        self._refresh_input_rate()
        layout.addWidget(timing_group)

        acquisition_group = QGroupBox("Acquisition task", page)
        acquisition_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        acquisition_layout = QVBoxLayout(acquisition_group)
        self.acquisition_widget = DaqmxTaskDefinitionWidget(
            acquisition_group, task_kind=DaqmxTaskKind.ACQUISITION
        )
        self.acquisition_widget.set_definition(self._plugin._acquisition_definition)
        self.acquisition_widget.definition_changed.connect(self._set_acquisition_definition)
        self.acquisition_widget.snapshot_changed.connect(self._set_trigger_resources)
        acquisition_layout.addWidget(self.acquisition_widget)
        layout.addWidget(acquisition_group)

        output_label = (
            "Generate an output value" if self._point_timing else "Generate an output waveform"
        )
        self.output_enabled_check = QCheckBox(output_label, page)
        self.output_enabled_check.setChecked(self._plugin._output_enabled)
        layout.addWidget(self.output_enabled_check)
        self.output_group = QGroupBox("Output task", page)
        self.output_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        output_layout = QVBoxLayout(self.output_group)
        self.output_widget = DaqmxTaskDefinitionWidget(
            self.output_group, task_kind=DaqmxTaskKind.OUTPUT
        )
        self.output_widget.set_definition(self._plugin._output_definition)
        self.output_widget.definition_changed.connect(self._set_output_definition)
        self.output_widget.snapshot_changed.connect(self._set_trigger_resources)
        output_layout.addWidget(self.output_widget)
        self.output_group.setEnabled(self._plugin._output_enabled)
        self.output_enabled_check.toggled.connect(self._set_output_enabled)
        layout.addWidget(self.output_group)
        layout.addStretch(1)
        self.general_scroll.setWidget(page)
        return self.general_scroll

    def _build_advanced_page(self) -> QScrollArea:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.advanced_scroll = scroll
        page = QWidget(scroll)
        self.advanced_page = page
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.input_trigger_widget = DaqmxInputTriggerWidget(
            page, trigger=self._plugin._input_trigger
        )
        self.output_trigger_widget = DaqmxOutputTriggerWidget(
            page, trigger=self._plugin._output_trigger
        )
        self.input_trigger_widget.trigger_changed.connect(self._set_input_trigger)
        self.output_trigger_widget.trigger_changed.connect(self._set_output_trigger)
        alignment = Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        layout.addWidget(self.input_trigger_widget, 0, alignment)
        layout.addWidget(self.output_trigger_widget, 0, alignment)
        layout.addStretch(1)
        scroll.setWidget(page)
        return scroll

    def _set_input_trigger(self, value: DaqmxInputTrigger) -> None:
        self._plugin._input_trigger = value

    def _set_output_trigger(self, value: DaqmxOutputTrigger) -> None:
        self._plugin._output_trigger = value

    def _set_trigger_resources(self, snapshot: DaqmxSystemInfo) -> None:
        terminals = tuple(terminal for device in snapshot.devices for terminal in device.terminals)
        lines = tuple(
            line
            for device in snapshot.devices
            for line in device.digital_outputs
            if "/line" in line.casefold()
        )
        self.input_trigger_widget.set_available_terminals(terminals)
        self.output_trigger_widget.set_available_lines(lines)

    def _set_acquisition_definition(self, value: DaqmxTaskDefinition) -> None:
        self._plugin._acquisition_definition = value

    def _set_output_definition(self, value: DaqmxTaskDefinition) -> None:
        self._plugin._output_definition = value

    def _set_output_enabled(self, enabled: bool) -> None:
        self._plugin._output_enabled = enabled
        self.output_group.setEnabled(enabled)

    def _set_sample_rate(self, value: float) -> None:
        self._plugin._sample_rate_hz = value
        self._refresh_input_rate()

    def _set_oversampling(self, value: int) -> None:
        self._plugin._oversampling = value
        self._refresh_input_rate()

    def _refresh_input_rate(self) -> None:
        if self._point_timing:
            duration = self.oversampling_spin.value() / self.sample_rate_spin.value()
            self.input_rate_label.setText(f"{duration:g} s")
        else:
            input_rate = self.sample_rate_spin.value() * self.oversampling_spin.value()
            self.input_rate_label.setText(f"{input_rate:g} Hz")


class DaqmxTracePlugin(TracePlugin):
    """Acquire a hardware-timed DAQmx trace with optional synchronized output.

    Use this plugin when a complete input trace should be acquired as one
    finite NI-DAQmx operation. The scan generator supplies the x values. If
    output generation is enabled, those values are also written to the
    selected output task while the acquisition runs. This is the most
    efficient DAQmx workflow when no other sequence steps need to execute
    between points. Use
    :class:`~stoner_measurement.plugins.state_scan.daqmx.DaqmxPointScanPlugin`
    when nested sequence steps must run at every value, or
    :class:`~stoner_measurement.plugins.command.daqmx_set.DaqmxSetCommand`
    for one set-and-acquire operation.

    The **Scan** tab defines the finite sequence of values. On the **Settings**
    tab, the nested **General** page sets the scan-point rate, input
    oversampling, acquisition task, and optional output task. Acquisition
    channels may be selected directly from a device, from NI MAX global
    channels, or by loading a saved task. Physical analogue and digital input
    channels are supported. The optional output task similarly supports
    analogue or digital outputs. Custom NI scales may be selected for analogue
    physical channels. Counter input and output channels are not supported.

    The configured scan-point rate is multiplied by **Input oversampling** to
    obtain the hardware sample rate. Every scan value occupies that many
    consecutive hardware samples. The output buffer repeats the value across
    the same window, and the acquisition samples in the window are averaged to
    produce one result. The returned ``DAQmx Trace`` contains ``Scan value`` as
    its x column and one floating-point data column for every discovered input
    channel. The first input is assigned the y role and subsequent inputs the
    z role, so the trace can be consumed directly by plot, save, fit, and
    transform plugins.

    The **Advanced** page configures input and output triggering. The input
    task may start immediately or from a rising or falling digital or analogue
    edge. An analogue edge also has a trigger-level setting. Input triggering
    is applied to the acquisition task, which remains the timing master.

    **Generate an output trigger pulse** creates a separate one-line,
    hardware-timed digital-output task. It shares the acquisition sample clock
    and is armed from the acquisition task's internal start event. **Phase** is
    a normalized position through the generated scan: 0 degrees is the start
    and 360 degrees is the end. Delay, high time, low time, and idle polarity
    define the pulse around that position. All pulse times are quantized to the
    hardware sample period and the complete pulse must fit inside the finite
    scan. Optional waveform and trigger-output tasks are armed before the
    acquisition task so that an external input trigger starts them together.

    Direct physical channels, global channels, and saved tasks must resolve to
    compatible DAQmx task types. Automatic sample-clock and start-event routing
    is based on the acquisition device's internal terminals. Some device
    combinations require explicit NI routing that this plugin cannot infer;
    cross-device synchronization should therefore be verified on the intended
    hardware.

    Attributes:
        scan_generator (BaseScanGenerator):
            Generator defining the trace values and finite point count.
        _sample_rate_hz (float):
            Requested scan-point rate in hertz.
        _oversampling (int):
            Number of acquisition samples averaged for each scan value.
        _output_enabled (bool):
            Whether the scan values are generated by the output task.
        _input_trigger (DaqmxInputTrigger):
            Start-trigger configuration applied to the acquisition task.
        _output_trigger (DaqmxOutputTrigger):
            Optional synchronized digital pulse configuration.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        For a voltage-driven analogue-input trace, select an ``ao`` channel as
        the output task, one or more ``ai`` channels as the acquisition task,
        choose a scan generator, and enable output generation. A point rate of
        100 Hz with oversampling 10 runs the hardware at 1 kHz and returns one
        averaged reading every 10 ms.
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
        self._scan_values: np.ndarray | None = None
        self._input_channel_names: tuple[str, ...] = ()
        self._configured = False
        self._apply_initial_config()

    @property
    def name(self) -> str:
        """Plugin catalogue name."""
        return "DAQmx Trace"

    @property
    def x_label(self) -> str:
        """Label for scan-generator values."""
        return "Scan value"

    @property
    def y_label(self) -> str:
        """Generic label for discovered acquisition channels."""
        return "DAQmx input"

    def _validate_configuration(self) -> None:
        if self._acquisition_definition.task_kind is not DaqmxTaskKind.ACQUISITION:
            raise ValueError("The acquisition task definition has the wrong direction.")
        validate_task_definition(self._acquisition_definition)
        if self._output_enabled:
            if self._output_definition.task_kind is not DaqmxTaskKind.OUTPUT:
                raise ValueError("The output task definition has the wrong direction.")
            validate_task_definition(self._output_definition)
        if not np.isfinite(self._sample_rate_hz) or self._sample_rate_hz <= 0:
            raise ValueError("The scan/output sample rate must be positive.")
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
        """Create and verify DAQmx tasks without starting acquisition or output."""
        self.disconnect()
        self._set_status(TraceStatus.CONNECTING)
        runtime: Any | None = None
        input_task: Any | None = None
        output_task: Any | None = None
        trigger_output_task: Any | None = None
        try:
            self._validate_configuration()
            runtime = self._runtime_factory()
            input_task = runtime.create_task(self._acquisition_definition)
            runtime.verify_task(input_task, DaqmxTaskKind.ACQUISITION)
            if self._output_enabled:
                output_task = runtime.create_task(self._output_definition)
                runtime.verify_task(output_task, DaqmxTaskKind.OUTPUT)
            if self._output_trigger.enabled:
                trigger_output_task = runtime.create_digital_output_task(self._output_trigger.line)
                runtime.verify_task(trigger_output_task, DaqmxTaskKind.OUTPUT)
        except Exception:
            if runtime is not None:
                for task in (trigger_output_task, output_task, input_task):
                    if task is not None:
                        with suppress(Exception):
                            runtime.close(task)
            self._set_status(TraceStatus.ERROR)
            raise
        self._runtime = runtime
        self._input_task = input_task
        self._output_task = output_task
        self._trigger_output_task = trigger_output_task
        self._set_status(TraceStatus.IDLE)

    def configure(self) -> None:
        """Configure finite clocks, synchronization, buffers, and resource commits."""
        if self._runtime is None or self._input_task is None:
            raise RuntimeError("Not connected — call connect() before configure().")
        self._set_status(TraceStatus.CONFIGURING)
        self._configured = False
        try:
            self._validate_configuration()
            scan_values = np.asarray(self.scan_generator.generate(), dtype=float)
            if scan_values.ndim != 1 or scan_values.size < 2:
                raise ValueError("The DAQmx trace scan must contain at least two points.")
            if not np.all(np.isfinite(scan_values)):
                raise ValueError("DAQmx output scan values must all be finite.")

            self._runtime.prepare_for_configuration(self._input_task)
            hardware_rate = self._sample_rate_hz * self._oversampling
            hardware_samples = scan_values.size * self._oversampling
            self._runtime.configure_finite_timing(
                self._input_task,
                hardware_rate,
                hardware_samples,
            )
            self._runtime.configure_input_start_trigger(self._input_task, self._input_trigger)
            sample_clock_source = ""
            if self._output_task is not None or self._trigger_output_task is not None:
                sample_clock_source = self._runtime.input_sample_clock_source(self._input_task)
            if self._output_task is not None:
                self._runtime.prepare_for_configuration(self._output_task)
                self._runtime.configure_finite_timing(
                    self._output_task,
                    hardware_rate,
                    hardware_samples,
                    source=sample_clock_source,
                )
                self._runtime.configure_output_start_from_input(self._output_task, self._input_task)
                self._runtime.write_output(
                    self._output_task, np.repeat(scan_values, self._oversampling)
                )
                self._runtime.commit_task(self._output_task)
            if self._trigger_output_task is not None:
                trigger_values = _build_output_trigger_values(
                    self._output_trigger, hardware_rate, hardware_samples
                )
                self._runtime.prepare_for_configuration(self._trigger_output_task)
                self._runtime.configure_finite_timing(
                    self._trigger_output_task,
                    hardware_rate,
                    hardware_samples,
                    source=sample_clock_source,
                )
                self._runtime.configure_output_start_from_input(
                    self._trigger_output_task, self._input_task
                )
                self._runtime.write_output(self._trigger_output_task, trigger_values)
                self._runtime.commit_task(self._trigger_output_task)
            self._runtime.commit_task(self._input_task)
            channel_names = self._runtime.channel_names(self._input_task)
            if not channel_names:
                raise ValueError("The acquisition task contains no input channels.")
            self._scan_values = scan_values
            self._input_channel_names = channel_names
            self._configured = True
        except Exception:
            self._scan_values = None
            self._input_channel_names = ()
            self._set_status(TraceStatus.ERROR)
            raise
        self._set_status(TraceStatus.IDLE)

    def _measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Run one finite synchronized acquisition and reduce oversampled windows."""
        _ = parameters
        if (
            not self._configured
            or self._runtime is None
            or self._input_task is None
            or self._scan_values is None
        ):
            raise RuntimeError("Plugin must be connected and configured before measuring.")
        point_count = self._scan_values.size
        sample_count = point_count * self._oversampling
        timeout = max(10.0, (point_count / self._sample_rate_hz) * 3.0 + 2.0)
        try:
            if self._output_task is not None:
                self._runtime.start(self._output_task)
            if self._trigger_output_task is not None:
                self._runtime.start(self._trigger_output_task)
            self._runtime.start(self._input_task)
            raw = np.asarray(
                self._runtime.read(self._input_task, sample_count, timeout), dtype=float
            )
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
        expected_shape = (len(self._input_channel_names), sample_count)
        if raw.shape != expected_shape:
            raise ValueError(
                f"DAQmx returned acquisition shape {raw.shape}; expected {expected_shape}."
            )
        reduced = raw.reshape(len(self._input_channel_names), point_count, self._oversampling).mean(
            axis=2
        )
        columns: dict[str, np.ndarray] = {"x": self._scan_values.copy()}
        roles: dict[str, str] = {}
        for index, channel_name in enumerate(self._input_channel_names):
            columns[channel_name] = reduced[index]
            roles[channel_name] = COLUMN_ROLE_Y if index == 0 else COLUMN_ROLE_Z
        return {
            self.name: TraceData(
                pd.DataFrame(columns),
                column_roles=roles,
                names={"x": self.x_label, **{name: name for name in self._input_channel_names}},
            )
        }

    def disconnect(self) -> None:
        """Disarm pending operations and clear every owned DAQmx task."""
        runtime, self._runtime = self._runtime, None
        input_task, self._input_task = self._input_task, None
        output_task, self._output_task = self._output_task, None
        trigger_output_task, self._trigger_output_task = self._trigger_output_task, None
        self._configured = False
        self._scan_values = None
        self._input_channel_names = ()
        failures: list[Exception] = []
        if runtime is not None:
            self._set_status(TraceStatus.DISCONNECTING)
            for task in (trigger_output_task, output_task, input_task):
                if task is not None:
                    try:
                        runtime.stop(task)
                    except Exception as exc:  # preserve cleanup of the other owned task
                        failures.append(exc)
                    try:
                        runtime.close(task)
                    except Exception as exc:  # preserve cleanup of the other owned task
                        failures.append(exc)
        self._set_status(TraceStatus.IDLE)
        if failures:
            raise RuntimeError(
                "One or more DAQmx tasks could not be released cleanly."
            ) from failures[0]

    def to_json(self) -> dict[str, Any]:
        """Serialize task definitions, timing, and non-default advanced settings."""
        data = super().to_json()
        data.update(
            {
                "acquisition_task": self._acquisition_definition.to_dict(),
                "output_enabled": self._output_enabled,
                "output_task": self._output_definition.to_dict(),
                "sample_rate_hz": self._sample_rate_hz,
                "oversampling": self._oversampling,
            }
        )
        if self._input_trigger != DaqmxInputTrigger():
            data["input_trigger"] = self._input_trigger.to_dict()
        if self._output_trigger != DaqmxOutputTrigger():
            data["output_trigger"] = self._output_trigger.to_dict()
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        super()._restore_from_json(data)
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
        """Return nested General and Advanced DAQmx settings pages."""
        return DaqmxTraceSettingsWidget(self)


__all__ = ["DaqmxTracePlugin", "DaqmxTraceSettingsWidget"]
