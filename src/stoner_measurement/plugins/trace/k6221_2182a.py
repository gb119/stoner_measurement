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
from collections.abc import Generator
from typing import Any

import numpy as np
import pandas as pd
import pyvisa
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.keithley.k2182 import Keithley2182A
from stoner_measurement.instruments.keithley.k6221 import Keithley6221
from stoner_measurement.instruments.transport.gpib_transport import GpibTransport
from stoner_measurement.plugins.trace.base import (
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
    TracePlugin,
    TraceStatus,
)
from stoner_measurement.scan import FunctionScanGenerator, ListScanGenerator, SteppedScanGenerator
from stoner_measurement.ui.widgets import FILTER_GPIB, SIComboBox, SISpinBox, VisaResourceComboBox

#: Poll interval in seconds when waiting for the 2182A buffer to fill.
_POLL_INTERVAL: float = 0.25

#: Safety factor applied to the theoretical sweep duration when computing timeout.
_TIMEOUT_FACTOR: float = 5.0

#: Minimum timeout in seconds regardless of sweep duration.
_TIMEOUT_MIN: float = 10.0

#: Available fixed current output ranges for the 6221 (amps).
_6221_FIXED_RANGES: tuple[float, ...] = (
    1e-10, 1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1,
)

#: Available fixed voltage measurement ranges for the 2182A (volts).
_2182A_FIXED_RANGES: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0, 100.0, 120.0)

#: Supported NPLC settings for the 2182A.
_2182A_NPLC_OPTIONS: tuple[float, ...] = (0.1, 1.0, 10.0)

#: Supported display/data digits for the 2182A (number of digits integer, e.g. 4 → 4.5 digits).
_2182A_DIGITS_OPTIONS: tuple[int, ...] = (4, 5, 6, 7)

#: Currents whose absolute value is below this threshold (in amps) are treated as
#: zero when computing R(t) = V/I.  The value is intentionally much smaller than
#: any realistic 6221 output (minimum non-zero range: 100 pA) so that it catches
#: only genuine zero-current points set by the scan generator.
_ZERO_CURRENT_THRESHOLD: float = 1e-30

#: Maximum compliance voltage supported by the 6221 (volts).
_6221_MAX_COMPLIANCE_V: float = 105.0

#: Terminator required by the 2182A when relaying commands via the 6221 serial port.
_2182A_SERIAL_TERMINATOR: str = "\r\n"

#: End-of-response terminator for 2182A serial relay responses.
_2182A_RESPONSE_TERMINATOR: str = "\n"

#: Maximum number of ``SYST:COMM:SER:ENT?`` chunks to read for one 2182A response.
_MAX_SERIAL_ENTRY_CHUNKS: int = 64

_CLEANUP_EXCEPTIONS: tuple[type[Exception], ...] = (
    OSError,
    RuntimeError,
    pyvisa.Error,
)


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


class Keithley6221_2182APlugin(TracePlugin):
    """Trace plugin for the Keithley 6221 / 2182A synchronised list sweep.

    The 6221 is programmed with the full current list derived from the active
    scan generator.  Trigger-link handshaking synchronises the source and
    measurement: after each source step and settling delay the 6221 asserts a
    trigger-link pulse that starts a 2182A measurement; on completion the 2182A
    asserts its meter-complete output which steps the 6221 to the next point.
    Voltage readings accumulate in the 2182A trace buffer; the complete dataset
    is retrieved and returned after the sweep finishes.

    The 2182A may be addressed directly over GPIB or through the 6221's built-in
    RS-232 serial relay interface.

    After acquisition, a single trace channel named ``"IV"`` is returned,
    backed by a :class:`~pandas.DataFrame` with:

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
        _filter_enabled (bool):
            Enable the 2182A digital (averaging) filter.
        _filter_count (int):
            Number of readings averaged by the 2182A digital filter.
        _analog_filter (bool):
            Enable the 2182A low-pass analogue filter.
        _relative_enabled (bool):
            Enable the 2182A relative (REL) subtraction mode.
        _digits (int):
            Number of display and data digits for the 2182A (4–7).
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
        >>> from PyQt6.QtWidgets import QApplication
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
        self.scan_generator = FunctionScanGenerator(parent=self)
        self.scan_generator.units = "A"

        # Connection settings
        self._6221_resource: str = "GPIB0::22::INSTR"
        self._2182a_resource: str = "GPIB0::7::INSTR"
        self._connection_mode: ConnectionMode = ConnectionMode.VIA_6221_SERIAL

        # Source settings
        self._compliance_mode: ComplianceMode = ComplianceMode.VOLTAGE
        self._compliance: float = 10.0
        self._compliance_resistance: float = 1000.0
        self._source_delay: float = 1e-3
        self._source_range_mode: SourceRangeMode = SourceRangeMode.BEST
        self._source_range: float = 1e-3

        # 2182A measurement settings
        self._nplc: float = 1.0
        self._voltage_range: float = 0.0
        self._filter_enabled: bool = False
        self._filter_count: int = 10
        self._analog_filter: bool = False
        self._relative_enabled: bool = False
        self._digits: int = 6

        # Trigger-link line assignments
        self._output_tlink: int = 1
        self._input_tlink: int = 2

        # Runtime state — populated in connect()
        self._k6221: Keithley6221 | None = None
        self._k2182a: Keithley2182A | None = None
        self._sweep_values: np.ndarray | None = None
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().name
            'k6221_dc_iv'
        """
        return "k6221_dc_iv"

    @property
    def trace_title(self) -> str:
        """Human-readable display title.

        Returns:
            (str):
                ``"6221/2182A I-V"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().trace_title
            '6221/2182A I-V'
        """
        return "6221/2182A I-V"

    @property
    def x_label(self) -> str:
        """Axis label for the source current.

        Returns:
            (str):
                ``"I"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().y_units
            'V'
        """
        return "V"

    @property
    def channel_names(self) -> list[str]:
        """Name of the single multicolumn measurement channel.

        Returns:
            (list[str]):
                ``["IV"]``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().channel_names
            ['IV']
        """
        return ["IV"]

    def measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Acquire the sweep and return a single multicolumn ``"IV"`` trace.

        Runs the hardware sweep via :meth:`execute` to collect all ``(I, V)``
        pairs, then builds a :class:`~stoner_measurement.plugins.trace.base.TraceData`
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> # plugin.connect(); plugin.configure()
            >>> # result = plugin.measure({})  # requires real hardware
        """
        self._set_status(TraceStatus.MEASURING)
        try:
            pairs = list(self.execute(parameters))
        finally:
            self._set_status(TraceStatus.DATA_AVAILABLE)

        if pairs:
            i_arr = np.array([i for i, _ in pairs], dtype=float)
            v_arr = np.array([v for _, v in pairs], dtype=float)
        else:
            i_arr = np.array([], dtype=float)
            v_arr = np.array([], dtype=float)

        with np.errstate(invalid="ignore", divide="ignore"):
            r_arr = np.where(
                np.abs(i_arr) > _ZERO_CURRENT_THRESHOLD,
                v_arr / i_arr,
                float("nan"),
            )
        p_arr = i_arr * v_arr

        df = pd.DataFrame(
            {"V": v_arr, "R": r_arr, "P": p_arr},
            index=pd.Index(i_arr, name="x"),
        )
        column_roles = {
            "V": COLUMN_ROLE_Y,
            "R": COLUMN_ROLE_Z,
            "P": COLUMN_ROLE_Z,
        }
        names = {
            "x": self.x_label,
            "V": "V",
            "R": "R",
            "P": "P",
        }
        units = {
            "x": self.x_units,
            "V": self.y_units,
            "R": "Ω",
            "P": "W",
        }
        self.data = {
            "IV": TraceData(df=df, column_roles=column_roles, names=names, units=units)
        }
        self._update_channel_statistics()
        return self.data

    # ------------------------------------------------------------------
    # 2182A command routing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serial_send_payload(cmd: str) -> str:
        """Return *cmd* with one 2182A serial terminator and escaped quotes.

        Args:
            cmd (str):
                SCPI command to send to the 2182A.

        Returns:
            (str):
                Command string with trailing CR/LF terminator and doubled
                embedded quotes for safe inclusion in a SCPI quoted string.
        """
        command = cmd.rstrip("\r\n")
        payload = f"{command}{_2182A_SERIAL_TERMINATOR}"
        return payload.replace('"', '""')

    def _read_serial_entry_chunk(self) -> str:
        """Read one raw chunk from ``SYST:COMM:SER:ENT?`` without stripping CR/LF.

        Returns:
            (str):
                One serial relay payload chunk returned by the 6221 for
                ``SYST:COMM:SER:ENT?``, preserving any CR/LF from the 2182A
                response while removing only the outer 6221 query terminator.
        """
        instrument = self._k6221
        if instrument is None:
            raise RuntimeError("Keithley 6221 is not connected.")
        protocol = instrument.protocol
        terminator = getattr(protocol, "terminator", b"\n")
        payload = protocol.format_query("SYST:COMM:SER:ENT?")
        instrument.transport.write(payload)
        instrument._log_comms_traffic("TX", payload)
        raw = instrument.transport.read_until(terminator)
        instrument._log_comms_traffic("RX", raw)
        if raw.endswith(terminator):
            raw = raw[: -len(terminator)]
        return raw.decode("utf-8", errors="replace")

    def _nvm_write(self, cmd: str) -> None:
        """Send *cmd* to the 2182A using the active connection mode.

        Args:
            cmd (str):
                SCPI command to send to the 2182A.
        """
        if self._connection_mode is ConnectionMode.VIA_6221_SERIAL:
            payload = self._serial_send_payload(cmd)
            self._k6221.write(f'SYST:COMM:SER:SEND "{payload}"')
        else:
            if self._k2182a is None:
                raise RuntimeError(
                    "DIRECT_GPIB mode selected but no 2182A connection is open. "
                    "Call connect() before sending commands to the 2182A."
                )
            self._k2182a.write(cmd)

    def _nvm_query(self, cmd: str) -> str:
        """Send *cmd* to the 2182A and return its response.

        Args:
            cmd (str):
                SCPI query command to send to the 2182A.

        Returns:
            (str):
                Query response string without trailing CR/LF terminator.

        Raises:
            RuntimeError:
                If DIRECT_GPIB mode is selected but no 2182A is connected, or
                if the serial relay path does not yield a line-terminated
                response (LF) within the configured chunk limit.
        """
        if self._connection_mode is ConnectionMode.VIA_6221_SERIAL:
            payload = self._serial_send_payload(cmd)
            self._k6221.write(f'SYST:COMM:SER:SEND "{payload}"')
            parts: list[str] = []
            for _ in range(_MAX_SERIAL_ENTRY_CHUNKS):
                chunk = self._read_serial_entry_chunk()
                parts.append(chunk)
                combined = "".join(parts)
                if combined.endswith(_2182A_RESPONSE_TERMINATOR):
                    return combined.rstrip("\r\n")
            raise RuntimeError(
                "Timed out reading 2182A serial relay response: "
                "no line terminator (LF) received."
            )
        if self._k2182a is None:
            raise RuntimeError(
                "DIRECT_GPIB mode selected but no 2182A connection is open. "
                "Call connect() before querying the 2182A."
            )
        return self._k2182a.query(cmd).strip()

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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> # plugin.connect()  # requires real hardware
        """
        self._set_status(TraceStatus.CONNECTING)
        transport_6221: GpibTransport | None = None
        transport_2182a: GpibTransport | None = None
        try:
            transport_6221 = GpibTransport.from_resource_string(self._6221_resource, timeout=10.0)
            transport_6221.open()
            self._k6221 = Keithley6221(transport_6221)
            idn = self._k6221.query("*IDN?")
            if "6221" not in idn:
                raise RuntimeError(f"Unexpected instrument at {self._6221_resource!r}: {idn!r}")

            if self._connection_mode is ConnectionMode.DIRECT_GPIB:
                transport_2182a = GpibTransport.from_resource_string(self._2182a_resource, timeout=10.0)
                transport_2182a.open()
                self._k2182a = Keithley2182A(transport_2182a)
                idn2 = self._k2182a.query("*IDN?")
                if "2182" not in idn2:
                    raise RuntimeError(
                        f"Unexpected instrument at {self._2182a_resource!r}: {idn2!r}"
                    )
        except Exception:
            # Clean up any partially-opened transports to avoid leaking VISA sessions.
            for transport in (transport_2182a, transport_6221):
                if transport is not None:
                    try:
                        transport.close()
                    except _CLEANUP_EXCEPTIONS:
                        pass
            self._k6221 = None
            self._k2182a = None
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

        Measurement settings (NPLC, voltage range, digital filter, analogue
        filter, relative mode, digits) are also applied to the 2182A.

        Raises:
            RuntimeError:
                If not connected (call :meth:`connect` first).
            ValueError:
                If the scan generator produces no points.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> # plugin.connect(); plugin.configure()  # requires real hardware
        """
        if self._k6221 is None:
            raise RuntimeError("Not connected — call connect() before configure().")

        self._set_status(TraceStatus.CONFIGURING)
        try:
            self._sweep_values = self.scan_generator.generate()
            n = len(self._sweep_values)
            if n == 0:
                raise ValueError("Scan generator produced no points.")

            # ---- 6221: reset and configure LIST sweep ----
            self._k6221.write("*RST")
            time.sleep(0.1)

            # Build current list — the driver's configure_custom_sweep handles
            # batching into 100-point chunks automatically.
            self._k6221.configure_custom_sweep(
                tuple(float(v) for v in self._sweep_values),
                delay=self._source_delay,
            )

            # ---- 6221: per-point compliance ----
            if self._compliance_mode is ComplianceMode.RESISTANCE:
                comp_values = [abs(float(v)) * self._compliance_resistance for v in self._sweep_values]
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
                self._k6221.write("SOUR:SWE:RANG AUTO")
            elif self._source_range_mode is SourceRangeMode.FIXED:
                self._k6221.write(f"SOUR:CURR:RANG {self._source_range:.6e}")
            else:
                self._k6221.write("SOUR:SWE:RANG BEST")
            self._k6221.write("SOUR:SWE:COUN 1")

            # ---- 6221: trigger-link ----
            # Output a trigger pulse after each source step and settling delay.
            self._k6221.write(f"TRIG:OLIN {self._output_tlink}")
            # Accept a trigger on the input line to advance to the next point.
            self._k6221.write(f"TRIG:ILIN {self._input_tlink}")
            self._k6221.write("TRIG:DIR ACC")

            # ---- 2182A: reset and configure ----
            self._nvm_write("*RST")
            time.sleep(0.2)

            self._nvm_write(f"DISP:DIGS {self._digits}")
            self._nvm_write(f"SENS:VOLT:NPLC {self._nplc:.4f}")
            if self._voltage_range > 0.0:
                self._nvm_write("SENS:VOLT:RANG:AUTO 0")
                self._nvm_write(f"SENS:VOLT:RANG {self._voltage_range:.6e}")
            else:
                self._nvm_write("SENS:VOLT:RANG:AUTO 1")

            if self._filter_enabled:
                self._nvm_write("SENS:VOLT:DFIL:STAT 1")
                self._nvm_write(f"SENS:VOLT:DFIL:COUN {self._filter_count}")
            else:
                self._nvm_write("SENS:VOLT:DFIL:STAT 0")

            self._nvm_write(f"SENS:VOLT:LPAS:STAT {1 if self._analog_filter else 0}")
            self._nvm_write(f"SENS:VOLT:REL:STAT {1 if self._relative_enabled else 0}")

            # ---- 2182A: trace buffer ----
            self._nvm_write("TRAC:CLE")
            self._nvm_write(f"TRAC:POIN {n}")
            self._nvm_write("TRAC:FEED SENS")
            self._nvm_write("TRAC:FEED:CONT NEXT")

            # ---- 2182A: trigger ----
            self._nvm_write("TRIG:SOUR EXT")
            self._nvm_write(f"TRIG:COUN {n}")

        except Exception:
            self._set_status(TraceStatus.ERROR)
            raise
        self._set_status(TraceStatus.IDLE)

    def execute(self, parameters: dict[str, Any]) -> Generator[tuple[float, float]]:
        """Arm the sweep, collect the complete trace, and yield (I, V) pairs.

        Arms the 6221 sweep, initiates the 2182A trigger system, and enables
        the 6221 output to start the sweep.  Polls the 2182A buffer until all
        *n* readings have been stored, then reads the buffer and yields the
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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> # plugin.connect(); plugin.configure()
            >>> # pts = list(plugin.execute({}))  # requires real hardware
        """
        if self._k6221 is None:
            raise RuntimeError("Not connected — call connect() before execute().")
        if self._sweep_values is None:
            raise RuntimeError("Not configured — call configure() before execute().")

        n = len(self._sweep_values)
        # Estimate a generous timeout: n points × (NPLC/50 + source_delay) × safety factor.
        # Assumes 50 Hz mains frequency; the timeout is conservative enough to also
        # cover 60 Hz installations without adjustment.
        line_period = 1.0 / 50.0
        point_time = self._nplc * line_period + self._source_delay
        timeout = max(_TIMEOUT_MIN, n * point_time * _TIMEOUT_FACTOR)

        try:
            # Arm 6221 sweep and initiate 2182A trigger system.
            self._k6221.write("SOUR:SWE:ARM")
            self._nvm_write("INIT")

            # Enable 6221 output — this starts the sweep.
            self._k6221.write("OUTP:STAT 1")

            # Poll until buffer is full.
            deadline = time.monotonic() + timeout
            while True:
                buf_count_str = self._nvm_query("TRAC:POIN:ACT?")
                try:
                    buf_count = int(float(buf_count_str))
                except ValueError:
                    buf_count = 0
                if buf_count >= n:
                    break
                if time.monotonic() > deadline:
                    self._k6221.write("SOUR:SWE:ABOR")
                    self._k6221.write("OUTP:STAT 0")
                    raise RuntimeError(
                        f"Timeout waiting for 2182A buffer to fill: "
                        f"got {buf_count} of {n} readings after {timeout:.1f} s."
                    )
                time.sleep(_POLL_INTERVAL)

            # Disable output and read buffer.
            self._k6221.write("OUTP:STAT 0")
            raw = self._nvm_query("TRAC:DATA?")
            voltages = self._parse_csv_floats(raw)
            if len(voltages) != n:
                raise RuntimeError(
                    f"2182A returned {len(voltages)} readings but expected {n}. "
                    "The trace buffer may be incomplete."
                )
        except Exception:
            # Attempt a clean abort on any failure.
            try:
                self._k6221.write("SOUR:SWE:ABOR")
                self._k6221.write("OUTP:STAT 0")
            except _CLEANUP_EXCEPTIONS:
                pass
            raise

        yield from zip(self._sweep_values, voltages)

    def disconnect(self) -> None:
        """Disable the 6221 output and close all instrument connections.

        Always attempts to disable the 6221 output before closing
        connections, even if a previous operation failed.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = Keithley6221_2182APlugin()
            >>> plugin.disconnect()
            >>> plugin.status is TraceStatus.IDLE
            True
        """
        self._set_status(TraceStatus.DISCONNECTING)
        for instr in (self._k6221, self._k2182a):
            if instr is not None:
                try:
                    if instr is self._k6221:
                        instr.write("OUTP:STAT 0")
                except _CLEANUP_EXCEPTIONS:
                    pass
                try:
                    instr.disconnect()
                except _CLEANUP_EXCEPTIONS:
                    pass
        self._k6221 = None
        self._k2182a = None
        self._sweep_values = None
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
            >>> from PyQt6.QtWidgets import QApplication
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
        data["nplc"] = self._nplc
        data["voltage_range"] = self._voltage_range
        data["filter_enabled"] = self._filter_enabled
        data["filter_count"] = self._filter_count
        data["analog_filter"] = self._analog_filter
        data["relative_enabled"] = self._relative_enabled
        data["digits"] = self._digits
        data["output_tlink"] = self._output_tlink
        data["input_tlink"] = self._input_tlink
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore plugin settings from *data*.

        Args:
            data (dict[str, Any]):
                Serialised plugin dict as produced by :meth:`to_json`.
        """
        _log = logging.getLogger(__name__)
        super()._restore_from_json(data)
        self._6221_resource = data.get("resource_6221", self._6221_resource)
        self._2182a_resource = data.get("resource_2182a", self._2182a_resource)
        mode_str = data.get("connection_mode", self._connection_mode.value)
        try:
            self._connection_mode = ConnectionMode(mode_str)
        except ValueError:
            _log.warning(
                "Unknown connection_mode value %r in saved config; "
                "falling back to default (%s).",
                mode_str,
                self._connection_mode.value,
            )
        comp_mode_str = data.get("compliance_mode", self._compliance_mode.value)
        try:
            self._compliance_mode = ComplianceMode(comp_mode_str)
        except ValueError:
            _log.warning(
                "Unknown compliance_mode value %r in saved config; "
                "falling back to default (%s).",
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
            _log.warning(
                "Unknown source_range_mode value %r in saved config; "
                "falling back to default (%s).",
                range_mode_str,
                self._source_range_mode.value,
            )
        self._source_range = float(data.get("source_range", self._source_range))
        self._nplc = float(data.get("nplc", self._nplc))
        self._voltage_range = float(data.get("voltage_range", self._voltage_range))
        self._filter_enabled = bool(data.get("filter_enabled", self._filter_enabled))
        self._filter_count = int(data.get("filter_count", self._filter_count))
        self._analog_filter = bool(data.get("analog_filter", self._analog_filter))
        self._relative_enabled = bool(data.get("relative_enabled", self._relative_enabled))
        self._digits = int(data.get("digits", self._digits))
        self._output_tlink = int(data.get("output_tlink", self._output_tlink))
        self._input_tlink = int(data.get("input_tlink", self._input_tlink))

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
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from PyQt6.QtWidgets import QWidget
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
        mode_combo.setCurrentIndex(0 if self._connection_mode is ConnectionMode.VIA_6221_SERIAL else 1)

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
        comp_mode_combo.setCurrentIndex(
            0 if self._compliance_mode is ComplianceMode.VOLTAGE else 1
        )
        comp_mode_combo.setToolTip(
            "Voltage: a fixed compliance voltage is applied to every sweep point.\n"
            "Resistance: per-point compliance is |current| × compliance resistance."
        )

        compliance_sb = SISpinBox(suffix="V", value=self._compliance)
        compliance_sb.setMinimum(0.1)
        compliance_sb.setMaximum(105.0)
        compliance_sb.setToolTip("Fixed compliance voltage limit for the 6221 current source.")
        compliance_sb.setVisible(self._compliance_mode is ComplianceMode.VOLTAGE)

        compliance_r_label = QLabel("Compliance resistance:")
        compliance_r_sb = SISpinBox(suffix="Ω", value=self._compliance_resistance)
        compliance_r_sb.setMinimum(0.1)
        compliance_r_sb.setMaximum(1e9)
        compliance_r_sb.setToolTip(
            "Compliance resistance in ohms.  Per-point compliance voltage = |I| × R."
        )
        compliance_r_sb.setVisible(self._compliance_mode is ComplianceMode.RESISTANCE)
        compliance_r_label.setVisible(self._compliance_mode is ComplianceMode.RESISTANCE)

        def _on_comp_mode_changed(index: int) -> None:
            mode = comp_mode_combo.itemData(index)
            self._compliance_mode = mode
            is_voltage = mode is ComplianceMode.VOLTAGE
            compliance_sb.setVisible(is_voltage)
            compliance_r_sb.setVisible(not is_voltage)
            compliance_r_label.setVisible(not is_voltage)

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
            src_range_combo.addItem(
                SIComboBox.format_si(rng, "A"), (SourceRangeMode.FIXED, rng)
            )
        # Set the current selection: use math.isclose so that JSON round-trips
        # and minor floating-point differences don't prevent the correct item
        # from being re-selected.  _ZERO_CURRENT_THRESHOLD is reserved for
        # zero-current detection in execute_multichannel().
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

        def _on_compliance_changed(value: float) -> None:
            self._compliance = value

        def _on_compliance_r_changed(value: float) -> None:
            self._compliance_resistance = value

        def _on_delay_changed(value: float) -> None:
            self._source_delay = value

        def _on_src_range_changed(index: int) -> None:
            mode, val = src_range_combo.itemData(index)
            self._source_range_mode = mode
            if mode is SourceRangeMode.FIXED:
                self._source_range = val

        compliance_sb.sigValueChanged.connect(_on_compliance_changed)
        compliance_r_sb.sigValueChanged.connect(_on_compliance_r_changed)
        delay_sb.sigValueChanged.connect(_on_delay_changed)
        src_range_combo.currentIndexChanged.connect(_on_src_range_changed)

        src_form.addRow("Compliance mode:", comp_mode_combo)
        src_form.addRow("Compliance voltage:", compliance_sb)
        src_form.addRow(compliance_r_label, compliance_r_sb)
        src_form.addRow("Source delay:", delay_sb)
        src_form.addRow("Source range:", src_range_combo)
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
            "Integration time in power-line cycles.\n"
            "The 2182A supports 0.1, 1.0, and 10.0 PLC."
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

        # -- digital filter --
        filter_chk = QCheckBox()
        filter_chk.setChecked(self._filter_enabled)
        filter_chk.setToolTip("Enable the 2182A digital averaging filter.")

        filter_count_sb = QSpinBox()
        filter_count_sb.setMinimum(1)
        filter_count_sb.setMaximum(100)
        filter_count_sb.setValue(self._filter_count)
        filter_count_sb.setEnabled(self._filter_enabled)
        filter_count_sb.setToolTip(
            "Number of readings averaged per sample when the digital filter is enabled."
        )

        # -- analogue filter and relative mode --
        analog_filter_chk = QCheckBox()
        analog_filter_chk.setChecked(self._analog_filter)
        analog_filter_chk.setToolTip("Enable the 2182A low-pass analogue filter.")

        relative_chk = QCheckBox()
        relative_chk.setChecked(self._relative_enabled)
        relative_chk.setToolTip(
            "Enable 2182A relative (REL) mode — subtracts a reference reading from each measurement."
        )

        def _on_nplc_changed(index: int) -> None:
            self._nplc = nplc_combo.itemData(index)

        def _on_vrange_changed(value: float) -> None:
            self._voltage_range = value

        def _on_digits_changed(index: int) -> None:
            self._digits = digits_combo.itemData(index)

        def _on_filter_toggled(state: bool) -> None:
            self._filter_enabled = state
            filter_count_sb.setEnabled(state)

        def _on_filter_count_changed(value: int) -> None:
            self._filter_count = value

        def _on_analog_filter_toggled(state: bool) -> None:
            self._analog_filter = state

        def _on_relative_toggled(state: bool) -> None:
            self._relative_enabled = state

        nplc_combo.currentIndexChanged.connect(_on_nplc_changed)
        vrange_combo.valueChanged.connect(_on_vrange_changed)
        digits_combo.currentIndexChanged.connect(_on_digits_changed)
        filter_chk.toggled.connect(_on_filter_toggled)
        filter_count_sb.valueChanged.connect(_on_filter_count_changed)
        analog_filter_chk.toggled.connect(_on_analog_filter_toggled)
        relative_chk.toggled.connect(_on_relative_toggled)

        meas_form.addRow("Integration time (NPLC):", nplc_combo)
        meas_form.addRow("Voltage range:", vrange_combo)
        meas_form.addRow("Display digits:", digits_combo)
        meas_form.addRow("Digital filter:", filter_chk)
        meas_form.addRow("Filter count:", filter_count_sb)
        meas_form.addRow("Analogue filter:", analog_filter_chk)
        meas_form.addRow("Relative mode:", relative_chk)
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

        trig_form.addRow("6221 output line (→ 2182A):", out_line_sb)
        trig_form.addRow("6221 input line (← 2182A):", in_line_sb)
        root_layout.addWidget(trig_group)

        root_layout.addStretch()
        return root

    def _about_html(self) -> str:
        """Return an HTML description of the plugin for the *About* tab.

        Returns:
            (str):
                HTML-formatted description string.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_csv_floats(values: str) -> tuple[float, ...]:
        """Parse a comma-separated numeric payload into a tuple of floats."""
        stripped = values.strip()
        if not stripped:
            return ()
        tokens = [t.strip() for t in stripped.split(",")]
        try:
            return tuple(float(t) for t in tokens if t)
        except ValueError as exc:
            raise ValueError(f"Malformed numeric response from 2182A: {values!r}") from exc
