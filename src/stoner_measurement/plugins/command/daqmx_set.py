"""One-shot NI-DAQmx set-and-acquire command."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qtpy.QtWidgets import QFormLayout, QGroupBox, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.plugins.state_scan.daqmx import (
    DaqmxPointScanPlugin,
    DaqmxPointScanSettingsWidget,
)
from stoner_measurement.plugins.trace.daqmx_runtime import NidaqmxRuntime
from stoner_measurement.ui.widgets import SISpinBox


class DaqmxSetSettingsWidget(DaqmxPointScanSettingsWidget):
    """Single value control followed by the shared DAQmx point settings."""

    def __init__(self, command: DaqmxSetCommand, parent: QWidget | None = None) -> None:
        self._command = command
        super().__init__(command._point_plugin, parent)
        stimulus = QGroupBox("Output point", self.general_page)
        form = QFormLayout(stimulus)
        self.value_spin = SISpinBox(
            stimulus,
            allow_expressions=True,
            value=command._value,
        )
        self.value_spin.setObjectName("daqmx_set_value")
        self.value_spin.setMinimum(-1.0e12)
        self.value_spin.setMaximum(1.0e12)
        self.value_spin.setToolTip(
            "Output value or sequence expression evaluated whenever this command runs."
        )
        form.addRow("Output value", self.value_spin)
        self.value_spin.valueChanged.connect(self._set_value)
        self.general_layout.insertWidget(0, stimulus)

    def _set_value(self, value: float | str) -> None:
        self._command._value = value


class DaqmxSetCommand(CommandPlugin):
    """Set one DAQmx value and perform one synchronized point acquisition.

    Use this leaf command when a sequence needs one DAQmx set-and-acquire
    operation rather than a DAQmx-controlled scan. The output value may be a
    number or an expression evaluated in the live sequence namespace whenever
    the command runs. This makes the command suitable inside an outer
    temperature, field, motor, or other state scan. Use
    :class:`~stoner_measurement.plugins.state_scan.daqmx.DaqmxPointScanPlugin`
    when DAQmx itself should define the repeated scan axis, or
    :class:`~stoner_measurement.plugins.trace.daqmx.DaqmxTracePlugin` for one
    buffered multi-point trace.

    Set DAQmx has one command configuration page and no scan-generator or data
    collection page. The nested **General** page starts with the
    expression-capable **Output value**, followed by acquisition timing and
    task selection. **Generate an output value** enables the DAQmx output-task
    selector and is checked by default. Uncheck it to use the command as a
    one-shot acquisition only. The page also displays the resulting
    point-acquisition time.

    Acquisition and output tasks may be selected from direct physical
    channels, NI MAX global channels, or saved tasks. Acquisition and
    value-output tasks are restricted to analogue channels, and custom NI
    scales may be used with physical channels. Each physical input has its own
    symmetric range, defaulting to +/-10 V and populated from the device where
    possible. A common RSE, NRSE, or differential mode applies to all selected
    physical inputs. Counter channels are not supported.

    Each execution creates and verifies the selected tasks, writes the output
    value as a constant buffer for the configured number of samples, and
    acquires the matching input window. It publishes ``Output value`` plus a
    population mean and population standard deviation for every discovered
    input channel. The channel results appear as ``<channel> Mean`` and
    ``<channel> Standard Deviation`` in the sequence value catalogue. All DAQmx
    tasks are stopped and released before the command returns, including when
    execution fails.

    The **Advanced** page configures an immediate, digital-edge, or
    analogue-edge input trigger and an optional synchronized digital output
    pulse. Input triggering is applied to the acquisition task. The pulse is a
    separate one-line hardware-timed output task that shares the acquisition
    clock and internal start event, and it is generated once per command
    execution. Phase is the normalized position within this single point's
    acquisition window. Pulse delay and high/low times must be representable at
    the configured acquisition rate and fit inside the window.

    Because this is a command plugin, it connects, configures, measures, and
    disconnects on every execution. That lifecycle is convenient for isolated
    operations but has more overhead than DAQmx Point Scan, which retains its
    tasks across all points. Automatic synchronization routing also assumes
    compatible NI hardware and should be verified for cross-device tasks.

    Attributes:
        _value (float | str):
            Literal output value or sequence expression evaluated at runtime.
        _last_value (float | None):
            Evaluated value used by the most recent successful execution.
        _point_plugin (DaqmxPointScanPlugin):
            Shared implementation of task configuration, triggering,
            acquisition, reduction, and cleanup.
        _channel_names (tuple[str, ...]):
            Input channel names discovered during the most recent execution.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Place Set DAQmx beneath a temperature scan and enter an expression such
        as ``bias_voltage`` for **Output value**. Every outer-loop iteration
        evaluates the current expression, generates that value for one finite
        acquisition window, and publishes the new input statistics for later
        commands.
    """

    def __init__(
        self,
        parent=None,
        *,
        runtime_factory: Callable[[], Any] = NidaqmxRuntime,
    ) -> None:
        super().__init__(parent)
        self._value: float | str = 0.0
        self._last_value: float | None = None
        self._channel_names: tuple[str, ...] = ()
        self._point_plugin = DaqmxPointScanPlugin(
            parent=self,
            runtime_factory=runtime_factory,
        )
        self._point_plugin._output_enabled = True
        self._apply_initial_config()

    @property
    def name(self) -> str:
        """Plugin catalogue name."""
        return "Set DAQmx"

    def execute(self) -> None:
        """Evaluate and perform one complete DAQmx point acquisition."""
        value = self.eval_float(self._value)
        try:
            self._point_plugin.connect()
            self._point_plugin.configure()
            self._point_plugin.set_state(value)
            discovered = self._point_plugin._reported_channel_names()
            channels_changed = discovered != self._channel_names
            self._channel_names = discovered
            self._last_value = value
            if channels_changed and self.sequence_engine is not None:
                self.sequence_engine.refresh_data_catalogs()
        finally:
            self._point_plugin.disconnect()

    def get_mean(self, channel: str) -> float | None:
        """Return the most recent mean for *channel*."""
        return self._point_plugin.get_mean(channel)

    def get_standard_deviation(self, channel: str) -> float | None:
        """Return the most recent population standard deviation for *channel*."""
        return self._point_plugin.get_standard_deviation(channel)

    def reported_values(self) -> dict[str, str]:
        """Publish the evaluated output value and every input statistic."""
        var = self.instance_name
        values = {f"{var}:Output value": f"{var}._last_value"}
        for channel in self._reported_channel_names():
            values[f"{var}:{channel} Mean"] = f"{var}.get_mean({channel!r})"
            values[f"{var}:{channel} Standard Deviation"] = (
                f"{var}.get_standard_deviation({channel!r})"
            )
        return values

    def reported_value_units(self) -> dict[str, str]:
        """Report the output unit without guessing DAQmx input scale units."""
        var = self.instance_name
        units = {f"{var}:Output value": self._point_plugin.units}
        for channel in self._reported_channel_names():
            units[f"{var}:{channel} Mean"] = ""
            units[f"{var}:{channel} Standard Deviation"] = ""
        return units

    def _reported_channel_names(self) -> tuple[str, ...]:
        """Return discovered names, falling back to configured channel names."""
        return self._channel_names or self._point_plugin._reported_channel_names()

    def to_json(self) -> dict[str, Any]:
        """Serialize the value and shared DAQmx configuration."""
        data = super().to_json()
        data["value"] = self._value
        data.update(self._point_plugin.daqmx_configuration_to_json())
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        super()._restore_from_json(data)
        self._value = data.get("value", self._value)
        self._point_plugin.restore_daqmx_configuration(data)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return the single-value and shared DAQmx settings widget."""
        return DaqmxSetSettingsWidget(self, parent)

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Allow the shared DAQmx settings box to fill the command tab."""
        tabs = super().config_tabs(parent)
        layout = tabs[0][1].layout()
        if layout is not None:
            for index in range(layout.count()):
                widget = layout.itemAt(index).widget()
                if isinstance(widget, DaqmxSetSettingsWidget):
                    layout.setStretch(index, 1)
                    break
        return tabs


__all__ = ["DaqmxSetCommand", "DaqmxSetSettingsWidget"]
