"""Keithley 2182A/182 nanovoltmeter drivers."""

from __future__ import annotations

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


class Keithley2182A(Nanovoltmeter):
    """Driver for the Keithley 2182A nanovoltmeter.

    Attributes:
        transport (BaseTransport):
            Transport layer (serial, GPIB, or Ethernet).
        protocol (BaseProtocol):
            Protocol instance (defaults to :class:`ScpiProtocol`).
    """
    
    _MODEL="MODEL 2182A"

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the Keithley 2182A driver, defaulting to :class:`ScpiProtocol`."""
        super().__init__(transport=transport, protocol=protocol if protocol is not None else ScpiProtocol())
        
    def connect(self) -> None:
        """Open the transport connection to the instrument.

        After opening the transport, any data accumulated in the transport
        buffer since the last session is discarded via
        :meth:`~stoner_measurement.instruments.transport.base.BaseTransport.flush`
        so that stale responses from previous commands cannot be misread as
        replies to new queries.

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
            self.transport.write("*CLS",host=True) # Clear error nuffer on 6221
        self.write("*CLS")

    def reset(self) -> None:
        """Send the standard IEEE 488.2 reset command (``*RST``).

        Instruments that do not support ``*RST`` should override this method.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.protocol import ScpiProtocol
            >>> from stoner_measurement.instruments.base_instrument import BaseInstrument
            >>> t = NullTransport()
            >>> instr = BaseInstrument(t, ScpiProtocol())
            >>> instr.connect()
            >>> instr.reset()
            >>> t.write_log
            [b'*RST\\n']
            >>> instr.disconnect()
        """
        self.write("*RST",slow=2000)

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
        self.write(f":TRAC:POIN {size}")

    def set_buffer_feed_sense(self) -> None:
        """Set trace feed source to measurement readings (``:TRAC:FEED SENS``)."""
        self.write(":TRAC:FEED SENS")

    def set_buffer_feed_continuous_next(self) -> None:
        """Set feed mode to continuous-next (``:TRAC:FEED:CONT NEXT``)."""
        self.write(":TRAC:FEED:CONT NEXT")

    def read_buffer(self, count: int | None = None) -> tuple[float, ...]:
        """Read values from the instrument trace buffer.

        Keyword Parameters:
            count (int | None):
                Number of points to read from the start of the buffer.
                If ``None``, read all available points.

        Returns:
            (tuple[float, ...]):
                Parsed buffer readings.

        Raises:
            ValueError:
                If *count* is not positive.
        """
        if count is None:
            payload = self.query(":TRAC:DATA?")
            return self._parse_csv_floats(payload)
        if count <= 0:
            raise ValueError("count must be a positive integer.")
        payload = self.query(":TRAC:DATA?")
        return self._parse_csv_floats(payload)

    def get_capabilities(self) -> NanovoltmeterCapabilities:
        """Return static capability metadata for the Keithley 2182A.

        Returns:
            (NanovoltmeterCapabilities):
                Capability descriptor.
        """
        return NanovoltmeterCapabilities(
            has_function_selection=True,
            has_filter=True,
            has_trigger=True,
            has_buffer=True,
            supported_functions=(NanovoltmeterFunction.VOLT, NanovoltmeterFunction.TEMP),
        )


class Keithley182(Keithley2182A):
    """Driver for the Keithley 182 nanovoltmeter."""
