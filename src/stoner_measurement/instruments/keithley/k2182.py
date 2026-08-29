"""Keithley 2182A SCPI nanovoltmeter driver."""

from __future__ import annotations

import numpy as np

from stoner_measurement.instruments.electrometer import ElectrometerDataFormat
from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.keithley._scpi_data_format import (
    KeithleyByteOrder,
    KeithleyScpiDataFormatMixin,
)
from stoner_measurement.instruments.nanovoltmeter import (
    Nanovoltmeter,
    NanovoltmeterCapabilities,
    NanovoltmeterFunction,
    NanovoltmeterTriggerSource,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport
from stoner_measurement.instruments.transport.gpib_transport import (
    PassThroughGpibTransport,
)

__all__ = ["Keithley2182A", "KeithleyByteOrder"]


class Keithley2182A(KeithleyScpiDataFormatMixin, Nanovoltmeter):
    """Driver for the Keithley 2182A nanovoltmeter.

    Attributes:
        transport (BaseTransport):
            Transport layer (serial, GPIB, or Ethernet).
        protocol (BaseProtocol):
            Protocol instance (defaults to :class:`ScpiProtocol`).
    """

    _MODEL = "MODEL 2182A"

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the Keithley 2182A driver, defaulting to :class:`ScpiProtocol`."""
        super().__init__(
            transport=transport, protocol=protocol if protocol is not None else ScpiProtocol()
        )
        self._initialise_data_format_state()
        self._buffer_size: int | None = None

    def connect(self) -> None:
        """Open the transport connection to the instrument.

        After opening the transport, any data accumulated in the transport
        buffer since the last session is discarded via
        :meth:`~stoner_measurement.instruments.transport.base.BaseTransport.flush`
        so that stale responses from previous commands cannot be misread as
        replies to new queries. The instrument is then cleared and reset to
        its IEEE-488.2 defaults, with reset completion confirmed before
        normal status checking resumes.

        Raises:
            ConnectionError:
                If the underlying transport cannot be opened.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> instr = BaseInstrument(NullTransport(), ScpiProtocol())
            >>> instr.connect()
            >>> instr.is_connected
            True
            >>> instr.disconnect()
        """
        super().connect()
        if isinstance(self.transport, PassThroughGpibTransport):
            with self.transport.suppress_status_error_check():
                self.transport.write(b"*CLS", host=True)  # Clear error buffer on 6221
        self.reset()

    def reset(self) -> None:
        """Clear and reset the 2182A, waiting until reset has completed.

        Status-byte and automatic error checks are suspended only for this
        recovery sequence so that a stale Error Available bit cannot prevent
        ``*CLS`` from clearing the condition. The sequence follows the 2182A
        manual: clear status, issue ``*RST;*OPC?``, verify completion, and
        clear any reset-time events before restoring normal error checking.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> t = NullTransport(responses=[b"1\\n"])
            >>> t.open()
            >>> instr = Keithley2182A(t)
            >>> instr.reset()
            >>> t.write_log
            [b'*CLS\\n', b'*RST;*OPC?\\n', b'*CLS\\n']
            >>> instr.disconnect()
        """
        with self._lock:
            auto_check_errors = self.auto_check_errors
            self.auto_check_errors = False
            try:
                with self.transport.suppress_status_error_check():
                    # The 2182A manual states that *RST does not clear the
                    # error queue and may take long enough to require *OPC?.
                    # Clear stale status first, wait for reset completion,
                    # then clear reset-time events before normal checked I/O.
                    self.write("*CLS")
                    response = self.query("*RST;*OPC?", slow=500)
                    if response not in {"1", "+1"}:
                        raise InstrumentError(
                            "Unexpected operation-complete response after "
                            f"2182A reset: {response!r}"
                        )
                    self.write("*CLS")
            finally:
                self.auto_check_errors = auto_check_errors
        self._initialise_data_format_state()

    @staticmethod
    def _parse_csv_floats(values: str) -> tuple[float, ...]:
        """Parse a comma-separated numeric payload into a tuple of floats."""
        stripped = values.strip()
        if not stripped:
            return ()
        tokens = [token.strip() for token in stripped.split(",")]
        if "" in tokens:
            raise ValueError(f"Malformed numeric response: {values!r}")
        try:
            return tuple(float(token) for token in tokens)
        except ValueError as exc:
            raise ValueError(f"Malformed numeric response: {values!r}") from exc

    @staticmethod
    def parse_csv_floats(values: str) -> tuple[float, ...]:
        """Parse a comma-separated numeric payload.

        Args:
            values (str):
                Raw comma-separated numeric response string.

        Returns:
            (tuple[float, ...]):
                Parsed floating-point values.

        Raises:
            ValueError:
                If *values* contains malformed numeric tokens.
        """
        return Keithley2182A._parse_csv_floats(values)

    def measure_voltage(self) -> float:
        """Trigger a voltage measurement and return the result in volts.

        Returns:
            (float):
                Measured voltage in volts.
        """
        return float(self.query(":READ?"))

    def get_range(self) -> float:
        """Return the active voltage measurement range in volts.

        Returns:
            (float):
                Active measurement range in volts.
        """
        return float(self.query(":SENS:VOLT:RANG?"))

    def set_range(self, value: float) -> None:
        """Set the voltage measurement range in volts.

        Args:
            value (float):
                Measurement range in volts.  Must be positive.

        Raises:
            ValueError:
                If *value* is not positive.
        """
        if value <= 0.0:
            raise ValueError("Range must be positive.")
        self.write(f":SENS:VOLT:RANG {value}")

    def get_autorange(self) -> bool:
        """Return ``True`` if autorange is enabled.

        Returns:
            (bool):
                ``True`` when autorange is active.
        """
        return self.query(":SENS:VOLT:RANG:AUTO?") == "1"

    def set_autorange(self, state: bool) -> None:
        """Enable or disable autorange.

        Args:
            state (bool):
                ``True`` to enable autorange.
        """
        self.write(f":SENS:VOLT:RANG:AUTO {1 if state else 0}")

    def get_nplc(self) -> float:
        """Return the integration time in power-line cycles.

        Returns:
            (float):
                Integration time in power-line cycles.
        """
        return float(self.query(":SENS:VOLT:NPLC?"))

    def set_nplc(self, value: float) -> None:
        """Set the integration time in power-line cycles.

        Args:
            value (float):
                Integration time in power-line cycles.  Must be positive.

        Raises:
            ValueError:
                If *value* is not positive.
        """
        if value <= 0.0:
            raise ValueError("NPLC must be positive.")
        self.write(f":SENS:VOLT:NPLC {value}")

    def set_digits(self, digits: int) -> None:
        """Set display and data digits.

        Args:
            digits (int):
                Number of digits to display/store (valid range: 4..8).

        Raises:
            ValueError:
                If *digits* is outside ``4..8``.
        """
        if not 4 <= digits <= 8:
            raise ValueError("digits must be in the range 4..8.")
        self.write(f":SENS:VOLT:DIG {digits}")

    def get_measure_function(self) -> NanovoltmeterFunction:
        """Return the active measurement function.

        Returns:
            (NanovoltmeterFunction):
                Active measurement function.
        """
        token = self.query(":SENS:FUNC?").strip().strip("'\"").upper()
        return NanovoltmeterFunction(token)

    def set_measure_function(self, function: NanovoltmeterFunction) -> None:
        """Set the active measurement function.

        Args:
            function (NanovoltmeterFunction):
                Function to select.
        """
        self.write(f':SENS:FUNC "{function.value}"')

    def get_filter_enabled(self) -> bool:
        """Return ``True`` if the digital filter is enabled.

        Returns:
            (bool):
                ``True`` when the digital filter is active.
        """
        return self.query(":SENS:VOLT:DFIL:STAT?") == "1"

    def set_filter_enabled(self, state: bool) -> None:
        """Enable or disable the digital filter.

        Args:
            state (bool):
                ``True`` to enable the filter.
        """
        self.write(f":SENS:VOLT:DFIL:STAT {1 if state else 0}")

    def get_filter_count(self) -> int:
        """Return the digital filter averaging count.

        Returns:
            (int):
                Number of readings averaged per sample.
        """
        return int(float(self.query(":SENS:VOLT:DFIL:COUN?")))

    def set_filter_count(self, count: int) -> None:
        """Set the digital filter averaging count.

        Args:
            count (int):
                Number of readings to average.  Must be positive.

        Raises:
            ValueError:
                If *count* is not positive.
        """
        if count <= 0:
            raise ValueError("Filter count must be positive.")
        self.write(f":SENS:VOLT:DFIL:COUN {count}")

    def set_filter_type(self, filter_type: str) -> None:
        """Select the repeating or moving-window digital filter.

        ``"WINDOW"`` is accepted as the user-facing name for the
        instrument's ``MOV`` (moving-window) mode.  ``"MOVING"`` remains an
        accepted alias for callers using the SCPI manual's terminology.
        """
        token = filter_type.strip().upper()
        if token not in {"REPEAT", "WINDOW", "MOVING"}:
            raise ValueError("Filter type must be 'REPEAT', 'WINDOW', or 'MOVING'.")
        # REPEAT is an instrument SCPI token, not a credential.
        self.write(f":SENS:VOLT:DFIL:TCON {'REP' if token == 'REPEAT' else 'MOV'}")  # nosec B105

    def get_trigger_delay(self) -> float:
        """Return the trigger delay in seconds."""
        return float(self.query(":TRIG:DEL?"))

    def set_trigger_delay(self, delay: float) -> None:
        """Set the delay between a trigger event and measurement in seconds."""
        if not 0.0 <= delay <= 999999.999:
            raise ValueError("Trigger delay must be in the range 0..999999.999 seconds.")
        self.write(f":TRIG:DEL {delay}")

    def get_line_sync_enabled(self) -> bool:
        """Return whether A/D conversions are synchronized to the power line."""
        return self.query(":SYST:LSYN?") == "1"

    def set_line_sync_enabled(self, state: bool) -> None:
        """Enable or disable power-line synchronization of A/D conversions."""
        self.write(f":SYST:LSYN {1 if state else 0}")

    def get_autozero_enabled(self) -> bool:
        """Return whether automatic zero-reference measurements are enabled."""
        return self.query(":SYST:AZER?") == "1"

    def set_autozero_enabled(self, state: bool) -> None:
        """Enable or disable automatic zero-reference measurements."""
        self.write(f":SYST:AZER {1 if state else 0}")

    def set_analog_filter_enabled(self, state: bool) -> None:
        """Enable or disable the analogue low-pass filter.

        Args:
            state (bool):
                ``True`` to enable, ``False`` to disable.
        """
        self.write(f":SENS:VOLT:LPAS:STAT {1 if state else 0}")

    def set_relative_enabled(self, state: bool) -> None:
        """Enable or disable relative (REL) mode.

        Args:
            state (bool):
                ``True`` to enable, ``False`` to disable.
        """
        self.write(f":SENS:VOLT:REF:STAT {1 if state else 0}")

    def get_relative_value(self) -> float:
        """Return the channel-one voltage reference used by relative mode."""
        return float(self.query(":SENS:VOLT:REF?"))

    def set_relative_value(self, value: float) -> None:
        """Set the channel-one voltage reference used by relative mode."""
        if not -120.0 <= value <= 120.0:
            raise ValueError("Relative voltage must be in the range -120..120 V.")
        self.write(f":SENS:VOLT:REF {value}")

    def get_trigger_source(self) -> NanovoltmeterTriggerSource:
        """Return the trigger source selection.

        Returns:
            (NanovoltmeterTriggerSource):
                Active trigger source.
        """
        return NanovoltmeterTriggerSource(self.query(":TRIG:SOUR?").strip().upper())

    def set_trigger_source(self, source: NanovoltmeterTriggerSource) -> None:
        """Set the trigger source.

        Args:
            source (NanovoltmeterTriggerSource):
                Trigger source to select.
        """
        self.write(f":TRIG:SOUR {source.value}")

    def get_trigger_count(self) -> int:
        """Return the configured trigger count.

        Returns:
            (int):
                Number of triggers configured.
        """
        return int(float(self.query(":TRIG:COUN?")))

    def set_trigger_count(self, count: int) -> None:
        """Set the trigger count.

        Args:
            count (int):
                Number of triggers.  Must be positive.

        Raises:
            ValueError:
                If *count* is not positive.
        """
        if count <= 0:
            raise ValueError("Trigger count must be positive.")
        self.write(f":TRIG:COUN {count}")

    def initiate(self) -> None:
        """Arm the trigger system and begin a measurement sequence."""
        self.write(":INIT")

    def abort(self) -> None:
        """Abort a running measurement sequence and return to idle."""
        self.write(":ABOR")

    def clear_buffer(self) -> None:
        """Clear all readings from the instrument trace buffer."""
        self.write(":TRAC:CLE")

    def get_buffer_count(self) -> int:
        """Return the number of readings currently stored in the trace buffer."""
        return int(float(self.query(":TRAC:POIN?")))

    def get_buffer_size(self) -> int:
        """Return the configured trace capacity, querying only if it is not cached."""
        if self._buffer_size is None:
            self._buffer_size = int(float(self.query(":TRAC:POIN?")))
        return self._buffer_size

    def set_buffer_size(self, size: int) -> None:
        """Set the trace buffer point capacity.

        Args:
            size (int):
                Number of points to allocate in the trace buffer.

        Raises:
            ValueError:
                If *size* is not positive.
        """
        if size <= 0:
            raise ValueError("size must be positive.")
        if size == self._buffer_size:
            return
        self.write(f":TRAC:POIN {size}")
        self._buffer_size = size

    def set_buffer_feed_sense(self) -> None:
        """Set trace feed source to measurement readings (``:TRAC:FEED SENS``)."""
        self.write(":TRAC:FEED SENS")

    def set_buffer_feed_continuous_next(self) -> None:
        """Set feed mode to continuous-next (``:TRAC:FEED:CONT NEXT``)."""
        self.write(":TRAC:FEED:CONT NEXT")

    def read_buffer(self, count: int | None = None) -> tuple[float, ...] | np.ndarray:
        """Read values from the instrument trace buffer.

        Keyword Parameters:
            count (int | None):
                Number of points to read from the start of the buffer.
                If ``None``, read all available points.

        Returns:
            (tuple[float, ...] | numpy.ndarray):
                Parsed ASCII readings, or a zero-copy NumPy view for binary
                formats.

        Raises:
            ValueError:
                If *count* is not positive.
        """
        if count is not None and count <= 0:
            raise ValueError("count must be a positive integer.")
        # A non-None value makes the 6221 relay collect the complete trace
        # before issuing its separate status query.  Zero adds no delay.
        slow = 0 if count is None else round(count * 0.05)
        if self._data_format is ElectrometerDataFormat.ASCII:
            payload = self.query(":TRAC:DATA?", slow=slow)
            values = self._parse_csv_floats(payload)
            return values if count is None else values[:count]

        raw = self._query_raw(":TRAC:DATA?", slow=slow)
        return self.parse_binary_floats(
            raw,
            data_format=self._data_format,
            byte_order=self._byte_order,
            count=count,
        )

    CAPABILITIES = NanovoltmeterCapabilities(
        has_function_selection=True,
        has_filter=True,
        has_trigger=True,
        has_buffer=True,
        has_data_format=True,
        has_byte_order=True,
        supported_functions=(NanovoltmeterFunction.VOLT, NanovoltmeterFunction.TEMP),
        fixed_voltage_ranges=(0.01, 0.1, 1.0, 10.0, 100.0, 120.0),
        nplc_values=(0.1, 1.0, 10.0),
        digit_values=(4, 5, 6, 7, 8),
        filter_types=("OFF", "REPEAT", "WINDOW"),
        default_nplc=1.0,
        default_digits=8,
        default_filter_type="OFF",
        counted_filter_types=("REPEAT",),
        analog_filter_time_multiplier=2.0,
        supports_filter_count=True,
        supports_analog_filter=True,
        supports_relative=True,
        supports_line_sync=True,
        supports_autozero=True,
        relative_limits=(-120.0, 120.0),
    )

    def get_capabilities(self) -> NanovoltmeterCapabilities:
        """Return static capability metadata for the Keithley 2182A.

        Returns:
            (NanovoltmeterCapabilities):
                Capability descriptor.
        """
        return self.CAPABILITIES
