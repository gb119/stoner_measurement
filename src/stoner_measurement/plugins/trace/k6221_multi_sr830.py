"""Keithley 6221 + multiple lock-in amplifier trace plugin."""

from __future__ import annotations

import enum
import logging
import math
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from typing import Any, cast

import numpy as np
import pandas as pd
import pyvisa
from qtpy.QtWidgets import (
    QAbstractItemView,
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
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.trace_data import COLUMN_ROLE_Y, TraceData
from stoner_measurement.instruments.current_source import CurrentWaveform
from stoner_measurement.instruments.keithley.k6221 import Keithley6221
from stoner_measurement.instruments.lockin_amplifier import (
    LockInExpandFactor,
    LockInInputCoupling,
    LockInInputSource,
    LockInLineFilter,
    LockInOutput,
    LockInOutputChannel,
    LockinRefenceEdge,
    LockInReferenceSource,
    LockInReserveMode,
)
from stoner_measurement.instruments.signal_recovery import SR7265, SR7265Status
from stoner_measurement.instruments.srs.sr830 import SRS830, SRS830LIAStatus
from stoner_measurement.instruments.transport.gpib_transport import GpibTransport
from stoner_measurement.plugins.trace.base import TracePlugin, TraceStatus
from stoner_measurement.qt_compat import pyqtSignal
from stoner_measurement.scan import FunctionScanGenerator, ListScanGenerator, SteppedScanGenerator
from stoner_measurement.ui.aspect_ratio_widget import set_table_visible_row_count
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.theme import colour
from stoner_measurement.ui.widgets import (
    FILTER_GPIB,
    AutoSISpinBox,
    SIComboBox,
    SISpinBox,
    VisaResourceComboBox,
)

_CLEANUP_EXCEPTIONS: tuple[type[Exception], ...] = (OSError, RuntimeError, pyvisa.Error)
_ZERO_CURRENT_THRESHOLD: float = 1e-30
_SR830_TIME_CONSTANTS: tuple[float, ...] = SRS830.supported_time_constants()
_SR830_SENSITIVITIES: tuple[float, ...] = SRS830.supported_sensitivities()
_SR830_FILTER_SLOPES: tuple[int, ...] = SRS830.supported_filter_slopes()
_SR830_MAX_HARMONIC: int = SRS830.max_harmonic()
_SR7265_TIME_CONSTANTS: tuple[float, ...] = SR7265.supported_time_constants()
_SR7265_FILTER_SLOPES: tuple[int, ...] = SR7265.supported_filter_slopes()
_SR7265_MAX_HARMONIC: int = SR7265.max_harmonic()
_SR830_STATUS_IFC = 1 << 1
_SR7265_STATUS_COMMAND_COMPLETE = 1 << 0
_SR830_STATUS_LIA = 1 << 3
_TRACE_NAME = "Signals"
SupportedLockIn = SRS830 | SR7265

# Row indices for the transposed lock-in configuration table.
_ROW_LABEL = 0
_ROW_MODEL = 1
_ROW_RESOURCE = 2
_ROW_OUTPUT_X = 3
_ROW_OUTPUT_Y = 4
_ROW_OUTPUT_R = 5
_ROW_OUTPUT_THETA = 6
_ROW_SENSITIVITY = 7
_ROW_HARMONIC = 8
_ROW_PHASE = 9
_ROW_OFFSET_PCT = 10
_ROW_EXPAND = 11
_ROW_RESERVE = 12
_ROW_INPUT = 13
_ROW_SLOPE = 14
_ROW_COUPLING = 15
_ROW_LINE_FILTER = 16
_LOCKIN_TABLE_ROWS = 17

_LOCKIN_OUTPUT_ROWS: dict[LockInOutput, int] = {
    LockInOutput.X: _ROW_OUTPUT_X,
    LockInOutput.Y: _ROW_OUTPUT_Y,
    LockInOutput.R: _ROW_OUTPUT_R,
    LockInOutput.THETA: _ROW_OUTPUT_THETA,
}

_LOCKIN_ROW_LABELS: list[str] = [
    "Label",
    "Model",
    "Resource",
    "Output X",
    "Output Y",
    "Output R",
    "Output THETA",
    "Sensitivity",
    "Harmonic",
    "Phase (\u00b0)",
    "Offset (%)",
    "Expand",
    "Reserve",
    "Input",
    "Filter slope",
    "Coupling",
    "Line filter",
]


class WaveformScanMode(enum.Enum):
    """Selectable 6221 sine-wave parameter to scan."""

    AMPLITUDE = "amplitude"
    OFFSET = "offset"
    FREQUENCY = "frequency"


class LockInModel(enum.Enum):
    """Lock-in models supported by the 6221 trace plugin."""

    SR830 = "SR830"
    SR7265 = "SR7265"

    @property
    def display_name(self) -> str:
        """Return the model name shown in the configuration editor."""
        if self is LockInModel.SR7265:
            return SR7265.DISPLAY_NAME
        return "SRS SR830"


def _lockin_driver_class(model: LockInModel) -> type[SRS830] | type[SR7265]:
    """Return the concrete driver class for *model*."""
    if model is LockInModel.SR7265:
        return SR7265
    return SRS830


def _lockin_time_constants(model: LockInModel) -> tuple[float, ...]:
    """Return time constants supported by *model*."""
    if model is LockInModel.SR7265:
        return _SR7265_TIME_CONSTANTS
    return _SR830_TIME_CONSTANTS


def _is_current_input(source: LockInInputSource) -> bool:
    """Return whether the selected input measures current."""
    return source in (LockInInputSource.I_1MOHM, LockInInputSource.I_100MOHM)


def _lockin_input_options(model: LockInModel) -> list[tuple[str, LockInInputSource]]:
    """Return model-supported input modes with hardware-specific labels."""
    options = [("A", LockInInputSource.A), ("A-B", LockInInputSource.A_MINUS_B)]
    if model is LockInModel.SR7265:
        options.insert(1, ("B (inverted)", LockInInputSource.B))
        options.extend(
            [
                ("Current (wide bandwidth)", LockInInputSource.I_1MOHM),
                ("Current (low noise)", LockInInputSource.I_100MOHM),
            ]
        )
    else:
        options.extend(
            [
                ("Current (1 MΩ)", LockInInputSource.I_1MOHM),
                ("Current (100 MΩ)", LockInInputSource.I_100MOHM),
            ]
        )
    return options


def _lockin_sensitivities(
    model: LockInModel, source: LockInInputSource = LockInInputSource.A_MINUS_B
) -> tuple[float, ...]:
    """Return full-scale ranges in volts or amperes for the selected input."""
    if model is LockInModel.SR7265:
        return SR7265.supported_sensitivities(source)
    if _is_current_input(source):
        values = tuple(value * 1e-6 for value in _SR830_SENSITIVITIES)
        if source is LockInInputSource.I_100MOHM:
            return tuple(value for value in values if value <= 1e-8)
        return values
    return _SR830_SENSITIVITIES


def _sensitivity_driver_scale(model: LockInModel, source: LockInInputSource) -> float:
    """Adapt the SR830 driver's voltage-indexed sensitivity API to amperes."""
    return 1e-6 if model is LockInModel.SR830 and _is_current_input(source) else 1.0


def _sensitivity_index(value: float, sensitivities: tuple[float, ...]) -> int | None:
    """Match a hardware range despite floating-point unit conversion rounding."""
    return next(
        (
            index
            for index, sensitivity in enumerate(sensitivities)
            if math.isclose(value, sensitivity, rel_tol=1e-9)
        ),
        None,
    )


def _output_unit(entry: LockInEntry, output: LockInOutput) -> str:
    """Return the physical unit of an output in the selected input mode."""
    return (
        "A"
        if _is_current_input(entry.input_source) and output is not LockInOutput.THETA
        else output.unit
    )


def _lockin_filter_slopes(model: LockInModel) -> tuple[int, ...]:
    """Return filter slopes supported by *model*."""
    if model is LockInModel.SR7265:
        return _SR7265_FILTER_SLOPES
    return _SR830_FILTER_SLOPES


def _lockin_max_harmonic(model: LockInModel) -> int:
    """Return the largest detection harmonic supported by *model*."""
    if model is LockInModel.SR7265:
        return _SR7265_MAX_HARMONIC
    return _SR830_MAX_HARMONIC


def _lockin_has_output_offsets(model: LockInModel) -> bool:
    """Return whether *model* implements output offset and expansion."""
    return model is LockInModel.SR830


@dataclass
class LockInEntry:
    """Configuration for one lock-in amplifier instance.

    Attributes:
        label (str):
            Human-readable name used to identify this lock-in's channels.
        model (LockInModel):
            Concrete lock-in model used for connection and configuration.
        resource (str):
            VISA resource string for the lock-in instrument.
        filter_slope (int):
            Output-filter slope in dB/octave.
        input_coupling (LockInInputCoupling):
            AC or DC input coupling.
        line_filter (LockInLineFilter):
            Line-frequency notch filters to enable.
        input_source (LockInInputSource):
            Voltage or current input mode supported by the selected model.
        sensitivity (float):
            Initial input sensitivity in volts or amperes for the input mode.
        offset_pct (float):
            Output offset as a percentage of full scale (−105 to +105).
        offset_auto (bool):
            When ``True``, calculate per-channel offsets from settled readings
            during :meth:`Keithley6221_MultiSR830Plugin.configure`.
        expand (LockInExpandFactor):
            Output expand factor.
        reserve_mode (LockInReserveMode):
            Dynamic reserve operating mode.
        outputs (tuple[LockInOutput, ...]):
            Ordered selection of outputs to record (1–4 unique values).
        harmonic (int):
            Detection harmonic (1 to :data:`_SR830_MAX_HARMONIC`).
        phase (float | None):
            Reference phase offset in degrees, or ``None`` to run auto-phase
            after settling during configure.
        auto_sensitivity (bool):
            When ``True``, this lock-in participates in dynamic auto-sensitivity
            during measurement (subject to the plugin-level master enable).
        auto_offsets (dict[str, float]):
            Per-channel offset percentages populated by :meth:`~Keithley6221_MultiSR830Plugin.auto_offset`.
            Keys are :class:`~stoner_measurement.instruments.lockin_amplifier.LockInOutputChannel`
            value strings (``"X"``, ``"Y"``, ``"R"``).
    """

    label: str = "LIA 1"
    model: LockInModel = LockInModel.SR830
    resource: str = "GPIB0::8::INSTR"
    filter_slope: int = 12
    input_coupling: LockInInputCoupling = LockInInputCoupling.AC
    line_filter: LockInLineFilter = LockInLineFilter.NONE
    input_source: LockInInputSource = LockInInputSource.A_MINUS_B
    sensitivity: float = 1e-3
    offset_pct: float = 0.0
    offset_auto: bool = False
    expand: LockInExpandFactor = LockInExpandFactor.X1
    reserve_mode: LockInReserveMode = LockInReserveMode.NORMAL
    outputs: tuple[LockInOutput, ...] = (LockInOutput.X,)
    harmonic: int = 1
    phase: float | None = 0.0
    auto_sensitivity: bool = True
    auto_offsets: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-friendly representation of this entry."""
        return {
            "label": self.label,
            "model": self.model.value,
            "resource": self.resource,
            "filter_slope": self.filter_slope,
            "input_coupling": self.input_coupling.value,
            "line_filter": self.line_filter.value,
            "input_source": self.input_source.value,
            "sensitivity": self.sensitivity,
            "offset_pct": self.offset_pct,
            "offset_auto": self.offset_auto,
            "expand": int(self.expand.value),
            "reserve_mode": self.reserve_mode.value,
            "outputs": [output.value for output in self.outputs],
            "harmonic": self.harmonic,
            "phase": "auto" if self.phase is None else self.phase,
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
    """One lock-in reading plus the value used for auto-sensitivity decisions."""

    output_values: dict[LockInOutput, float]
    ratio_signal: float


class Keithley6221_MultiSR830Plugin(TracePlugin):  # pylint: disable=invalid-name
    """Measure one swept 6221 parameter with one or more supported lock-ins.

    Use this plugin when a Keithley 6221 provides an AC excitation and one or
    more SRS SR830 or SIGNAL RECOVERY 7265 lock-in amplifiers measure the
    response. It is designed for experiments where you want to scan the
    waveform amplitude, offset, or frequency and record one or more lock-in
    outputs for each point.

    In the configuration tabs you first choose the 6221 connection and source
    settings, including the GPIB resource, the waveform parameter to scan, the
    fixed sine settings that are not being swept, the trigger-link output line,
    and the source-range policy. The same page also provides common lock-in
    settings such as time constant, auto-ranging thresholds,
    and the cooldown multiple used to decide how long to wait
    between successive readings. A resistance-conversion option can be enabled
    to add derived resistance channels from the measured lock-in voltages.

    The second tab contains the lock-in configuration table. Each column
    represents one instrument. For each lock-in you choose its model and set a
    human-readable label, resource string, selected output channels,
    sensitivity, whether it participates in auto-sensitivity, harmonic,
    input source, coupling, filter slope, line rejection, and numeric or
    automatic reference phase. Choices depend on the selected model.
    SR830 entries also provide output
    offset, expand factor, and reserve mode. Multiple outputs may be selected
    for each lock-in using separate check boxes for X, Y, R, and THETA.

    The scan generator defines the swept values. The plugin returns one
    shared-x trace named **Signals**, with columns named from lock-in labels
    and selected outputs. Resistance conversion adds derived columns for
    non-angular outputs.

    The runtime lifecycle follows a persistent-output model: :meth:`configure`
    leaves the 6221 output enabled, each :meth:`measure` reuses that configured
    source state to acquire a fresh scan, and :meth:`disconnect` turns the
    output off.

    Attributes:
        _6221_resource (str):
            VISA resource string for the Keithley 6221 current source.
        _scan_mode (WaveformScanMode):
            Which 6221 waveform parameter is scanned: amplitude, offset, or
            frequency.
        _waveform_amplitude (float):
            Fixed sine-wave amplitude in amps when amplitude is not the scanned
            quantity. This is interpreted as a zero-to-peak current.
        _waveform_offset (float):
            Fixed DC current offset in amps when offset is not the scanned
            quantity.
        _waveform_frequency (float):
            Fixed sine-wave frequency in hertz when frequency is not the
            scanned quantity.
        _phase_marker_tlink (int):
            Trigger-link output line used by the 6221 phase marker.
        _time_constant (float):
            Common lock-in time constant in seconds.
        _filter_slope (int):
            Legacy migration default for the per-lock-in filter slope.
        _input_coupling (LockInInputCoupling):
            Legacy migration default for per-lock-in input coupling.
        _line_filter (LockInLineFilter):
            Legacy migration default for per-lock-in line rejection.
        _read_rate_multiple (float):
            Multiplier applied to the time constant when enforcing a minimum
            interval between readings.
        _auto_sensitivity_enabled (bool):
            Master enable for automatic sensitivity adjustment.
        _auto_sensitivity_low (float):
            Lower signal-to-full-scale ratio threshold for auto-sensitivity.
        _auto_sensitivity_high (float):
            Upper signal-to-full-scale ratio threshold for auto-sensitivity.
        _offset_enabled (bool):
            When ``True``, apply stored or measured output-offset corrections to
            X, Y, and R readings.
        _source_range_mode (str):
            6221 source-range policy: ``"AUTO"``, ``"BEST"``, or ``"FIXED"``.
        _resistance_enabled (bool):
            When ``True``, emit derived resistance channels for non-angular
            lock-in outputs.
        _lockin_entries (list[LockInEntry]):
            Per-lock-in configuration entries defining labels, resources,
            outputs, sensitivity, harmonic, phase, and related settings.
        instance_name (str):
            Inherited Python identifier for this instance in the Script tab and
            QtConsole.
        comment (str):
            Inherited optional note displayed beside this step.
        sequence_engine (SequenceEngine | None):
            Inherited owning engine and its live namespace; None while
            detached.
        scan_generator (BaseScanGenerator):
            Inherited generator defining acquisition source values.
        data (dict[str, TraceData]):
            Inherited latest trace tables, keyed by trace name; inspect each
            table through its df attribute.
        status (TraceStatus):
            Inherited acquisition status, including data availability and
            errors.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        With an instance named ``k6221_multi_sr830`` in the sequence, use the
        QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            k6221_multi_sr830._time_constant = 0.1
            k6221_multi_sr830._lockin_entries
            k6221_multi_sr830.data
    """

    offset_addition_changed = pyqtSignal(bool)

    _scan_generator_class = ListScanGenerator
    _scan_generator_classes = [FunctionScanGenerator, SteppedScanGenerator, ListScanGenerator]

    def __init__(self, parent=None) -> None:
        """Initialise default connection, source, and lock-in settings."""
        super().__init__(parent)
        self._log = logging.getLogger(__name__)
        self.scan_generator = ListScanGenerator(stages=[(0.0, True)], parent=self)

        self._6221_resource: str = "GPIB0::13::INSTR"
        self._scan_mode: WaveformScanMode = WaveformScanMode.OFFSET
        self._waveform_amplitude: float | str = 1e-3
        self._waveform_offset: float | str = 0.0
        self._waveform_frequency: float | str = 367.0
        self._phase_marker_tlink: int = 4

        self._time_constant: float = 0.3
        self._filter_slope: int = 12
        self._input_coupling: LockInInputCoupling = LockInInputCoupling.AC
        self._line_filter: LockInLineFilter = LockInLineFilter.NONE
        self._read_rate_multiple: float | str = 3.0
        self._auto_sensitivity_enabled: bool = False
        self._auto_sensitivity_low: float | str = 0.1
        self._auto_sensitivity_high: float | str = 0.9
        self._offset_enabled: bool = False
        self._source_range_mode: str = "BEST"

        self._resistance_enabled: bool = False

        self._lockin_entries: list[LockInEntry] = [LockInEntry()]

        self._k6221: Keithley6221 | None = None
        self._lockins: list[SupportedLockIn] = []
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
        return _output_unit(self._lockin_entries[0], self._lockin_entries[0].outputs[0])

    @property
    def trace_names(self) -> list[str]:
        """Return the single shared-x trace dataset name."""
        return [_TRACE_NAME]

    def reported_values(self) -> dict[str, str]:
        """Return configured 6221 values and averaged outputs from every lock-in.

        Lock-in catalogue names use ``instance.label.output`` so that every
        selected output remains independently addressable even though the
        acquired data is stored in one shared multicolumn trace.
        """
        var = self.instance_name
        values = {
            f"{var}.K6221.offset": f"{var}._waveform_offset",
            f"{var}.K6221.amplitude": f"{var}._waveform_amplitude",
            f"{var}.K6221.frequency": f"{var}._waveform_frequency",
        }
        if not self._report_channel_statistics:
            return values

        for index, entry in enumerate(self._lockin_entries):
            label = entry.label.strip() or f"LIA {index + 1}"
            multiple_outputs = len(entry.outputs) > 1
            for output in entry.outputs:
                column = f"{label} {output.value}" if multiple_outputs else label
                statistic_key = f"{_TRACE_NAME} {column}"
                values[f"{var}.{label}.{output.value}"] = (
                    f"{var}.get_channel_statistic({statistic_key!r}, 'mean')"
                )
        return values

    def reported_value_units(self) -> dict[str, str]:
        """Return units for source settings and averaged lock-in outputs."""
        var = self.instance_name
        units = {
            f"{var}.K6221.offset": "A",
            f"{var}.K6221.amplitude": "A",
            f"{var}.K6221.frequency": "Hz",
        }
        if not self._report_channel_statistics:
            return units

        for index, entry in enumerate(self._lockin_entries):
            label = entry.label.strip() or f"LIA {index + 1}"
            for output in entry.outputs:
                units[f"{var}.{label}.{output.value}"] = _output_unit(entry, output)
        return units

    def set_scan_generator_class(self, cls) -> None:
        """Replace the scan generator class and update the displayed units."""
        super().set_scan_generator_class(cls)
        self._apply_scan_units()

    def _measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Acquire all lock-in outputs once as one shared-x multicolumn trace."""
        x_values, channel_values, specs = self._acquire_trace(parameters)
        frame = pd.DataFrame({"x": np.asarray(x_values, dtype=float)})
        roles: dict[str, str] = {}
        names = {"x": self.x_label}
        units = {"x": self.x_units}
        for spec in specs:
            frame[spec.name] = np.asarray(channel_values[spec.name], dtype=float)
            roles[spec.name] = COLUMN_ROLE_Y
            names[spec.name] = spec.name
            units[spec.name] = spec.unit
        return {
            _TRACE_NAME: TraceData(
                df=frame,
                column_roles=roles,
                names=names,
                units=units,
            )
        }

    def connect(self) -> None:
        """Open the 6221 and all configured lock-in connections."""
        self._validate_configuration()
        self._set_status(TraceStatus.CONNECTING)
        transports: list[GpibTransport] = []
        self._lockins = []
        try:
            transport_6221 = GpibTransport.from_resource_string(
                self._6221_resource, timeout=10.0, poll_time=0.05
            )
            transports.append(transport_6221)
            self._k6221 = Keithley6221(transport_6221)
            self._k6221.connect()
            self._k6221.confirm_identity()

            with ThreadPoolExecutor(max_workers=max(1, len(self._lockin_entries))) as executor:
                futures = [
                    executor.submit(self._connect_one_lockin, entry)
                    for entry in self._lockin_entries
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

    def _connect_one_lockin(self, entry: LockInEntry) -> tuple[GpibTransport, SupportedLockIn]:
        """Create, connect, and identity-verify one configured lock-in.

        If any step fails the transport is closed before propagating the
        exception, preventing transport resource leaks in the calling
        parallel connection loop.

        Args:
            entry (LockInEntry):
                Lock-in configuration entry providing the VISA resource string.

        Returns:
            (GpibTransport):
                Opened transport bound to the lock-in.
            (LockInAmplifier):
                Connected and verified concrete lock-in driver.

        Raises:
            RuntimeError:
                If the instrument identity does not match the selected model.
        """
        transport = GpibTransport.from_resource_string(
            entry.resource,
            timeout=10.0,
            command_complete_mask=(
                _SR7265_STATUS_COMMAND_COMPLETE
                if entry.model is LockInModel.SR7265
                else _SR830_STATUS_IFC
            ),
        )
        try:
            lockin = _lockin_driver_class(entry.model)(transport)
            lockin.connect()
            identity = lockin.identify()
            identity_token = "7265" if entry.model is LockInModel.SR7265 else "SR830"
            if identity_token not in identity.upper():
                raise RuntimeError(
                    f"Unexpected {entry.model.value} identity {identity!r} "
                    f"for resource {entry.resource!r}."
                )
        except Exception:
            try:
                transport.close()
            except _CLEANUP_EXCEPTIONS:
                pass
            raise
        return transport, lockin

    def _connect_temporary_6221(self) -> tuple[GpibTransport, Keithley6221]:
        """Open and identity-check the configured 6221 for a temporary UI action."""
        transport = GpibTransport.from_resource_string(
            self._6221_resource, timeout=10.0, poll_time=0.05
        )
        try:
            source = Keithley6221(transport)
            source.connect()
            source.confirm_identity()
        except Exception:
            transport.close()
            raise
        return transport, source

    def _read_one_temporary_lockin(self, index: int) -> tuple[int, dict[str, Any]]:
        """Read common and per-lock-in settings using a temporary connection."""
        entry = self._lockin_entries[index]
        transport, lockin = self._connect_one_lockin(entry)
        try:
            settings: dict[str, Any] = {
                "time_constant": lockin.get_time_constant(),
                "filter_slope": lockin.get_filter_slope(),
                "input_coupling": lockin.get_input_coupling(),
                "line_filter": lockin.get_line_filter(),
                "input_source": lockin.get_input_source(),
                "sensitivity": lockin.get_sensitivity(),
                "harmonic": lockin.get_harmonic(),
                "phase": lockin.get_reference_phase(),
                "offsets": {},
            }
            settings["sensitivity"] *= _sensitivity_driver_scale(
                entry.model, settings["input_source"]
            )
            if entry.model is LockInModel.SR830:
                sr830 = cast(SRS830, lockin)
                settings["reserve_mode"] = sr830.get_reserve_mode()
                for output in entry.outputs:
                    channel = output.offset_channel()
                    if channel is not None:
                        settings["offsets"][channel.value] = sr830.get_output_offset(channel)
            return index, settings
        finally:
            try:
                lockin.disconnect()
            finally:
                transport.close()

    def read_temporary_instrument_settings(
        self, indices: list[int]
    ) -> tuple[dict[str, float], list[tuple[int, dict[str, Any]]]]:
        """Read the 6221 and selected lock-ins without retaining their connections."""
        if not indices:
            raise ValueError("At least one lock-in must be selected.")
        transport, source = self._connect_temporary_6221()
        try:
            source_settings = {
                "amplitude": source.get_waveform_amplitude(),
                "offset": source.get_offset_current(),
                "frequency": source.get_frequency(),
            }
        finally:
            try:
                source.disconnect()
            finally:
                transport.close()

        with ThreadPoolExecutor(max_workers=len(indices)) as executor:
            results = list(executor.map(self._read_one_temporary_lockin, indices))
        return source_settings, results

    def auto_offset_temporary_lockins(self, indices: list[int]) -> None:
        """Auto-offset selected supported lock-ins using temporary connections."""
        if not indices:
            raise ValueError("At least one lock-in must be selected.")
        source_transport, source = self._connect_temporary_6221()

        def _offset_one(index: int) -> None:
            entry = self._lockin_entries[index]
            transport, lockin = self._connect_one_lockin(entry)
            try:
                self._wait_for_offset_stability()
                self._auto_offset_one_lockin(entry, lockin)
            finally:
                try:
                    lockin.disconnect()
                finally:
                    transport.close()

        try:
            source.enable_output(True)
            with ThreadPoolExecutor(max_workers=len(indices)) as executor:
                for future in [executor.submit(_offset_one, index) for index in indices]:
                    future.result()
        finally:
            try:
                source.enable_output(False)
                source.disconnect()
            finally:
                source_transport.close()
        self._enable_offset_addition_for_nonzero_offsets()

    def configure(self) -> None:
        """Apply the stored 6221 and lock-in settings to connected hardware.

        On successful completion the 6221 output is left enabled so subsequent
        measurements can reuse the configured waveform without reconfiguration.
        The output is disabled in :meth:`disconnect`.
        """
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
            self._k6221.set_waveform_amplitude(self.eval_float(self._waveform_amplitude))
            self._k6221.set_offset_current(self.eval_float(self._waveform_offset))
            self._k6221.set_frequency(self.eval_float(self._waveform_frequency))
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
            self._k6221.enable_output(True)
            self._configure_output_offsets()
            self._clear_configuration_lia_status()
        except Exception:
            self._set_status(TraceStatus.ERROR)
            raise

        timestamp = time.monotonic()
        self._record_read_timestamp(timestamp)
        self._set_status(TraceStatus.IDLE)

    def _configure_one_lockin(self, entry: LockInEntry, lockin: SupportedLockIn) -> None:
        """Apply common and per-entry settings to one lock-in.

        Args:
            entry (LockInEntry):
                Per-lockin configuration (harmonic, phase, sensitivity, etc.).
            lockin (SRS830):
                SR830 instrument driver to configure.
        """
        lockin.reset()
        lockin.set_reference_source(LockInReferenceSource.EXTERNAL)
        lockin.set_reference_source(LockInReferenceSource.EXTERNAL, LockinRefenceEdge.FALLING)
        lockin.set_time_constant(self._time_constant)
        lockin.set_filter_slope(entry.filter_slope)
        lockin.set_input_source(entry.input_source)
        lockin.set_input_coupling(entry.input_coupling)
        lockin.set_line_filter(entry.line_filter)
        lockin.set_harmonic(entry.harmonic)
        if entry.phase is not None:
            lockin.set_reference_phase(entry.phase)
        if entry.auto_sensitivity:
            lockin.auto_gain()
            selected_sensitivity = lockin.get_sensitivity()
            if isinstance(selected_sensitivity, (int, float)):
                entry.sensitivity = float(selected_sensitivity) * _sensitivity_driver_scale(
                    entry.model, entry.input_source
                )
        else:
            lockin.set_sensitivity(
                entry.sensitivity / _sensitivity_driver_scale(entry.model, entry.input_source)
            )
        if entry.model is LockInModel.SR830:
            cast(SRS830, lockin).set_reserve_mode(entry.reserve_mode)

    def _configure_output_offsets(self) -> None:
        """Apply manual offsets or calculate automatic offsets after settling."""
        has_auto_offset = any(
            entry.offset_auto and _lockin_has_output_offsets(entry.model)
            for entry in self._lockin_entries
        )
        if has_auto_offset:
            self._wait_for_offset_stability()

        with ThreadPoolExecutor(max_workers=max(1, len(self._lockins))) as executor:
            futures = [
                executor.submit(self._configure_one_lockin_offsets, entry, lockin)
                for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True)
            ]
            for future in futures:
                future.result()
        self._enable_offset_addition_for_nonzero_offsets()

    def _wait_for_offset_stability(self) -> None:
        """Wait at least three filter time constants before deriving an offset."""
        wait_time = max(self.eval_float(self._read_rate_multiple), 3.0) * self._time_constant
        if wait_time > 0.0:
            time.sleep(wait_time)

    def _clear_configuration_lia_status(self) -> None:
        """Clear configuration status and reject overload or reference errors."""
        sr830s = [
            lockin
            for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True)
            if entry.model is LockInModel.SR830
        ]
        for lockin in sr830s:
            lockin.write("*CLS")
        if sr830s:
            # Allow a fresh status observation after clearing latched setup events.
            time.sleep(0.1)
        for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True):
            if entry.model is LockInModel.SR7265:
                sr7265 = cast(SR7265, lockin)
                status_7265 = sr7265.read_status()
                sr7265.check_measurement_status(status_7265)
                if isinstance(status_7265, SR7265Status) and status_7265:
                    self._log.debug(
                        "Cleared 7265 %s configuration status: %s",
                        entry.resource,
                        status_7265.name or int(status_7265),
                    )
                continue
            status = cast(SRS830, lockin).read_lia_status()
            if isinstance(status, SRS830LIAStatus) and status.has_overload:
                message = f"SR830 {entry.resource} is overloaded after configuration: {status.name or int(status)}"
                self._log.error(message)
                raise RuntimeError(message)
            if status:
                self._log.debug(
                    "Cleared SR830 %s configuration LIA status: %s",
                    entry.resource,
                    status.name or int(status),
                )

    @staticmethod
    def _configure_one_lockin_offsets(entry: LockInEntry, lockin: SupportedLockIn) -> None:
        """Apply configured offset and expand values to one SR830."""
        if not _lockin_has_output_offsets(entry.model):
            entry.auto_offsets.clear()
            return
        sr830 = cast(SRS830, lockin)
        selected_offset_outputs: tuple[LockInOutput, ...] = tuple(
            output for output in entry.outputs if output.offset_channel() is not None
        )
        offset_outputs: tuple[LockInOutput, ...]
        if entry.offset_auto and entry.outputs != (LockInOutput.X,):
            offset_outputs = (LockInOutput.X, LockInOutput.Y)
        else:
            offset_outputs = selected_offset_outputs
        entry.auto_offsets.clear()
        measured_values = (
            sr830.measure_outputs(offset_outputs) if entry.offset_auto and offset_outputs else {}
        )
        for output in offset_outputs:
            channel = output.offset_channel()
            if channel is None:
                continue
            offset_pct = entry.offset_pct
            if entry.offset_auto:
                offset_pct = float(measured_values[output]) / entry.sensitivity * 100.0
                offset_pct = max(-105.0, min(105.0, offset_pct))
                entry.auto_offsets[channel.value] = offset_pct
            sr830.set_output_offset(channel, offset_pct, entry.expand)
            sr830.wait_for_ifc()

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
            raise RuntimeError(
                "Not connected — call connect() and configure() before auto_offset()."
            )
        self._k6221.enable_output(True)
        try:
            self._wait_for_offset_stability()
            with ThreadPoolExecutor(max_workers=max(1, len(self._lockins))) as executor:
                futures = [
                    executor.submit(self._auto_offset_one_lockin, entry, lockin)
                    for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True)
                ]
                for future in futures:
                    future.result()
            self._enable_offset_addition_for_nonzero_offsets()
        finally:
            self._k6221.enable_output(False)

    def _auto_offset_one_lockin(self, entry: LockInEntry, lockin: SupportedLockIn) -> None:
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
        if not _lockin_has_output_offsets(entry.model):
            raise ValueError(f"{entry.model.display_name} does not support output auto-offset.")
        sr830 = cast(SRS830, lockin)
        entry.auto_offsets.clear()
        for output in entry.outputs:
            channel = output.offset_channel()
            if channel is not None:
                sr830.auto_offset_channel(channel)
                offset_pct, _expand = sr830.get_output_offset(channel)
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
        self._waveform_amplitude = data.get("waveform_amplitude", self._waveform_amplitude)
        self._waveform_offset = data.get("waveform_offset", self._waveform_offset)
        self._waveform_frequency = data.get("waveform_frequency", self._waveform_frequency)
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
        self._read_rate_multiple = data.get("read_rate_multiple", self._read_rate_multiple)
        self._auto_sensitivity_enabled = bool(
            data.get("auto_sensitivity_enabled", self._auto_sensitivity_enabled)
        )
        self._auto_sensitivity_low = data.get("auto_sensitivity_low", self._auto_sensitivity_low)
        self._auto_sensitivity_high = data.get("auto_sensitivity_high", self._auto_sensitivity_high)
        saved_offset_preference = data.get("offset_enabled")
        self._source_range_mode = str(data.get("source_range_mode", self._source_range_mode))
        self._resistance_enabled = bool(data.get("resistance_enabled", self._resistance_enabled))

        restored_entries = data.get("lockins", [])
        if isinstance(restored_entries, list) and restored_entries:
            self._lockin_entries = [
                self._restore_lockin_entry(entry, index)
                for index, entry in enumerate(restored_entries)
            ]
        if saved_offset_preference is None:
            self._enable_offset_addition_for_nonzero_offsets()
        else:
            self._offset_enabled = bool(saved_offset_preference)
        self._apply_scan_units()

    def _plugin_config_tabs(self) -> QWidget:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        tab_widget = FontAwareTabWidget()

        # ---- Tab 1: Source & Common ----
        source_common_page = QWidget()
        sc_layout = QVBoxLayout(source_common_page)
        sc_layout.setContentsMargins(4, 4, 4, 4)

        source_group = QGroupBox("Connection + source")
        source_form = QFormLayout(source_group)

        resource_6221 = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        resource_6221.setCurrentText(self._6221_resource)
        resource_6221.currentTextChanged.connect(
            lambda text: setattr(self, "_6221_resource", text.strip())
        )

        scan_mode_combo = QComboBox()
        scan_mode_combo.addItem("Scan amplitude", WaveformScanMode.AMPLITUDE)
        scan_mode_combo.addItem("Scan offset", WaveformScanMode.OFFSET)
        scan_mode_combo.addItem("Scan frequency", WaveformScanMode.FREQUENCY)
        scan_mode_combo.setCurrentIndex(scan_mode_combo.findData(self._scan_mode))

        amplitude_sb = SISpinBox(
            suffix="A",
            siPrefix=True,
            value=self._waveform_amplitude,
            allow_expressions=True,
        )
        amplitude_sb.setMinimum(0.0)
        amplitude_sb.setMaximum(1.0)
        amplitude_sb.valueChanged.connect(lambda value: setattr(self, "_waveform_amplitude", value))

        offset_sb = SISpinBox(
            suffix="A", siPrefix=True, value=self._waveform_offset, allow_expressions=True
        )
        offset_sb.setMinimum(-1.0)
        offset_sb.setMaximum(1.0)
        offset_sb.valueChanged.connect(lambda value: setattr(self, "_waveform_offset", value))

        frequency_sb = SISpinBox(
            suffix="Hz",
            siPrefix=True,
            value=self._waveform_frequency,
            allow_expressions=True,
        )
        frequency_sb.setMinimum(1e-3)
        frequency_sb.setMaximum(1e6)
        frequency_sb.valueChanged.connect(lambda value: setattr(self, "_waveform_frequency", value))

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

        scan_mode_combo.currentIndexChanged.connect(
            lambda index: self._set_scan_mode(scan_mode_combo.itemData(index))
        )

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
        self._populate_time_constant_combo(time_constant_combo)
        time_constant_combo.valueChanged.connect(
            lambda value: setattr(self, "_time_constant", float(value))
        )

        read_multiple_sb = SISpinBox(value=self._read_rate_multiple, allow_expressions=True)
        read_multiple_sb.setMinimum(0.0)
        read_multiple_sb.setMaximum(1000.0)
        read_multiple_sb.valueChanged.connect(
            lambda value: setattr(self, "_read_rate_multiple", value)
        )

        auto_enabled = QCheckBox("Enable auto-ranging")
        auto_enabled.setChecked(self._auto_sensitivity_enabled)
        auto_enabled.toggled.connect(
            lambda checked: setattr(self, "_auto_sensitivity_enabled", bool(checked))
        )

        auto_low_sb = SISpinBox(value=self._auto_sensitivity_low, allow_expressions=True)
        auto_low_sb.setMinimum(0.0)
        auto_low_sb.setMaximum(1.0)
        auto_low_sb.setSingleStep(0.05)
        auto_low_sb.valueChanged.connect(
            lambda value: setattr(self, "_auto_sensitivity_low", value)
        )

        auto_high_sb = SISpinBox(value=self._auto_sensitivity_high, allow_expressions=True)
        auto_high_sb.setMinimum(0.0)
        auto_high_sb.setMaximum(1.0)
        auto_high_sb.setSingleStep(0.05)
        auto_high_sb.valueChanged.connect(
            lambda value: setattr(self, "_auto_sensitivity_high", value)
        )

        common_form.addRow("Time constant:", time_constant_combo)
        common_form.addRow("Read cooldown multiple:", read_multiple_sb)
        common_form.addRow(auto_enabled)
        common_form.addRow("Auto-ranging low ratio:", auto_low_sb)
        common_form.addRow("Auto-ranging high ratio:", auto_high_sb)
        sc_layout.addWidget(common_group)

        derived_group = QGroupBox("Resistance conversion")
        derived_form = QFormLayout(derived_group)

        resistance_enabled = QCheckBox("Create resistance-derived channels")
        resistance_enabled.setChecked(self._resistance_enabled)
        resistance_enabled.toggled.connect(
            lambda checked: setattr(self, "_resistance_enabled", bool(checked))
        )

        derived_form.addRow(resistance_enabled)
        sc_layout.addWidget(derived_group)
        sc_layout.addStretch()

        # ---- Tab 2: Lock-ins ----
        lockins_page = QWidget()
        lockins_layout = QVBoxLayout(lockins_page)
        lockins_layout.setContentsMargins(4, 4, 4, 4)

        lockins_table = QTableWidget()
        lockins_table.setRowCount(_LOCKIN_TABLE_ROWS)
        lockins_table.setVerticalHeaderLabels(_LOCKIN_ROW_LABELS)
        lockins_table.horizontalHeader().setVisible(False)
        lockins_table.verticalHeader().setDefaultSectionSize(28)
        lockins_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectColumns)
        lockins_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        set_table_visible_row_count(lockins_table, _LOCKIN_TABLE_ROWS)
        lockins_table.setStyleSheet(
            "QTableWidget::item:selected {"
            f"background-color: {colour('base')}; color: {colour('text')};"
            "}"
        )
        label_edits: dict[int, QLineEdit] = {}

        add_button = QPushButton("Add lock-in")
        remove_button = QPushButton("Remove selected")
        auto_offset_button = QPushButton("Run auto-offset")
        read_lockin_button = QPushButton("Read Lockin")
        update_selected_label_styles = partial(
            self._update_selected_label_styles,
            lockins_table,
            label_edits,
            auto_offset_button,
            read_lockin_button,
        )
        lockins_table.itemSelectionChanged.connect(update_selected_label_styles)
        self._enable_offset_addition_for_nonzero_offsets()
        offset_enabled_check = QCheckBox("Add offset to readings")
        offset_enabled_check.setToolTip(
            "Add the configured SR830 offset percentage back to each exported reading to estimate "
            "the signal before the lock-in output was zeroed. This does not change the lock-in settings."
        )
        offset_enabled_check.setChecked(self._offset_enabled)
        offset_enabled_check.toggled.connect(
            lambda checked: setattr(self, "_offset_enabled", bool(checked))
        )
        self.offset_addition_changed.connect(offset_enabled_check.setChecked)

        def _refresh_lockin_table() -> None:
            lockins_table.blockSignals(True)
            label_edits.clear()
            n_cols = len(self._lockin_entries)
            lockins_table.setColumnCount(n_cols)
            for col in range(n_cols):
                lockins_table.horizontalHeader().setSectionResizeMode(
                    col, QHeaderView.ResizeMode.Stretch
                )
                lockins_table.setColumnWidth(col, 180)

            for col, entry in enumerate(self._lockin_entries):
                label_edit = QLineEdit(entry.label)
                label_edit.textChanged.connect(
                    lambda text, *, idx=col: setattr(self._lockin_entries[idx], "label", text)
                )
                label_edits[col] = label_edit
                lockins_table.setCellWidget(_ROW_LABEL, col, label_edit)

                model_combo = QComboBox()
                for model in LockInModel:
                    model_combo.addItem(model.display_name, model)
                model_combo.setCurrentIndex(model_combo.findData(entry.model))
                model_combo.currentIndexChanged.connect(
                    lambda index, *, idx=col, combo=model_combo: self._set_lockin_model(
                        idx,
                        combo.itemData(index),
                        time_constant_combo,
                        _refresh_lockin_table,
                    )
                )
                lockins_table.setCellWidget(_ROW_MODEL, col, model_combo)

                resource_widget = VisaResourceComboBox(resource_filter=FILTER_GPIB)
                resource_widget.setCurrentText(entry.resource)
                resource_widget.currentTextChanged.connect(
                    lambda text, *, idx=col: setattr(
                        self._lockin_entries[idx], "resource", text.strip()
                    )
                )
                lockins_table.setCellWidget(_ROW_RESOURCE, col, resource_widget)

                self._populate_lockin_input_controls(
                    lockins_table, col, entry, _refresh_lockin_table
                )

                sensitivity_combo = SIComboBox(
                    unit="A" if _is_current_input(entry.input_source) else "V"
                )
                sensitivity_combo.addItem("Auto", None)
                for value in _lockin_sensitivities(entry.model, entry.input_source):
                    sensitivity_combo.addValueItem(value)
                if entry.auto_sensitivity:
                    sensitivity_combo.setCurrentIndex(0)
                else:
                    sensitivity_combo.setFloatValue(entry.sensitivity)

                sensitivity_combo.currentIndexChanged.connect(
                    lambda index, *, idx=col, combo=sensitivity_combo: self._set_lockin_sensitivity(
                        idx, combo.itemData(index)
                    )
                )
                lockins_table.setCellWidget(_ROW_SENSITIVITY, col, sensitivity_combo)

                harmonic_spin = QSpinBox()
                harmonic_spin.setMinimum(1)
                harmonic_spin.setMaximum(_lockin_max_harmonic(entry.model))
                harmonic_spin.setValue(entry.harmonic)
                harmonic_spin.valueChanged.connect(
                    lambda value, *, idx=col: setattr(
                        self._lockin_entries[idx], "harmonic", int(value)
                    )
                )
                lockins_table.setCellWidget(_ROW_HARMONIC, col, harmonic_spin)

                phase_spin = AutoSISpinBox(
                    suffix="\u00b0",
                    value=0.0 if entry.phase is None else entry.phase,
                    auto=entry.phase is None,
                )
                phase_spin.setMinimum(-360.0)
                phase_spin.setMaximum(360.0)
                phase_spin.valueChanged.connect(
                    lambda value, *, idx=col: setattr(
                        self._lockin_entries[idx], "phase", float(value)
                    )
                )
                phase_spin.autoChanged.connect(
                    lambda automatic, *, idx=col, spin=phase_spin: setattr(
                        self._lockin_entries[idx],
                        "phase",
                        None if automatic else float(spin.value()),
                    )
                )
                lockins_table.setCellWidget(_ROW_PHASE, col, phase_spin)

                offset_local = AutoSISpinBox(
                    suffix="%", value=entry.offset_pct, auto=entry.offset_auto
                )
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
                reserve_combo.setEnabled(entry.model is LockInModel.SR830)

                output_checks: list[tuple[LockInOutput, QCheckBox]] = []

                sync_outputs = partial(
                    self._sync_lockin_outputs,
                    output_checks,
                    offset_local,
                    expand_combo,
                    col,
                )

                for output in LockInOutput:
                    checkbox = QCheckBox(output.value)
                    checkbox.setStyleSheet("background: transparent;")
                    checkbox.setChecked(output in entry.outputs)
                    checkbox.toggled.connect(lambda _checked, sync=sync_outputs: sync())
                    output_checks.append((output, checkbox))
                    lockins_table.setCellWidget(_LOCKIN_OUTPUT_ROWS[output], col, checkbox)

                offset_local.valueChanged.connect(
                    lambda value, *, idx=col: self._set_lockin_offset(idx, value)
                )
                offset_local.autoChanged.connect(
                    lambda automatic, *, idx=col: setattr(
                        self._lockin_entries[idx], "offset_auto", bool(automatic)
                    )
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
                sync_outputs()

            remove_button.setEnabled(len(self._lockin_entries) > 1)
            lockins_table.blockSignals(False)
            update_selected_label_styles()

        add_button.clicked.connect(lambda: self._add_lockin_entry(_refresh_lockin_table))
        remove_button.clicked.connect(
            lambda: self._remove_selected_lockins(lockins_table, _refresh_lockin_table)
        )
        auto_offset_button.clicked.connect(
            lambda: self._auto_offset_selected_lockins(lockins_table, _refresh_lockin_table)
        )
        read_lockin_button.clicked.connect(
            lambda: self._read_selected_lockins(
                lockins_table,
                _refresh_lockin_table,
                amplitude_sb,
                offset_sb,
                frequency_sb,
                time_constant_combo,
            )
        )
        _refresh_lockin_table()

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(add_button)
        buttons_layout.addWidget(remove_button)
        buttons_layout.addWidget(auto_offset_button)
        buttons_layout.addWidget(read_lockin_button)
        buttons_layout.addStretch(1)

        lockins_layout.addWidget(lockins_table)
        lockins_layout.addLayout(buttons_layout)
        lockins_layout.addWidget(offset_enabled_check)
        lockins_layout.addStretch(1)

        tab_widget.addTab(source_common_page, "Source && Common")
        tab_widget.addTab(lockins_page, "Lock-ins")

        root_layout.addWidget(tab_widget)
        return root

    def _set_scan_mode(self, mode: Any) -> None:
        """Store a valid scan mode and update the scan generator units."""
        if isinstance(mode, WaveformScanMode):
            self._scan_mode = mode
        self._apply_scan_units()

    def _populate_lockin_input_controls(
        self, table: QTableWidget, column: int, entry: LockInEntry, refresh: Callable[[], None]
    ) -> None:
        """Create the per-instrument input and filter editors."""
        choices = (
            (_ROW_INPUT, "input_source", _lockin_input_options(entry.model)),
            (
                _ROW_SLOPE,
                "filter_slope",
                [(f"{slope} dB/oct", slope) for slope in _lockin_filter_slopes(entry.model)],
            ),
            (_ROW_COUPLING, "input_coupling", [(mode.value, mode) for mode in LockInInputCoupling]),
            (
                _ROW_LINE_FILTER,
                "line_filter",
                [
                    ("None", LockInLineFilter.NONE),
                    ("Line", LockInLineFilter.LINE),
                    ("2× line", LockInLineFilter.LINE_2X),
                    ("Line + 2× line", LockInLineFilter.BOTH),
                ],
            ),
        )
        for row, attribute, options in choices:
            combo = QComboBox()
            for label, value in options:
                combo.addItem(label, value)
            combo.setCurrentIndex(combo.findData(getattr(entry, attribute)))
            if attribute == "input_source":
                combo.currentIndexChanged.connect(
                    lambda index, *, editor=combo: self._set_lockin_input(
                        column, editor.itemData(index), refresh
                    )
                )
            else:
                combo.currentIndexChanged.connect(
                    lambda index, *, editor=combo, field_name=attribute: setattr(
                        entry, field_name, editor.itemData(index)
                    )
                )
            table.setCellWidget(row, column, combo)

    def _set_lockin_input(
        self, index: int, source: LockInInputSource, refresh: Callable[[], None]
    ) -> None:
        """Switch input mode and keep the displayed sensitivity within its ranges."""
        entry = self._lockin_entries[index]
        entry.input_source = source
        sensitivities = _lockin_sensitivities(entry.model, source)
        if _sensitivity_index(entry.sensitivity, sensitivities) is None:
            entry.sensitivity = sensitivities[-1]
        refresh()

    @staticmethod
    def _selected_lockin_indices(table: QTableWidget) -> list[int]:
        """Return selected lock-in columns in stable order."""
        return sorted({index.column() for index in table.selectedIndexes()})

    @staticmethod
    def _update_selected_label_styles(
        table: QTableWidget,
        label_edits: dict[int, QLineEdit],
        auto_offset_button: QPushButton,
        read_button: QPushButton,
    ) -> None:
        """Highlight selected label editors and enable selection actions."""
        selected = {index.column() for index in table.selectedIndexes()}
        auto_offset_button.setEnabled(bool(selected))
        read_button.setEnabled(bool(selected))
        selected_style = (
            "QLineEdit {"
            f"background-color: {colour('alternate_base')};"
            f"border: 1px solid {colour('tab_selected_border')};"
            "}"
        )
        for column, editor in label_edits.items():
            editor.setStyleSheet(selected_style if column in selected else "")

    def _set_lockin_sensitivity(self, index: int, selected: float | None) -> None:
        """Store an automatic or explicit sensitivity selection."""
        entry = self._lockin_entries[index]
        entry.auto_sensitivity = selected is None
        if selected is None:
            self._auto_sensitivity_enabled = True
        else:
            entry.sensitivity = float(selected)

    def _common_time_constants(self) -> tuple[float, ...]:
        """Return time constants supported by every configured lock-in model."""
        models = {entry.model for entry in self._lockin_entries} or {LockInModel.SR830}
        supported = set(_lockin_time_constants(models.pop()))
        for model in models:
            supported.intersection_update(_lockin_time_constants(model))
        return tuple(sorted(supported))

    def _populate_time_constant_combo(self, combo: SIComboBox) -> None:
        """Populate *combo* with values valid for the current model mixture."""
        values = self._common_time_constants()
        if not values:
            raise ValueError("The selected lock-in models have no common time constants.")
        selected = self._time_constant
        if selected not in values:
            selected = min(values, key=lambda value: abs(math.log(value / self._time_constant)))
            self._time_constant = selected
        combo.blockSignals(True)
        combo.clear()
        for value in values:
            combo.addValueItem(value)
        combo.setFloatValue(selected)
        combo.blockSignals(False)

    def _set_lockin_model(
        self,
        index: int,
        model: Any,
        time_constant_combo: SIComboBox,
        refresh: Callable[[], None],
    ) -> None:
        """Store a model choice and refresh model-dependent controls."""
        if not isinstance(model, LockInModel):
            return
        entry = self._lockin_entries[index]
        entry.model = model
        if entry.input_source not in dict(_lockin_input_options(model)).values():
            entry.input_source = LockInInputSource.A_MINUS_B
        sensitivities = _lockin_sensitivities(model, entry.input_source)
        if _sensitivity_index(entry.sensitivity, sensitivities) is None:
            entry.sensitivity = sensitivities[-1] if _is_current_input(entry.input_source) else 1e-3
        if entry.filter_slope not in _lockin_filter_slopes(model):
            entry.filter_slope = 12
        entry.harmonic = min(entry.harmonic, _lockin_max_harmonic(model))
        if not _lockin_has_output_offsets(model):
            entry.offset_auto = False
            entry.offset_pct = 0.0
            entry.expand = LockInExpandFactor.X1
            entry.auto_offsets.clear()
        self._populate_time_constant_combo(time_constant_combo)
        refresh()

    def _sync_lockin_outputs(
        self,
        checks: list[tuple[LockInOutput, QCheckBox]],
        offset_widget: QWidget,
        expand_widget: QWidget,
        index: int,
    ) -> None:
        """Store selected outputs, retaining one output and updating dependencies."""
        outputs = tuple(output for output, checkbox in checks if checkbox.isChecked())
        if not outputs:
            default_output, default_check = checks[0]
            default_check.blockSignals(True)
            default_check.setChecked(True)
            default_check.blockSignals(False)
            outputs = (default_output,)
        self._lockin_entries[index].outputs = outputs
        supports_offset = _lockin_has_output_offsets(self._lockin_entries[index].model) and any(
            output.offset_channel() is not None for output in outputs
        )
        offset_widget.setEnabled(supports_offset)
        expand_widget.setEnabled(supports_offset)

    def _set_lockin_offset(self, index: int, value: float) -> None:
        """Store a manual output offset and enable compensation when needed."""
        self._lockin_entries[index].offset_pct = float(value)
        self._enable_offset_addition_for_nonzero_offsets()

    def _add_lockin_entry(self, refresh: Callable[[], None]) -> None:
        """Append a conventionally named lock-in entry and refresh the editor."""
        label = f"LIA {len(self._lockin_entries) + 1}"
        self._lockin_entries.append(LockInEntry(label=label, resource="GPIB0::9::INSTR"))
        refresh()

    def _remove_selected_lockins(self, table: QTableWidget, refresh: Callable[[], None]) -> None:
        """Remove selected entries while retaining at least one lock-in."""
        selected = list(reversed(self._selected_lockin_indices(table)))
        if not selected or len(self._lockin_entries) == 1:
            return
        for column in selected:
            self._lockin_entries.pop(column)
        refresh()

    def _restore_lockin_selection(self, table: QTableWidget, columns: list[int]) -> None:
        """Restore selected columns after rebuilding the lock-in table."""
        for column in columns:
            table.selectColumn(column)

    def _auto_offset_selected_lockins(
        self, table: QTableWidget, refresh: Callable[[], None]
    ) -> None:
        """Auto-offset selected lock-ins through temporary connections."""
        selected = self._selected_lockin_indices(table)
        try:
            self.auto_offset_temporary_lockins(selected)
            refresh()
            self._restore_lockin_selection(table, selected)
        except (OSError, RuntimeError, ValueError, pyvisa.Error) as exc:
            self._log.warning("Auto-offset not available: %s", exc)

    def _read_selected_lockins(
        self,
        table: QTableWidget,
        refresh: Callable[[], None],
        amplitude: SISpinBox,
        offset: SISpinBox,
        frequency: SISpinBox,
        time_constant: SIComboBox,
    ) -> None:
        """Read source and selected lock-ins, then refresh their controls."""
        selected = self._selected_lockin_indices(table)
        try:
            source_settings, lockin_settings = self.read_temporary_instrument_settings(selected)
            self._apply_read_source_settings(source_settings, amplitude, offset, frequency)
            for index, settings in lockin_settings:
                self._apply_read_lockin_settings(index, settings)
            time_constant.setFloatValue(self._time_constant)
            self._enable_offset_addition_for_nonzero_offsets()
            refresh()
            self._restore_lockin_selection(table, selected)
        except (OSError, RuntimeError, ValueError, pyvisa.Error) as exc:
            self._log.warning("Instrument settings could not be read: %s", exc)

    def _apply_read_source_settings(
        self,
        settings: dict[str, Any],
        amplitude: SISpinBox,
        offset: SISpinBox,
        frequency: SISpinBox,
    ) -> None:
        """Store source settings read from the instrument and update editors."""
        self._waveform_amplitude = settings["amplitude"]
        self._waveform_offset = settings["offset"]
        self._waveform_frequency = settings["frequency"]
        amplitude.setValue(self._waveform_amplitude)
        offset.setValue(self._waveform_offset)
        frequency.setValue(self._waveform_frequency)

    def _apply_read_lockin_settings(self, index: int, settings: dict[str, Any]) -> None:
        """Store common and per-lock-in settings read from one instrument."""
        self._time_constant = settings["time_constant"]
        entry = self._lockin_entries[index]
        entry.filter_slope = settings["filter_slope"]
        entry.input_coupling = settings["input_coupling"]
        entry.line_filter = settings["line_filter"]
        entry.input_source = settings.get("input_source", entry.input_source)
        entry.sensitivity = settings["sensitivity"]
        entry.auto_sensitivity = False
        entry.harmonic = settings["harmonic"]
        entry.phase = settings["phase"]
        if "reserve_mode" in settings:
            entry.reserve_mode = settings["reserve_mode"]
        offsets = settings["offsets"]
        if not _lockin_has_output_offsets(entry.model):
            entry.offset_auto = False
            entry.offset_pct = 0.0
            entry.expand = LockInExpandFactor.X1
        entry.auto_offsets = {channel: value[0] for channel, value in offsets.items()}
        if offsets:
            entry.offset_pct, entry.expand = next(iter(offsets.values()))
            entry.offset_auto = False

    def _channel_specs(self) -> list[ChannelSpec]:
        specs: list[ChannelSpec] = []
        for index, entry in enumerate(self._lockin_entries):
            base_name = entry.label.strip() or f"LIA {index + 1}"
            append_suffix = len(entry.outputs) > 1
            for output in entry.outputs:
                output_name = f"{base_name} {output.value}" if append_suffix else base_name
                specs.append(
                    ChannelSpec(
                        lockin_index=index,
                        output=output,
                        name=output_name,
                        unit=_output_unit(entry, output),
                    )
                )
                if (
                    self._resistance_enabled
                    and output is not LockInOutput.THETA
                    and not _is_current_input(entry.input_source)
                ):
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
        """Validate source, automatic-ranging, and lock-in configuration."""
        waveform_amplitude = self.eval_float(self._waveform_amplitude)
        waveform_frequency = self.eval_float(self._waveform_frequency)
        read_rate_multiple = self.eval_float(self._read_rate_multiple)
        auto_sensitivity_low = self.eval_float(self._auto_sensitivity_low)
        auto_sensitivity_high = self.eval_float(self._auto_sensitivity_high)
        self._validate_source_settings(
            waveform_amplitude,
            waveform_frequency,
            read_rate_multiple,
        )
        self._validate_auto_sensitivity_thresholds(
            auto_sensitivity_low,
            auto_sensitivity_high,
        )
        self._validate_lockin_entries()

    def _validate_source_settings(
        self,
        waveform_amplitude: float,
        waveform_frequency: float,
        read_rate_multiple: float,
    ) -> None:
        """Validate settings shared by the 6221 source and acquisition loop."""
        if not self._6221_resource.strip():
            raise ValueError("A 6221 resource must be configured.")
        if not self._lockin_entries:
            raise ValueError("At least one lock-in entry must be configured.")
        if waveform_amplitude < 0.0:
            raise ValueError("Waveform amplitude must be non-negative.")
        if waveform_frequency <= 0.0:
            raise ValueError("Waveform frequency must be positive.")
        if not 1 <= self._phase_marker_tlink <= 6:
            raise ValueError("Phase-marker trigger-link line must be in the range 1..6.")
        if read_rate_multiple < 0.0:
            raise ValueError("Read cooldown multiple must be non-negative.")
        for model in {entry.model for entry in self._lockin_entries}:
            time_constants = _lockin_time_constants(model)
            if self._time_constant not in time_constants:
                raise ValueError(
                    f"Time constant for {model.display_name} must be one of {time_constants!r}."
                )
        if self._source_range_mode not in {"AUTO", "BEST", "FIXED"}:
            raise ValueError("Source range mode must be one of 'AUTO', 'BEST', or 'FIXED'.")

    @staticmethod
    def _validate_auto_sensitivity_thresholds(low: float, high: float) -> None:
        """Validate the lower and upper automatic-sensitivity thresholds."""
        if not 0.0 <= low <= 1.0:
            raise ValueError("Auto-ranging low threshold must lie between 0 and 1.")
        if not 0.0 <= high <= 1.0:
            raise ValueError("Auto-ranging high threshold must lie between 0 and 1.")
        if low >= high:
            raise ValueError("Auto-ranging low threshold must be lower than the high threshold.")

    def _validate_lockin_entries(self) -> None:
        """Validate every lock-in entry and cross-entry uniqueness constraints."""
        labels: list[str] = []
        resources: list[str] = []
        for index, entry in enumerate(self._lockin_entries, start=1):
            label, resource = self._validate_lockin_entry(index, entry)
            labels.append(label)
            resources.append(resource)

        if len(set(labels)) != len(labels):
            raise ValueError("Each lock-in label must be unique.")
        if len(set(resources)) != len(resources):
            raise ValueError("Each lock-in resource must be unique.")
        if self._6221_resource.strip() in resources:
            raise ValueError("The 6221 resource conflicts with a lock-in resource.")
        channel_names = [spec.name for spec in self._channel_specs()]
        if len(set(channel_names)) != len(channel_names):
            raise ValueError("Derived channel names must be unique.")

    @staticmethod
    def _validate_lockin_entry(index: int, entry: LockInEntry) -> tuple[str, str]:
        """Validate one lock-in entry and return its normalised identity fields."""
        label = entry.label.strip()
        resource = entry.resource.strip()
        if not label:
            raise ValueError(f"Lock-in {index} must have a non-empty label.")
        if not resource:
            raise ValueError(f"Lock-in {label!r} must have a non-empty resource string.")
        filter_slopes = _lockin_filter_slopes(entry.model)
        if entry.filter_slope not in filter_slopes:
            raise ValueError(f"Filter slope for {label!r} must be one of {filter_slopes!r}.")
        if entry.input_source not in dict(_lockin_input_options(entry.model)).values():
            raise ValueError(f"Unsupported input source for {entry.model.display_name}.")
        sensitivities = _lockin_sensitivities(entry.model, entry.input_source)
        if _sensitivity_index(entry.sensitivity, sensitivities) is None:
            raise ValueError(f"Lock-in {label!r} sensitivity must be one of {sensitivities!r}.")
        if not 1 <= len(entry.outputs) <= 4:
            raise ValueError(f"Lock-in {label!r} must define between 1 and 4 outputs.")
        if len(set(entry.outputs)) != len(entry.outputs):
            raise ValueError(f"Lock-in {label!r} outputs must be unique.")
        max_harmonic = _lockin_max_harmonic(entry.model)
        if not 1 <= entry.harmonic <= max_harmonic:
            raise ValueError(f"Lock-in {label!r} harmonic must be between 1 and {max_harmonic}.")
        return label, resource

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
            max_amp = (
                float(np.max(np.abs(sweep)))
                if sweep is not None and sweep.size > 0
                else abs(self.eval_float(self._waveform_amplitude))
            )
            return max_amp + abs(self.eval_float(self._waveform_offset))
        if self._scan_mode is WaveformScanMode.OFFSET:
            max_off = (
                float(np.max(np.abs(sweep)))
                if sweep is not None and sweep.size > 0
                else abs(self.eval_float(self._waveform_offset))
            )
            return abs(self.eval_float(self._waveform_amplitude)) + max_off
        return abs(self.eval_float(self._waveform_amplitude)) + abs(
            self.eval_float(self._waveform_offset)
        )

    def _run_auto_phase(self, output_off: bool = False) -> None:
        """Enable the 6221 output, settle, and run auto-phase for entries that request it."""
        if not any(entry.phase is None for entry in self._lockin_entries):
            return
        if self._k6221 is None:
            raise RuntimeError("Not connected.")
        self._k6221.enable_output(True)
        try:
            wait_time = self._time_constant * self.eval_float(self._read_rate_multiple)
            if wait_time > 0.0:
                time.sleep(wait_time)
            phase_lockins = [
                lockin
                for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True)
                if entry.phase is None
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
        channel_values: dict[str, list[float]] = {spec.name: [] for spec in specs}

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
                    if self._offset_enabled and _lockin_has_output_offsets(entry.model):
                        output_value = self._apply_offset_correction(
                            entry, spec.output, output_value
                        )
                    if spec.derived_resistance:
                        value = self._convert_to_resistance(output_value, current_amplitude)
                    else:
                        value = output_value
                    channel_values[spec.name].append(float(value))
                self._apply_auto_sensitivity(readings)
        except Exception:
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
        cooldown = self._time_constant * self.eval_float(self._read_rate_multiple)
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

    def _read_one_lockin(
        self, entry: LockInEntry, lockin: SupportedLockIn
    ) -> tuple[str, LockInReading]:
        """Read outputs from one lock-in and return ``(resource, reading)``.

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
        try:
            measured_values = lockin.measure_outputs(requested_outputs)
        except TimeoutError:
            if entry.model is not LockInModel.SR830:
                raise
            sr830 = cast(SRS830, lockin)
            status_byte = sr830.read_status_byte() or 0
            if not self._recover_expanded_lockin_read(entry, sr830, status_byte):
                raise
            measured_values = sr830.measure_outputs(requested_outputs)
        output_values = {output: float(measured_values[output]) for output in entry.outputs}
        ratio_signal = abs(float(measured_values[LockInOutput.R]))
        return entry.resource, LockInReading(output_values, float(ratio_signal))

    def _recover_expanded_lockin_read(
        self,
        entry: LockInEntry,
        lockin: SRS830,
        status_byte: int,
    ) -> bool:
        """Drop expansion and clear status before retrying a timed-out SR830 read."""
        if not status_byte & _SR830_STATUS_LIA or entry.expand is LockInExpandFactor.X1:
            return False

        offset_channels = {
            LockInOutputChannel(channel_name)
            for channel_name in entry.auto_offsets
            if channel_name in LockInOutputChannel._value2member_map_
        }
        offset_channels.update(
            channel for output in entry.outputs if (channel := output.offset_channel()) is not None
        )
        if not offset_channels:
            return False

        self._log.warning(
            "SR830 %s read timed out with STB=%d while expanded; retrying at x1.",
            entry.resource,
            status_byte,
        )
        for channel in sorted(offset_channels, key=lambda item: item.value):
            offset_pct = entry.auto_offsets.get(channel.value, entry.offset_pct)
            lockin.set_output_offset(channel, offset_pct, LockInExpandFactor.X1)
            lockin.wait_for_ifc()
        entry.expand = LockInExpandFactor.X1
        lockin.write("*CLS")
        return True

    def _trigger_gpib_lockins(self) -> None:
        for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True):
            if entry.model is not LockInModel.SR830:
                continue
            transport = lockin.transport
            if isinstance(transport, GpibTransport):
                transport.send_group_execute_trigger()

    def _apply_auto_sensitivity(self, readings: dict[str, LockInReading]) -> None:
        if not self._auto_sensitivity_enabled:
            return
        with ThreadPoolExecutor(max_workers=max(1, len(self._lockins))) as executor:
            futures = [
                executor.submit(
                    self._apply_auto_sensitivity_one_lockin,
                    entry,
                    lockin,
                    readings[entry.resource],
                    _lockin_sensitivities(entry.model, entry.input_source),
                )
                for entry, lockin in zip(self._lockin_entries, self._lockins, strict=True)
            ]
            for future in futures:
                future.result()

    def _apply_auto_sensitivity_one_lockin(
        self,
        entry: LockInEntry,
        lockin: SupportedLockIn,
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
        index = _sensitivity_index(entry.sensitivity, sensitivities)
        if index is None:
            return
        new_index = index
        if ratio < self.eval_float(self._auto_sensitivity_low) and index > 0:
            new_index = index - 1
        elif (
            ratio > self.eval_float(self._auto_sensitivity_high) and index < len(sensitivities) - 1
        ):
            new_index = index + 1
        if new_index != index:
            new_sensitivity = sensitivities[new_index]
            lockin.set_sensitivity(
                new_sensitivity / _sensitivity_driver_scale(entry.model, entry.input_source)
            )
            entry.sensitivity = new_sensitivity

    def _apply_offset_correction(
        self, entry: LockInEntry, output: LockInOutput, value: float
    ) -> float:
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
        if not _lockin_has_output_offsets(entry.model):
            return value
        channel = output.offset_channel()
        if channel is None:
            return value
        if channel.value in entry.auto_offsets:
            offset_pct = entry.auto_offsets[channel.value]
        else:
            offset_pct = entry.offset_pct
        return value + (offset_pct / 100.0) * entry.sensitivity

    def _enable_offset_addition_for_nonzero_offsets(self) -> None:
        """Enable adding offsets to readings when any configured offset is nonzero."""
        has_offset = any(
            _lockin_has_output_offsets(entry.model)
            and (
                abs(entry.offset_pct) > 0.0
                or any(abs(value) > 0.0 for value in entry.auto_offsets.values())
            )
            for entry in self._lockin_entries
        )
        if not has_offset or self._offset_enabled:
            return
        self._offset_enabled = True
        self.offset_addition_changed.emit(True)

    def _current_amplitude_for_point(self, scan_value: float) -> float:
        if self._scan_mode is WaveformScanMode.AMPLITUDE:
            return abs(scan_value)
        return abs(self.eval_float(self._waveform_amplitude))

    def _convert_to_resistance(self, signal: float, amplitude: float) -> float:
        """Convert an RMS lock-in voltage reading into resistance using the 6221 peak current amplitude."""
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
            {str(k): float(v) for k, v in auto_offsets_raw.items()}
            if isinstance(auto_offsets_raw, dict)
            else {}
        )
        phase_raw = data.get("phase", 0.0)
        phase = (
            None
            if bool(data.get("auto_phase", False))
            or (isinstance(phase_raw, str) and phase_raw.strip().casefold() == "auto")
            else float(phase_raw)
        )
        return LockInEntry(
            label=str(data.get("label", default_label)),
            model=self._parse_enum(
                LockInModel,
                data.get("model", LockInModel.SR830.value),
                LockInModel.SR830,
                "model",
            ),
            resource=str(data.get("resource", "GPIB0::8::INSTR")),
            filter_slope=int(data.get("filter_slope", self._filter_slope)),
            input_coupling=self._parse_enum(
                LockInInputCoupling,
                data.get("input_coupling", self._input_coupling.value),
                self._input_coupling,
                "input_coupling",
            ),
            line_filter=self._parse_enum(
                LockInLineFilter,
                data.get("line_filter", self._line_filter.value),
                self._line_filter,
                "line_filter",
            ),
            input_source=self._parse_enum(
                LockInInputSource,
                data.get("input_source", LockInInputSource.A_MINUS_B.value),
                LockInInputSource.A_MINUS_B,
                "input_source",
            ),
            sensitivity=float(data.get("sensitivity", 1e-3)),
            offset_pct=float(data.get("offset_pct", 0.0)),
            offset_auto=bool(data.get("offset_auto", False)),
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
            phase=phase,
            auto_sensitivity=bool(data.get("auto_sensitivity", True)),
            auto_offsets=auto_offsets,
        )

    def _restore_lockin_outputs(self, data: dict[str, Any]) -> tuple[LockInOutput, ...]:
        values = data.get("outputs", data.get("output", [LockInOutput.X.value]))
        try:
            return self._parse_outputs(values)
        except ValueError:
            self._log.warning(
                "Unknown output selection %r in saved config; falling back to %s.",
                values,
                LockInOutput.X,
            )
            return (LockInOutput.X,)

    @staticmethod
    def _parse_outputs(value: Any) -> tuple[LockInOutput, ...]:
        """Parse lock-in output selections from text or serialised data.

        Notes:
            The shorthand token ``"T"`` is accepted as an alias for
            ``"THETA"`` in text input fields.
        """
        if isinstance(value, str):
            tokens = [
                token.strip() for token in value.replace(";", ",").split(",") if token.strip()
            ]
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
