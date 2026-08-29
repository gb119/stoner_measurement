"""Hardware-timed NI-DAQmx acquisition and generation trace plugin."""

from __future__ import annotations

from collections.abc import Callable
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.trace_data import COLUMN_ROLE_Y, COLUMN_ROLE_Z, TraceData
from stoner_measurement.plugins.trace.base import TracePlugin, TraceStatus
from stoner_measurement.plugins.trace.daqmx_runtime import (
    NidaqmxRuntime,
    validate_task_definition,
)
from stoner_measurement.ui.widgets import (
    DaqmxTaskDefinition,
    DaqmxTaskDefinitionWidget,
    DaqmxTaskKind,
    SISpinBox,
)


class DaqmxTraceSettingsWidget(QTabWidget):
    """General DAQmx task/timing controls and an advanced trigger placeholder."""

    def __init__(self, plugin: DaqmxTracePlugin, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plugin = plugin
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
        timing_form.addRow("Scan point rate", self.sample_rate_spin)
        self.oversampling_spin = QSpinBox(timing_group)
        self.oversampling_spin.setRange(1, 100_000)
        self.oversampling_spin.setValue(self._plugin._oversampling)
        timing_form.addRow("Input oversampling", self.oversampling_spin)
        self.input_rate_label = QLabel(timing_group)
        timing_form.addRow("Hardware sample rate", self.input_rate_label)
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
        acquisition_layout.addWidget(self.acquisition_widget)
        layout.addWidget(acquisition_group)

        self.output_enabled_check = QCheckBox("Generate an output waveform", page)
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
        output_layout.addWidget(self.output_widget)
        self.output_group.setEnabled(self._plugin._output_enabled)
        self.output_enabled_check.toggled.connect(self._set_output_enabled)
        layout.addWidget(self.output_group)
        layout.addStretch(1)
        self.general_scroll.setWidget(page)
        return self.general_scroll

    def _build_advanced_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        label = QLabel(
            "External start, reference, pause, and exported trigger routing will be "
            "configured here. For now, an enabled output task uses the acquisition "
            "sample clock and is armed from its internal start event.",
            page,
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)
        return page

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
        input_rate = self.sample_rate_spin.value() * self.oversampling_spin.value()
        self.input_rate_label.setText(f"{input_rate:g} Hz")


class DaqmxTracePlugin(TracePlugin):
    """Acquire a finite DAQmx trace, optionally with synchronized generation.

    The scan generator defines both the x values and the finite point count. An
    optional output task holds each value for one configured point interval.
    Input channels run at an integer multiple of the point rate; the output
    buffer repeats each value at that same hardware rate and shares the input
    sample clock. Consecutive input samples in each point window are averaged
    to return one reading per scan value.

    Physical AI/AO and DI/DO tasks are supported, as are compatible MAX global
    channels and saved tasks. Counter channels require measurement-specific
    configuration and are intentionally rejected for now. The Advanced page is
    reserved for explicit external and exported trigger routing.
    """

    def __init__(
        self,
        parent=None,
        *,
        runtime_factory: Callable[[], Any] = NidaqmxRuntime,
    ) -> None:
        super().__init__(parent)
        self._acquisition_definition = DaqmxTaskDefinition(
            task_kind=DaqmxTaskKind.ACQUISITION
        )
        self._output_definition = DaqmxTaskDefinition(task_kind=DaqmxTaskKind.OUTPUT)
        self._output_enabled = False
        self._sample_rate_hz = 1000.0
        self._oversampling = 1
        self._runtime_factory = runtime_factory
        self._runtime: Any | None = None
        self._input_task: Any | None = None
        self._output_task: Any | None = None
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

    def connect(self) -> None:
        """Create and verify DAQmx tasks without starting acquisition or output."""
        self.disconnect()
        self._set_status(TraceStatus.CONNECTING)
        runtime: Any | None = None
        input_task: Any | None = None
        output_task: Any | None = None
        try:
            self._validate_configuration()
            runtime = self._runtime_factory()
            input_task = runtime.create_task(self._acquisition_definition)
            runtime.verify_task(input_task, DaqmxTaskKind.ACQUISITION)
            if self._output_enabled:
                output_task = runtime.create_task(self._output_definition)
                runtime.verify_task(output_task, DaqmxTaskKind.OUTPUT)
        except Exception:
            if runtime is not None:
                for task in (output_task, input_task):
                    if task is not None:
                        runtime.close(task)
            self._set_status(TraceStatus.ERROR)
            raise
        self._runtime = runtime
        self._input_task = input_task
        self._output_task = output_task
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
            if self._output_task is not None:
                self._runtime.prepare_for_configuration(self._output_task)
                self._runtime.configure_finite_timing(
                    self._output_task,
                    hardware_rate,
                    hardware_samples,
                    source=self._runtime.input_sample_clock_source(self._input_task),
                )
                self._runtime.configure_output_start_from_input(
                    self._output_task, self._input_task
                )
                self._runtime.write_output(
                    self._output_task, np.repeat(scan_values, self._oversampling)
                )
                self._runtime.commit_task(self._output_task)
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
            self._runtime.start(self._input_task)
            raw = np.asarray(
                self._runtime.read(self._input_task, sample_count, timeout), dtype=float
            )
            if self._output_task is not None:
                self._runtime.wait_until_done(self._output_task, timeout)
        finally:
            self._runtime.stop(self._input_task)
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
        self._configured = False
        self._scan_values = None
        self._input_channel_names = ()
        failures: list[Exception] = []
        if runtime is not None:
            self._set_status(TraceStatus.DISCONNECTING)
            for task in (output_task, input_task):
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
        """Serialize task definitions and hardware timing."""
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
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        super()._restore_from_json(data)
        if "acquisition_task" in data:
            self._acquisition_definition = DaqmxTaskDefinition.from_dict(
                data["acquisition_task"]
            )
        if "output_task" in data:
            self._output_definition = DaqmxTaskDefinition.from_dict(data["output_task"])
        self._output_enabled = bool(data.get("output_enabled", self._output_enabled))
        self._sample_rate_hz = float(data.get("sample_rate_hz", self._sample_rate_hz))
        self._oversampling = max(1, int(data.get("oversampling", self._oversampling)))

    def _plugin_config_tabs(self) -> QWidget:
        """Return nested General and Advanced DAQmx settings pages."""
        return DaqmxTraceSettingsWidget(self)


__all__ = ["DaqmxTracePlugin", "DaqmxTraceSettingsWidget"]
