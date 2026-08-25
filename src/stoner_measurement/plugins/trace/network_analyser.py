"""Trace plugin for frequency- and power-swept network-analyser measurements."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core import COLUMN_ROLE_Y, COLUMN_ROLE_Z, TraceData
from stoner_measurement.instruments import (
    NetworkAnalyser,
    SweepConfiguration,
    SweepType,
    TraceFormat,
)
from stoner_measurement.instruments.transport import GpibTransport
from stoner_measurement.plugins._network_analyser_support import (
    NETWORK_ANALYSER_DRIVER_LABELS,
    NETWORK_ANALYSER_DRIVERS,
    OUTPUT_FORMATS,
    S_PARAMETERS,
    NetworkAnalyserModel,
    NetworkAnalyserSweepVariable,
    format_s_parameter_values,
    s_parameter_units,
)
from stoner_measurement.plugins.trace.base import TracePlugin, TraceStatus
from stoner_measurement.scan import NetworkAnalyserScanGenerator, RampMode
from stoner_measurement.ui.widgets import (
    FILTER_GPIB,
    SISpinBox,
    VisaResourceComboBox,
)


class NetworkAnalyserTracePlugin(TracePlugin):
    """Acquire an instrument-controlled frequency or source-power sweep.

    Use this trace plugin when the network analyser should perform a complete
    sweep internally and return all selected S-parameters together. This is
    the fastest of the network-analyser workflows and is intended for ordinary
    frequency-response or power-response traces. Use
    :class:`~stoner_measurement.plugins.state_scan.network_analyser.NetworkAnalyserPointScanPlugin`
    instead when other sequence steps must run at every analyser point.

    The **Scan** tab defines the start, stop, and number of points. Frequency
    sweeps may use linear or exponential (log-spaced) points; power sweeps are
    linear. Arbitrary lists and general waveform generators are unavailable
    because this plugin maps the requested points onto the analyser's native
    sweep modes. The **Settings** tab selects the Agilent E5062A or N5222A,
    GPIB resource, channel, sweep variable, complementary fixed frequency or
    power, IF bandwidth, averaging, correction state, timeout, S-parameters,
    and output representation.

    Each measurement returns one trace named ``S parameters``. Its x column is
    frequency in hertz or source power in dBm, followed by one floating-point
    column for each selected S-parameter. S-parameters may be reported as log
    magnitude in dB, linear magnitude, phase in degrees, real part, or
    imaginary part. **Apply error correction** uses the calibration currently
    active in the selected analyser channel; it does not create or replace a
    calibration.

    Frequency, power, bandwidth, and timeout controls accept sequence
    expressions. They are evaluated when the plugin is configured, before the
    analyser's native sweep runs. They are therefore suitable for values fixed
    for the whole trace, but not for changing a setting between sweep points.

    Attributes:
        scan_generator (NetworkAnalyserScanGenerator):
            Restricted linear/logarithmic generator used to define the native
            analyser sweep.
        _sweep_variable (NetworkAnalyserSweepVariable):
            Whether frequency or source power supplies the trace x axis.
        _selected_parameters (tuple[str, ...]):
            S-parameters returned as trace columns.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        For a conventional transmission measurement, select **Frequency**,
        choose ``S21``, set the fixed source power, and configure a linear or
        exponential frequency range on the **Scan** tab. The completed trace
        can then be consumed by plot, fit, save, and transform plugins as
        ``S parameters``.
    """

    _scan_generator_class = NetworkAnalyserScanGenerator
    _scan_generator_classes = [NetworkAnalyserScanGenerator]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = NetworkAnalyserModel.E5062A
        self._resource = "GPIB0::17::INSTR"
        self._sweep_variable = NetworkAnalyserSweepVariable.FREQUENCY
        self._fixed_power_dbm: float | str = -10.0
        self._fixed_frequency_hz: float | str = 1.0e9
        self._if_bandwidth_hz: float | str = 1.0e3
        self._averaging_enabled = False
        self._averaging_count = 1
        self._corrected = True
        self._output_format = TraceFormat.LOG_MAGNITUDE
        self._channel = 1
        self._timeout: float | str = 60.0
        self._selected_parameters: tuple[str, ...] = ("S11", "S21")
        self._analyser: NetworkAnalyser | None = None
        self._sweep_values: np.ndarray | None = None
        self.scan_generator.units = "Hz"
        self._apply_initial_config()
        self._sync_generator_mode()

    @property
    def name(self) -> str:
        return "NetworkAnalyser"

    @property
    def trace_names(self) -> list[str]:
        return ["S parameters"]

    @property
    def x_label(self) -> str:
        return (
            "Frequency"
            if self._sweep_variable is NetworkAnalyserSweepVariable.FREQUENCY
            else "Source power"
        )

    @property
    def x_units(self) -> str:
        return (
            "Hz"
            if self._sweep_variable is NetworkAnalyserSweepVariable.FREQUENCY
            else "dBm"
        )

    @property
    def y_label(self) -> str:
        return OUTPUT_FORMATS[self._output_format]

    @property
    def y_units(self) -> str:
        return s_parameter_units(self._output_format)

    def _sync_generator_mode(self) -> None:
        generator = self.scan_generator
        if not isinstance(generator, NetworkAnalyserScanGenerator):
            raise TypeError("Network analyser plugin requires NetworkAnalyserScanGenerator.")
        is_frequency = self._sweep_variable is NetworkAnalyserSweepVariable.FREQUENCY
        generator.units = "Hz" if is_frequency else "dBm"
        generator.set_exponential_available(is_frequency)

    def connect(self) -> None:
        """Open the selected GPIB analyser and verify its exact model."""
        self._set_status(TraceStatus.CONNECTING)
        analyser: NetworkAnalyser | None = None
        try:
            transport = GpibTransport.from_resource_string(
                self._resource,
                timeout=self.eval_float(self._timeout),
            )
            analyser = NETWORK_ANALYSER_DRIVERS[self._model](transport)
            analyser.connect()
            analyser.get_capabilities()
        except Exception:
            if analyser is not None:
                try:
                    analyser.disconnect()
                except (OSError, RuntimeError):
                    pass
            self._analyser = None
            self._set_status(TraceStatus.ERROR)
            raise
        self._analyser = analyser
        self._set_status(TraceStatus.IDLE)

    def configure(self) -> None:
        """Configure sweep grid, fixed stimulus, averaging, and trace slots."""
        if self._analyser is None:
            raise RuntimeError("Not connected — call connect() before configure().")
        if not self._selected_parameters:
            raise ValueError("Select at least one S-parameter.")

        self._set_status(TraceStatus.CONFIGURING)
        try:
            values = np.asarray(self.scan_generator.generate(), dtype=float)
            capabilities = self._analyser.get_capabilities()
            if len(self._selected_parameters) > capabilities.max_traces_per_channel:
                raise ValueError("The selected analyser does not have enough trace slots.")
            for parameter in self._selected_parameters:
                response_port = int(parameter[1])
                source_port = int(parameter[2])
                if max(response_port, source_port) > capabilities.port_count:
                    raise ValueError(
                        f"{parameter} requires a port absent from this analyser."
                    )

            if_bandwidth = self.eval_float(self._if_bandwidth_hz)
            if self._sweep_variable is NetworkAnalyserSweepVariable.FREQUENCY:
                sweep_type = (
                    SweepType.LOGARITHMIC
                    if self.scan_generator.mode is RampMode.EXPONENTIAL
                    else SweepType.LINEAR
                )
                configuration = SweepConfiguration(
                    sweep_type=sweep_type,
                    start_hz=float(values[0]),
                    stop_hz=float(values[-1]),
                    points=len(values),
                    if_bandwidth_hz=if_bandwidth,
                    source_power_dbm=self.eval_float(self._fixed_power_dbm),
                )
            else:
                cw_frequency = self.eval_float(self._fixed_frequency_hz)
                configuration = SweepConfiguration(
                    sweep_type=SweepType.POWER,
                    start_hz=cw_frequency,
                    stop_hz=cw_frequency,
                    points=len(values),
                    if_bandwidth_hz=if_bandwidth,
                )

            self._analyser.set_sweep_configuration(configuration, self._channel)
            if self._sweep_variable is NetworkAnalyserSweepVariable.POWER:
                self._analyser.set_cw_frequency(
                    self.eval_float(self._fixed_frequency_hz), self._channel
                )
                self._analyser.set_power_sweep_range(
                    float(values[0]), float(values[-1]), self._channel
                )
            self._analyser.set_averaging(
                self._averaging_enabled,
                self._averaging_count if self._averaging_enabled else None,
                self._channel,
            )
            for trace, parameter in enumerate(self._selected_parameters, start=1):
                self._analyser.set_measurement_parameter(parameter, self._channel, trace)
            self._sweep_values = values
        except Exception:
            self._sweep_values = None
            self._set_status(TraceStatus.ERROR)
            raise
        self._set_status(TraceStatus.IDLE)

    def _measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Run one synchronized internal sweep and return formatted S-parameters."""
        _ = parameters
        if self._analyser is None or self._sweep_values is None:
            raise RuntimeError("Plugin must be connected and configured before measuring.")
        sweep = self._analyser.acquire(
            channel=self._channel,
            traces=tuple(range(1, len(self._selected_parameters) + 1)),
            timeout=self.eval_float(self._timeout),
            corrected=self._corrected,
        )
        if any(len(trace.values) != len(self._sweep_values) for trace in sweep.traces):
            raise ValueError("Network analyser returned an unexpected sweep length.")
        columns: dict[str, np.ndarray] = {"x": self._sweep_values.copy()}
        roles: dict[str, str] = {}
        for index, trace in enumerate(sweep.traces):
            parameter = self._selected_parameters[index]
            columns[parameter] = format_s_parameter_values(
                trace.values, self._output_format
            )
            roles[parameter] = COLUMN_ROLE_Y if index == 0 else COLUMN_ROLE_Z
        names = {"x": self.x_label, **{parameter: parameter for parameter in self._selected_parameters}}
        units = {
            "x": self.x_units,
            **{parameter: self.y_units for parameter in self._selected_parameters},
        }
        return {
            "S parameters": TraceData(
                pd.DataFrame(columns), column_roles=roles, names=names, units=units
            )
        }

    def disconnect(self) -> None:
        """Close the analyser transport without changing its RF output state."""
        analyser, self._analyser = self._analyser, None
        self._sweep_values = None
        if analyser is not None:
            analyser.disconnect()
        self._set_status(TraceStatus.IDLE)

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data.update(
            {
                "model": self._model.value,
                "resource": self._resource,
                "sweep_variable": self._sweep_variable.value,
                "fixed_power_dbm": self._fixed_power_dbm,
                "fixed_frequency_hz": self._fixed_frequency_hz,
                "if_bandwidth_hz": self._if_bandwidth_hz,
                "averaging_enabled": self._averaging_enabled,
                "averaging_count": self._averaging_count,
                "corrected": self._corrected,
                "output_format": self._output_format.value,
                "channel": self._channel,
                "timeout": self._timeout,
                "selected_parameters": list(self._selected_parameters),
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        super()._restore_from_json(data)
        self._model = NetworkAnalyserModel(data.get("model", self._model.value))
        self._resource = str(data.get("resource", self._resource))
        self._sweep_variable = NetworkAnalyserSweepVariable(
            data.get("sweep_variable", self._sweep_variable.value)
        )
        self._fixed_power_dbm = data.get("fixed_power_dbm", self._fixed_power_dbm)
        self._fixed_frequency_hz = data.get(
            "fixed_frequency_hz", self._fixed_frequency_hz
        )
        self._if_bandwidth_hz = data.get("if_bandwidth_hz", self._if_bandwidth_hz)
        self._averaging_enabled = bool(
            data.get("averaging_enabled", self._averaging_enabled)
        )
        self._averaging_count = max(1, int(data.get("averaging_count", self._averaging_count)))
        self._corrected = bool(data.get("corrected", self._corrected))
        output_format = TraceFormat(data.get("output_format", self._output_format.value))
        self._output_format = (
            output_format if output_format in OUTPUT_FORMATS else TraceFormat.LOG_MAGNITUDE
        )
        self._channel = max(1, int(data.get("channel", self._channel)))
        self._timeout = data.get("timeout", self._timeout)
        selected = tuple(
            str(parameter).upper()
            for parameter in data.get("selected_parameters", self._selected_parameters)
            if str(parameter).upper() in S_PARAMETERS
        )
        self._selected_parameters = selected or self._selected_parameters
        self._sync_generator_mode()

    def _plugin_config_tabs(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(4, 4, 4, 4)

        connection_group = QGroupBox("Connection")
        connection_form = QFormLayout(connection_group)
        driver = QComboBox()
        driver.setObjectName("network_analyser_model")
        for model in NetworkAnalyserModel:
            driver.addItem(NETWORK_ANALYSER_DRIVER_LABELS[model], model)
        driver.setCurrentIndex(driver.findData(self._model))
        resource = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        resource.setObjectName("network_analyser_resource")
        resource.setCurrentText(self._resource)
        channel = QSpinBox()
        channel.setObjectName("network_analyser_channel")
        channel.setRange(1, 256)
        channel.setValue(self._channel)
        connection_form.addRow("Analyser model:", driver)
        connection_form.addRow("GPIB resource:", resource)
        connection_form.addRow("Channel:", channel)
        layout.addWidget(connection_group)

        sweep_group = QGroupBox("Sweep")
        sweep_form = QFormLayout(sweep_group)
        variable = QComboBox()
        variable.setObjectName("network_analyser_sweep_variable")
        variable.addItem("Frequency", NetworkAnalyserSweepVariable.FREQUENCY)
        variable.addItem("Source power", NetworkAnalyserSweepVariable.POWER)
        variable.setCurrentIndex(variable.findData(self._sweep_variable))
        fixed_power_label = QLabel("Fixed source power:")
        fixed_power = SISpinBox(
            allow_expressions=True, suffix="dBm", value=self._fixed_power_dbm
        )
        fixed_power.setObjectName("network_analyser_fixed_power")
        fixed_power.setMinimum(-200.0)
        fixed_power.setMaximum(100.0)
        fixed_frequency_label = QLabel("Fixed frequency:")
        fixed_frequency = SISpinBox(
            allow_expressions=True, suffix="Hz", value=self._fixed_frequency_hz
        )
        fixed_frequency.setObjectName("network_analyser_fixed_frequency")
        fixed_frequency.setMinimum(1.0)
        fixed_frequency.setMaximum(1.0e12)
        if_bandwidth = SISpinBox(
            allow_expressions=True, suffix="Hz", value=self._if_bandwidth_hz
        )
        if_bandwidth.setObjectName("network_analyser_if_bandwidth")
        if_bandwidth.setMinimum(1.0)
        if_bandwidth.setMaximum(1.0e9)
        sweep_form.addRow("Sweep variable:", variable)
        sweep_form.addRow(fixed_power_label, fixed_power)
        sweep_form.addRow(fixed_frequency_label, fixed_frequency)
        sweep_form.addRow("IF bandwidth:", if_bandwidth)
        layout.addWidget(sweep_group)

        traces_group = QGroupBox("S-parameters")
        traces_layout = QHBoxLayout(traces_group)
        trace_checks: dict[str, QCheckBox] = {}
        for parameter in S_PARAMETERS:
            check = QCheckBox(parameter)
            check.setObjectName(f"network_analyser_{parameter.lower()}")
            check.setChecked(parameter in self._selected_parameters)
            trace_checks[parameter] = check
            traces_layout.addWidget(check)
        layout.addWidget(traces_group)

        acquisition_group = QGroupBox("Acquisition")
        acquisition_form = QFormLayout(acquisition_group)
        averaging = QCheckBox()
        averaging.setObjectName("network_analyser_averaging")
        averaging.setChecked(self._averaging_enabled)
        averaging_count = QSpinBox()
        averaging_count.setObjectName("network_analyser_averaging_count")
        averaging_count.setRange(1, 65_536)
        averaging_count.setValue(self._averaging_count)
        averaging_count.setEnabled(self._averaging_enabled)
        corrected = QCheckBox()
        corrected.setObjectName("network_analyser_corrected")
        corrected.setChecked(self._corrected)
        output_format = QComboBox()
        output_format.setObjectName("network_analyser_output_format")
        for trace_format, label in OUTPUT_FORMATS.items():
            output_format.addItem(label, trace_format)
        output_format.setCurrentIndex(output_format.findData(self._output_format))
        timeout = SISpinBox(allow_expressions=True, suffix="s", value=self._timeout)
        timeout.setObjectName("network_analyser_timeout")
        timeout.setMinimum(0.1)
        timeout.setMaximum(86_400.0)
        acquisition_form.addRow("Enable averaging:", averaging)
        acquisition_form.addRow("Average count:", averaging_count)
        acquisition_form.addRow("Apply error correction:", corrected)
        acquisition_form.addRow("S-parameter representation:", output_format)
        acquisition_form.addRow("Sweep timeout:", timeout)
        layout.addWidget(acquisition_group)
        layout.addStretch()

        def on_variable_changed(index: int) -> None:
            self._sweep_variable = variable.itemData(index)
            is_frequency = self._sweep_variable is NetworkAnalyserSweepVariable.FREQUENCY
            fixed_power_label.setVisible(is_frequency)
            fixed_power.setVisible(is_frequency)
            fixed_frequency_label.setVisible(not is_frequency)
            fixed_frequency.setVisible(not is_frequency)
            self._sync_generator_mode()

        def on_parameter_toggled(_checked: bool) -> None:
            self._selected_parameters = tuple(
                parameter for parameter, check in trace_checks.items() if check.isChecked()
            )

        def on_averaging_toggled(enabled: bool) -> None:
            self._averaging_enabled = enabled
            averaging_count.setEnabled(enabled)

        driver.currentIndexChanged.connect(
            lambda index: setattr(self, "_model", driver.itemData(index))
        )
        resource.currentTextChanged.connect(
            lambda text: setattr(self, "_resource", text.strip())
        )
        channel.valueChanged.connect(lambda value: setattr(self, "_channel", value))
        variable.currentIndexChanged.connect(on_variable_changed)
        fixed_power.valueChanged.connect(
            lambda value: setattr(self, "_fixed_power_dbm", value)
        )
        fixed_frequency.valueChanged.connect(
            lambda value: setattr(self, "_fixed_frequency_hz", value)
        )
        if_bandwidth.valueChanged.connect(
            lambda value: setattr(self, "_if_bandwidth_hz", value)
        )
        for check in trace_checks.values():
            check.toggled.connect(on_parameter_toggled)
        averaging.toggled.connect(on_averaging_toggled)
        averaging_count.valueChanged.connect(
            lambda value: setattr(self, "_averaging_count", value)
        )
        corrected.toggled.connect(lambda enabled: setattr(self, "_corrected", enabled))
        output_format.currentIndexChanged.connect(
            lambda index: setattr(self, "_output_format", output_format.itemData(index))
        )
        timeout.valueChanged.connect(lambda value: setattr(self, "_timeout", value))
        on_variable_changed(variable.currentIndex())
        return root
