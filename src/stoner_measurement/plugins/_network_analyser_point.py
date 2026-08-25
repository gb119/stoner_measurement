"""Shared CW point-measurement behaviour for network-analyser plugins."""

from __future__ import annotations

from typing import Any

import numpy as np
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

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
    format_s_parameter_values,
)
from stoner_measurement.ui.widgets import (
    FILTER_GPIB,
    SISpinBox,
    VisaResourceComboBox,
)

CW_MEASUREMENT_POINTS = 2


def initialise_point_measurement(plugin: Any) -> None:
    """Install common point-measurement settings on *plugin*."""
    plugin._model = NetworkAnalyserModel.E5062A
    plugin._resource = "GPIB0::17::INSTR"
    plugin._if_bandwidth_hz = 1.0e3
    plugin._averaging_enabled = False
    plugin._averaging_count = 1
    plugin._corrected = True
    plugin._output_format = TraceFormat.LOG_MAGNITUDE
    plugin._channel = 1
    plugin._timeout = 60.0
    plugin._selected_parameters = ("S11", "S21")
    plugin._external_pulse_modulation = False
    plugin._pulse_source_port = 1
    plugin._analyser = None
    plugin._last_s_parameters = {}


def connect_point_analyser(plugin: Any) -> None:
    """Connect the selected analyser and verify its runtime capabilities."""
    analyser: NetworkAnalyser | None = None
    try:
        transport = GpibTransport.from_resource_string(
            plugin._resource, timeout=plugin.eval_float(plugin._timeout)
        )
        analyser = NETWORK_ANALYSER_DRIVERS[plugin._model](transport)
        analyser.connect()
        analyser.get_capabilities()
    except Exception:
        if analyser is not None:
            try:
                analyser.disconnect()
            except (OSError, RuntimeError):
                pass
        plugin._analyser = None
        raise
    plugin._analyser = analyser


def configure_point_analyser(plugin: Any, initial_frequency_hz: float) -> None:
    """Configure a short CW acquisition and selected measurement slots."""
    analyser: NetworkAnalyser | None = plugin._analyser
    if analyser is None:
        raise RuntimeError("Not connected — call connect() before configure().")
    if not plugin._selected_parameters:
        raise ValueError("Select at least one S-parameter.")
    capabilities = analyser.get_capabilities()
    if len(plugin._selected_parameters) > capabilities.max_traces_per_channel:
        raise ValueError("The selected analyser does not have enough trace slots.")
    for parameter in plugin._selected_parameters:
        if max(int(parameter[1]), int(parameter[2])) > capabilities.port_count:
            raise ValueError(f"{parameter} requires a port absent from this analyser.")

    analyser.set_sweep_configuration(
        SweepConfiguration(
            SweepType.CW,
            initial_frequency_hz,
            initial_frequency_hz,
            CW_MEASUREMENT_POINTS,
            if_bandwidth_hz=plugin.eval_float(plugin._if_bandwidth_hz),
        ),
        plugin._channel,
    )
    analyser.set_averaging(
        plugin._averaging_enabled,
        plugin._averaging_count if plugin._averaging_enabled else None,
        plugin._channel,
    )
    for trace, parameter in enumerate(plugin._selected_parameters, start=1):
        analyser.set_measurement_parameter(parameter, plugin._channel, trace)

    if plugin._external_pulse_modulation:
        if plugin._model is not NetworkAnalyserModel.N5222A:
            raise NotImplementedError(
                "External TTL pulse modulation is not documented for the E5062A."
            )
        analyser.set_external_pulse_modulation(
            True, plugin._channel, plugin._pulse_source_port
        )
    elif plugin._model is NetworkAnalyserModel.N5222A:
        analyser.set_external_pulse_modulation(
            False, plugin._channel, plugin._pulse_source_port
        )


def acquire_point(
    plugin: Any, frequency_hz: float, power_dbm: float
) -> dict[str, float]:
    """Set one frequency/power state and return formatted scalar S-parameters."""
    analyser: NetworkAnalyser | None = plugin._analyser
    if analyser is None:
        raise RuntimeError("Not connected — call connect() before acquiring.")
    analyser.set_cw_frequency(float(frequency_hz), plugin._channel)
    analyser.set_source_power(float(power_dbm), plugin._channel)
    sweep = analyser.acquire(
        channel=plugin._channel,
        traces=tuple(range(1, len(plugin._selected_parameters) + 1)),
        timeout=plugin.eval_float(plugin._timeout),
        corrected=plugin._corrected,
    )
    measured: dict[str, float] = {}
    for parameter, trace in zip(plugin._selected_parameters, sweep.traces, strict=True):
        if len(trace.values) == 0:
            raise ValueError(f"The analyser returned no values for {parameter}.")
        complex_mean = np.asarray(trace.values, dtype=np.complex128).mean()
        measured[parameter] = float(
            format_s_parameter_values(
                np.asarray([complex_mean]), plugin._output_format
            )[0]
        )
    plugin._last_s_parameters = measured
    return measured


def disconnect_point_analyser(plugin: Any) -> None:
    """Disable any gate enabled by *plugin*, then release its transport."""
    analyser, plugin._analyser = plugin._analyser, None
    if analyser is None:
        return
    try:
        if (
            plugin._external_pulse_modulation
            and plugin._model is NetworkAnalyserModel.N5222A
        ):
            analyser.set_external_pulse_modulation(
                False, plugin._channel, plugin._pulse_source_port
            )
    except (OSError, RuntimeError, ValueError):
        pass
    finally:
        analyser.disconnect()


def common_point_json(plugin: Any) -> dict[str, Any]:
    """Return the settings shared by point-measurement plugins."""
    return {
        "model": plugin._model.value,
        "resource": plugin._resource,
        "if_bandwidth_hz": plugin._if_bandwidth_hz,
        "averaging_enabled": plugin._averaging_enabled,
        "averaging_count": plugin._averaging_count,
        "corrected": plugin._corrected,
        "output_format": plugin._output_format.value,
        "channel": plugin._channel,
        "timeout": plugin._timeout,
        "selected_parameters": list(plugin._selected_parameters),
        "external_pulse_modulation": plugin._external_pulse_modulation,
        "pulse_source_port": plugin._pulse_source_port,
    }


def restore_common_point_json(plugin: Any, data: dict[str, Any]) -> None:
    """Restore settings shared by point-measurement plugins."""
    plugin._model = NetworkAnalyserModel(data.get("model", plugin._model.value))
    plugin._resource = str(data.get("resource", plugin._resource))
    plugin._if_bandwidth_hz = data.get(
        "if_bandwidth_hz", plugin._if_bandwidth_hz
    )
    plugin._averaging_enabled = bool(
        data.get("averaging_enabled", plugin._averaging_enabled)
    )
    plugin._averaging_count = max(
        1, int(data.get("averaging_count", plugin._averaging_count))
    )
    plugin._corrected = bool(data.get("corrected", plugin._corrected))
    output_format = TraceFormat(data.get("output_format", plugin._output_format.value))
    plugin._output_format = (
        output_format if output_format in OUTPUT_FORMATS else TraceFormat.LOG_MAGNITUDE
    )
    plugin._channel = max(1, int(data.get("channel", plugin._channel)))
    plugin._timeout = data.get("timeout", plugin._timeout)
    selected = tuple(
        str(parameter).upper()
        for parameter in data.get("selected_parameters", plugin._selected_parameters)
        if str(parameter).upper() in S_PARAMETERS
    )
    plugin._selected_parameters = selected or plugin._selected_parameters
    plugin._external_pulse_modulation = bool(
        data.get("external_pulse_modulation", plugin._external_pulse_modulation)
    )
    plugin._pulse_source_port = max(
        1, int(data.get("pulse_source_port", plugin._pulse_source_port))
    )


def build_point_settings_widget(
    plugin: Any, stimulus: QWidget, *, object_prefix: str
) -> QWidget:
    """Build the shared connection, acquisition, and modulation settings UI."""
    root = QWidget()
    layout = QVBoxLayout(root)
    layout.setContentsMargins(4, 4, 4, 4)

    connection = QGroupBox("Connection")
    connection_form = QFormLayout(connection)
    model = QComboBox()
    model.setObjectName(f"{object_prefix}_model")
    for choice in NetworkAnalyserModel:
        model.addItem(NETWORK_ANALYSER_DRIVER_LABELS[choice], choice)
    model.setCurrentIndex(model.findData(plugin._model))
    resource = VisaResourceComboBox(resource_filter=FILTER_GPIB)
    resource.setObjectName(f"{object_prefix}_resource")
    resource.setCurrentText(plugin._resource)
    channel = QSpinBox()
    channel.setRange(1, 256)
    channel.setValue(plugin._channel)
    connection_form.addRow("Analyser model:", model)
    connection_form.addRow("GPIB resource:", resource)
    connection_form.addRow("Channel:", channel)
    layout.addWidget(connection)
    layout.addWidget(stimulus)

    parameters_group = QGroupBox("S-parameters")
    parameters_layout = QHBoxLayout(parameters_group)
    parameter_checks: dict[str, QCheckBox] = {}
    for parameter in S_PARAMETERS:
        check = QCheckBox(parameter)
        check.setChecked(parameter in plugin._selected_parameters)
        parameter_checks[parameter] = check
        parameters_layout.addWidget(check)
    layout.addWidget(parameters_group)

    acquisition = QGroupBox("Acquisition")
    acquisition_form = QFormLayout(acquisition)
    if_bandwidth = SISpinBox(
        allow_expressions=True, suffix="Hz", value=plugin._if_bandwidth_hz
    )
    if_bandwidth.setObjectName(f"{object_prefix}_if_bandwidth")
    if_bandwidth.setMinimum(1.0)
    if_bandwidth.setMaximum(1.0e9)
    averaging = QCheckBox()
    averaging.setChecked(plugin._averaging_enabled)
    average_count = QSpinBox()
    average_count.setRange(1, 65_536)
    average_count.setValue(plugin._averaging_count)
    average_count.setEnabled(plugin._averaging_enabled)
    corrected = QCheckBox()
    corrected.setChecked(plugin._corrected)
    output_format = QComboBox()
    for trace_format, label in OUTPUT_FORMATS.items():
        output_format.addItem(label, trace_format)
    output_format.setCurrentIndex(output_format.findData(plugin._output_format))
    timeout = SISpinBox(allow_expressions=True, suffix="s", value=plugin._timeout)
    timeout.setMinimum(0.1)
    timeout.setMaximum(86_400.0)
    acquisition_form.addRow("IF bandwidth:", if_bandwidth)
    acquisition_form.addRow("Enable averaging:", averaging)
    acquisition_form.addRow("Average count:", average_count)
    acquisition_form.addRow("Apply error correction:", corrected)
    acquisition_form.addRow("S-parameter representation:", output_format)
    acquisition_form.addRow("Point timeout:", timeout)
    layout.addWidget(acquisition)

    modulation = QGroupBox("External pulse modulation")
    modulation.setObjectName(f"{object_prefix}_modulation")
    modulation_form = QFormLayout(modulation)
    pulse_enabled = QCheckBox("Enable external TTL RF gating")
    pulse_enabled.setObjectName(f"{object_prefix}_external_pulse")
    pulse_enabled.setChecked(plugin._external_pulse_modulation)
    pulse_enabled.setToolTip(
        "Uses the PNA RFPulseModIn TTL input to gate RF on/off; this is not analogue amplitude modulation."
    )
    pulse_port = QSpinBox()
    pulse_port.setObjectName(f"{object_prefix}_pulse_port")
    pulse_port.setRange(1, 4)
    pulse_port.setValue(plugin._pulse_source_port)
    pulse_port.setEnabled(plugin._external_pulse_modulation)
    modulation_form.addRow("External modulation:", pulse_enabled)
    modulation_form.addRow("Source port:", pulse_port)
    layout.addWidget(modulation)
    layout.addStretch()

    def parameters_changed(_checked: bool) -> None:
        plugin._selected_parameters = tuple(
            parameter
            for parameter, check in parameter_checks.items()
            if check.isChecked()
        )

    def averaging_changed(enabled: bool) -> None:
        plugin._averaging_enabled = enabled
        average_count.setEnabled(enabled)

    def model_changed(index: int) -> None:
        plugin._model = model.itemData(index)
        is_pna = plugin._model is NetworkAnalyserModel.N5222A
        modulation.setEnabled(is_pna)
        if not is_pna:
            pulse_enabled.setChecked(False)

    def pulse_enabled_changed(enabled: bool) -> None:
        plugin._external_pulse_modulation = enabled
        pulse_port.setEnabled(enabled)

    model.currentIndexChanged.connect(model_changed)
    resource.currentTextChanged.connect(
        lambda text: setattr(plugin, "_resource", text.strip())
    )
    channel.valueChanged.connect(lambda value: setattr(plugin, "_channel", value))
    if_bandwidth.valueChanged.connect(
        lambda value: setattr(plugin, "_if_bandwidth_hz", value)
    )
    for check in parameter_checks.values():
        check.toggled.connect(parameters_changed)
    averaging.toggled.connect(averaging_changed)
    average_count.valueChanged.connect(
        lambda value: setattr(plugin, "_averaging_count", value)
    )
    corrected.toggled.connect(
        lambda enabled: setattr(plugin, "_corrected", enabled)
    )
    output_format.currentIndexChanged.connect(
        lambda index: setattr(plugin, "_output_format", output_format.itemData(index))
    )
    timeout.valueChanged.connect(lambda value: setattr(plugin, "_timeout", value))
    pulse_enabled.toggled.connect(pulse_enabled_changed)
    pulse_port.valueChanged.connect(
        lambda value: setattr(plugin, "_pulse_source_port", value)
    )
    model_changed(model.currentIndex())
    return root
