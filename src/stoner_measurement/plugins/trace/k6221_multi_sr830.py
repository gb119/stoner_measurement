"""Keithley 6221 + multiple SR830 trace plugin."""

from __future__ import annotations

import enum
import logging
import math
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
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
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.current_source import CurrentWaveform
from stoner_measurement.instruments.keithley.k6221 import Keithley6221
from stoner_measurement.instruments.lockin_amplifier import (
    LockInExpandFactor,
    LockInInputCoupling,
    LockInInputShielding,
    LockInInputSource,
    LockInLineFilter,
    LockInOutput,
    LockInReferenceSource,
    LockInReserveMode,
    LockinRefenceEdge,
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
_SR830_MAX_HARMONIC: int = SRS830.max_harmonic()

# Row indices for the transposed lock-in configuration table.
_ROW_LABEL = 0
_ROW_RESOURCE = 1
_ROW_INPUT_SOURCE = 2
_ROW_INPUT_SHIELDING = 3
_ROW_OUTPUT_X = 4
_ROW_OUTPUT_Y = 5
_ROW_OUTPUT_R = 6
_ROW_OUTPUT_THETA = 7
_ROW_SENSITIVITY = 8
_ROW_AUTO_SENSITIVITY = 9
_ROW_HARMONIC = 10
_ROW_PHASE = 11
_ROW_AUTO_PHASE = 12
_ROW_OFFSET_PCT = 13
_ROW_EXPAND = 14
_ROW_RESERVE = 15
_LOCKIN_TABLE_ROWS = 16

# Ordered (LockInOutput, row-index) pairs for the per-output checkbox rows.
_OUTPUT_ROWS: tuple[tuple[LockInOutput, int], ...] = (
    (LockInOutput.X, _ROW_OUTPUT_X),
    (LockInOutput.Y, _ROW_OUTPUT_Y),
    (LockInOutput.R, _ROW_OUTPUT_R),
    (LockInOutput.THETA, _ROW_OUTPUT_THETA),
)

_LOCKIN_ROW_LABELS: list[str] = [
    "Label",
    "Resource",
    "Input source",
    "Input shield",
    "Output X",
    "Output Y",
    "Output R",
    "Output \u03b8",
    "Sensitivity",
    "Auto-sensitivity",
    "Harmonic",
    "Phase (\u00b0)",
    "Auto-phase",
    "Offset (%)",
    "Expand",
    "Reserve",
]


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
    """Configuration for one SR830 instance.

    Attributes:
        label (str):
            Human-readable name used to identify this lock-in's channels.
        resource (str):
            VISA resource string for the SR830 instrument.
        input_source (LockInInputSource):
            Input voltage/current source configuration (A, A−B, I 1 MΩ, I 100 MΩ).
        input_shielding (LockInInputShielding):
            Input connector shield grounding (float or ground).
        sensitivity (float):
            Initial input sensitivity in volts.
        offset_pct (float):
            Output offset as a percentage of full scale (−105 to +105).
        expand (LockInExpandFactor):
            Output expand factor.
        reserve_mode (LockInReserveMode):
            Dynamic reserve operating mode.
        outputs (tuple[LockInOutput, ...]):
            Ordered selection of outputs to record (1–4 unique values).
        harmonic (int):
            Detection harmonic (1 to :data:`_SR830_MAX_HARMONIC`).
        phase (float):
            Reference phase offset in degrees.
        auto_phase (bool):
            When ``True``, run auto-phase after settling during configure.
        auto_sensitivity (bool):
            When ``True``, this lock-in participates in dynamic auto-sensitivity
            during measurement (subject to the plugin-level master enable).
        auto_offsets (dict[str, float]):
            Per-channel offset percentages populated by :meth:`~Keithley6221_MultiSR830Plugin.auto_offset`.
            Keys are :class:`~stoner_measurement.instruments.lockin_amplifier.LockInOutputChannel`
            value strings (``"X"``, ``"Y"``, ``"R"``).
    """

    label: str = "LIA 1"
    resource: str = "GPIB0::8::INSTR"
    input_source: LockInInputSource = LockInInputSource.A_MINUS_B
    input_shielding: LockInInputShielding = LockInInputShielding.FLOAT
    sensitivity: float = 1e-3
    offset_pct: float = 0.0
    expand: LockInExpandFactor = LockInExpandFactor.X1
    reserve_mode: LockInReserveMode = LockInReserveMode.NORMAL
    outputs: tuple[LockInOutput, ...] = (LockInOutput.X,)
    harmonic: int = 1
    phase: float = 0.0
    auto_phase: bool = False
    auto_sensitivity: bool = True
    auto_offsets: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this entry."""
        return {
            "label": self.label,
            "resource": self.resource,
            "input_source": self.input_source.value,
            "input_shielding": self.input_shielding.value,
            "sensitivity": self.sensitivity,
            "offset_pct": self.offset_pct,
            "expand": int(self.expand.value),
            "reserve_mode": self.reserve_mode.value,
            "outputs": [output.value for output in self.outputs],
            "harmonic": self.harmonic,
            "phase": self.phase,
            "auto_phase": self.auto_phase,
            "auto_sensitivity": self.auto_sensitivity,
            "auto_offsets": dict(self.auto_offsets),
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

    _scan_generator_class = ListScanGenerator
    _scan_generator_classes = [FunctionScanGenerator, SteppedScanGenerator, ListScanGenerator]

    def __init__(self, parent=None) -> None:
        """Initialise default connection, source, and lock-in settings."""
        super().__init__(parent)
        self._log = logging.getLogger(__name__)
        self.scan_generator = ListScanGenerator(parent=self)

        self._6221_resource: str = "GPIB0::13::INSTR"
        self._scan_mode: WaveformScanMode = WaveformScanMode.OFFSET
        self._waveform_amplitude: float = 1e-3
        self._waveform_offset: float = 0.0
        self._waveform_frequency: float = 367.0
        self._phase_marker_tlink: int = 4

        self._time_constant: float = 0.3
        self._filter_slope: int = 12
        self._input_coupling: LockInInputCoupling = LockInInputCoupling.AC
        self._line_filter: LockInLineFilter = LockInLineFilter.NONE
        self._read_rate_multiple: float = 3.0
        self._auto_sensitivity_enabled: bool = False
        self._auto_sensitivity_low: float = 0.1
        self._auto_sensitivity_high: float = 0.9
        self._offset_enabled: bool = False
        self._source_range_mode: str = "BEST"

        self._resistance_enabled: bool = False

        self._lockin_entries: list[LockInEntry] = [LockInEntry()]

        self._k6221: Keithley6221 | None = None
        self._lockins: list[SRS830] = []
        self._sweep_values: np.ndarray | None = None
        self._last_read_at: dict[str, float] = {}

        self._report_channel_statistics = True
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
            transport_6221 = GpibTransport.from_resource_string(self._6221_resource, timeout=10.0, poll_time=0.05)
            transports.append(transport_6221)
            self._k6221 = Keithley6221(transport_6221)
            self._k6221.connect()
            self._k6221.confirm_identity()

            with ThreadPoolExecutor(max_workers=max(1, len(self._lockin_entries))) as executor:
                futures = [
                    executor.submit(self._connect_one_lockin, entry) for entry in self._lockin_entries
                ]
                first_error: Exception | None = None
                for future in futures:
                    try:
                        transport, lockin = future.result()
                        transports.append(transport)
                        self._lockins.append(lockin)
                    except Exception as exc:  # noqa: BLE001
                        if first_error is None:
                            first_error = exc
            if first_error is not None:
                raise first_error
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

    def _connect_one_lockin(self, entry: LockInEntry) -> tuple[GpibTransport, SRS830]:
        """Create, connect, and identity-verify one SR830.

        If any step fails the transport is closed before propagating the
        exception, preventing transport resource leaks in the calling
        parallel connection loop.

        Args:
            entry (LockInEntry):
                Lock-in configuration entry providing the VISA resource string.

        Returns:
            (GpibTransport):
                Opened transport bound to the SR830.
            (SRS830):
                Connected and verified SR830 instrument driver.

        Raises:
            RuntimeError:
                If the instrument identity does not contain ``"SR830"``.
        """
        transport = GpibTransport.from_resource_string(entry.resource, timeout=10.0)
        try:
            lockin = SRS830(transport)
            lockin.connect()
            identity = lockin.identify()
            if "SR830" not in identity.upper():
                raise RuntimeError(
                    f"Unexpected SR830 identity {identity!r} for resource {entry.resource!r}."
                )
        except Exception:
            try:
                transport.close()
            except _CLEANUP_EXCEPTIONS:
                pass
            raise
        return transport, lockin

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
            self._apply_source_range()
            self._k6221.wave_start()

            with ThreadPoolExecutor(max_workers=max(1, len(self._lockins))) as executor:
                futures = [
                    executor.submit(self._configure_one_lockin, entry, lockin)
                    for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True)
                ]
                for future in futures:
                    future.result()

            self._run_auto_phase()
        except Exception:
            self._set_status(TraceStatus.ERROR)
            raise

        timestamp = time.monotonic()
        self._record_read_timestamp(timestamp)
        self._set_status(TraceStatus.IDLE)

    def _configure_one_lockin(self, entry: LockInEntry, lockin: SRS830) -> None:
        """Apply common and per-entry settings to one SR830.

        Args:
            entry (LockInEntry):
                Per-lockin configuration (harmonic, phase, sensitivity, etc.).
            lockin (SRS830):
                SR830 instrument driver to configure.
        """
        lockin.reset()
        lockin.set_reference_source(LockInReferenceSource.EXTERNAL)
        lockin.set_time_constant(self._time_constant)
        lockin.set_filter_slope(self._filter_slope)
        lockin.set_input_source(entry.input_source)
        lockin.set_input_shielding(entry.input_shielding)
        lockin.set_input_coupling(self._input_coupling)
        lockin.set_line_filter(self._line_filter)
        lockin.set_harmonic(entry.harmonic)
        lockin.set_reference_phase(entry.phase)
        lockin.set_reference_source(LockInReferenceSource.EXTERNAL, LockinRefenceEdge.FALLING)
        lockin.set_sensitivity(entry.sensitivity)
        lockin.set_reserve_mode(entry.reserve_mode)
        for output in entry.outputs:
            offset_channel = output.offset_channel()
            if offset_channel is not None:
                lockin.set_output_offset(offset_channel, entry.offset_pct, entry.expand)

    def auto_offset(self) -> None:
        """Enable the 6221, settle, and run auto-offset on all configured lock-in output channels.

        For each lock-in and each output that supports an offset channel (X, Y, R), this
        method sends the SR830 ``AOFF`` command and reads back the resulting offset
        percentage, storing it in :attr:`LockInEntry.auto_offsets`.  The stored offsets
        are applied as additive corrections to subsequent measurements when
        :attr:`_offset_enabled` is ``True``.

        Raises:
            RuntimeError:
                If the instruments are not connected.
        """
        if self._k6221 is None or not self._lockins:
            raise RuntimeError("Not connected — call connect() and configure() before auto_offset().")
        self._k6221.enable_output(True)
        try:
            wait_time = self._time_constant * self._read_rate_multiple
            if wait_time > 0.0:
                time.sleep(wait_time)
            with ThreadPoolExecutor(max_workers=max(1, len(self._lockins))) as executor:
                futures = [
                    executor.submit(self._auto_offset_one_lockin, entry, lockin)
                    for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True)
                ]
                for future in futures:
                    future.result()
        finally:
            self._k6221.enable_output(False)

    def _auto_offset_one_lockin(self, entry: LockInEntry, lockin: SRS830) -> None:
        """Run auto-offset on all offsettable outputs of one lock-in entry.

        For each output in *entry* that supports an offset channel (X, Y, R),
        sends ``AOFF`` and reads back the resulting offset percentage into
        :attr:`LockInEntry.auto_offsets`.

        Args:
            entry (LockInEntry):
                Lock-in configuration entry whose :attr:`~LockInEntry.auto_offsets`
                dict is updated in place.
            lockin (SRS830):
                SR830 instrument driver to send the auto-offset command to.
        """
        entry.auto_offsets.clear()
        for output in entry.outputs:
            channel = output.offset_channel()
            if channel is not None:
                lockin.auto_offset_channel(channel)
                offset_pct, _expand = lockin.get_output_offset(channel)
                entry.auto_offsets[channel.value] = float(offset_pct)

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
                "line_filter": self._line_filter.value,
                "read_rate_multiple": self._read_rate_multiple,
                "auto_sensitivity_enabled": self._auto_sensitivity_enabled,
                "auto_sensitivity_low": self._auto_sensitivity_low,
                "auto_sensitivity_high": self._auto_sensitivity_high,
                "offset_enabled": self._offset_enabled,
                "source_range_mode": self._source_range_mode,
                "resistance_enabled": self._resistance_enabled,
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
        self._line_filter = self._parse_enum(
            LockInLineFilter,
            data.get("line_filter", self._line_filter.value),
            self._line_filter,
            "line_filter",
        )
        self._read_rate_multiple = float(data.get("read_rate_multiple", self._read_rate_multiple))
        self._auto_sensitivity_enabled = bool(data.get("auto_sensitivity_enabled", self._auto_sensitivity_enabled))
        self._auto_sensitivity_low = float(data.get("auto_sensitivity_low", self._auto_sensitivity_low))
        self._auto_sensitivity_high = float(data.get("auto_sensitivity_high", self._auto_sensitivity_high))
        self._offset_enabled = bool(data.get("offset_enabled", self._offset_enabled))
        self._source_range_mode = str(data.get("source_range_mode", self._source_range_mode))
        self._resistance_enabled = bool(data.get("resistance_enabled", self._resistance_enabled))
        # resistance_mode was removed; silently ignore it if present in legacy configs.

        restored_entries = data.get("lockins", [])
        if isinstance(restored_entries, list) and restored_entries:
            self._lockin_entries = [
                self._restore_lockin_entry(entry, index) for index, entry in enumerate(restored_entries)
            ]
        self._apply_scan_units()

    def _plugin_config_tabs(self) -> QWidget:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        tab_widget = QTabWidget()

        # ---- Tab 1: Source & Common ----
        source_common_page = QWidget()
        sc_layout = QVBoxLayout(source_common_page)
        sc_layout.setContentsMargins(4, 4, 4, 4)

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
        amplitude_sb.valueChanged.connect(lambda value: setattr(self, "_waveform_amplitude", float(value)))

        offset_sb = SISpinBox(suffix="A", siPrefix=True, value=self._waveform_offset)
        offset_sb.setMinimum(-1.0)
        offset_sb.setMaximum(1.0)
        offset_sb.valueChanged.connect(lambda value: setattr(self, "_waveform_offset", float(value)))

        frequency_sb = SISpinBox(suffix="Hz", siPrefix=True, value=self._waveform_frequency)
        frequency_sb.setMinimum(1e-3)
        frequency_sb.setMaximum(1e6)
        frequency_sb.valueChanged.connect(lambda value: setattr(self, "_waveform_frequency", float(value)))

        phase_combo = QComboBox()
        for line in range(1, 7):
            phase_combo.addItem(f"Line {line}", line)
        phase_combo.setCurrentIndex(phase_combo.findData(self._phase_marker_tlink))
        phase_combo.currentIndexChanged.connect(
            lambda index: setattr(self, "_phase_marker_tlink", int(phase_combo.itemData(index)))
        )

        range_combo = QComboBox()
        range_combo.addItem("Auto", "AUTO")
        range_combo.addItem("Best fixed", "BEST")
        range_combo.addItem("Fixed (calculated)", "FIXED")
        range_combo.setCurrentIndex(range_combo.findData(self._source_range_mode))
        range_combo.currentIndexChanged.connect(
            lambda index: setattr(self, "_source_range_mode", range_combo.itemData(index))
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
        source_form.addRow("Source range:", range_combo)
        sc_layout.addWidget(source_group)

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

        line_filter_combo = QComboBox()
        line_filter_combo.addItem("None", LockInLineFilter.NONE)
        line_filter_combo.addItem("Line", LockInLineFilter.LINE)
        line_filter_combo.addItem("2\u00d7 line", LockInLineFilter.LINE_2X)
        line_filter_combo.addItem("Line + 2\u00d7 line", LockInLineFilter.BOTH)
        line_filter_combo.setCurrentIndex(line_filter_combo.findData(self._line_filter))
        line_filter_combo.currentIndexChanged.connect(
            lambda index: setattr(self, "_line_filter", line_filter_combo.itemData(index))
        )

        read_multiple_sb = SISpinBox(value=self._read_rate_multiple)
        read_multiple_sb.setMinimum(0.0)
        read_multiple_sb.setMaximum(1000.0)
        read_multiple_sb.valueChanged.connect(lambda value: setattr(self, "_read_rate_multiple", float(value)))

        auto_enabled = QCheckBox("Enable auto-sensitivity")
        auto_enabled.setChecked(self._auto_sensitivity_enabled)
        auto_enabled.toggled.connect(lambda checked: setattr(self, "_auto_sensitivity_enabled", bool(checked)))

        auto_low_sb = SISpinBox(value=self._auto_sensitivity_low)
        auto_low_sb.setMinimum(0.0)
        auto_low_sb.setMaximum(1.0)
        auto_low_sb.setSingleStep(0.05)
        auto_low_sb.valueChanged.connect(lambda value: setattr(self, "_auto_sensitivity_low", float(value)))

        auto_high_sb = SISpinBox(value=self._auto_sensitivity_high)
        auto_high_sb.setMinimum(0.0)
        auto_high_sb.setMaximum(1.0)
        auto_high_sb.setSingleStep(0.05)
        auto_high_sb.valueChanged.connect(lambda value: setattr(self, "_auto_sensitivity_high", float(value)))

        common_form.addRow("Time constant:", time_constant_combo)
        common_form.addRow("Filter slope:", slope_combo)
        common_form.addRow("Coupling:", coupling_combo)
        common_form.addRow("Line filter:", line_filter_combo)
        common_form.addRow("Read cooldown multiple:", read_multiple_sb)
        common_form.addRow(auto_enabled)
        common_form.addRow("Auto-sensitivity low ratio:", auto_low_sb)
        common_form.addRow("Auto-sensitivity high ratio:", auto_high_sb)
        sc_layout.addWidget(common_group)

        derived_group = QGroupBox("Resistance conversion")
        derived_form = QFormLayout(derived_group)

        resistance_enabled = QCheckBox("Create resistance-derived channels")
        resistance_enabled.setChecked(self._resistance_enabled)
        resistance_enabled.toggled.connect(lambda checked: setattr(self, "_resistance_enabled", bool(checked)))

        derived_form.addRow(resistance_enabled)
        sc_layout.addWidget(derived_group)
        sc_layout.addStretch(1)

        # ---- Tab 2: Lock-ins ----
        lockins_page = QWidget()
        lockins_layout = QVBoxLayout(lockins_page)
        lockins_layout.setContentsMargins(4, 4, 4, 4)

        lockins_table = QTableWidget()
        lockins_table.setRowCount(_LOCKIN_TABLE_ROWS)
        lockins_table.setVerticalHeaderLabels(_LOCKIN_ROW_LABELS)
        lockins_table.horizontalHeader().setVisible(False)
        lockins_table.horizontalHeader().setMinimumSectionSize(180)
        lockins_table.verticalHeader().setDefaultSectionSize(28)
        lockins_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectColumns)

        add_button = QPushButton("Add lock-in")
        remove_button = QPushButton("Remove selected")
        auto_offset_button = QPushButton("Run auto-offset")
        offset_enabled_check = QCheckBox("Offset compensation enabled")
        offset_enabled_check.setChecked(self._offset_enabled)
        offset_enabled_check.toggled.connect(lambda checked: setattr(self, "_offset_enabled", bool(checked)))

        def _refresh_lockin_table() -> None:
            lockins_table.blockSignals(True)
            n_cols = len(self._lockin_entries)
            lockins_table.setColumnCount(n_cols)
            for col in range(n_cols):
                lockins_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)

            for col, entry in enumerate(self._lockin_entries):
                label_edit = QLineEdit(entry.label)
                label_edit.textChanged.connect(
                    lambda text, *, idx=col: setattr(self._lockin_entries[idx], "label", text)
                )
                lockins_table.setCellWidget(_ROW_LABEL, col, label_edit)

                resource_widget = VisaResourceComboBox(resource_filter=FILTER_GPIB)
                resource_widget.setCurrentText(entry.resource)
                resource_widget.currentTextChanged.connect(
                    lambda text, *, idx=col: setattr(self._lockin_entries[idx], "resource", text.strip())
                )
                lockins_table.setCellWidget(_ROW_RESOURCE, col, resource_widget)

                input_source_combo = QComboBox()
                input_source_combo.addItem("A (voltage)", LockInInputSource.A)
                input_source_combo.addItem("A\u2212B (voltage)", LockInInputSource.A_MINUS_B)
                input_source_combo.addItem("I (1 M\u03a9)", LockInInputSource.I_1MOHM)
                input_source_combo.addItem("I (100 M\u03a9)", LockInInputSource.I_100MOHM)
                input_source_combo.setCurrentIndex(input_source_combo.findData(entry.input_source))
                input_source_combo.currentIndexChanged.connect(
                    lambda index, *, idx=col, combo=input_source_combo: setattr(
                        self._lockin_entries[idx], "input_source", combo.itemData(index)
                    )
                )
                lockins_table.setCellWidget(_ROW_INPUT_SOURCE, col, input_source_combo)

                input_shield_combo = QComboBox()
                input_shield_combo.addItem("Float", LockInInputShielding.FLOAT)
                input_shield_combo.addItem("Ground", LockInInputShielding.GROUND)
                input_shield_combo.setCurrentIndex(input_shield_combo.findData(entry.input_shielding))
                input_shield_combo.currentIndexChanged.connect(
                    lambda index, *, idx=col, combo=input_shield_combo: setattr(
                        self._lockin_entries[idx], "input_shielding", combo.itemData(index)
                    )
                )
                lockins_table.setCellWidget(_ROW_INPUT_SHIELDING, col, input_shield_combo)

                # Per-output checkboxes — one row each for X, Y, R, θ.
                output_checks: dict[LockInOutput, QCheckBox] = {}
                for output, row in _OUTPUT_ROWS:
                    cb = QCheckBox()
                    cb.setChecked(output in entry.outputs)
                    output_checks[output] = cb
                    lockins_table.setCellWidget(row, col, cb)

                sensitivity_combo = SIComboBox(unit="V")
                for value in _SR830_SENSITIVITIES:
                    sensitivity_combo.addValueItem(value)
                sensitivity_combo.setFloatValue(entry.sensitivity)
                sensitivity_combo.valueChanged.connect(
                    lambda value, *, idx=col: setattr(self._lockin_entries[idx], "sensitivity", float(value))
                )
                lockins_table.setCellWidget(_ROW_SENSITIVITY, col, sensitivity_combo)

                auto_sens_check = QCheckBox()
                auto_sens_check.setChecked(entry.auto_sensitivity)
                auto_sens_check.toggled.connect(
                    lambda checked, *, idx=col: setattr(self._lockin_entries[idx], "auto_sensitivity", bool(checked))
                )
                lockins_table.setCellWidget(_ROW_AUTO_SENSITIVITY, col, auto_sens_check)

                harmonic_spin = QSpinBox()
                harmonic_spin.setMinimum(1)
                harmonic_spin.setMaximum(_SR830_MAX_HARMONIC)
                harmonic_spin.setValue(entry.harmonic)
                harmonic_spin.valueChanged.connect(
                    lambda value, *, idx=col: setattr(self._lockin_entries[idx], "harmonic", int(value))
                )
                lockins_table.setCellWidget(_ROW_HARMONIC, col, harmonic_spin)

                phase_spin = SISpinBox(suffix="\u00b0", value=entry.phase)
                phase_spin.setMinimum(-360.0)
                phase_spin.setMaximum(360.0)
                phase_spin.valueChanged.connect(
                    lambda value, *, idx=col: setattr(self._lockin_entries[idx], "phase", float(value))
                )
                lockins_table.setCellWidget(_ROW_PHASE, col, phase_spin)

                auto_phase_check = QCheckBox()
                auto_phase_check.setChecked(entry.auto_phase)
                auto_phase_check.toggled.connect(
                    lambda checked, *, idx=col: setattr(self._lockin_entries[idx], "auto_phase", bool(checked))
                )
                lockins_table.setCellWidget(_ROW_AUTO_PHASE, col, auto_phase_check)

                offset_local = SISpinBox(suffix="%", value=entry.offset_pct)
                offset_local.setMinimum(-105.0)
                offset_local.setMaximum(105.0)

                expand_combo = QComboBox()
                expand_combo.addItem("\u00d71", LockInExpandFactor.X1)
                expand_combo.addItem("\u00d710", LockInExpandFactor.X10)
                expand_combo.addItem("\u00d7100", LockInExpandFactor.X100)
                expand_combo.setCurrentIndex(expand_combo.findData(entry.expand))

                reserve_combo = QComboBox()
                reserve_combo.addItem("High reserve", LockInReserveMode.HIGH_RESERVE)
                reserve_combo.addItem("Normal", LockInReserveMode.NORMAL)
                reserve_combo.addItem("Low noise", LockInReserveMode.LOW_NOISE)
                reserve_combo.setCurrentIndex(reserve_combo.findData(entry.reserve_mode))

                def _rebuild_outputs(
                    *,
                    idx=col,
                    checks=output_checks,
                    offset_w=offset_local,
                    expand_w=expand_combo,
                ) -> None:
                    outputs = tuple(
                        o
                        for o, _row in _OUTPUT_ROWS
                        if checks[o].isChecked()
                    )
                    if not outputs:
                        # Ensure at least one output is always selected.
                        outputs = (LockInOutput.X,)
                        checks[LockInOutput.X].setChecked(True)
                    self._lockin_entries[idx].outputs = outputs
                    supports_offset = any(o.offset_channel() is not None for o in outputs)
                    offset_w.setEnabled(supports_offset)
                    expand_w.setEnabled(supports_offset)

                for _output_cb in output_checks.values():
                    _output_cb.toggled.connect(lambda _checked, f=_rebuild_outputs: f())

                offset_local.valueChanged.connect(
                    lambda value, *, idx=col: setattr(self._lockin_entries[idx], "offset_pct", float(value))
                )
                expand_combo.currentIndexChanged.connect(
                    lambda index, *, idx=col, combo=expand_combo: setattr(
                        self._lockin_entries[idx], "expand", combo.itemData(index)
                    )
                )
                reserve_combo.currentIndexChanged.connect(
                    lambda index, *, idx=col, combo=reserve_combo: setattr(
                        self._lockin_entries[idx], "reserve_mode", combo.itemData(index)
                    )
                )

                lockins_table.setCellWidget(_ROW_OFFSET_PCT, col, offset_local)
                lockins_table.setCellWidget(_ROW_EXPAND, col, expand_combo)
                lockins_table.setCellWidget(_ROW_RESERVE, col, reserve_combo)
                _rebuild_outputs()

            remove_button.setEnabled(len(self._lockin_entries) > 1)
            lockins_table.blockSignals(False)

        def _next_lockin_label() -> str:
            return f"LIA {len(self._lockin_entries) + 1}"

        def _add_lockin() -> None:
            self._lockin_entries.append(LockInEntry(label=_next_lockin_label(), resource="GPIB0::9::INSTR"))
            _refresh_lockin_table()

        def _remove_selected_lockin() -> None:
            selected = sorted({index.column() for index in lockins_table.selectedIndexes()}, reverse=True)
            if not selected or len(self._lockin_entries) == 1:
                return
            for col in selected:
                self._lockin_entries.pop(col)
            _refresh_lockin_table()

        add_button.clicked.connect(_add_lockin)
        remove_button.clicked.connect(_remove_selected_lockin)

        def _safe_auto_offset() -> None:
            """Invoke auto_offset(), logging any RuntimeError rather than propagating it."""
            try:
                self.auto_offset()
            except RuntimeError as exc:
                self._log.warning("Auto-offset not available: %s", exc)

        auto_offset_button.clicked.connect(_safe_auto_offset)
        _refresh_lockin_table()

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(add_button)
        buttons_layout.addWidget(remove_button)
        buttons_layout.addWidget(auto_offset_button)
        buttons_layout.addStretch(1)

        lockins_layout.addWidget(lockins_table)
        lockins_layout.addLayout(buttons_layout)
        lockins_layout.addWidget(offset_enabled_check)

        tab_widget.addTab(source_common_page, "Source && Common")
        tab_widget.addTab(lockins_page, "Lock-ins")

        root_layout.addWidget(tab_widget)
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
                            unit="\u03a9",
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
        if self._source_range_mode not in {"AUTO", "BEST", "FIXED"}:
            raise ValueError("Source range mode must be one of 'AUTO', 'BEST', or 'FIXED'.")

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
            if not 1 <= entry.harmonic <= _SR830_MAX_HARMONIC:
                raise ValueError(f"Lock-in {label!r} harmonic must be between 1 and {_SR830_MAX_HARMONIC}.")
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

    def _apply_source_range(self) -> None:
        """Apply the configured source-current range to the 6221."""
        if self._k6221 is None:
            raise RuntimeError("Not connected.")
        if self._source_range_mode == "FIXED":
            max_current = self._calculate_max_current()
            if max_current > 0.0:
                self._k6221.set_fixed_range(max_current)
        elif self._source_range_mode == "AUTO":
            self._k6221.set_sweep_range_mode("AUTO")
        else:
            self._k6221.set_sweep_range_mode("BEST")

    def _calculate_max_current(self) -> float:
        """Calculate the maximum absolute peak current for the current scan configuration.

        Returns:
            (float):
                Maximum instantaneous output current magnitude in amps.
        """
        sweep = self._sweep_values
        if self._scan_mode is WaveformScanMode.AMPLITUDE:
            max_amp = float(np.max(np.abs(sweep))) if sweep is not None and sweep.size > 0 else abs(self._waveform_amplitude)
            return max_amp + abs(self._waveform_offset)
        if self._scan_mode is WaveformScanMode.OFFSET:
            max_off = float(np.max(np.abs(sweep))) if sweep is not None and sweep.size > 0 else abs(self._waveform_offset)
            return abs(self._waveform_amplitude) + max_off
        return abs(self._waveform_amplitude) + abs(self._waveform_offset)

    def _run_auto_phase(self, output_off:bool = False) -> None:
        """Enable the 6221 output, settle, and run auto-phase for entries that request it."""
        if not any(entry.auto_phase for entry in self._lockin_entries):
            return
        if self._k6221 is None:
            raise RuntimeError("Not connected.")
        self._k6221.enable_output(True)
        try:
            wait_time = self._time_constant * self._read_rate_multiple
            if wait_time > 0.0:
                time.sleep(wait_time)
            phase_lockins = [
                lockin
                for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True)
                if entry.auto_phase
            ]
            with ThreadPoolExecutor(max_workers=max(1, len(phase_lockins))) as executor:
                futures = [executor.submit(lockin.auto_phase) for lockin in phase_lockins]
                for future in futures:
                    future.result()
        finally:
            if output_off:
                self._k6221.enable_output(False)

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
                current_amplitude = self._current_amplitude_for_point(float(scan_value))
                for spec in specs:
                    entry = self._lockin_entries[spec.lockin_index]
                    reading = readings[entry.resource]
                    output_value = reading.output_values[spec.output]
                    if self._offset_enabled:
                        output_value = self._apply_offset_correction(entry, spec.output, output_value)
                    if spec.derived_resistance:
                        value = self._convert_to_resistance(output_value, current_amplitude)
                    else:
                        value = output_value
                    channel_values[spec.name].append(float(value))
                self._apply_auto_sensitivity(readings)
        except:
            self._k6221.enable_output(False)
            raise

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
        with ThreadPoolExecutor(max_workers=max(1, len(self._lockins))) as executor:
            futures = [
                executor.submit(self._read_one_lockin, entry, lockin)
                for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True)
            ]
            results = [future.result() for future in futures]
        return dict(results)

    def _read_one_lockin(self, entry: LockInEntry, lockin: SRS830) -> tuple[str, LockInReading]:
        """Read outputs from one SR830 and return ``(resource, reading)``.

        Args:
            entry (LockInEntry):
                Lock-in configuration entry specifying the requested outputs.
            lockin (SRS830):
                SR830 instrument driver to read from.

        Returns:
            (str):
                VISA resource string identifying this lock-in (used as the
                key in the readings dict returned by :meth:`_read_lockins`).
            (LockInReading):
                Measured output values and the R-channel signal used for
                auto-sensitivity decisions.
        """
        requested_outputs = entry.outputs
        if LockInOutput.R not in requested_outputs:
            requested_outputs = (*requested_outputs, LockInOutput.R)
        measured_values = lockin.measure_outputs(requested_outputs)
        output_values = {output: float(measured_values[output]) for output in entry.outputs}
        ratio_signal = abs(float(measured_values[LockInOutput.R]))
        return entry.resource, LockInReading(output_values, float(ratio_signal))

    def _trigger_gpib_lockins(self) -> None:
        for lockin in self._lockins:
            transport = lockin.transport
            if isinstance(transport, GpibTransport):
                transport.send_group_execute_trigger()

    def _apply_auto_sensitivity(self, readings: dict[str, LockInReading]) -> None:
        if not self._auto_sensitivity_enabled:
            return
        sensitivities = _SR830_SENSITIVITIES
        with ThreadPoolExecutor(max_workers=max(1, len(self._lockins))) as executor:
            futures = [
                executor.submit(
                    self._apply_auto_sensitivity_one_lockin,
                    entry,
                    lockin,
                    readings[entry.resource],
                    sensitivities,
                )
                for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True)
            ]
            for future in futures:
                future.result()

    def _apply_auto_sensitivity_one_lockin(
        self,
        entry: LockInEntry,
        lockin: SRS830,
        reading: LockInReading,
        sensitivities: tuple[float, ...],
    ) -> None:
        """Adjust the sensitivity of one lock-in if the signal ratio is out of range.

        Args:
            entry (LockInEntry):
                Lock-in configuration entry whose :attr:`~LockInEntry.sensitivity`
                is updated in place when a range change is made.
            lockin (SRS830):
                SR830 instrument driver to apply the new sensitivity to.
            reading (LockInReading):
                Most recent reading for this lock-in, used to compute the
                signal-to-full-scale ratio.
            sensitivities (tuple[float, ...]):
                Ordered sequence of all valid SR830 sensitivity values, used to
                step up or down from the current setting.
        """
        if not entry.auto_sensitivity:
            return
        if entry.sensitivity <= 0.0:
            return
        ratio = abs(reading.ratio_signal) / entry.sensitivity
        try:
            index = sensitivities.index(entry.sensitivity)
        except ValueError:
            return
        new_index = index
        if ratio < self._auto_sensitivity_low and index > 0:
            new_index = index - 1
        elif ratio > self._auto_sensitivity_high and index < len(sensitivities) - 1:
            new_index = index + 1
        if new_index != index:
            new_sensitivity = sensitivities[new_index]
            lockin.set_sensitivity(new_sensitivity)
            entry.sensitivity = new_sensitivity

    def _apply_offset_correction(self, entry: LockInEntry, output: LockInOutput, value: float) -> float:
        """Return the true signal value by reversing the SR830 output offset.

        When the SR830 has an offset applied, the SNAP output equals
        ``(true_signal - offset_voltage)``.  This method adds back the offset
        voltage to recover the true signal.

        Args:
            entry (LockInEntry):
                Lock-in entry containing offset information.
            output (LockInOutput):
                The output component being corrected.
            value (float):
                Measured (offset-subtracted) value from the SR830.

        Returns:
            (float):
                Offset-corrected true signal value.
        """
        channel = output.offset_channel()
        if channel is None:
            return value
        if channel.value in entry.auto_offsets:
            offset_pct = entry.auto_offsets[channel.value]
        else:
            offset_pct = entry.offset_pct
        return value + (offset_pct / 100.0) * entry.sensitivity

    def _current_amplitude_for_point(self, scan_value: float) -> float:
        if self._scan_mode is WaveformScanMode.AMPLITUDE:
            return abs(scan_value)
        return abs(self._waveform_amplitude)

    def _convert_to_resistance(self, signal: float, amplitude: float) -> float:
        """Convert a lock-in RMS voltage reading to resistance.

        The 6221 amplitude parameter is the peak (amplitude) value of the sine
        wave.  The SR830 reports RMS voltage.  To compute a consistent resistance
        both quantities must be expressed in the same form, so the peak current is
        converted to its RMS equivalent before dividing into the RMS voltage:

            R = V_rms / I_rms = V_rms / (I_peak / sqrt(2))

        Args:
            signal (float):
                RMS voltage reading from the SR830 in volts.
            amplitude (float):
                Peak current amplitude from the 6221 in amps.

        Returns:
            (float):
                Computed resistance in ohms, or NaN when the current is
                effectively zero.
        """
        current = amplitude / math.sqrt(2.0)
        if abs(current) <= _ZERO_CURRENT_THRESHOLD:
            return float("nan")
        return signal / current

    def _restore_lockin_entry(self, data: Any, index: int) -> LockInEntry:
        default_label = f"LIA {index + 1}"
        if not isinstance(data, dict):
            return LockInEntry(label=default_label)
        auto_offsets_raw = data.get("auto_offsets", {})
        auto_offsets: dict[str, float] = (
            {str(k): float(v) for k, v in auto_offsets_raw.items()} if isinstance(auto_offsets_raw, dict) else {}
        )
        return LockInEntry(
            label=str(data.get("label", default_label)),
            resource=str(data.get("resource", "GPIB0::8::INSTR")),
            input_source=self._parse_enum(
                LockInInputSource,
                data.get("input_source", LockInInputSource.A_MINUS_B.value),
                LockInInputSource.A_MINUS_B,
                "input_source",
            ),
            input_shielding=self._parse_enum(
                LockInInputShielding,
                data.get("input_shielding", LockInInputShielding.FLOAT.value),
                LockInInputShielding.FLOAT,
                "input_shielding",
            ),
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
            harmonic=int(data.get("harmonic", 1)),
            phase=float(data.get("phase", 0.0)),
            auto_phase=bool(data.get("auto_phase", False)),
            auto_sensitivity=bool(data.get("auto_sensitivity", True)),
            auto_offsets=auto_offsets,
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
        """Parse lock-in output selections from text or serialised data.

        Notes:
            The shorthand token ``"T"`` is accepted as an alias for
            ``"THETA"`` in text input fields.
        """
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
