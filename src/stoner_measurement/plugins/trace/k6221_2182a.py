"""Keithley 6221/2182A synchronous list-sweep trace plugin.

Drives a Keithley 6221 precision current source and a Keithley 2182A
nanovoltmeter in a synchronised list sweep.  The 6221 steps through a
current list programmed from the active scan generator; after each source
step it asserts a trigger-link pulse to start a 2182A measurement, and the
2182A asserts its meter-complete output to advance the 6221 to the next
point.  All measured voltages are stored in the 2182A's trace buffer and
retrieved as a block after the sweep completes.

The 2182A may be reached in two ways:

* **Via 6221 serial relay** — the 6221 relays RS-232 commands to the 2182A
  using ``SYST:COMM:SER:SEND`` / ``SYST:COMM:SER:ENT?``.  Only the 6221
  needs a GPIB connection.
* **Direct GPIB** — the 2182A has its own GPIB connection.  Both
  instruments must be given VISA resource strings.
"""

from __future__ import annotations

import enum
import logging
import math
import time
from typing import Any

import numpy as np
import pandas as pd
import pyvisa
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.trace_data import COLUMN_ROLE_Y, COLUMN_ROLE_Z, TraceData
from stoner_measurement.instruments.current_source import CurrentSource
from stoner_measurement.instruments.keithley.k2182 import Keithley2182A
from stoner_measurement.instruments.keithley.k6221 import Keithley6221
from stoner_measurement.instruments.nanovoltmeter import (
    Nanovoltmeter,
    NanovoltmeterTriggerSource,
)
from stoner_measurement.instruments.transport.gpib_transport import (
    GpibTransport,
    PassThroughGpibTransport,
)
from stoner_measurement.plugins.trace._differential import (
    modulate_current_sweep,
    reduce_differential_readings,
)
from stoner_measurement.plugins.trace._nanovoltmeter_support import (
    NANOVOLTMETER_DRIVER_LABELS as _NANOVOLTMETER_DRIVER_LABELS,
)
from stoner_measurement.plugins.trace._nanovoltmeter_support import (
    NANOVOLTMETER_DRIVERS as _NANOVOLTMETER_DRIVERS,
)
from stoner_measurement.plugins.trace.base import (
    TracePlugin,
    TraceStatus,
)
from stoner_measurement.scan import (
    FunctionScanGenerator,
    ListScanGenerator,
    SteppedScanGenerator,
)
from stoner_measurement.ui.widgets import (
    FILTER_GPIB,
    SIComboBox,
    SISpinBox,
    VisaResourceComboBox,
)

#: Poll interval in seconds when waiting for the 2182A buffer to fill.
_POLL_INTERVAL: float = 0.25

#: Safety factor applied to the theoretical sweep duration when computing timeout.
_TIMEOUT_FACTOR: float = 5.0

#: Minimum timeout in seconds regardless of sweep duration.
_TIMEOUT_MIN: float = 10.0
_POST_SWEEP_DELAY_MIN: float = 0.25

#: Available fixed current output ranges for the 6221 (amps).
_6221_FIXED_RANGES: tuple[float, ...] = (
    1e-10,
    1e-9,
    1e-8,
    1e-7,
    1e-6,
    1e-5,
    1e-4,
    1e-3,
    1e-2,
    1e-1,
)

#: Available fixed voltage measurement ranges for the 2182A (volts).
_2182A_FIXED_RANGES = Keithley2182A.CAPABILITIES.fixed_voltage_ranges

#: Supported NPLC settings for the 2182A.
_2182A_NPLC_OPTIONS = Keithley2182A.CAPABILITIES.nplc_values

#: Supported display/data digits for the 2182A (number of digits integer, e.g. 4 → 4.5 digits, range 4–8).
_2182A_DIGITS_OPTIONS = Keithley2182A.CAPABILITIES.digit_values

#: Currents whose absolute value is below this threshold (in amps) are treated as
#: zero when computing R(t) = V/I.  The value is intentionally much smaller than
#: any realistic 6221 output (minimum non-zero range: 100 pA) so that it catches
#: only genuine zero-current points set by the scan generator.
_ZERO_CURRENT_THRESHOLD: float = 1e-30

#: Maximum compliance voltage supported by the 6221 (volts).
_6221_MAX_COMPLIANCE_V: float = 105.0

_CLEANUP_EXCEPTIONS: tuple[type[Exception], ...] = (
    OSError,
    RuntimeError,
    pyvisa.Error,
)

_LINE_PERIOD = 0.02


class ConnectionMode(enum.Enum):
    """How the 2182A nanovoltmeter is connected to the system.

    Attributes:
        VIA_6221_SERIAL:
            The 2182A is connected to the RS-232 port of the 6221.  All
            commands to the 2182A are relayed via ``SYST:COMM:SER:SEND``
            and ``SYST:COMM:SER:ENT?`` on the 6221.
        DIRECT_GPIB:
            The 2182A has its own GPIB connection and is addressed
            independently via its own VISA resource string.
    """

    VIA_6221_SERIAL = "via_6221_serial"
    DIRECT_GPIB = "direct_gpib"


class ComplianceMode(enum.Enum):
    """Mode used to determine the compliance voltage for each sweep point.

    Attributes:
        VOLTAGE:
            A fixed compliance voltage in volts is applied to every point.
        RESISTANCE:
            The compliance voltage per point is calculated as
            ``|current| × compliance_resistance``, where
            *compliance_resistance* is set by the user.  This is programmed
            into the instrument as a per-point compliance list.
    """

    VOLTAGE = "voltage"
    RESISTANCE = "resistance"


class SourceRangeMode(enum.Enum):
    """Output current range selection mode for the 6221.

    Attributes:
        BEST:
            The instrument selects the best fixed range once before the sweep
            starts, based on the largest current in the list.
        AUTO:
            The instrument re-evaluates and changes the range at each point.
        FIXED:
            A specific fixed range is programmed via :attr:`_source_range`.
    """

    BEST = "BEST"
    AUTO = "AUTO"
    FIXED = "FIXED"


class DigitalFilterType(enum.Enum):
    """Digital-filter mode exposed by the 2182A measurement controls."""

    OFF = "off"
    REPEAT = "repeat"
    WINDOW = "window"


class SecondaryTriggerMode(enum.Enum):
    """Hardware trigger routing used by the optional second voltmeter."""

    PARALLEL = "parallel"
    DAISY_CHAIN = "daisy_chain"


class Keithley6221_2182APlugin(TracePlugin):  # pylint: disable=invalid-name
    """Measure an I-V sweep using a Keithley 6221 and 2182A.

    Use this plugin for current-driven transport measurements where a Keithley
    6221 sources a list of current values and a Keithley 2182A measures the
    corresponding voltage. It is intended for automated I-V acquisition with
    hardware-triggered synchronisation between the two instruments.

    In the configuration tabs you choose the instrument connection mode, GPIB
    resources, compliance behaviour, source delay, source range policy, 2182A
    integration and filtering settings, and trigger-link line assignments. The
    scan generator defines the current list that will be swept.

    The source/instrument tab therefore configures how the 6221 and 2182A are
    connected and triggered, while the scan tab defines the current points. The
    compliance controls select either a direct voltage limit or a resistance-
    based derived limit. Additional controls configure the 2182A integration
    time, voltage range, digital and analogue filtering, relative mode, and
    digit count. The Help/About tab uses this docstring to explain how those
    settings map to the automated I-V measurement.

    The result is a single trace channel named **IV**. Besides the measured
    voltage, the plugin also derives resistance and power columns for
    convenience. An optional, independently connected nanovoltmeter can buffer
    the same sweep and add a second prefixed V/R/P column set. Both meters use
    external trigger input. They may be wired in parallel, with the primary
    returning the meter-complete handshake, or daisy-chained so the primary
    triggers the secondary and the secondary advances the 6221.

    For more technical use, the 6221 is programmed with the full current list
    derived from the active scan generator and trigger-link handshaking keeps
    the source and voltmeter synchronised. After acquisition, a single trace
    channel named ``"IV"`` is returned, backed by a
    :class:`~pandas.DataFrame` with:

    * **x** (index) — programmed source current in amps.
    * **V** (:data:`~stoner_measurement.plugins.trace.base.COLUMN_ROLE_Y`) —
      measured voltage in volts.
    * **R** (:data:`~stoner_measurement.plugins.trace.base.COLUMN_ROLE_Z`) —
      resistance V/I in ohms (``float("nan")`` when I is effectively zero).
    * **P** (:data:`~stoner_measurement.plugins.trace.base.COLUMN_ROLE_Z`) —
      power I×V in watts.

    Attributes:
        _6221_resource (str):
            VISA resource string for the Keithley 6221 (e.g.
            ``"GPIB0::22::INSTR"``).
        _2182a_resource (str):
            VISA resource string for the Keithley 2182A, used only in
            ``DIRECT_GPIB`` mode (e.g. ``"GPIB0::7::INSTR"``).
        _connection_mode (ConnectionMode):
            Whether the 2182A is reached via 6221 serial relay or its own
            GPIB connection.
        _compliance_mode (ComplianceMode):
            Whether the compliance limit is expressed as a fixed voltage or
            as a resistance (per-point voltage = ``|I| × compliance_resistance``).
        _compliance (float):
            Compliance voltage in volts when :attr:`_compliance_mode` is
            :attr:`~ComplianceMode.VOLTAGE`.
        _compliance_resistance (float):
            Compliance resistance in ohms when :attr:`_compliance_mode` is
            :attr:`~ComplianceMode.RESISTANCE`.
        _source_delay (float):
            Source settling delay between output change and trigger to
            2182A, in seconds.
        _source_range_mode (SourceRangeMode):
            How the 6221 output range is selected during the sweep.
        _source_range (float):
            Fixed current range in amps, used when :attr:`_source_range_mode`
            is :attr:`~SourceRangeMode.FIXED`.
        _nplc (float):
            2182A integration time in power-line cycles.  Valid values are
            ``0.1``, ``1.0``, and ``10.0``.
        _voltage_range (float):
            Fixed voltage range in volts for the 2182A.  Set to ``0.0``
            for autorange.
        _filter_type (DigitalFilterType):
            Disabled, repeating, or moving-window digital filtering.
        _filter_count (int):
            Number of readings averaged by the 2182A digital filter.
        _trigger_delay (float):
            Delay between the external trigger and the 2182A conversion.
        _line_sync (bool):
            Synchronize 2182A A/D conversions to the power line.
        _autozero (bool):
            Enable automatic zero-reference measurements on the 2182A.
        _analog_filter (bool):
            Enable the 2182A low-pass analogue filter.
        _relative_enabled (bool):
            Enable the 2182A relative (REL) subtraction mode.
        _relative_value (float):
            Voltage reference subtracted while relative mode is enabled.
        _digits (int):
            Number of display and data digits for the 2182A (4–8).
        _output_tlink (int):
            Trigger-link line number (1–6) on which the 6221 outputs the
            "source ready" trigger pulse to the 2182A.
        _input_tlink (int):
            Trigger-link line number (1–6) on which the 6221 accepts the
            "meter complete" trigger pulse from the 2182A.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> plugin = Keithley6221_2182APlugin()
        >>> plugin.name
        'k6221_dc_iv'
        >>> plugin.x_units
        'A'
        >>> plugin.y_units
        'V'
    """

    _scan_generator_class = FunctionScanGenerator
    _scan_generator_classes = [
        FunctionScanGenerator,
        SteppedScanGenerator,
        ListScanGenerator,
    ]

    def __init__(self, parent=None) -> None:
        """Initialise the plugin with default instrument and measurement settings."""
        super().__init__(parent)
        self._log = logging.getLogger(__name__)
        self.scan_generator = FunctionScanGenerator(parent=self)
        self.scan_generator.units = "A"

        # Connection settings
        self._6221_resource: str = "GPIB0::13::INSTR"
        self._2182a_resource: str = "GPIB0::7::INSTR"
        self._connection_mode: ConnectionMode = ConnectionMode.VIA_6221_SERIAL

        # Optional independently connected nanovoltmeter.  Trigger-link routing
        # determines whether it runs in parallel or completes a daisy chain.
        self._secondary_enabled: bool = False
        self._secondary_driver: str = "keithley_2182a"
        self._secondary_resource: str = "GPIB0::8::INSTR"
        self._secondary_prefix: str = "secondary"
        self._secondary_trigger_mode: SecondaryTriggerMode = SecondaryTriggerMode.PARALLEL

        # Source settings
        self._compliance_mode: ComplianceMode = ComplianceMode.VOLTAGE
        self._compliance: float = 10.0
        self._compliance_resistance: float = 1000.0
        self._source_delay: float = 1e-3
        self._source_range_mode: SourceRangeMode = SourceRangeMode.BEST
        self._source_range: float = 1e-3
        self._differential_mode: bool = False
        self._differential_conductance: bool = False
        self._delta_current: float = 1e-6

        # 2182A measurement settings
        self._nplc: float = 1.0
        self._voltage_range: float = 0.0
        self._filter_type: DigitalFilterType = DigitalFilterType.OFF
        self._filter_count: int = 10
        self._trigger_delay: float = 0.0
        self._line_sync: bool = False
        self._autozero: bool = True
        self._analog_filter: bool = False
        self._relative_enabled: bool = False
        self._relative_value: float = 0.0
        self._digits: int = 8

        # Secondary nanovoltmeter measurement settings
        self._secondary_nplc: float = 1.0
        self._secondary_voltage_range: float = 0.0
        self._secondary_filter_type: str = "OFF"
        self._secondary_filter_count: int = 10
        self._secondary_trigger_delay: float = 0.0
        self._secondary_line_sync: bool = False
        self._secondary_autozero: bool = True
        self._secondary_analog_filter: bool = False
        self._secondary_relative_enabled: bool = False
        self._secondary_relative_value: float = 0.0
        self._secondary_digits: int = 8

        # Trigger-link line assignments
        # Match the factory 2182A wiring: EXT TRIG input is line 2 and
        # voltmeter-complete (VMC) output is line 1.
        self._output_tlink: int = 2
        self._input_tlink: int = 1

        # Runtime state — populated in connect()
        self._k6221: CurrentSource | None = None
        self._k2182a: Nanovoltmeter | None = None
        self._secondary_nanovoltmeter: Nanovoltmeter | None = None
        self._secondary_voltages: tuple[float, ...] | None = None
        self._sweep_values: np.ndarray | None = None
        self._nominal_sweep_values: np.ndarray | None = None
        self._apply_initial_config()

    # ------------------------------------------------------------------
    # Plugin identity
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Unique identifier for the Keithley 6221 / 2182A plugin.

        Returns:
            (str):
                ``"k6221_dc_iv"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().name
            'k6221_dc_iv'
        """
        return "k6221_dc_iv"

    @property
    def x_label(self) -> str:
        """Axis label for the source current.

        Returns:
            (str):
                ``"I"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().x_label
            'I'
        """
        return "I"

    @property
    def y_label(self) -> str:
        """Axis label for the measured voltage.

        Returns:
            (str):
                ``"V"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().y_label
            'V'
        """
        return "V"

    @property
    def x_units(self) -> str:
        """Physical units for the source current axis.

        Returns:
            (str):
                ``"A"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().x_units
            'A'
        """
        return "A"

    @property
    def y_units(self) -> str:
        """Physical units for the voltage axis.

        Returns:
            (str):
                ``"V"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().y_units
            'V'
        """
        return "V"

    @property
    def trace_names(self) -> list[str]:
        """Name of the single multicolumn measurement channel.

        Returns:
            (list[str]):
                ``["IV"]``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().trace_names
            ['IV']
        """
        return ["IV"]

    def reported_values(self) -> dict[str, str]:
        """Return mean/std outputs for each derived IV trace column."""
        if not self._report_channel_statistics:
            return {}

        var = self.instance_name
        values: dict[str, str] = {}
        response_column = (
            "G" if self._differential_mode and self._differential_conductance else "R"
        )
        columns = ["V", response_column, "P"]
        if self._secondary_enabled:
            columns.extend(self._secondary_column_names())
        for column in columns:
            key = f"IV {column}"
            values[f"{var}:{key} mean"] = f"{var}.get_channel_statistic({key!r}, 'mean')"
            values[f"{var}:{key} std"] = f"{var}.get_channel_statistic({key!r}, 'std')"
        return values

    def _measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Acquire the sweep and return a single multicolumn ``"IV"`` trace.

        Runs the hardware sweep via :meth:`execute` to collect all ``(I, V)``
        pairs, then builds a :class:`~stoner_measurement.core.TraceData`
        backed by a :class:`~pandas.DataFrame` with x = source current and
        three dependent-variable columns:

        * **V** (:data:`~stoner_measurement.plugins.trace.base.COLUMN_ROLE_Y`) —
          measured voltage in volts.
        * **R** (:data:`~stoner_measurement.plugins.trace.base.COLUMN_ROLE_Z`) —
          resistance V/I in ohms (``float("nan")`` when I is effectively zero).
        * **P** (:data:`~stoner_measurement.plugins.trace.base.COLUMN_ROLE_Z`) —
          power I×V in watts.

        The result is stored as :attr:`data` and also returned.

        Args:
            parameters (dict[str, Any]):
                Step-specific overrides forwarded to :meth:`execute`.

        Returns:
            (dict[str, TraceData]):
                Single-entry mapping ``{"IV": trace_data}`` where
                *trace_data* carries columns V, R, and P keyed by their
                respective role constants.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> # plugin.connect(); plugin.configure()
            >>> # result = plugin.measure({})  # requires real hardware
        """
        pairs = self._acquire_pairs(parameters)

        if pairs:
            i_arr = np.array([i for i, _ in pairs], dtype=float)
            v_arr = np.array([v for _, v in pairs], dtype=float)
        else:
            i_arr = np.array([], dtype=float)
            v_arr = np.array([], dtype=float)

        response_name = "R"
        response_unit = "Ω"
        if self._differential_mode:
            if self._nominal_sweep_values is None:
                raise RuntimeError("Differential sweep completed without nominal scan values.")
            reduced = reduce_differential_readings(
                self._nominal_sweep_values,
                v_arr,
                self._delta_current,
                conductance=self._differential_conductance,
            )
            i_arr = reduced.current
            v_arr = reduced.voltage
            r_arr = reduced.response
            p_arr = reduced.power
            if self._differential_conductance:
                response_name = "G"
                response_unit = "S"
        else:
            with np.errstate(invalid="ignore", divide="ignore"):
                r_arr = np.where(
                    np.abs(i_arr) > _ZERO_CURRENT_THRESHOLD,
                    v_arr / i_arr,
                    float("nan"),
                )
            p_arr = i_arr * v_arr

        columns: dict[str, np.ndarray] = {"V": v_arr, response_name: r_arr, "P": p_arr}
        column_roles = {
            "V": COLUMN_ROLE_Y,
            response_name: COLUMN_ROLE_Z,
            "P": COLUMN_ROLE_Z,
        }
        names = {
            "x": self.x_label,
            "V": "V",
            response_name: response_name,
            "P": "P",
        }
        units = {
            "x": self.x_units,
            "V": self.y_units,
            response_name: response_unit,
            "P": "W",
        }

        if self._secondary_enabled:
            secondary = np.asarray(self._secondary_voltages or (), dtype=float)
            expected_secondary = (
                len(self._sweep_values)
                if self._differential_mode and self._sweep_values is not None
                else len(i_arr)
            )
            if len(secondary) != expected_secondary:
                raise RuntimeError(
                    "Secondary nanovoltmeter returned an unexpected number of readings."
                )
            if self._differential_mode:
                assert self._nominal_sweep_values is not None
                secondary_reduced = reduce_differential_readings(
                    self._nominal_sweep_values,
                    secondary,
                    self._delta_current,
                    conductance=self._differential_conductance,
                )
                secondary = secondary_reduced.voltage
                secondary_r = secondary_reduced.response
                secondary_p = secondary_reduced.power
            else:
                with np.errstate(invalid="ignore", divide="ignore"):
                    secondary_r = np.where(
                        np.abs(i_arr) > _ZERO_CURRENT_THRESHOLD,
                        secondary / i_arr,
                        float("nan"),
                    )
                secondary_p = i_arr * secondary
            secondary_names = self._secondary_column_names(response_name=response_name)
            for column, values, unit, role in zip(
                secondary_names,
                (secondary, secondary_r, secondary_p),
                (self.y_units, response_unit, "W"),
                (COLUMN_ROLE_Y, COLUMN_ROLE_Z, COLUMN_ROLE_Z),
                strict=True,
            ):
                columns[column] = values
                column_roles[column] = role
                names[column] = column
                units[column] = unit

        df = pd.DataFrame(
            columns,
            index=pd.Index(i_arr, name="x"),
        )
        return {"IV": TraceData(df=df, column_roles=column_roles, names=names, units=units)}

    def _secondary_column_names(self, *, response_name: str | None = None) -> tuple[str, str, str]:
        """Return prefixed voltage, resistance, and power column names."""
        prefix = self._secondary_prefix.strip() or "secondary"
        if response_name is None:
            response_name = (
                "G" if self._differential_mode and self._differential_conductance else "R"
            )
        return (f"{prefix} V", f"{prefix} {response_name}", f"{prefix} P")

    # ------------------------------------------------------------------
    # Lifecycle API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open connections to the 6221 and, in direct mode, the 2182A.

        Opens a GPIB connection to the 6221 using :attr:`_6221_resource`.
        When :attr:`_connection_mode` is :attr:`~ConnectionMode.DIRECT_GPIB`
        a second GPIB connection is opened to the 2182A using
        :attr:`_2182a_resource`.

        Raises:
            ConnectionError:
                If either instrument cannot be reached.
            RuntimeError:
                If the 6221 identity string does not contain ``"6221"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> # plugin.connect()  # requires real hardware
        """
        self._set_status(TraceStatus.CONNECTING)
        transport_6221: GpibTransport | None = None
        transport_2182a: GpibTransport | None = None
        transport_secondary: GpibTransport | None = None
        try:
            # connect to 6221
            transport_6221 = GpibTransport.from_resource_string(self._6221_resource, timeout=10.0)
            self._k6221 = Keithley6221(transport_6221)
            self._k6221.connect()
            self._k6221.confirm_identity()
            # Setup transport for 2182 as passthru or direct
            if self._connection_mode is ConnectionMode.DIRECT_GPIB:
                transport_2182a = GpibTransport.from_resource_string(
                    self._2182a_resource, timeout=10.0
                )
            else:  # Via 6221
                transport_2182a = PassThroughGpibTransport.from_resource_string(
                    self._6221_resource, timeout=10.0
                )
            self._k2182a = Keithley2182A(transport_2182a)
            self._k2182a.connect()
            self._k2182a.confirm_identity()

            if self._secondary_enabled:
                driver_class = _NANOVOLTMETER_DRIVERS[self._secondary_driver]
                transport_secondary = GpibTransport.from_resource_string(
                    self._secondary_resource, timeout=10.0
                )
                self._secondary_nanovoltmeter = driver_class(transport_secondary)  # type: ignore[call-arg]
                self._secondary_nanovoltmeter.connect()
                self._secondary_nanovoltmeter.confirm_identity()

        except Exception as err:
            # Clean up any partially-opened transports to avoid leaking VISA sessions.
            self._log.debug(f"Connection error {err}")
            for transport in (transport_secondary, transport_2182a, transport_6221):
                if transport is not None:
                    try:
                        transport.close()
                    except _CLEANUP_EXCEPTIONS:
                        pass
            self._k6221 = None
            self._k2182a = None
            self._secondary_nanovoltmeter = None
            self._set_status(TraceStatus.ERROR)
            raise
        self._set_status(TraceStatus.IDLE)

    def configure(self) -> None:
        """Program the complete sweep into the 6221 and configure the 2182A.

        Reads the full list of source current values from the active scan
        generator and loads them as a ``LIST`` sweep into the 6221.  The
        2182A trace buffer is sized to match the point count and trigger-link
        handshaking is configured so that:

        * The 6221 outputs a trigger pulse on :attr:`_output_tlink` after
          each source step and settling delay.
        * The 6221 advances to the next point when it receives a trigger on
          :attr:`_input_tlink`.
        * The 2182A triggers on the external input (trigger-link line
          :attr:`_output_tlink`) and asserts meter-complete on
          :attr:`_input_tlink`.

        Compliance is programmed as per-point values: in
        :attr:`~ComplianceMode.VOLTAGE` mode every point uses
        :attr:`_compliance`; in :attr:`~ComplianceMode.RESISTANCE` mode each
        per-point voltage equals ``|I| × _compliance_resistance``.

        Measurement settings (NPLC, voltage range, trigger delay, line sync,
        autozero, digital filter, analogue filter, relative mode, and digits)
        are also applied to the 2182A. Once
        configuration completes successfully, the 6221 output is enabled and
        left on so successive :meth:`measure` calls can start fresh sweeps
        without reconfiguration. The output is disabled in :meth:`disconnect`.

        Raises:
            RuntimeError:
                If not connected (call :meth:`connect` first).
            ValueError:
                If the scan generator produces no points.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> # plugin.connect(); plugin.configure()  # requires real hardware
        """
        # ---- Check connected ok ----
        if self._k6221 is None:
            self._log.error(
                f"{self.__class__.__name__}:Not connected — call connect() before execute()."
            )
            raise RuntimeError("Not connected — call connect() before execute().")
        if self._k2182a is None:
            self._log.error(
                f"{self.__class__.__name__}:DIRECT_GPIB mode selected but 2182A is not connected."
            )
            raise RuntimeError("DIRECT_GPIB mode selected but 2182A is not connected.")
        if self._secondary_enabled and self._secondary_nanovoltmeter is None:
            raise RuntimeError("Secondary nanovoltmeter is enabled but not connected.")

        self._set_status(TraceStatus.CONFIGURING)
        try:
            self._nominal_sweep_values = np.asarray(self.scan_generator.generate(), dtype=float)
            self._sweep_values = (
                modulate_current_sweep(self._nominal_sweep_values, self._delta_current)
                if self._differential_mode
                else self._nominal_sweep_values.copy()
            )
            n = len(self._sweep_values)
            if n == 0:
                raise ValueError("Scan generator produced no points.")
            overrun_warning = self._parallel_overrun_warning()
            if overrun_warning is not None:
                self._log.warning(overrun_warning)

            # ---- 6221: reset and configure LIST sweep ----
            self._k6221.reset()

            # Build current list — the driver's configure_custom_sweep handles
            # batching into 100-point chunks automatically.
            self._k6221.configure_custom_sweep(
                tuple(float(v) for v in self._sweep_values),
                delay=self._source_delay,
            )

            # ---- 6221: per-point compliance ----
            if self._compliance_mode is ComplianceMode.RESISTANCE:
                comp_values = [
                    abs(float(v)) * self._compliance_resistance for v in self._sweep_values
                ]
                max_comp = max(comp_values) if comp_values else 0.0
                if max_comp > _6221_MAX_COMPLIANCE_V:
                    raise ValueError(
                        f"Resistance-mode compliance would reach {max_comp:.3g} V "
                        f"(max {_6221_MAX_COMPLIANCE_V} V for the 6221). "
                        "Reduce the compliance resistance or the sweep currents."
                    )
            else:
                comp_values = [self._compliance] * n
            self._k6221.configure_list_compliance(comp_values)

            # ---- 6221: output range ----
            if self._source_range_mode is SourceRangeMode.AUTO:
                self._k6221.set_sweep_range_mode("AUTO")
            elif self._source_range_mode is SourceRangeMode.FIXED:
                self._k6221.set_fixed_range(self._source_range)
            else:
                self._k6221.set_sweep_range_mode("BEST")
            self._k6221.set_sweep_count(1)
            self._k6221.configure_sweep_complete_srq()

            # ---- 6221: trigger-link ----
            # Output a trigger pulse after each source step and settling delay.
            self._k6221.configure_arm()
            self._k6221.configure_trigger(
                source="TLIN",
                direction="SOUR",
                tlink_in=self._input_tlink,
                tlink_out=self._output_tlink,
                output="DEL",
            )

            # ---- 2182A: reset and configure ----
            self._k2182a.reset()

            self._k2182a.set_digits(self._digits)
            self._k2182a.set_nplc(self._nplc)
            self._k2182a.set_line_sync_enabled(self._line_sync)
            self._k2182a.set_autozero_enabled(self._autozero)
            if self._voltage_range > 0.0:
                self._k2182a.set_autorange(False)
                self._k2182a.set_range(self._voltage_range)
            else:
                self._k2182a.set_autorange(True)

            filter_enabled = self._filter_type is not DigitalFilterType.OFF
            self._k2182a.set_filter_enabled(filter_enabled)
            if filter_enabled:
                self._k2182a.set_filter_count(self._filter_count)
                self._k2182a.set_filter_type(self._filter_type.name)

            self._k2182a.set_analog_filter_enabled(self._analog_filter)
            self._k2182a.set_relative_value(self._relative_value)
            self._k2182a.set_relative_enabled(self._relative_enabled)

            # ---- 2182A: trace buffer ----
            self._k2182a.clear_buffer()
            self._k2182a.set_buffer_size(n)
            self._k2182a.set_buffer_feed_sense()
            self._k2182a.set_buffer_feed_continuous_next()

            # ---- 2182A: trigger ----
            self._k2182a.set_trigger_source(NanovoltmeterTriggerSource.EXT)
            self._k2182a.set_trigger_delay(self._trigger_delay)
            self._k2182a.set_trigger_count(n)

            if self._secondary_enabled:
                assert self._secondary_nanovoltmeter is not None
                self._configure_nanovoltmeter(
                    self._secondary_nanovoltmeter,
                    n,
                    prefix="_secondary_",
                )

            # ---- 6221 arm to go ----
            self._k6221.sweep_abort()
            self._k6221.sweep_arm()

        except Exception as exc:
            self._log.error(f"{self.__class__.__name__}: Exception during confgiure {exc}")
            self._set_status(TraceStatus.ERROR)
            raise
        self._set_status(TraceStatus.IDLE)

    def _configure_nanovoltmeter(
        self,
        meter: Nanovoltmeter,
        count: int,
        *,
        prefix: str,
    ) -> None:
        """Apply one meter's measurement, buffer, and trigger settings."""

        def get(name: str) -> Any:
            return getattr(self, f"{prefix}{name}")

        capabilities = meter.get_capabilities()
        if capabilities.supports_safe_reset:
            meter.reset()
        meter.set_digits(get("digits"))
        meter.set_nplc(get("nplc"))
        if capabilities.supports_line_sync:
            meter.set_line_sync_enabled(get("line_sync"))  # type: ignore[attr-defined]
        if capabilities.supports_autozero:
            meter.set_autozero_enabled(get("autozero"))  # type: ignore[attr-defined]
        voltage_range = get("voltage_range")
        meter.set_autorange(voltage_range <= 0.0)
        if voltage_range > 0.0:
            meter.set_range(voltage_range)
        filter_type = get("filter_type")
        filter_enabled = filter_type != "OFF"
        meter.set_filter_enabled(filter_enabled)
        if filter_enabled:
            if capabilities.supports_filter_count:
                meter.set_filter_count(get("filter_count"))
            meter.set_filter_type(filter_type)  # type: ignore[attr-defined]
        if capabilities.supports_analog_filter:
            meter.set_analog_filter_enabled(get("analog_filter"))
        if capabilities.supports_relative:
            meter.set_relative_value(get("relative_value"))  # type: ignore[attr-defined]
            meter.set_relative_enabled(get("relative_enabled"))
        if capabilities.max_buffer_points is not None and count > capabilities.max_buffer_points:
            raise ValueError(
                f"{type(meter).__name__} supports at most "
                f"{capabilities.max_buffer_points} buffered readings; requested {count}."
            )
        meter.clear_buffer()
        meter.set_buffer_size(count)
        meter.set_buffer_feed_sense()
        meter.set_buffer_feed_continuous_next()
        meter.set_trigger_source(NanovoltmeterTriggerSource.EXT)
        meter.set_trigger_delay(get("trigger_delay"))  # type: ignore[attr-defined]
        meter.set_trigger_count(count)

    def _acquire_pairs(self, parameters: dict[str, Any]) -> list[tuple[float, float]]:
        """Arm the sweep, collect the complete trace, and yield (I, V) pairs.

        Arms the 6221 sweep and initiates the 2182A trigger system. The 6221
        output is expected to have been enabled during :meth:`configure`, so
        this method just starts the programmed sweep. It then waits for the
        6221 sweep-complete service request, reads the 2182A buffer (retrying
        until all *n* readings are available), and yields the
        ``(source_current, voltage)`` pair for each scan point in order.

        Args:
            parameters (dict[str, Any]):
                Step-specific overrides.  Currently unused; present for
                compatibility with the :class:`~TracePlugin` interface.

        Yields:
            (tuple[float, float]):
                ``(current_A, voltage_V)`` pairs in scan order.

        Raises:
            RuntimeError:
                If :meth:`configure` has not been called, or if the sweep
                does not complete within the timeout.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> # plugin.connect(); plugin.configure()
            >>> # pts = list(plugin.execute({}))  # requires real hardware
        """
        # ---- Check connected ok ----
        if self._k6221 is None:
            self._log.error(
                f"{self.__class__.__name__}:Not connected — call connect() before execute()."
            )
            raise RuntimeError("Not connected — call connect() before execute().")
        if self._k2182a is None:
            self._log.error(
                f"{self.__class__.__name__}:DIRECT_GPIB mode selected but 2182A is not connected."
            )
            raise RuntimeError("DIRECT_GPIB mode selected but 2182A is not connected.")
        if self._secondary_enabled and self._secondary_nanovoltmeter is None:
            raise RuntimeError("Secondary nanovoltmeter is enabled but not connected.")
        if self._sweep_values is None:
            self._log.error(
                f"{self.__class__.__name__}:Not configured — call configure() before execute()."
            )
            raise RuntimeError("Not configured — call configure() before execute().")

        n = len(self._sweep_values)
        # Estimate a generous timeout: n points × (NPLC/50 + source_delay) × safety factor.
        # Assumes 50 Hz mains frequency; the timeout is conservative enough to also
        # cover 60 Hz installations without adjustment.
        filter_conversions = (
            self._filter_count if self._filter_type is DigitalFilterType.REPEAT else 1
        )
        point_time = (
            self._nplc * _LINE_PERIOD * filter_conversions
            + self._source_delay
            + self._trigger_delay
        )
        if (
            self._secondary_enabled
            and self._secondary_trigger_mode is SecondaryTriggerMode.DAISY_CHAIN
        ):
            point_time += self._secondary_measurement_time()
        timeout = max(_TIMEOUT_MIN, n * point_time * _TIMEOUT_FACTOR)
        post_sweep_delay = self._post_sweep_delay()

        try:
            # ---- Arm 6221 sweep and initiate 2182A trigger system. ----
            self._k6221.clear_sweep_complete_event()
            self._k2182a.set_buffer_feed_continuous_next()
            self._k2182a.initiate()
            self._secondary_voltages = None
            if self._secondary_enabled:
                assert self._secondary_nanovoltmeter is not None
                self._secondary_nanovoltmeter.set_buffer_feed_continuous_next()
                self._secondary_nanovoltmeter.initiate()

            # ---- Start sweep ----
            self._k6221.sweep_init()

            # ---- Wait for sweep to finish ----
            if not self._k6221.wait_for_sweep_complete_srq(timeout):
                self._k6221.sweep_abort()
                self._k2182a.abort()
                if self._secondary_nanovoltmeter is not None:
                    self._secondary_nanovoltmeter.abort()
                self._k6221.enable_output(False)
                raise RuntimeError(
                    f"Timeout waiting for 6221 sweep-complete SRQ after {timeout:.1f} s."
                )

            # Allow the 2182A to finish the final measurement and commit it to memory.
            time.sleep(post_sweep_delay)

            # ---- Read buffered data from both voltmeters. ----
            voltages = self._read_meter_buffer(
                self._k2182a, n, label="2182A", post_sweep_delay=post_sweep_delay
            )
            if self._secondary_enabled:
                assert self._secondary_nanovoltmeter is not None
                self._secondary_voltages = self._read_meter_buffer(
                    self._secondary_nanovoltmeter,
                    n,
                    label="Secondary nanovoltmeter",
                    post_sweep_delay=post_sweep_delay,
                )
        except Exception as exc:
            # ---- Attempt a clean abort on any failure. ----
            self._log.error(f"{self.__class__.__name__}: Exception during execute loop {exc}")
            try:
                self._k6221.sweep_abort()
                self._k2182a.abort()
                if self._secondary_nanovoltmeter is not None:
                    self._secondary_nanovoltmeter.abort()
                self._k6221.enable_output(False)
            except _CLEANUP_EXCEPTIONS as exc:
                self._log.error(f"{self.__class__.__name__}:Exceptions during cleanup {exc}")
                pass
            raise

        return list(zip(self._sweep_values, voltages, strict=True))

    def _read_meter_buffer(
        self,
        meter: Nanovoltmeter,
        count: int,
        *,
        label: str,
        post_sweep_delay: float,
    ) -> tuple[float, ...]:
        """Read a complete meter buffer, allowing its final reading to settle."""
        read_deadline = time.monotonic() + max(_TIMEOUT_MIN / 2.0, post_sweep_delay * 4.0)
        while True:
            readings = meter.read_buffer(count=count)
            if len(readings) == count:
                return readings
            if time.monotonic() > read_deadline:
                raise RuntimeError(
                    f"{label} returned {len(readings)} readings but expected {count} "
                    f"after waiting {post_sweep_delay:.2f} s beyond sweep completion."
                )
            time.sleep(_POLL_INTERVAL)

    def _post_sweep_delay(self) -> float:
        """Return a conservative delay for the final 2182A reading to complete."""
        delays = [self._primary_measurement_time()]
        if self._secondary_enabled:
            delays.append(self._secondary_measurement_time())
        return max(_POST_SWEEP_DELAY_MIN, *delays)

    def _primary_measurement_time(self) -> float:
        """Estimate one primary conversion, including enabled filtering."""
        filter_multiplier = (
            self._filter_count if self._filter_type is DigitalFilterType.REPEAT else 1
        )
        analog_multiplier = 2 if self._analog_filter else 1
        return (
            self._trigger_delay + self._nplc * _LINE_PERIOD * filter_multiplier * analog_multiplier
        )

    def _secondary_measurement_time(self) -> float:
        """Estimate one secondary conversion, including enabled filtering."""
        capabilities = _NANOVOLTMETER_DRIVERS[self._secondary_driver].CAPABILITIES
        filter_multiplier = (
            self._secondary_filter_count
            if self._secondary_filter_type in capabilities.counted_filter_types
            else 1
        )
        analog_multiplier = (
            capabilities.analog_filter_time_multiplier if self._secondary_analog_filter else 1.0
        )
        return (
            self._secondary_trigger_delay
            + self._secondary_nplc * _LINE_PERIOD * filter_multiplier * analog_multiplier
        )

    def _parallel_overrun_warning(self) -> str | None:
        """Return a warning when parallel secondary acquisition may overrun."""
        if (
            not self._secondary_enabled
            or self._secondary_trigger_mode is not SecondaryTriggerMode.PARALLEL
        ):
            return None
        secondary_time = self._secondary_measurement_time()
        trigger_interval = self._primary_measurement_time() + self._source_delay
        if secondary_time <= trigger_interval:
            return None
        return (
            "Potential secondary nanovoltmeter measurement overrun in parallel trigger mode: "
            f"the secondary conversion is estimated at {secondary_time:.4g} s, but only "
            f"{trigger_interval:.4g} s is available before the next trigger. Increase the "
            "primary integration/filter time or source delay, reduce the secondary "
            "integration/filter time, or use daisy-chain triggering."
        )

    def disconnect(self) -> None:
        """Disable the 6221 output and close all instrument connections.

        Always attempts to disable the 6221 output before closing
        connections, even if a previous operation failed.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> plugin.disconnect()
            >>> plugin.status is TraceStatus.IDLE
            True
        """
        self._set_status(TraceStatus.DISCONNECTING)
        for instr in (self._k6221, self._k2182a, self._secondary_nanovoltmeter):
            if instr is not None:
                try:
                    if instr is self._k6221:
                        instr.enable_output(False)
                except _CLEANUP_EXCEPTIONS:
                    pass
                try:
                    instr.disconnect()
                except _CLEANUP_EXCEPTIONS:
                    pass
        self._k6221 = None
        self._k2182a = None
        self._secondary_nanovoltmeter = None
        self._secondary_voltages = None
        self._sweep_values = None
        self._nominal_sweep_values = None
        self._set_status(TraceStatus.IDLE)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Serialise the plugin configuration to a JSON-compatible dict.

        Extends the base :meth:`~TracePlugin.to_json` dict with all
        instrument and measurement settings.

        Returns:
            (dict[str, Any]):
                JSON-serialisable configuration dictionary.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> d = plugin.to_json()
            >>> d["compliance"]
            10.0
            >>> d["connection_mode"]
            'via_6221_serial'
        """
        data = super().to_json()
        data["resource_6221"] = self._6221_resource
        data["resource_2182a"] = self._2182a_resource
        data["connection_mode"] = self._connection_mode.value
        data["compliance_mode"] = self._compliance_mode.value
        data["compliance"] = self._compliance
        data["compliance_resistance"] = self._compliance_resistance
        data["source_delay"] = self._source_delay
        data["source_range_mode"] = self._source_range_mode.value
        data["source_range"] = self._source_range
        data["differential_mode"] = self._differential_mode
        if self._differential_mode:
            data["differential_conductance"] = self._differential_conductance
            data["delta_current"] = self._delta_current
        data["nplc"] = self._nplc
        data["voltage_range"] = self._voltage_range
        data["filter_type"] = self._filter_type.value
        # Retained so older readers can still interpret newly saved configs.
        data["filter_enabled"] = self._filter_type is not DigitalFilterType.OFF
        data["filter_count"] = self._filter_count
        data["trigger_delay"] = self._trigger_delay
        data["line_sync"] = self._line_sync
        data["autozero"] = self._autozero
        data["analog_filter"] = self._analog_filter
        data["relative_enabled"] = self._relative_enabled
        data["relative_value"] = self._relative_value
        data["digits"] = self._digits
        data["output_tlink"] = self._output_tlink
        data["input_tlink"] = self._input_tlink
        secondary: dict[str, Any] = {"enabled": self._secondary_enabled}
        if self._secondary_enabled:
            secondary.update(
                {
                    "driver": self._secondary_driver,
                    "resource": self._secondary_resource,
                    "prefix": self._secondary_prefix.strip() or "secondary",
                    "trigger_mode": self._secondary_trigger_mode.value,
                    "nplc": self._secondary_nplc,
                    "voltage_range": self._secondary_voltage_range,
                    "filter_type": self._secondary_filter_type.lower(),
                    "filter_count": self._secondary_filter_count,
                    "trigger_delay": self._secondary_trigger_delay,
                    "line_sync": self._secondary_line_sync,
                    "autozero": self._secondary_autozero,
                    "analog_filter": self._secondary_analog_filter,
                    "relative_enabled": self._secondary_relative_enabled,
                    "relative_value": self._secondary_relative_value,
                    "digits": self._secondary_digits,
                }
            )
        data["secondary_nanovoltmeter"] = secondary
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore plugin settings from *data*.

        Args:
            data (dict[str, Any]):
                Serialised plugin dict as produced by :meth:`to_json`.
        """
        super()._restore_from_json(data)
        self._6221_resource = data.get("resource_6221", self._6221_resource)
        self._2182a_resource = data.get("resource_2182a", self._2182a_resource)
        mode_str = data.get("connection_mode", self._connection_mode.value)
        try:
            self._connection_mode = ConnectionMode(mode_str)
        except ValueError:
            self._log.warning(
                "Unknown connection_mode value %r in saved config; falling back to default (%s).",
                mode_str,
                self._connection_mode.value,
            )
        comp_mode_str = data.get("compliance_mode", self._compliance_mode.value)
        try:
            self._compliance_mode = ComplianceMode(comp_mode_str)
        except ValueError:
            self._log.warning(
                "Unknown compliance_mode value %r in saved config; falling back to default (%s).",
                comp_mode_str,
                self._compliance_mode.value,
            )
        self._compliance = float(data.get("compliance", self._compliance))
        self._compliance_resistance = float(
            data.get("compliance_resistance", self._compliance_resistance)
        )
        self._source_delay = float(data.get("source_delay", self._source_delay))
        range_mode_str = data.get("source_range_mode", self._source_range_mode.value)
        try:
            self._source_range_mode = SourceRangeMode(range_mode_str)
        except ValueError:
            self._log.warning(
                "Unknown source_range_mode value %r in saved config; falling back to default (%s).",
                range_mode_str,
                self._source_range_mode.value,
            )
        self._source_range = float(data.get("source_range", self._source_range))
        self._differential_mode = bool(data.get("differential_mode", self._differential_mode))
        if self._differential_mode:
            self._differential_conductance = bool(
                data.get("differential_conductance", self._differential_conductance)
            )
            self._delta_current = float(data.get("delta_current", self._delta_current))
        self._nplc = float(data.get("nplc", self._nplc))
        self._voltage_range = float(data.get("voltage_range", self._voltage_range))
        filter_type_str = data.get("filter_type")
        if filter_type_str is None:
            self._filter_type = (
                DigitalFilterType.REPEAT
                if data.get("filter_enabled", False)
                else DigitalFilterType.OFF
            )
        else:
            try:
                restored_filter = DigitalFilterType(filter_type_str)
                if restored_filter not in {
                    DigitalFilterType.OFF,
                    DigitalFilterType.REPEAT,
                    DigitalFilterType.WINDOW,
                }:
                    raise ValueError(filter_type_str)
                self._filter_type = restored_filter
            except ValueError:
                self._log.warning(
                    "Unknown filter_type value %r in saved config; falling back to default (%s).",
                    filter_type_str,
                    self._filter_type.value,
                )
        self._filter_count = int(data.get("filter_count", self._filter_count))
        self._trigger_delay = float(data.get("trigger_delay", self._trigger_delay))
        self._line_sync = bool(data.get("line_sync", self._line_sync))
        self._autozero = bool(data.get("autozero", self._autozero))
        self._analog_filter = bool(data.get("analog_filter", self._analog_filter))
        self._relative_enabled = bool(data.get("relative_enabled", self._relative_enabled))
        self._relative_value = float(data.get("relative_value", self._relative_value))
        self._digits = int(data.get("digits", self._digits))
        self._output_tlink = int(data.get("output_tlink", self._output_tlink))
        self._input_tlink = int(data.get("input_tlink", self._input_tlink))
        secondary = data.get("secondary_nanovoltmeter", {})
        if not isinstance(secondary, dict):
            self._log.warning("Ignoring invalid secondary_nanovoltmeter configuration.")
            return
        self._secondary_enabled = bool(secondary.get("enabled", False))
        if not self._secondary_enabled:
            return
        driver = str(secondary.get("driver", self._secondary_driver))
        if driver in _NANOVOLTMETER_DRIVERS:
            self._secondary_driver = driver
        else:
            self._log.warning(
                "Unknown secondary nanovoltmeter driver %r; falling back to %s.",
                driver,
                self._secondary_driver,
            )
        self._secondary_resource = str(secondary.get("resource", self._secondary_resource))
        self._secondary_prefix = (
            str(secondary.get("prefix", self._secondary_prefix)).strip() or "secondary"
        )
        trigger_mode = secondary.get("trigger_mode", self._secondary_trigger_mode.value)
        try:
            self._secondary_trigger_mode = SecondaryTriggerMode(trigger_mode)
        except ValueError:
            self._log.warning(
                "Unknown secondary trigger_mode value %r; falling back to %s.",
                trigger_mode,
                self._secondary_trigger_mode.value,
            )
        self._secondary_nplc = float(secondary.get("nplc", self._secondary_nplc))
        self._secondary_voltage_range = float(
            secondary.get("voltage_range", self._secondary_voltage_range)
        )
        filter_type = str(secondary.get("filter_type", self._secondary_filter_type)).upper()
        supported_filter_types = _NANOVOLTMETER_DRIVERS[
            self._secondary_driver
        ].CAPABILITIES.filter_types
        if filter_type in supported_filter_types:
            self._secondary_filter_type = filter_type
        else:
            self._secondary_filter_type = (
                _NANOVOLTMETER_DRIVERS[self._secondary_driver].CAPABILITIES.default_filter_type
                or supported_filter_types[0]
            )
            self._log.warning(
                "Unknown secondary filter_type value %r; falling back to %s.",
                filter_type,
                self._secondary_filter_type,
            )
        self._secondary_filter_count = int(
            secondary.get("filter_count", self._secondary_filter_count)
        )
        self._secondary_trigger_delay = float(
            secondary.get("trigger_delay", self._secondary_trigger_delay)
        )
        self._secondary_line_sync = bool(secondary.get("line_sync", self._secondary_line_sync))
        self._secondary_autozero = bool(secondary.get("autozero", self._secondary_autozero))
        self._secondary_analog_filter = bool(
            secondary.get("analog_filter", self._secondary_analog_filter)
        )
        self._secondary_relative_enabled = bool(
            secondary.get("relative_enabled", self._secondary_relative_enabled)
        )
        self._secondary_relative_value = float(
            secondary.get("relative_value", self._secondary_relative_value)
        )
        self._secondary_digits = int(secondary.get("digits", self._secondary_digits))

    # ------------------------------------------------------------------
    # Configuration UI
    # ------------------------------------------------------------------

    def _plugin_config_tabs(self) -> QWidget:
        """Return a settings widget with all instrument and measurement controls.

        Returns a :class:`~PyQt6.QtWidgets.QWidget` with four group boxes:

        * **Connection** — connection mode selector and VISA resource fields.
          The mode combo and resource selectors are disabled while the plugin
          is connected (i.e. while :attr:`status` is not
          :attr:`~TraceStatus.IDLE` or :attr:`~TraceStatus.ERROR`) to prevent
          inconsistent runtime state.
        * **Source** — compliance mode and value, source delay, and current
          range drop-down (with SI-formatted range labels).
        * **Measurement** — NPLC combo (0.1 / 1.0 / 10.0 PLC), voltage range
          drop-down, display digits, digital filter, analogue filter, and
          relative mode controls.
        * **Trigger link** — output and input trigger-link line selectors.

        Returns:
            (QWidget):
                Configured settings widget for the *Settings* tab.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from qtpy.QtWidgets import QWidget
            >>> isinstance(Keithley6221_2182APlugin()._plugin_config_tabs(), QWidget)
            True
        """
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(4, 4, 4, 4)

        # ---- Connection group ----
        conn_group = QGroupBox("Connection")
        conn_form = QFormLayout(conn_group)

        mode_combo = QComboBox()
        mode_combo.addItem("Via 6221 serial port", ConnectionMode.VIA_6221_SERIAL)
        mode_combo.addItem("Direct GPIB", ConnectionMode.DIRECT_GPIB)
        mode_combo.setCurrentIndex(
            0 if self._connection_mode is ConnectionMode.VIA_6221_SERIAL else 1
        )

        res_6221 = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        res_6221.setCurrentText(self._6221_resource)

        res_2182a = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        res_2182a.setCurrentText(self._2182a_resource)
        res_2182a_label = QLabel("2182A GPIB resource:")
        res_2182a.setEnabled(self._connection_mode is ConnectionMode.DIRECT_GPIB)
        res_2182a_label.setEnabled(self._connection_mode is ConnectionMode.DIRECT_GPIB)

        _conn_widgets = (mode_combo, res_6221, res_2182a)

        def _update_conn_widgets_enabled() -> None:
            """Enable/disable connection controls based on connection status."""
            disconnected = self._status in (TraceStatus.IDLE, TraceStatus.ERROR)
            for w in _conn_widgets:
                w.setEnabled(disconnected)
            # The 2182A resource selector has the extra DIRECT_GPIB constraint.
            if disconnected:
                direct = self._connection_mode is ConnectionMode.DIRECT_GPIB
                res_2182a.setEnabled(direct)
                res_2182a_label.setEnabled(direct)

        # Keep connection controls in sync with status changes.
        self.status_changed.connect(lambda _: _update_conn_widgets_enabled())
        # Apply initial state.
        _update_conn_widgets_enabled()

        def _on_mode_changed(index: int) -> None:
            mode = mode_combo.itemData(index)
            self._connection_mode = mode
            direct = mode is ConnectionMode.DIRECT_GPIB
            res_2182a.setEnabled(direct)
            res_2182a_label.setEnabled(direct)

        def _on_6221_resource_changed(text: str) -> None:
            self._6221_resource = text.strip()

        def _on_2182a_resource_changed(text: str) -> None:
            self._2182a_resource = text.strip()

        mode_combo.currentIndexChanged.connect(_on_mode_changed)
        res_6221.currentTextChanged.connect(_on_6221_resource_changed)
        res_2182a.currentTextChanged.connect(_on_2182a_resource_changed)

        conn_form.addRow("Connection mode:", mode_combo)
        conn_form.addRow("6221 GPIB resource:", res_6221)
        conn_form.addRow(res_2182a_label, res_2182a)
        root_layout.addWidget(conn_group)

        # ---- Source group ----
        src_group = QGroupBox("Source (6221)")
        src_form = QFormLayout(src_group)

        # -- compliance mode selector --
        comp_mode_combo = QComboBox()
        comp_mode_combo.addItem("Fixed voltage", ComplianceMode.VOLTAGE)
        comp_mode_combo.addItem("Resistance (V = |I|×R)", ComplianceMode.RESISTANCE)
        comp_mode_combo.setCurrentIndex(0 if self._compliance_mode is ComplianceMode.VOLTAGE else 1)
        comp_mode_combo.setObjectName("compliance_mode")
        comp_mode_combo.setToolTip(
            "Voltage: a fixed compliance voltage is applied to every sweep point.\n"
            "Resistance: per-point compliance is |current| × compliance resistance."
        )

        is_voltage_compliance = self._compliance_mode is ComplianceMode.VOLTAGE
        compliance_level_label = QLabel("Level (V):" if is_voltage_compliance else "Level (Ω):")
        compliance_level_label.setObjectName("compliance_level_label")
        compliance_level_sb = SISpinBox(
            suffix="V" if is_voltage_compliance else "Ω",
            value=self._compliance if is_voltage_compliance else self._compliance_resistance,
        )
        compliance_level_sb.setObjectName("compliance_level")
        compliance_level_sb.setMinimum(0.1)
        compliance_level_sb.setMaximum(105.0 if is_voltage_compliance else 1e9)

        compliance_group = QGroupBox("Compliance")
        compliance_group.setObjectName("compliance_group")
        compliance_layout = QHBoxLayout(compliance_group)
        compliance_layout.addWidget(QLabel("Mode:"))
        compliance_layout.addWidget(comp_mode_combo)
        compliance_layout.addWidget(compliance_level_label)
        compliance_layout.addWidget(compliance_level_sb)

        def _on_comp_mode_changed(index: int) -> None:
            mode = comp_mode_combo.itemData(index)
            self._compliance_mode = mode
            is_voltage = mode is ComplianceMode.VOLTAGE
            compliance_level_sb.blockSignals(True)
            compliance_level_label.setText("Level (V):" if is_voltage else "Level (Ω):")
            compliance_level_sb.setSuffix("V" if is_voltage else "Ω")
            compliance_level_sb.setMaximum(105.0 if is_voltage else 1e9)
            compliance_level_sb.setValue(
                self._compliance if is_voltage else self._compliance_resistance
            )
            compliance_level_sb.blockSignals(False)

        comp_mode_combo.currentIndexChanged.connect(_on_comp_mode_changed)

        delay_sb = SISpinBox(suffix="s", value=self._source_delay)
        delay_sb.setMinimum(1e-3)
        delay_sb.setMaximum(9999.0)
        delay_sb.setToolTip("Settling delay after each source step before triggering the 2182A.")

        # -- source range combo: stores (SourceRangeMode, float) tuples --
        src_range_combo = SIComboBox(unit="A")
        src_range_combo.addItem("Best (auto, set once)", (SourceRangeMode.BEST, 0.0))
        src_range_combo.addItem("Auto (per-point)", (SourceRangeMode.AUTO, 0.0))
        for rng in _6221_FIXED_RANGES:
            src_range_combo.addItem(SIComboBox.format_si(rng, "A"), (SourceRangeMode.FIXED, rng))
        # Set the current selection: use math.isclose so that JSON round-trips
        # and minor floating-point differences don't prevent the correct item
        # from being re-selected.  _ZERO_CURRENT_THRESHOLD is reserved for
        # zero-current detection in the derived resistance calculation.
        _cur_src_idx = 0
        for _i in range(src_range_combo.count()):
            _mode, _val = src_range_combo.itemData(_i)
            if _mode is self._source_range_mode:
                if _mode is SourceRangeMode.FIXED:
                    if math.isclose(_val, self._source_range, rel_tol=1e-9, abs_tol=1e-30):
                        _cur_src_idx = _i
                        break
                else:
                    _cur_src_idx = _i
                    break
        src_range_combo.setCurrentIndex(_cur_src_idx)
        src_range_combo.setToolTip(
            "Current output range for the 6221.\n"
            "Best: the instrument picks the best fixed range for the whole sweep.\n"
            "Auto: range is re-evaluated at each point.\n"
            "Fixed: a specific range is held for the entire sweep."
        )

        differential_enabled = QCheckBox("Enable alternating delta-current mode")
        differential_enabled.setObjectName("differential_mode")
        differential_enabled.setChecked(self._differential_mode)
        differential_conductance = QCheckBox(
            "Report differential conductance (otherwise differential resistance)"
        )
        differential_conductance.setObjectName("differential_conductance")
        differential_conductance.setChecked(self._differential_conductance)
        differential_conductance.setEnabled(self._differential_mode)
        delta_current = SISpinBox(suffix="A", value=self._delta_current)
        delta_current.setObjectName("delta_current")
        delta_current.setMinimum(1e-15)
        delta_current.setMaximum(0.1)
        delta_current.setEnabled(self._differential_mode)

        def _on_differential_mode_toggled(enabled: bool) -> None:
            self._differential_mode = enabled
            differential_conductance.setEnabled(enabled)
            delta_current.setEnabled(enabled)

        def _on_compliance_level_changed(value: float) -> None:
            if self._compliance_mode is ComplianceMode.VOLTAGE:
                self._compliance = value
            else:
                self._compliance_resistance = value

        def _on_delay_changed(value: float) -> None:
            self._source_delay = value

        def _on_src_range_changed(index: int) -> None:
            mode, val = src_range_combo.itemData(index)
            self._source_range_mode = mode
            if mode is SourceRangeMode.FIXED:
                self._source_range = val

        compliance_level_sb.valueChanged.connect(_on_compliance_level_changed)
        delay_sb.valueChanged.connect(_on_delay_changed)
        src_range_combo.currentIndexChanged.connect(_on_src_range_changed)
        differential_enabled.toggled.connect(_on_differential_mode_toggled)
        differential_conductance.toggled.connect(
            lambda enabled: setattr(self, "_differential_conductance", enabled)
        )
        delta_current.valueChanged.connect(lambda value: setattr(self, "_delta_current", value))

        src_form.addRow(compliance_group)
        src_form.addRow("Source delay:", delay_sb)
        src_form.addRow("Source range:", src_range_combo)
        src_form.addRow("Differential mode:", differential_enabled)
        src_form.addRow("Delta current:", delta_current)
        src_form.addRow("Differential result:", differential_conductance)
        root_layout.addWidget(src_group)

        # ---- Measurement group ----
        meas_group = QGroupBox("Measurement (2182A)")
        meas_form = QFormLayout(meas_group)

        # -- NPLC combo (2182A only supports 0.1, 1.0, 10.0) --
        nplc_combo = QComboBox()
        for _nplc_val in _2182A_NPLC_OPTIONS:
            nplc_combo.addItem(f"{_nplc_val:g} PLC", _nplc_val)
        _nplc_idx = 0
        for _i, _nv in enumerate(_2182A_NPLC_OPTIONS):
            # NPLC options are 0.1 / 1.0 / 10.0 — 1e-9 absolute tolerance is
            # more than sufficient to match any of these after JSON round-trip.
            if abs(_nv - self._nplc) < 1e-9:
                _nplc_idx = _i
                break
        nplc_combo.setCurrentIndex(_nplc_idx)
        nplc_combo.setToolTip(
            "Integration time in power-line cycles.\nThe 2182A supports 0.1, 1.0, and 10.0 PLC."
        )

        # -- voltage range combo: uses SIComboBox so labels are auto-formatted --
        vrange_combo = SIComboBox(unit="V")
        vrange_combo.addSpecialItem("Auto", 0.0)
        for _vr in _2182A_FIXED_RANGES:
            vrange_combo.addValueItem(_vr)
        vrange_combo.setFloatValue(self._voltage_range)
        vrange_combo.setToolTip("Voltage measurement range for the 2182A.")

        # -- digits combo --
        digits_combo = QComboBox()
        for _d in _2182A_DIGITS_OPTIONS:
            digits_combo.addItem(f"{_d}.5 digits", _d)
        _digits_idx = 0
        for _i, _d in enumerate(_2182A_DIGITS_OPTIONS):
            if _d == self._digits:
                _digits_idx = _i
                break
        digits_combo.setCurrentIndex(_digits_idx)
        digits_combo.setToolTip("Number of display and data digits for the 2182A.")

        trigger_delay_sb = SISpinBox(suffix="s", value=self._trigger_delay)
        trigger_delay_sb.setObjectName("trigger_delay")
        trigger_delay_sb.setMinimum(0.0)
        trigger_delay_sb.setMaximum(999999.999)
        trigger_delay_sb.setToolTip(
            "Delay between the external trigger and the start of the 2182A measurement."
        )
        timing_row = QWidget()
        timing_row.setObjectName("timing_row")
        timing_layout = QHBoxLayout(timing_row)
        timing_layout.setContentsMargins(0, 0, 0, 0)
        timing_layout.addWidget(QLabel("NPLC:"))
        timing_layout.addWidget(nplc_combo)
        timing_layout.addWidget(QLabel("Trigger delay:"))
        timing_layout.addWidget(trigger_delay_sb)

        input_row = QWidget()
        input_row.setObjectName("input_row")
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(QLabel("Range:"))
        input_layout.addWidget(vrange_combo)
        input_layout.addWidget(QLabel("Digits:"))
        input_layout.addWidget(digits_combo)

        autozero_chk = QCheckBox("Autozero")
        autozero_chk.setObjectName("autozero")
        autozero_chk.setChecked(self._autozero)
        autozero_chk.setToolTip(
            "Enable automatic zero-reference measurements for improved long-term accuracy."
        )

        line_sync_chk = QCheckBox("Line sync")
        line_sync_chk.setObjectName("line_sync")
        line_sync_chk.setChecked(self._line_sync)
        line_sync_chk.setToolTip(
            "Synchronize A/D conversions to the power line to reduce noise. "
            "The 2182A ignores this setting below 1 PLC."
        )
        zero_sync_row = QWidget()
        zero_sync_row.setObjectName("zero_sync_row")
        zero_sync_layout = QHBoxLayout(zero_sync_row)
        zero_sync_layout.setContentsMargins(0, 0, 0, 0)
        zero_sync_layout.addWidget(autozero_chk)
        zero_sync_layout.addWidget(line_sync_chk)

        # -- digital filter --
        filter_type_combo = QComboBox()
        filter_type_combo.setObjectName("digital_filter_type")
        filter_type_combo.addItem("Off", DigitalFilterType.OFF)
        filter_type_combo.addItem("Repeat", DigitalFilterType.REPEAT)
        filter_type_combo.addItem("Window", DigitalFilterType.WINDOW)
        filter_type_combo.setCurrentIndex(list(DigitalFilterType).index(self._filter_type))
        filter_type_combo.setToolTip(
            "Repeat performs the configured number of new conversions; Window uses the moving-window filter."
        )

        filter_count_sb = QSpinBox()
        filter_count_sb.setMinimum(1)
        filter_count_sb.setMaximum(100)
        filter_count_sb.setValue(self._filter_count)
        filter_count_sb.setEnabled(self._filter_type is not DigitalFilterType.OFF)
        filter_count_sb.setToolTip(
            "Number of readings averaged per sample when the digital filter is enabled."
        )
        filter_row = QWidget()
        filter_row.setObjectName("filter_row")
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.addWidget(filter_type_combo)
        filter_layout.addWidget(QLabel("Count:"))
        filter_layout.addWidget(filter_count_sb)

        # -- analogue filter and relative mode --
        analog_filter_chk = QCheckBox()
        analog_filter_chk.setChecked(self._analog_filter)
        analog_filter_chk.setToolTip("Enable the 2182A low-pass analogue filter.")

        relative_chk = QCheckBox("Enabled")
        relative_chk.setChecked(self._relative_enabled)
        relative_chk.setToolTip(
            "Enable 2182A relative (REL) mode — subtracts a reference reading from each measurement."
        )

        relative_value_sb = SISpinBox(suffix="V", value=self._relative_value)
        relative_value_sb.setObjectName("relative_value")
        relative_value_sb.setMinimum(-120.0)
        relative_value_sb.setMaximum(120.0)
        relative_value_sb.setEnabled(self._relative_enabled)
        relative_value_sb.setToolTip(
            "Voltage reference subtracted from each channel-one measurement in REL mode."
        )
        relative_row = QWidget()
        relative_row.setObjectName("relative_row")
        relative_layout = QHBoxLayout(relative_row)
        relative_layout.setContentsMargins(0, 0, 0, 0)
        relative_layout.addWidget(relative_chk)
        relative_layout.addWidget(QLabel("Level:"))
        relative_layout.addWidget(relative_value_sb)

        def _on_nplc_changed(index: int) -> None:
            self._nplc = nplc_combo.itemData(index)

        def _on_vrange_changed(value: float) -> None:
            self._voltage_range = value

        def _on_digits_changed(index: int) -> None:
            self._digits = digits_combo.itemData(index)

        def _on_filter_type_changed(index: int) -> None:
            self._filter_type = filter_type_combo.itemData(index)
            filter_count_sb.setEnabled(self._filter_type is not DigitalFilterType.OFF)

        def _on_filter_count_changed(value: int) -> None:
            self._filter_count = value

        def _on_analog_filter_toggled(state: bool) -> None:
            self._analog_filter = state

        def _on_relative_toggled(state: bool) -> None:
            self._relative_enabled = state
            relative_value_sb.setEnabled(state)

        nplc_combo.currentIndexChanged.connect(_on_nplc_changed)
        vrange_combo.valueChanged.connect(_on_vrange_changed)
        digits_combo.currentIndexChanged.connect(_on_digits_changed)
        trigger_delay_sb.valueChanged.connect(lambda value: setattr(self, "_trigger_delay", value))
        autozero_chk.toggled.connect(lambda state: setattr(self, "_autozero", state))
        line_sync_chk.toggled.connect(lambda state: setattr(self, "_line_sync", state))
        filter_type_combo.currentIndexChanged.connect(_on_filter_type_changed)
        filter_count_sb.valueChanged.connect(_on_filter_count_changed)
        analog_filter_chk.toggled.connect(_on_analog_filter_toggled)
        relative_chk.toggled.connect(_on_relative_toggled)
        relative_value_sb.valueChanged.connect(
            lambda value: setattr(self, "_relative_value", value)
        )

        meas_form.addRow("Timing:", timing_row)
        meas_form.addRow("Input:", input_row)
        meas_form.addRow("Accuracy:", zero_sync_row)
        meas_form.addRow("Digital filter:", filter_row)
        meas_form.addRow("Analogue filter:", analog_filter_chk)
        meas_form.addRow("Relative mode:", relative_row)
        root_layout.addWidget(meas_group)

        # ---- Trigger link group ----
        trig_group = QGroupBox("Trigger link")
        trig_form = QFormLayout(trig_group)

        out_line_sb = QSpinBox()
        out_line_sb.setMinimum(1)
        out_line_sb.setMaximum(6)
        out_line_sb.setValue(self._output_tlink)
        out_line_sb.setToolTip(
            "Trigger-link line on which the 6221 outputs the 'source ready' "
            "pulse to start a 2182A measurement."
        )

        in_line_sb = QSpinBox()
        in_line_sb.setMinimum(1)
        in_line_sb.setMaximum(6)
        in_line_sb.setValue(self._input_tlink)
        in_line_sb.setToolTip(
            "Trigger-link line on which the 6221 accepts the 'meter complete' "
            "pulse from the 2182A to advance to the next source point."
        )

        def _on_out_line_changed(value: int) -> None:
            self._output_tlink = value

        def _on_in_line_changed(value: int) -> None:
            self._input_tlink = value

        out_line_sb.valueChanged.connect(_on_out_line_changed)
        in_line_sb.valueChanged.connect(_on_in_line_changed)

        trigger_lines_row = QWidget()
        trigger_lines_row.setObjectName("trigger_lines_row")
        trigger_lines_layout = QHBoxLayout(trigger_lines_row)
        trigger_lines_layout.setContentsMargins(0, 0, 0, 0)
        trigger_lines_layout.addWidget(QLabel("6221 → 2182A:"))
        trigger_lines_layout.addWidget(out_line_sb)
        trigger_lines_layout.addWidget(QLabel("2182A → 6221:"))
        trigger_lines_layout.addWidget(in_line_sb)
        trig_form.addRow("Lines:", trigger_lines_row)
        root_layout.addWidget(trig_group)

        root_layout.addStretch()

        pages = QTabWidget()
        pages.setObjectName("nanovoltmeter_settings_pages")
        secondary_page = self._secondary_config_page()
        for signal in (
            nplc_combo.currentIndexChanged,
            delay_sb.valueChanged,
            trigger_delay_sb.valueChanged,
            filter_type_combo.currentIndexChanged,
            filter_count_sb.valueChanged,
            analog_filter_chk.toggled,
        ):
            signal.connect(lambda _: self._update_secondary_timing_warning(secondary_page))
        pages.addTab(root, "Primary 6221 / 2182A")
        pages.addTab(secondary_page, "Secondary nanovoltmeter")
        return pages

    def _secondary_config_page(self) -> QWidget:
        """Build the optional secondary-nanovoltmeter settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)

        enabled = QCheckBox("Use a second nanovoltmeter")
        enabled.setObjectName("secondary_enabled")
        enabled.setChecked(self._secondary_enabled)
        enabled.setToolTip(
            "Acquire a second buffered voltage trace. The meter must be connected "
            "directly by GPIB and wired for the selected trigger-link routing."
        )
        layout.addWidget(enabled)

        controls = QGroupBox("Secondary nanovoltmeter")
        controls.setObjectName("secondary_controls")
        controls.setEnabled(self._secondary_enabled)
        form = QFormLayout(controls)

        driver_combo = QComboBox()
        driver_combo.setObjectName("secondary_driver")
        for driver_id, label in _NANOVOLTMETER_DRIVER_LABELS.items():
            driver_combo.addItem(label, driver_id)
        driver_combo.setCurrentIndex(driver_combo.findData(self._secondary_driver))

        resource = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        resource.setObjectName("secondary_resource")
        resource.setCurrentText(self._secondary_resource)

        prefix = QLineEdit(self._secondary_prefix)
        prefix.setObjectName("secondary_prefix")
        prefix.setToolTip("Prefix applied to the secondary V, R, and P trace columns.")

        trigger_mode = QComboBox()
        trigger_mode.setObjectName("secondary_trigger_mode")
        trigger_mode.addItem(
            "Parallel: 6221 triggers both; primary completes",
            SecondaryTriggerMode.PARALLEL,
        )
        trigger_mode.addItem(
            "Daisy-chain: 6221 → primary → secondary → 6221",
            SecondaryTriggerMode.DAISY_CHAIN,
        )
        trigger_mode.setCurrentIndex(trigger_mode.findData(self._secondary_trigger_mode))
        trigger_mode.setToolTip(
            "Both meters use external trigger input. This selection records the physical "
            "wiring and adjusts timing estimation; it does not change meter trigger commands."
        )

        connection_row = QWidget()
        connection_layout = QHBoxLayout(connection_row)
        connection_layout.setContentsMargins(0, 0, 0, 0)
        connection_layout.addWidget(QLabel("Driver:"))
        connection_layout.addWidget(driver_combo)
        connection_layout.addWidget(QLabel("GPIB resource:"))
        connection_layout.addWidget(resource)
        form.addRow("Connection:", connection_row)
        form.addRow("Channel prefix:", prefix)
        form.addRow("Trigger wiring:", trigger_mode)

        timing_warning = QLabel()
        timing_warning.setObjectName("secondary_timing_warning")
        timing_warning.setWordWrap(True)
        timing_warning.setStyleSheet("color: #b05a00;")
        form.addRow(timing_warning)

        nplc = QComboBox()
        nplc.setObjectName("secondary_nplc")
        for value in _2182A_NPLC_OPTIONS:
            nplc.addItem(f"{value:g} PLC", value)
        nplc.setCurrentIndex(
            min(
                range(nplc.count()),
                key=lambda index: abs(nplc.itemData(index) - self._secondary_nplc),
            )
        )
        trigger_delay = SISpinBox(suffix="s", value=self._secondary_trigger_delay)
        trigger_delay.setObjectName("secondary_trigger_delay")
        trigger_delay.setMinimum(0.0)
        trigger_delay.setMaximum(999999.999)
        timing_row = QWidget()
        timing_layout = QHBoxLayout(timing_row)
        timing_layout.setContentsMargins(0, 0, 0, 0)
        timing_layout.addWidget(QLabel("NPLC:"))
        timing_layout.addWidget(nplc)
        timing_layout.addWidget(QLabel("Trigger delay:"))
        timing_layout.addWidget(trigger_delay)

        voltage_range = SIComboBox(unit="V")
        voltage_range.setObjectName("secondary_voltage_range")
        voltage_range.addSpecialItem("Auto", 0.0)
        for value in _2182A_FIXED_RANGES:
            voltage_range.addValueItem(value)
        voltage_range.setFloatValue(self._secondary_voltage_range)
        digits = QComboBox()
        digits.setObjectName("secondary_digits")
        for value in _2182A_DIGITS_OPTIONS:
            digits.addItem(f"{value}.5 digits", value)
        digits.setCurrentIndex(digits.findData(self._secondary_digits))
        input_row = QWidget()
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(QLabel("Range:"))
        input_layout.addWidget(voltage_range)
        input_layout.addWidget(QLabel("Digits:"))
        input_layout.addWidget(digits)

        autozero = QCheckBox("Autozero")
        autozero.setObjectName("secondary_autozero")
        autozero.setChecked(self._secondary_autozero)
        line_sync = QCheckBox("Line sync")
        line_sync.setObjectName("secondary_line_sync")
        line_sync.setChecked(self._secondary_line_sync)
        accuracy_row = QWidget()
        accuracy_layout = QHBoxLayout(accuracy_row)
        accuracy_layout.setContentsMargins(0, 0, 0, 0)
        accuracy_layout.addWidget(autozero)
        accuracy_layout.addWidget(line_sync)

        filter_type = QComboBox()
        filter_type.setObjectName("secondary_filter_type")
        for filter_mode in Keithley2182A.CAPABILITIES.filter_types:
            label = filter_mode.title()
            filter_type.addItem(label, filter_mode)
        filter_type.setCurrentIndex(filter_type.findData(self._secondary_filter_type))
        filter_count = QSpinBox()
        filter_count.setObjectName("secondary_filter_count")
        filter_count.setRange(1, 100)
        filter_count.setValue(self._secondary_filter_count)
        filter_count.setEnabled(self._secondary_filter_type != "OFF")
        filter_row = QWidget()
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.addWidget(filter_type)
        filter_count_label = QLabel("Count:")
        filter_layout.addWidget(filter_count_label)
        filter_layout.addWidget(filter_count)

        analog_filter = QCheckBox()
        analog_filter.setObjectName("secondary_analog_filter")
        analog_filter.setChecked(self._secondary_analog_filter)
        relative_enabled = QCheckBox("Enabled")
        relative_enabled.setObjectName("secondary_relative_enabled")
        relative_enabled.setChecked(self._secondary_relative_enabled)
        relative_value = SISpinBox(suffix="V", value=self._secondary_relative_value)
        relative_value.setObjectName("secondary_relative_value")
        relative_value.setMinimum(-120.0)
        relative_value.setMaximum(120.0)
        relative_value.setEnabled(self._secondary_relative_enabled)
        relative_row = QWidget()
        relative_layout = QHBoxLayout(relative_row)
        relative_layout.setContentsMargins(0, 0, 0, 0)
        relative_layout.addWidget(relative_enabled)
        relative_layout.addWidget(QLabel("Level:"))
        relative_layout.addWidget(relative_value)

        form.addRow("Timing:", timing_row)
        form.addRow("Input:", input_row)
        form.addRow("Accuracy:", accuracy_row)
        form.addRow("Digital filter:", filter_row)
        form.addRow("Analogue filter:", analog_filter)
        form.addRow("Relative mode:", relative_row)
        layout.addWidget(controls)
        layout.addStretch()

        def update_connection_controls() -> None:
            disconnected = self._status in (TraceStatus.IDLE, TraceStatus.ERROR)
            enabled.setEnabled(disconnected)
            driver_combo.setEnabled(disconnected)
            resource.setEnabled(disconnected)

        def toggle_secondary(state: bool) -> None:
            self._secondary_enabled = state
            controls.setEnabled(state)

        def apply_driver_options() -> None:
            """Expose only settings the selected nanovoltmeter can represent."""
            capabilities = _NANOVOLTMETER_DRIVERS[self._secondary_driver].CAPABILITIES
            nplc_options = capabilities.nplc_values
            range_options = capabilities.fixed_voltage_ranges
            digit_options = capabilities.digit_values
            filter_options = tuple((name.title(), name) for name in capabilities.filter_types)

            for combo in (nplc, voltage_range, digits, filter_type):
                combo.blockSignals(True)
            nplc.clear()
            for nplc_option in nplc_options:
                nplc.addItem(f"{nplc_option:g} PLC", nplc_option)
            if self._secondary_nplc not in nplc_options:
                self._secondary_nplc = capabilities.default_nplc or nplc_options[0]
            nplc.setCurrentIndex(nplc.findData(self._secondary_nplc))

            voltage_range.clear()
            voltage_range.addSpecialItem("Auto", 0.0)
            for range_option in range_options:
                voltage_range.addValueItem(range_option)
            if self._secondary_voltage_range not in (0.0, *range_options):
                self._secondary_voltage_range = 0.0
            voltage_range.setFloatValue(self._secondary_voltage_range)

            digits.clear()
            for digit_option in digit_options:
                digits.addItem(f"{digit_option}.5 digits", digit_option)
            if self._secondary_digits not in digit_options:
                self._secondary_digits = capabilities.default_digits or digit_options[-1]
            digits.setCurrentIndex(digits.findData(self._secondary_digits))

            filter_type.clear()
            for filter_label, filter_option in filter_options:
                filter_type.addItem(filter_label, filter_option)
            supported_filters = tuple(filter_option for _, filter_option in filter_options)
            if self._secondary_filter_type not in supported_filters:
                self._secondary_filter_type = (
                    capabilities.default_filter_type or supported_filters[0]
                )
            filter_type.setCurrentIndex(filter_type.findData(self._secondary_filter_type))
            for combo in (nplc, voltage_range, digits, filter_type):
                combo.blockSignals(False)

            autozero.setEnabled(capabilities.supports_autozero)
            line_sync.setEnabled(capabilities.supports_line_sync)
            filter_count_label.setEnabled(capabilities.supports_filter_count)
            filter_count.setEnabled(
                capabilities.supports_filter_count and self._secondary_filter_type != "OFF"
            )
            analog_filter.setEnabled(capabilities.supports_analog_filter)
            relative_enabled.setEnabled(capabilities.supports_relative)
            relative_value.setEnabled(
                capabilities.supports_relative and self._secondary_relative_enabled
            )
            if capabilities.relative_limits is not None:
                relative_value.setMinimum(capabilities.relative_limits[0])
                relative_value.setMaximum(capabilities.relative_limits[1])

        def set_driver(index: int) -> None:
            self._secondary_driver = driver_combo.itemData(index)
            apply_driver_options()

        def set_filter_type(index: int) -> None:
            self._secondary_filter_type = filter_type.itemData(index)
            capabilities = _NANOVOLTMETER_DRIVERS[self._secondary_driver].CAPABILITIES
            filter_count.setEnabled(
                capabilities.supports_filter_count and self._secondary_filter_type != "OFF"
            )

        def set_relative_enabled(state: bool) -> None:
            self._secondary_relative_enabled = state
            relative_value.setEnabled(state)

        enabled.toggled.connect(toggle_secondary)
        driver_combo.currentIndexChanged.connect(set_driver)
        resource.currentTextChanged.connect(
            lambda text: setattr(self, "_secondary_resource", text.strip())
        )
        prefix.textChanged.connect(lambda text: setattr(self, "_secondary_prefix", text.strip()))
        trigger_mode.currentIndexChanged.connect(
            lambda index: setattr(self, "_secondary_trigger_mode", trigger_mode.itemData(index))
        )
        nplc.currentIndexChanged.connect(
            lambda index: setattr(self, "_secondary_nplc", nplc.itemData(index))
        )
        trigger_delay.valueChanged.connect(
            lambda value: setattr(self, "_secondary_trigger_delay", value)
        )
        voltage_range.valueChanged.connect(
            lambda value: setattr(self, "_secondary_voltage_range", value)
        )
        digits.currentIndexChanged.connect(
            lambda index: setattr(self, "_secondary_digits", digits.itemData(index))
        )
        autozero.toggled.connect(lambda state: setattr(self, "_secondary_autozero", state))
        line_sync.toggled.connect(lambda state: setattr(self, "_secondary_line_sync", state))
        filter_type.currentIndexChanged.connect(set_filter_type)
        filter_count.valueChanged.connect(
            lambda value: setattr(self, "_secondary_filter_count", value)
        )
        analog_filter.toggled.connect(
            lambda state: setattr(self, "_secondary_analog_filter", state)
        )
        relative_enabled.toggled.connect(set_relative_enabled)
        relative_value.valueChanged.connect(
            lambda value: setattr(self, "_secondary_relative_value", value)
        )
        self.status_changed.connect(lambda _: update_connection_controls())
        for signal in (
            enabled.toggled,
            trigger_mode.currentIndexChanged,
            nplc.currentIndexChanged,
            trigger_delay.valueChanged,
            filter_type.currentIndexChanged,
            filter_count.valueChanged,
            analog_filter.toggled,
        ):
            signal.connect(lambda _: self._update_secondary_timing_warning(page))
        update_connection_controls()
        apply_driver_options()
        self._update_secondary_timing_warning(page)
        return page

    def _update_secondary_timing_warning(self, page: QWidget) -> None:
        """Refresh the parallel-trigger overrun warning on the settings page."""
        label = page.findChild(QLabel, "secondary_timing_warning")
        if label is None:
            return
        warning = self._parallel_overrun_warning()
        label.setText(warning or "")
        label.setVisible(warning is not None)

    def _about_html(self) -> str:
        """Return an HTML description of the plugin for the *About* tab.

        Returns:
            (str):
                HTML-formatted description string.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> "<h3>" in plugin._about_html()
            True
        """
        return (
            "<h3>Keithley 6221 / 2182A &mdash; Synchronised List Sweep</h3>"
            "<p>Drives a Keithley 6221 precision current source and Keithley 2182A "
            "nanovoltmeter in a synchronised list sweep using trigger-link "
            "handshaking.</p>"
            "<p>The complete current list is derived from the active scan generator "
            "and loaded into the 6221 as a custom (<code>LIST</code>) sweep.  After "
            "each source step and settling delay the 6221 asserts a trigger-link pulse "
            "that starts a 2182A voltage measurement.  On completion the 2182A asserts "
            "its meter-complete output which advances the 6221 to the next current "
            "point.  All readings accumulate in the 2182A trace buffer and are "
            "retrieved as a block at the end of the sweep.</p>"
            "<h4>Optional secondary nanovoltmeter</h4>"
            "<p>A directly connected Keithley 2182A or legacy Keithley 182 can "
            "acquire the same sweep. "
            "Both meters use external triggering. In <b>parallel</b> wiring the 6221 "
            "triggers both meters and the primary meter advances the 6221. In "
            "<b>daisy-chain</b> wiring the trigger path is 6221 &rarr; primary meter "
            "&rarr; secondary meter &rarr; 6221. Daisy-chain timing includes both "
            "conversions; parallel configuration warns when the secondary conversion "
            "may overrun the next trigger.</p>"
            "<h4>Connection modes</h4>"
            "<dl>"
            "<dt><code>Via 6221 serial port</code></dt>"
            "<dd>Commands to the 2182A are relayed through the 6221 using "
            "<code>SYST:COMM:SER:SEND</code> and <code>SYST:COMM:SER:ENT?</code>.  "
            "Only one GPIB connection (to the 6221) is required.</dd>"
            "<dt><code>Direct GPIB</code></dt>"
            "<dd>The 2182A has its own GPIB address and is addressed independently. "
            "Both instruments need a VISA resource string.</dd>"
            "</dl>"
            "<h4>Trigger-link wiring</h4>"
            "<p>Connect the trigger-link cable between the 6221 and 2182A.  Configure "
            "the <b>Output line</b> (6221 &rarr; 2182A) and <b>Input line</b> "
            "(2182A &rarr; 6221) to match the physical wiring on the <b>Trigger link</b> "
            "panel.</p>"
        )
