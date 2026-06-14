"""Keithley 6221 + multiple SR830 trace plugin."""

from __future__ import annotations

import enum
import logging
import math
import time
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pyvisa
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.current_source import CurrentWaveform
from stoner_measurement.instruments.keithley.k6221 import Keithley6221
from stoner_measurement.instruments.lockin_amplifier import (
    LockInExpandFactor,
    LockInInputCoupling,
    LockInOutput,
    LockInReferenceSource,
    LockInReserveMode,
)
from stoner_measurement.instruments.srs.sr830 import SRS830
from stoner_measurement.instruments.transport.gpib_transport import GpibTransport
from stoner_measurement.plugins.trace.base import COLUMN_ROLE_Y, TraceData, TracePlugin, TraceStatus
from stoner_measurement.scan import FunctionScanGenerator, ListScanGenerator, SteppedScanGenerator
from stoner_measurement.ui.widgets import FILTER_GPIB, SIComboBox, SISpinBox, VisaResourceComboBox

_CLEANUP_EXCEPTIONS: tuple[type[Exception], ...] = (OSError, RuntimeError, pyvisa.Error)
_ZERO_CURRENT_THRESHOLD: float = 1e-30
_SR830_TIME_CONSTANTS: tuple[float, ...] = SRS830.supported_time_constants()
_SR830_SENSITIVITIES: tuple[float, ...] = SRS830.supported_sensitivities()
_SR830_FILTER_SLOPES: tuple[int, ...] = SRS830.supported_filter_slopes()


class WaveformScanMode(enum.Enum):
    """Selectable 6221 sine-wave parameter to scan."""

    AMPLITUDE = "amplitude"
    OFFSET = "offset"
    FREQUENCY = "frequency"


class ResistanceCurrentMode(enum.Enum):
    """How to interpret the 6221 sine amplitude when computing resistance."""

    RMS = "rms"
    PEAK = "peak"
    PEAK_TO_PEAK = "peak_to_peak"


@dataclass
class LockInEntry:
    """Configuration for one SR830 instance."""

    label: str = "LIA 1"
    resource: str = "GPIB0::8::INSTR"
    sensitivity: float = 1e-3
    offset_pct: float = 0.0
    expand: LockInExpandFactor = LockInExpandFactor.X1
    reserve_mode: LockInReserveMode = LockInReserveMode.NORMAL
    outputs: tuple[LockInOutput, ...] = (LockInOutput.X,)

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this entry."""
        return {
            "label": self.label,
            "resource": self.resource,
            "sensitivity": self.sensitivity,
            "offset_pct": self.offset_pct,
            "expand": int(self.expand.value),
            "reserve_mode": self.reserve_mode.value,
            "outputs": [output.value for output in self.outputs],
        }


@dataclass(frozen=True)
class ChannelSpec:
    """Static description of one output channel emitted by the plugin."""

    lockin_index: int
    output: LockInOutput
    name: str
    unit: str
    derived_resistance: bool = False


@dataclass(frozen=True)
class LockInReading:
    """One SR830 reading plus the value used for auto-sensitivity decisions."""

    output_values: dict[LockInOutput, float]
    ratio_signal: float


class Keithley6221_MultiSR830Plugin(TracePlugin):  # pylint: disable=invalid-name
    """Trace plugin for one 6221 source and multiple SR830 lock-ins."""

    _scan_generator_class = FunctionScanGenerator
    _scan_generator_classes = [FunctionScanGenerator, SteppedScanGenerator, ListScanGenerator]

    def __init__(self, parent=None) -> None:
        """Initialise default connection, source, and lock-in settings."""
        super().__init__(parent)
        self._log = logging.getLogger(__name__)
        self.scan_generator = FunctionScanGenerator(parent=self)

        self._6221_resource: str = "GPIB0::13::INSTR"
        self._scan_mode: WaveformScanMode = WaveformScanMode.AMPLITUDE
        self._waveform_amplitude: float = 1e-3
        self._waveform_offset: float = 0.0
        self._waveform_frequency: float = 17.0
        self._phase_marker_tlink: int = 3

        self._time_constant: float = 0.3
        self._filter_slope: int = 12
        self._input_coupling: LockInInputCoupling = LockInInputCoupling.AC
        self._read_rate_multiple: float = 3.0
        self._auto_sensitivity_enabled: bool = False
        self._auto_sensitivity_low: float = 0.1
        self._auto_sensitivity_high: float = 0.9

        self._resistance_enabled: bool = False
        self._resistance_mode: ResistanceCurrentMode = ResistanceCurrentMode.PEAK

        self._lockin_entries: list[LockInEntry] = [LockInEntry()]

        self._k6221: Keithley6221 | None = None
        self._lockins: list[SRS830] = []
        self._sweep_values: np.ndarray | None = None
        self._last_read_at: dict[str, float] = {}

        self._apply_scan_units()
        self._apply_initial_config()

    @property
    def name(self) -> str:
        """Return the unique plugin identifier."""
        return "k6221_multi_sr830"

    @property
    def trace_title(self) -> str:
        """Return the human-readable trace title."""
        return "6221 + multi-SR830"

    @property
    def x_label(self) -> str:
        """Return the label for the scanned 6221 sine parameter."""
        labels = {
            WaveformScanMode.AMPLITUDE: "Current amplitude",
            WaveformScanMode.OFFSET: "Current offset",
            WaveformScanMode.FREQUENCY: "Frequency",
        }
        return labels[self._scan_mode]

    @property
    def x_units(self) -> str:
        """Return the unit for the scanned 6221 sine parameter."""
        return "Hz" if self._scan_mode is WaveformScanMode.FREQUENCY else "A"

    @property
    def y_label(self) -> str:
        """Return the default dependent-axis label."""
        if not self._lockin_entries:
            return "Signal"
        return self._lockin_entries[0].label.strip() or "Signal"

    @property
    def y_units(self) -> str:
        """Return the default dependent-axis unit."""
        if not self._lockin_entries:
            return "V"
        return self._lockin_entries[0].outputs[0].unit

    @property
    def channel_names(self) -> list[str]:
        """Return the ordered list of emitted lock-in channel names."""
        return [spec.name for spec in self._channel_specs()]

    def set_scan_generator_class(self, cls) -> None:
        """Replace the scan generator class and update the displayed units."""
        super().set_scan_generator_class(cls)
        self._apply_scan_units()

    def measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Acquire the configured scan and return one trace per labelled channel."""
        self._set_status(TraceStatus.MEASURING)
        try:
            x_values, channel_values, specs = self._acquire_trace(parameters)
        finally:
            self._set_status(TraceStatus.DATA_AVAILABLE)

        data: dict[str, TraceData] = {}
        for spec in specs:
            y_values = np.asarray(channel_values.get(spec.name, []), dtype=float)
            df = pd.DataFrame({"y": y_values}, index=pd.Index(np.asarray(x_values, dtype=float), name="x"))
            data[spec.name] = TraceData(
                df=df,
                column_roles={"y": COLUMN_ROLE_Y},
                names={"x": self.x_label, "y": spec.name},
                units={"x": self.x_units, "y": spec.unit},
            )

        self.data = data
        self._update_channel_statistics()
        return data

    def execute(self, parameters: dict[str, Any]) -> Generator[tuple[float, float]]:
        """Acquire the scan and yield ``(x, y)`` pairs for the first channel."""
        x_values, channel_values, specs = self._acquire_trace(parameters)
        if not specs:
            return
        first_name = specs[0].name
        for x_value, y_value in zip(x_values, channel_values[first_name], strict=True):
            yield float(x_value), float(y_value)

    def execute_multichannel(self, parameters: dict[str, Any]) -> Generator[tuple[str, float, float]]:
        """Acquire the scan and yield ``(channel, x, y)`` tuples for every channel."""
        x_values, channel_values, specs = self._acquire_trace(parameters)
        for spec in specs:
            for x_value, y_value in zip(x_values, channel_values[spec.name], strict=True):
                yield spec.name, float(x_value), float(y_value)

    def connect(self) -> None:
        """Open the 6221 and all configured SR830 connections."""
        self._validate_configuration()
        self._set_status(TraceStatus.CONNECTING)
        transports: list[GpibTransport] = []
        self._lockins = []
        try:
            transport_6221 = GpibTransport.from_resource_string(self._6221_resource, timeout=10.0)
            transports.append(transport_6221)
            self._k6221 = Keithley6221(transport_6221)
            self._k6221.connect()
            self._k6221.confirm_identity()

            for entry in self._lockin_entries:
                transport = GpibTransport.from_resource_string(entry.resource, timeout=10.0)
                transports.append(transport)
                lockin = SRS830(transport)
                lockin.connect()
                identity = lockin.identify()
                if "SR830" not in identity.upper():
                    raise RuntimeError(
                        f"Unexpected SR830 identity {identity!r} for resource {entry.resource!r}."
                    )
                self._lockins.append(lockin)
        except Exception:
            for instrument in [*self._lockins, self._k6221]:
                if instrument is not None:
                    try:
                        instrument.disconnect()
                    except _CLEANUP_EXCEPTIONS:
                        pass
            for transport in reversed(transports):
                try:
                    transport.close()
                except _CLEANUP_EXCEPTIONS:
                    pass
            self._k6221 = None
            self._lockins = []
            self._set_status(TraceStatus.ERROR)
            raise

        self._last_read_at = {}
        self._set_status(TraceStatus.IDLE)

    def configure(self) -> None:
        """Apply the stored 6221 and SR830 settings to the connected hardware."""
        if self._k6221 is None or not self._lockins:
            raise RuntimeError("Not connected — call connect() before configure().")

        self._validate_configuration()
        self._set_status(TraceStatus.CONFIGURING)
        try:
            self._sweep_values = np.asarray(self.scan_generator.generate(), dtype=float)
            if self._sweep_values.size == 0:
                raise ValueError("Scan generator produced no points.")
            if self._scan_mode is WaveformScanMode.FREQUENCY and np.any(self._sweep_values <= 0.0):
                raise ValueError("Frequency scans require every scan point to be positive.")

            self._k6221.reset()
            self._k6221.set_waveform(CurrentWaveform.SINE)
            self._k6221.set_waveform_amplitude(self._waveform_amplitude)
            self._k6221.set_offset_current(self._waveform_offset)
            self._k6221.set_frequency(self._waveform_frequency)
            self._k6221.set_phase_marker_output_line(self._phase_marker_tlink)
            self._k6221.enable_phase_marker(True)

            for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True):
                lockin.reset()
                lockin.set_reference_source(LockInReferenceSource.EXTERNAL)
                lockin.set_time_constant(self._time_constant)
                lockin.set_filter_slope(self._filter_slope)
                lockin.set_input_coupling(self._input_coupling)
                lockin.set_sensitivity(entry.sensitivity)
                lockin.set_reserve_mode(entry.reserve_mode)
                for output in entry.outputs:
                    offset_channel = output.offset_channel()
                    if offset_channel is not None:
                        lockin.set_output_offset(offset_channel, entry.offset_pct, entry.expand)
        except Exception:
            self._set_status(TraceStatus.ERROR)
            raise
        self._set_status(TraceStatus.IDLE)

    def disconnect(self) -> None:
        """Disable the 6221 output and close all active instrument sessions."""
        self._set_status(TraceStatus.DISCONNECTING)
        if self._k6221 is not None:
            try:
                self._k6221.enable_output(False)
            except _CLEANUP_EXCEPTIONS:
                pass

        for instrument in [*self._lockins, self._k6221]:
            if instrument is None:
                continue
            try:
                instrument.disconnect()
            except _CLEANUP_EXCEPTIONS:
                pass

        self._k6221 = None
        self._lockins = []
        self._sweep_values = None
        self._last_read_at = {}
        self._set_status(TraceStatus.IDLE)

    def to_json(self) -> dict[str, Any]:
        """Serialise the plugin configuration to a JSON-compatible dictionary."""
        data = super().to_json()
        data.update(
            {
                "resource_6221": self._6221_resource,
                "scan_mode": self._scan_mode.value,
                "waveform_amplitude": self._waveform_amplitude,
                "waveform_offset": self._waveform_offset,
                "waveform_frequency": self._waveform_frequency,
                "phase_marker_tlink": self._phase_marker_tlink,
                "time_constant": self._time_constant,
                "filter_slope": self._filter_slope,
                "input_coupling": self._input_coupling.value,
                "read_rate_multiple": self._read_rate_multiple,
                "auto_sensitivity_enabled": self._auto_sensitivity_enabled,
                "auto_sensitivity_low": self._auto_sensitivity_low,
                "auto_sensitivity_high": self._auto_sensitivity_high,
                "resistance_enabled": self._resistance_enabled,
                "resistance_mode": self._resistance_mode.value,
                "lockins": [entry.to_json() for entry in self._lockin_entries],
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        super()._restore_from_json(data)
        self._6221_resource = str(data.get("resource_6221", self._6221_resource))
        self._scan_mode = self._parse_enum(
            WaveformScanMode,
            data.get("scan_mode", self._scan_mode.value),
            self._scan_mode,
            "scan_mode",
        )
        self._waveform_amplitude = float(data.get("waveform_amplitude", self._waveform_amplitude))
        self._waveform_offset = float(data.get("waveform_offset", self._waveform_offset))
        self._waveform_frequency = float(data.get("waveform_frequency", self._waveform_frequency))
        self._phase_marker_tlink = int(data.get("phase_marker_tlink", self._phase_marker_tlink))
        self._time_constant = float(data.get("time_constant", self._time_constant))
        self._filter_slope = int(data.get("filter_slope", self._filter_slope))
        self._input_coupling = self._parse_enum(
            LockInInputCoupling,
            data.get("input_coupling", self._input_coupling.value),
            self._input_coupling,
            "input_coupling",
        )
        self._read_rate_multiple = float(data.get("read_rate_multiple", self._read_rate_multiple))
        self._auto_sensitivity_enabled = bool(data.get("auto_sensitivity_enabled", self._auto_sensitivity_enabled))
        self._auto_sensitivity_low = float(data.get("auto_sensitivity_low", self._auto_sensitivity_low))
        self._auto_sensitivity_high = float(data.get("auto_sensitivity_high", self._auto_sensitivity_high))
        self._resistance_enabled = bool(data.get("resistance_enabled", self._resistance_enabled))
        self._resistance_mode = self._parse_enum(
            ResistanceCurrentMode,
            data.get("resistance_mode", self._resistance_mode.value),
            self._resistance_mode,
            "resistance_mode",
        )

        restored_entries = data.get("lockins", [])
        if isinstance(restored_entries, list) and restored_entries:
            self._lockin_entries = [self._restore_lockin_entry(entry, index) for index, entry in enumerate(restored_entries)]
        self._apply_scan_units()

    def _plugin_config_tabs(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(4, 4, 4, 4)

        source_group = QGroupBox("Connection + source")
        source_form = QFormLayout(source_group)

        resource_6221 = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        resource_6221.setCurrentText(self._6221_resource)
        resource_6221.currentTextChanged.connect(lambda text: setattr(self, "_6221_resource", text.strip()))

        scan_mode_combo = QComboBox()
        scan_mode_combo.addItem("Scan amplitude", WaveformScanMode.AMPLITUDE)
        scan_mode_combo.addItem("Scan offset", WaveformScanMode.OFFSET)
        scan_mode_combo.addItem("Scan frequency", WaveformScanMode.FREQUENCY)
        scan_mode_combo.setCurrentIndex(scan_mode_combo.findData(self._scan_mode))

        amplitude_sb = SISpinBox(suffix="A", siPrefix=True, value=self._waveform_amplitude)
        amplitude_sb.setMinimum(0.0)
        amplitude_sb.setMaximum(1.0)
        amplitude_sb.sigValueChanged.connect(lambda value: setattr(self, "_waveform_amplitude", float(value)))

        offset_sb = SISpinBox(suffix="A", siPrefix=True, value=self._waveform_offset)
        offset_sb.setMinimum(-1.0)
        offset_sb.setMaximum(1.0)
        offset_sb.sigValueChanged.connect(lambda value: setattr(self, "_waveform_offset", float(value)))

        frequency_sb = SISpinBox(suffix="Hz", siPrefix=True, value=self._waveform_frequency)
        frequency_sb.setMinimum(1e-3)
        frequency_sb.setMaximum(1e6)
        frequency_sb.sigValueChanged.connect(lambda value: setattr(self, "_waveform_frequency", float(value)))

        phase_combo = QComboBox()
        for line in range(1, 7):
            phase_combo.addItem(f"Line {line}", line)
        phase_combo.setCurrentIndex(phase_combo.findData(self._phase_marker_tlink))
        phase_combo.currentIndexChanged.connect(
            lambda index: setattr(self, "_phase_marker_tlink", int(phase_combo.itemData(index)))
        )

        def _on_scan_mode_changed(index: int) -> None:
            mode = scan_mode_combo.itemData(index)
            if isinstance(mode, WaveformScanMode):
                self._scan_mode = mode
                self._apply_scan_units()

        scan_mode_combo.currentIndexChanged.connect(_on_scan_mode_changed)

        source_form.addRow("6221 resource:", resource_6221)
        source_form.addRow("Scan parameter:", scan_mode_combo)
        source_form.addRow("Sine amplitude:", amplitude_sb)
        source_form.addRow("Sine offset:", offset_sb)
        source_form.addRow("Sine frequency:", frequency_sb)
        source_form.addRow("Phase-marker line:", phase_combo)
        layout.addWidget(source_group)

        common_group = QGroupBox("Common lock-in")
        common_form = QFormLayout(common_group)

        time_constant_combo = SIComboBox(unit="s")
        for value in _SR830_TIME_CONSTANTS:
            time_constant_combo.addValueItem(value)
        time_constant_combo.setFloatValue(self._time_constant)
        time_constant_combo.valueChanged.connect(lambda value: setattr(self, "_time_constant", float(value)))

        slope_combo = QComboBox()
        for slope in _SR830_FILTER_SLOPES:
            slope_combo.addItem(f"{slope} dB/oct", slope)
        slope_combo.setCurrentIndex(slope_combo.findData(self._filter_slope))
        slope_combo.currentIndexChanged.connect(
            lambda index: setattr(self, "_filter_slope", int(slope_combo.itemData(index)))
        )

        coupling_combo = QComboBox()
        coupling_combo.addItem("AC", LockInInputCoupling.AC)
        coupling_combo.addItem("DC", LockInInputCoupling.DC)
        coupling_combo.setCurrentIndex(coupling_combo.findData(self._input_coupling))
        coupling_combo.currentIndexChanged.connect(
            lambda index: setattr(self, "_input_coupling", coupling_combo.itemData(index))
        )

        read_multiple_sb = SISpinBox(value=self._read_rate_multiple)
        read_multiple_sb.setMinimum(0.0)
        read_multiple_sb.setMaximum(1000.0)
        read_multiple_sb.sigValueChanged.connect(lambda value: setattr(self, "_read_rate_multiple", float(value)))

        auto_enabled = QCheckBox("Enable auto-sensitivity")
        auto_enabled.setChecked(self._auto_sensitivity_enabled)
        auto_enabled.toggled.connect(lambda checked: setattr(self, "_auto_sensitivity_enabled", bool(checked)))

        auto_low_sb = SISpinBox(value=self._auto_sensitivity_low)
        auto_low_sb.setMinimum(0.0)
        auto_low_sb.setMaximum(1.0)
        auto_low_sb.setSingleStep(0.05)
        auto_low_sb.sigValueChanged.connect(lambda value: setattr(self, "_auto_sensitivity_low", float(value)))

        auto_high_sb = SISpinBox(value=self._auto_sensitivity_high)
        auto_high_sb.setMinimum(0.0)
        auto_high_sb.setMaximum(1.0)
        auto_high_sb.setSingleStep(0.05)
        auto_high_sb.sigValueChanged.connect(lambda value: setattr(self, "_auto_sensitivity_high", float(value)))

        common_form.addRow("Time constant:", time_constant_combo)
        common_form.addRow("Filter slope:", slope_combo)
        common_form.addRow("Coupling:", coupling_combo)
        common_form.addRow("Read cooldown multiple:", read_multiple_sb)
        common_form.addRow(auto_enabled)
        common_form.addRow("Auto-sensitivity low ratio:", auto_low_sb)
        common_form.addRow("Auto-sensitivity high ratio:", auto_high_sb)
        layout.addWidget(common_group)

        lockins_group = QGroupBox("Lock-ins")
        lockins_layout = QVBoxLayout(lockins_group)
        lockins_table = QTableWidget(lockins_group)
        lockins_table.setColumnCount(7)
        lockins_table.setHorizontalHeaderLabels(
            ["Label", "Resource", "Outputs", "Sensitivity", "Offset (%)", "Expand", "Reserve"]
        )
        lockins_table.verticalHeader().setVisible(False)
        for column in range(7):
            mode = QHeaderView.ResizeMode.ResizeToContents if column != 1 else QHeaderView.ResizeMode.Stretch
            lockins_table.horizontalHeader().setSectionResizeMode(column, mode)

        buttons_layout = QHBoxLayout()
        add_button = QPushButton("Add lock-in")
        remove_button = QPushButton("Remove selected")
        buttons_layout.addWidget(add_button)
        buttons_layout.addWidget(remove_button)
        buttons_layout.addStretch(1)

        def _refresh_lockin_table() -> None:
            lockins_table.blockSignals(True)
            lockins_table.setRowCount(len(self._lockin_entries))
            for row, entry in enumerate(self._lockin_entries):
                label_edit = QLineEdit(entry.label)
                label_edit.textChanged.connect(lambda text, *, idx=row: setattr(self._lockin_entries[idx], "label", text))
                lockins_table.setCellWidget(row, 0, label_edit)

                resource_widget = VisaResourceComboBox(resource_filter=FILTER_GPIB)
                resource_widget.setCurrentText(entry.resource)
                resource_widget.currentTextChanged.connect(
                    lambda text, *, idx=row: setattr(self._lockin_entries[idx], "resource", text.strip())
                )
                lockins_table.setCellWidget(row, 1, resource_widget)

                outputs_edit = QLineEdit(", ".join(output.value for output in entry.outputs))

                sensitivity_combo = SIComboBox(unit="V")
                for value in _SR830_SENSITIVITIES:
                    sensitivity_combo.addValueItem(value)
                sensitivity_combo.setFloatValue(entry.sensitivity)

                offset_local = SISpinBox(suffix="%", value=entry.offset_pct)
                offset_local.setMinimum(-105.0)
                offset_local.setMaximum(105.0)

                expand_combo = QComboBox()
                expand_combo.addItem("×1", LockInExpandFactor.X1)
                expand_combo.addItem("×10", LockInExpandFactor.X10)
                expand_combo.addItem("×100", LockInExpandFactor.X100)
                expand_combo.setCurrentIndex(expand_combo.findData(entry.expand))

                reserve_combo = QComboBox()
                reserve_combo.addItem("High reserve", LockInReserveMode.HIGH_RESERVE)
                reserve_combo.addItem("Normal", LockInReserveMode.NORMAL)
                reserve_combo.addItem("Low noise", LockInReserveMode.LOW_NOISE)
                reserve_combo.setCurrentIndex(reserve_combo.findData(entry.reserve_mode))

                def _sync_outputs(
                    text: str,
                    *,
                    idx=row,
                    output_widget=outputs_edit,
                    offset_widget=offset_local,
                    expand_widget=expand_combo,
                ) -> None:
                    try:
                        outputs = self._parse_outputs(text)
                    except ValueError:
                        output_widget.setText(", ".join(output.value for output in self._lockin_entries[idx].outputs))
                        outputs = self._lockin_entries[idx].outputs
                    self._lockin_entries[idx].outputs = outputs
                    supports_offset = any(output.offset_channel() is not None for output in outputs)
                    offset_widget.setEnabled(supports_offset)
                    expand_widget.setEnabled(supports_offset)

                outputs_edit.editingFinished.connect(lambda *, edit=outputs_edit: _sync_outputs(edit.text()))
                sensitivity_combo.valueChanged.connect(
                    lambda value, *, idx=row: setattr(self._lockin_entries[idx], "sensitivity", float(value))
                )
                offset_local.sigValueChanged.connect(
                    lambda value, *, idx=row: setattr(self._lockin_entries[idx], "offset_pct", float(value))
                )
                expand_combo.currentIndexChanged.connect(
                    lambda index, *, idx=row, combo=expand_combo: setattr(
                        self._lockin_entries[idx], "expand", combo.itemData(index)
                    )
                )
                reserve_combo.currentIndexChanged.connect(
                    lambda index, *, idx=row, combo=reserve_combo: setattr(
                        self._lockin_entries[idx], "reserve_mode", combo.itemData(index)
                    )
                )

                lockins_table.setCellWidget(row, 2, outputs_edit)
                lockins_table.setCellWidget(row, 3, sensitivity_combo)
                lockins_table.setCellWidget(row, 4, offset_local)
                lockins_table.setCellWidget(row, 5, expand_combo)
                lockins_table.setCellWidget(row, 6, reserve_combo)
                _sync_outputs(outputs_edit.text(), idx=row)

            lockins_table.blockSignals(False)

        def _next_lockin_label() -> str:
            return f"LIA {len(self._lockin_entries) + 1}"

        def _add_lockin() -> None:
            self._lockin_entries.append(LockInEntry(label=_next_lockin_label(), resource="GPIB0::9::INSTR"))
            _refresh_lockin_table()

        def _remove_selected_lockin() -> None:
            selected = sorted({index.row() for index in lockins_table.selectedIndexes()}, reverse=True)
            if not selected or len(self._lockin_entries) == 1:
                return
            for row in selected:
                self._lockin_entries.pop(row)
            _refresh_lockin_table()

        add_button.clicked.connect(_add_lockin)
        remove_button.clicked.connect(_remove_selected_lockin)
        _refresh_lockin_table()

        lockins_layout.addWidget(lockins_table)
        lockins_layout.addLayout(buttons_layout)
        layout.addWidget(lockins_group)

        derived_group = QGroupBox("Resistance conversion")
        derived_form = QFormLayout(derived_group)

        resistance_enabled = QCheckBox("Create resistance-derived channels")
        resistance_enabled.setChecked(self._resistance_enabled)
        resistance_enabled.toggled.connect(lambda checked: setattr(self, "_resistance_enabled", bool(checked)))

        resistance_mode_combo = QComboBox()
        resistance_mode_combo.addItem("Use RMS current", ResistanceCurrentMode.RMS)
        resistance_mode_combo.addItem("Use peak current", ResistanceCurrentMode.PEAK)
        resistance_mode_combo.addItem("Use peak-to-peak current", ResistanceCurrentMode.PEAK_TO_PEAK)
        resistance_mode_combo.setCurrentIndex(resistance_mode_combo.findData(self._resistance_mode))
        resistance_mode_combo.currentIndexChanged.connect(
            lambda index: setattr(self, "_resistance_mode", resistance_mode_combo.itemData(index))
        )

        derived_form.addRow(resistance_enabled)
        derived_form.addRow("Current interpretation:", resistance_mode_combo)
        layout.addWidget(derived_group)
        layout.addStretch(1)
        return root

    def _channel_specs(self) -> list[ChannelSpec]:
        specs: list[ChannelSpec] = []
        for index, entry in enumerate(self._lockin_entries):
            base_name = entry.label.strip() or f"LIA {index + 1}"
            append_suffix = len(entry.outputs) > 1
            for output in entry.outputs:
                output_name = f"{base_name} {output.value}" if append_suffix else base_name
                specs.append(ChannelSpec(lockin_index=index, output=output, name=output_name, unit=output.unit))
                if self._resistance_enabled and output is not LockInOutput.THETA:
                    specs.append(
                        ChannelSpec(
                            lockin_index=index,
                            output=output,
                            name=f"{output_name} resistance",
                            unit="Ω",
                            derived_resistance=True,
                        )
                    )
        return specs

    def _validate_configuration(self) -> None:
        if not self._6221_resource.strip():
            raise ValueError("A 6221 resource must be configured.")
        if not self._lockin_entries:
            raise ValueError("At least one SR830 lock-in entry must be configured.")
        if self._waveform_amplitude < 0.0:
            raise ValueError("Waveform amplitude must be non-negative.")
        if self._waveform_frequency <= 0.0:
            raise ValueError("Waveform frequency must be positive.")
        if not 1 <= self._phase_marker_tlink <= 6:
            raise ValueError("Phase-marker trigger-link line must be in the range 1..6.")
        if self._read_rate_multiple < 0.0:
            raise ValueError("Read cooldown multiple must be non-negative.")
        if not 0.0 <= self._auto_sensitivity_low <= 1.0:
            raise ValueError("Auto-sensitivity low threshold must lie between 0 and 1.")
        if not 0.0 <= self._auto_sensitivity_high <= 1.0:
            raise ValueError("Auto-sensitivity high threshold must lie between 0 and 1.")
        if self._auto_sensitivity_low >= self._auto_sensitivity_high:
            raise ValueError("Auto-sensitivity low threshold must be lower than the high threshold.")
        if self._filter_slope not in _SR830_FILTER_SLOPES:
            raise ValueError(f"Filter slope must be one of {_SR830_FILTER_SLOPES!r}.")
        if self._time_constant not in _SR830_TIME_CONSTANTS:
            raise ValueError(f"Time constant must be one of {_SR830_TIME_CONSTANTS!r}.")

        labels: list[str] = []
        resources: list[str] = []
        for index, entry in enumerate(self._lockin_entries, start=1):
            label = entry.label.strip()
            resource = entry.resource.strip()
            if not label:
                raise ValueError(f"Lock-in {index} must have a non-empty label.")
            if not resource:
                raise ValueError(f"Lock-in {label!r} must have a non-empty resource string.")
            if entry.sensitivity not in _SR830_SENSITIVITIES:
                raise ValueError(f"Lock-in {label!r} sensitivity must be one of {_SR830_SENSITIVITIES!r}.")
            if not 1 <= len(entry.outputs) <= 4:
                raise ValueError(f"Lock-in {label!r} must define between 1 and 4 outputs.")
            if len(set(entry.outputs)) != len(entry.outputs):
                raise ValueError(f"Lock-in {label!r} outputs must be unique.")
            labels.append(label)
            resources.append(resource)

        if len(set(labels)) != len(labels):
            raise ValueError("Each lock-in label must be unique.")
        if len(set(resources)) != len(resources):
            raise ValueError("Each SR830 resource must be unique.")
        if self._6221_resource.strip() in resources:
            raise ValueError("The 6221 resource conflicts with an SR830 resource.")

        channel_names = [spec.name for spec in self._channel_specs()]
        if len(set(channel_names)) != len(channel_names):
            raise ValueError("Derived channel names must be unique.")

    def _apply_scan_units(self) -> None:
        self.scan_generator.units = self.x_units

    def _acquire_trace(
        self,
        parameters: dict[str, Any],
    ) -> tuple[np.ndarray, dict[str, list[float]], list[ChannelSpec]]:
        del parameters
        if self._k6221 is None or not self._lockins:
            raise RuntimeError("Not connected — call connect() before execute().")
        if self._sweep_values is None:
            raise RuntimeError("Not configured — call configure() before execute().")

        x_values = np.asarray(self._sweep_values, dtype=float)
        specs = self._channel_specs()
        channel_values = {spec.name: [] for spec in specs}

        self._k6221.enable_output(True)
        try:
            for scan_value in x_values:
                self._apply_scan_value(float(scan_value))
                self._wait_for_read_cooldown()
                readings = self._read_lockins()
                timestamp = time.monotonic()
                self._record_read_timestamp(timestamp)
                self._apply_auto_sensitivity(readings)
                current_amplitude = self._current_amplitude_for_point(float(scan_value))
                for spec in specs:
                    entry = self._lockin_entries[spec.lockin_index]
                    reading = readings[entry.resource]
                    output_value = reading.output_values[spec.output]
                    if spec.derived_resistance:
                        value = self._convert_to_resistance(output_value, current_amplitude)
                    else:
                        value = output_value
                    channel_values[spec.name].append(float(value))
        finally:
            self._k6221.enable_output(False)

        return x_values, channel_values, specs

    def _apply_scan_value(self, value: float) -> None:
        if self._k6221 is None:
            raise RuntimeError("Not connected — call connect() before execute().")
        if self._scan_mode is WaveformScanMode.AMPLITUDE:
            self._k6221.set_waveform_amplitude(value)
        elif self._scan_mode is WaveformScanMode.OFFSET:
            self._k6221.set_offset_current(value)
        else:
            self._k6221.set_frequency(value)

    def _wait_for_read_cooldown(self) -> None:
        if not self._last_read_at:
            return
        cooldown = self._time_constant * self._read_rate_multiple
        if cooldown <= 0.0:
            return
        remaining = cooldown - (time.monotonic() - max(self._last_read_at.values()))
        if remaining > 0.0:
            time.sleep(remaining)

    def _record_read_timestamp(self, timestamp: float) -> None:
        for entry in self._lockin_entries:
            self._last_read_at[entry.resource] = timestamp

    def _read_lockins(self) -> dict[str, LockInReading]:
        self._trigger_gpib_lockins()
        readings: dict[str, LockInReading] = {}
        for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True):
            requested_outputs = entry.outputs
            if LockInOutput.R not in requested_outputs:
                requested_outputs = (*requested_outputs, LockInOutput.R)
            measured_values = lockin.measure_outputs(requested_outputs)
            output_values = {output: float(measured_values[output]) for output in entry.outputs}
            ratio_signal = abs(float(measured_values[LockInOutput.R]))
            readings[entry.resource] = LockInReading(output_values, float(ratio_signal))
        return readings

    def _trigger_gpib_lockins(self) -> None:
        for lockin in self._lockins:
            transport = lockin.transport
            if isinstance(transport, GpibTransport):
                transport.send_group_execute_trigger()

    def _apply_auto_sensitivity(self, readings: dict[str, LockInReading]) -> None:
        if not self._auto_sensitivity_enabled:
            return
        sensitivities = _SR830_SENSITIVITIES
        for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True):
            reading = readings[entry.resource]
            if entry.sensitivity <= 0.0:
                continue
            ratio = abs(reading.ratio_signal) / entry.sensitivity
            try:
                index = sensitivities.index(entry.sensitivity)
            except ValueError:
                continue
            new_index = index
            if ratio < self._auto_sensitivity_low and index > 0:
                new_index = index - 1
            elif ratio > self._auto_sensitivity_high and index < len(sensitivities) - 1:
                new_index = index + 1
            if new_index != index:
                new_sensitivity = sensitivities[new_index]
                lockin.set_sensitivity(new_sensitivity)
                entry.sensitivity = new_sensitivity

    def _current_amplitude_for_point(self, scan_value: float) -> float:
        if self._scan_mode is WaveformScanMode.AMPLITUDE:
            return abs(scan_value)
        return abs(self._waveform_amplitude)

    def _convert_to_resistance(self, signal: float, amplitude: float) -> float:
        if self._resistance_mode is ResistanceCurrentMode.RMS:
            current = amplitude / math.sqrt(2.0)
        elif self._resistance_mode is ResistanceCurrentMode.PEAK_TO_PEAK:
            current = amplitude * 2.0
        else:
            current = amplitude
        if abs(current) <= _ZERO_CURRENT_THRESHOLD:
            return float("nan")
        return signal / current

    def _restore_lockin_entry(self, data: Any, index: int) -> LockInEntry:
        default_label = f"LIA {index + 1}"
        if not isinstance(data, dict):
            return LockInEntry(label=default_label)
        return LockInEntry(
            label=str(data.get("label", default_label)),
            resource=str(data.get("resource", "GPIB0::8::INSTR")),
            sensitivity=float(data.get("sensitivity", 1e-3)),
            offset_pct=float(data.get("offset_pct", 0.0)),
            expand=self._parse_enum(
                LockInExpandFactor,
                data.get("expand", LockInExpandFactor.X1.value),
                LockInExpandFactor.X1,
                "expand",
            ),
            reserve_mode=self._parse_enum(
                LockInReserveMode,
                data.get("reserve_mode", LockInReserveMode.NORMAL.value),
                LockInReserveMode.NORMAL,
                "reserve_mode",
            ),
            outputs=self._restore_lockin_outputs(data),
        )

    def _restore_lockin_outputs(self, data: dict[str, Any]) -> tuple[LockInOutput, ...]:
        values = data.get("outputs", data.get("output", [LockInOutput.X.value]))
        try:
            return self._parse_outputs(values)
        except ValueError:
            self._log.warning("Unknown output selection %r in saved config; falling back to %s.", values, LockInOutput.X)
            return (LockInOutput.X,)

    @staticmethod
    def _parse_outputs(value: Any) -> tuple[LockInOutput, ...]:
        if isinstance(value, str):
            tokens = [token.strip() for token in value.replace(";", ",").split(",") if token.strip()]
        elif isinstance(value, list):
            tokens = [token for token in value if str(token).strip()]
        elif isinstance(value, tuple):
            tokens = [token for token in value if str(token).strip()]
        else:
            raise ValueError(f"Unsupported output selection format: {type(value).__name__}")
        if not tokens:
            raise ValueError("At least one output must be selected.")
        parsed: list[LockInOutput] = []
        for token in tokens:
            if isinstance(token, LockInOutput):
                parsed.append(token)
                continue
            key = str(token).strip().upper()
            if key == "T":
                key = "THETA"
            parsed.append(LockInOutput(key))
        if len(parsed) > 4:
            raise ValueError("At most four outputs can be selected.")
        deduped = tuple(dict.fromkeys(parsed))
        if not deduped:
            raise ValueError("At least one output must be selected.")
        return deduped

    def _parse_enum(self, enum_type, value: Any, default: Any, field_name: str):
        try:
            return enum_type(value)
        except ValueError:
            self._log.warning(
                "Unknown %s value %r in saved config; falling back to default (%s).",
                field_name,
                value,
                default.value,
            )
            return default
