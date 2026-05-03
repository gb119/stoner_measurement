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
import time
from collections.abc import Generator
from typing import Any

import numpy as np
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
from stoner_measurement.plugins.trace.base import TracePlugin, TraceStatus
from stoner_measurement.scan import ListScanGenerator, SteppedScanGenerator
from stoner_measurement.ui.widgets import FILTER_GPIB, SISpinBox, VisaResourceComboBox

#: Poll interval in seconds when waiting for the 2182A buffer to fill.
_POLL_INTERVAL: float = 0.25

#: Safety factor applied to the theoretical sweep duration when computing timeout.
_TIMEOUT_FACTOR: float = 5.0

#: Minimum timeout in seconds regardless of sweep duration.
_TIMEOUT_MIN: float = 10.0


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
        _compliance (float):
            Source compliance voltage in volts.
        _source_delay (float):
            Source settling delay between output change and trigger to
            2182A, in seconds.
        _source_range (float):
            Fixed current range in amps for the 6221 output.  Set to
            ``0.0`` to use ``BEST`` (automatic) ranging.
        _nplc (float):
            2182A integration time in power-line cycles.
        _voltage_range (float):
            Fixed voltage range in volts for the 2182A.  Set to ``0.0``
            for autorange.
        _filter_enabled (bool):
            Enable the 2182A digital filter.
        _filter_count (int):
            Number of readings averaged by the 2182A digital filter.
        _output_tlink (int):
            Trigger-link line number (1 or 2) on which the 6221 outputs the
            "source ready" trigger pulse to the 2182A.
        _input_tlink (int):
            Trigger-link line number (1 or 2) on which the 6221 accepts the
            "meter complete" trigger pulse from the 2182A.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> plugin = Keithley6221_2182APlugin()
        >>> plugin.name
        'Keithley6221_2182A'
        >>> plugin.x_units
        'A'
        >>> plugin.y_units
        'V'
    """

    _scan_generator_class = SteppedScanGenerator
    _scan_generator_classes = [SteppedScanGenerator, ListScanGenerator]

    def __init__(self, parent=None) -> None:
        """Initialise the plugin with default instrument and measurement settings."""
        super().__init__(parent)
        self.scan_generator = SteppedScanGenerator(parent=self)
        self.scan_generator.units = "A"

        # Connection settings
        self._6221_resource: str = "GPIB0::22::INSTR"
        self._2182a_resource: str = "GPIB0::7::INSTR"
        self._connection_mode: ConnectionMode = ConnectionMode.VIA_6221_SERIAL

        # Source settings
        self._compliance: float = 10.0
        self._source_delay: float = 1e-3
        self._source_range: float = 0.0

        # 2182A measurement settings
        self._nplc: float = 1.0
        self._voltage_range: float = 0.0
        self._filter_enabled: bool = False
        self._filter_count: int = 10

        # Trigger-link line assignments
        self._output_tlink: int = 1
        self._input_tlink: int = 2

        # Runtime state — populated in connect()
        self._k6221: Keithley6221 | None = None
        self._k2182a: Keithley2182A | None = None
        self._sweep_values: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Plugin identity
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Unique identifier for the Keithley 6221 / 2182A plugin.

        Returns:
            (str):
                ``"Keithley6221_2182A"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> Keithley6221_2182APlugin().name
            'Keithley6221_2182A'
        """
        return "Keithley6221_2182A"

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

    # ------------------------------------------------------------------
    # 2182A command routing helpers
    # ------------------------------------------------------------------

    def _nvm_write(self, cmd: str) -> None:
        """Send *cmd* to the 2182A using the active connection mode."""
        if self._connection_mode is ConnectionMode.VIA_6221_SERIAL:
            self._k6221.write(f'SYST:COMM:SER:SEND "{cmd}"')
        else:
            self._k2182a.write(cmd)

    def _nvm_query(self, cmd: str) -> str:
        """Send *cmd* to the 2182A and return its response."""
        if self._connection_mode is ConnectionMode.VIA_6221_SERIAL:
            self._k6221.write(f'SYST:COMM:SER:SEND "{cmd}"')
            return self._k6221.query("SYST:COMM:SER:ENT?").strip()
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

        Measurement settings (NPLC, voltage range, digital filter) are
        also applied to the 2182A.

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

            csv_vals = ",".join(f"{v:.6e}" for v in self._sweep_values)
            self._k6221.write("SOUR:SWE:SPAC LIST")
            self._k6221.write(f"SOUR:LIST:CURR {csv_vals}")
            self._k6221.write(f"SOUR:SWE:POIN {n}")
            self._k6221.write(f"SOUR:DEL {self._source_delay:.6e}")
            self._k6221.write(f"SOUR:CURR:COMP {self._compliance:.6e}")
            if self._source_range > 0.0:
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
        # Estimate a generous timeout: n points × (NPLC/50 + source_delay) × safety factor
        line_period = 1.0 / 50.0  # assume 50 Hz mains
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
        except Exception:
            # Attempt a clean abort on any failure.
            try:
                self._k6221.write("SOUR:SWE:ABOR")
                self._k6221.write("OUTP:STAT 0")
            except Exception:
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
                except Exception:
                    pass
                try:
                    instr.disconnect()
                except Exception:
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
        data["compliance"] = self._compliance
        data["source_delay"] = self._source_delay
        data["source_range"] = self._source_range
        data["nplc"] = self._nplc
        data["voltage_range"] = self._voltage_range
        data["filter_enabled"] = self._filter_enabled
        data["filter_count"] = self._filter_count
        data["output_tlink"] = self._output_tlink
        data["input_tlink"] = self._input_tlink
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
        self._connection_mode = ConnectionMode(mode_str)
        self._compliance = float(data.get("compliance", self._compliance))
        self._source_delay = float(data.get("source_delay", self._source_delay))
        self._source_range = float(data.get("source_range", self._source_range))
        self._nplc = float(data.get("nplc", self._nplc))
        self._voltage_range = float(data.get("voltage_range", self._voltage_range))
        self._filter_enabled = bool(data.get("filter_enabled", self._filter_enabled))
        self._filter_count = int(data.get("filter_count", self._filter_count))
        self._output_tlink = int(data.get("output_tlink", self._output_tlink))
        self._input_tlink = int(data.get("input_tlink", self._input_tlink))

    # ------------------------------------------------------------------
    # Configuration UI
    # ------------------------------------------------------------------

    def _plugin_config_tabs(self) -> QWidget:
        """Return a settings widget with all instrument and measurement controls.

        Returns a :class:`~PyQt6.QtWidgets.QWidget` with four collapsible
        group boxes:

        * **Connection** — connection mode selector and VISA resource fields.
        * **Source** — compliance voltage, source delay, and current range.
        * **Measurement** — NPLC, voltage range, and digital filter controls.
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

        res_6221 = VisaResourceComboBox(interface_filter=FILTER_GPIB)
        res_6221.setCurrentText(self._6221_resource)

        res_2182a = VisaResourceComboBox(interface_filter=FILTER_GPIB)
        res_2182a.setCurrentText(self._2182a_resource)
        res_2182a_label = QLabel("2182A GPIB resource:")
        res_2182a.setEnabled(self._connection_mode is ConnectionMode.DIRECT_GPIB)
        res_2182a_label.setEnabled(self._connection_mode is ConnectionMode.DIRECT_GPIB)

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

        compliance_sb = SISpinBox(suffix="V", value=self._compliance)
        compliance_sb.setMinimum(0.1)
        compliance_sb.setMaximum(105.0)
        compliance_sb.setToolTip("Compliance voltage limit for the 6221 current source.")

        delay_sb = SISpinBox(suffix="s", value=self._source_delay)
        delay_sb.setMinimum(1e-3)
        delay_sb.setMaximum(9999.0)
        delay_sb.setToolTip("Settling delay after each source step before triggering the 2182A.")

        range_sb = SISpinBox(suffix="A", value=self._source_range)
        range_sb.setMinimum(0.0)
        range_sb.setMaximum(0.105)
        range_sb.setToolTip("Fixed current output range in amps.  Set to 0 for automatic ranging.")

        def _on_compliance_changed(value: float) -> None:
            self._compliance = value

        def _on_delay_changed(value: float) -> None:
            self._source_delay = value

        def _on_range_changed(value: float) -> None:
            self._source_range = value

        compliance_sb.sigValueChanged.connect(_on_compliance_changed)
        delay_sb.sigValueChanged.connect(_on_delay_changed)
        range_sb.sigValueChanged.connect(_on_range_changed)

        src_form.addRow("Compliance voltage:", compliance_sb)
        src_form.addRow("Source delay:", delay_sb)
        src_form.addRow("Source range (0 = auto):", range_sb)
        root_layout.addWidget(src_group)

        # ---- Measurement group ----
        meas_group = QGroupBox("Measurement (2182A)")
        meas_form = QFormLayout(meas_group)

        nplc_sb = SISpinBox(value=self._nplc)
        nplc_sb.setMinimum(0.01)
        nplc_sb.setMaximum(60.0)
        nplc_sb.setToolTip("Integration time in power-line cycles (1 PLC ≈ 20 ms at 50 Hz).")

        vrange_sb = SISpinBox(suffix="V", value=self._voltage_range)
        vrange_sb.setMinimum(0.0)
        vrange_sb.setMaximum(120.0)
        vrange_sb.setToolTip("Voltage measurement range in volts.  Set to 0 for autorange.")

        filter_chk = QCheckBox()
        filter_chk.setChecked(self._filter_enabled)
        filter_chk.setToolTip("Enable the 2182A digital averaging filter.")

        filter_count_sb = QSpinBox()
        filter_count_sb.setMinimum(1)
        filter_count_sb.setMaximum(100)
        filter_count_sb.setValue(self._filter_count)
        filter_count_sb.setEnabled(self._filter_enabled)
        filter_count_sb.setToolTip("Number of readings averaged per sample when the digital filter is enabled.")

        def _on_nplc_changed(value: float) -> None:
            self._nplc = value

        def _on_vrange_changed(value: float) -> None:
            self._voltage_range = value

        def _on_filter_toggled(state: bool) -> None:
            self._filter_enabled = bool(state)
            filter_count_sb.setEnabled(bool(state))

        def _on_filter_count_changed(value: int) -> None:
            self._filter_count = value

        nplc_sb.sigValueChanged.connect(_on_nplc_changed)
        vrange_sb.sigValueChanged.connect(_on_vrange_changed)
        filter_chk.toggled.connect(_on_filter_toggled)
        filter_count_sb.valueChanged.connect(_on_filter_count_changed)

        meas_form.addRow("Integration time (NPLC):", nplc_sb)
        meas_form.addRow("Voltage range (0 = auto):", vrange_sb)
        meas_form.addRow("Digital filter:", filter_chk)
        meas_form.addRow("Filter count:", filter_count_sb)
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
