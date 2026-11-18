"""Keithley electrometer and picoammeter drivers."""

from __future__ import annotations

import numpy as np

from stoner_measurement.instruments.electrometer import (
    Electrometer,
    ElectrometerCapabilities,
    ElectrometerDataFormat,
    ElectrometerFunction,
    ElectrometerTriggerConfiguration,
)
from stoner_measurement.instruments.keithley._scpi_data_format import (
    KeithleyByteOrder,
    KeithleyScpiDataFormatMixin,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

_NPLC_MIN = 0.01
_NPLC_MAX = 10.0


class _KeithleyElectrometerBase(Electrometer):
    """Common SCPI implementation for Keithley electrometers."""

    MEASURE_FUNCTIONS = tuple(ElectrometerFunction)
    DATA_FORMATS = (ElectrometerDataFormat.ASCII, ElectrometerDataFormat.SREAL)
    MAX_BUFFER_POINTS = 2500
    HAS_BYTE_ORDER = False
    HAS_TRIGGER_OUTPUT_CONTROL = True

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
    ) -> None:
        """Initialise the Keithley electrometer base driver, defaulting to :class:`ScpiProtocol`."""
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )
        self._buffer_data_format = ElectrometerDataFormat.ASCII

    @staticmethod
    def _parse_csv_floats(values: str) -> tuple[float, ...]:
        """Parse a comma-separated numeric payload."""
        stripped = values.strip()
        if not stripped:
            return ()
        return tuple(float(token.strip()) for token in stripped.split(",") if token.strip())

    @staticmethod
    def _normalise_function(function_name: str) -> ElectrometerFunction:
        """Convert a SCPI function token to an enum value."""
        token = function_name.strip().strip("'\"").upper()
        if ":" in token:
            token = token.split(":", 1)[0]
        return ElectrometerFunction(token)

    def measure_current(self) -> float:
        """Trigger a current measurement and return current in amps."""
        self.write(":SENS:FUNC 'CURR'")
        return float(self.query(":READ?").split(",")[0])

    def get_range(self) -> float:
        """Return active current range in amps."""
        return float(self.query(":SENS:CURR:RANG?"))

    def set_range(self, value: float) -> None:
        """Set current range in amps."""
        if value <= 0.0:
            raise ValueError("Range must be positive.")
        self.write(f":SENS:CURR:RANG {value}")

    def get_autorange(self) -> bool:
        """Return ``True`` if autorange is enabled."""
        return self.query(":SENS:CURR:RANG:AUTO?") == "1"

    def set_autorange(self, state: bool) -> None:
        """Enable or disable autorange."""
        self.write(f":SENS:CURR:RANG:AUTO {1 if state else 0}")

    def get_nplc(self) -> float:
        """Return integration time in power-line cycles."""
        return float(self.query(":SENS:CURR:NPLC?"))

    def set_nplc(self, value: float) -> None:
        """Set integration time in power-line cycles."""
        if not _NPLC_MIN <= value <= _NPLC_MAX:
            raise ValueError(f"NPLC {value} out of range [{_NPLC_MIN}, {_NPLC_MAX}].")
        self.write(f":SENS:CURR:NPLC {value}")

    def get_measure_functions(self) -> tuple[ElectrometerFunction, ...]:
        """Return enabled measurement functions."""
        payload = self.query(":SENS:FUNC?")
        return tuple(self._normalise_function(token) for token in payload.split(",") if token.strip())

    def set_measure_functions(self, functions: tuple[ElectrometerFunction, ...]) -> None:
        """Enable one or more measurement functions."""
        if not functions:
            raise ValueError("At least one measurement function must be provided.")
        quoted = ",".join(f"'{function_name.value}'" for function_name in functions)
        self.write(f":SENS:FUNC {quoted}")

    def get_filter_enabled(self) -> bool:
        """Return ``True`` if digital averaging filter is enabled."""
        return self.query(":SENS:CURR:AVER:STAT?") == "1"

    def set_filter_enabled(self, state: bool) -> None:
        """Enable or disable digital averaging filter."""
        self.write(f":SENS:CURR:AVER:STAT {1 if state else 0}")

    def get_filter_count(self) -> int:
        """Return averaging filter count."""
        return int(float(self.query(":SENS:CURR:AVER:COUN?")))

    def set_filter_count(self, count: int) -> None:
        """Set averaging filter count."""
        if count <= 0:
            raise ValueError("Filter count must be positive.")
        self.write(f":SENS:CURR:AVER:COUN {count}")

    def configure_trigger_model(self, config: ElectrometerTriggerConfiguration) -> None:
        """Configure trigger and arm model settings."""
        if config.trigger_count <= 0:
            raise ValueError("Trigger count must be positive.")
        if config.arm_count <= 0:
            raise ValueError("Arm count must be positive.")
        if config.trigger_delay < 0.0:
            raise ValueError("Trigger delay must be non-negative.")
        self.write(f":TRIG:SOUR {config.trigger_source.value}")
        self.write(f":TRIG:COUN {config.trigger_count}")
        self.write(f":TRIG:DEL {config.trigger_delay}")
        self.write(f":ARM:SOUR {config.arm_source.value}")
        self.write(f":ARM:COUN {config.arm_count}")

    def initiate(self) -> None:
        """Start trigger execution."""
        # These meters defer most queries until they return to idle. An
        # immediate error-queue query here would block before the source can
        # send the first trigger. Check errors after the buffered read instead.
        with self._lock:
            check_errors = self.auto_check_errors
            self.auto_check_errors = False
            try:
                self.write(":INIT")
            finally:
                self.auto_check_errors = check_errors

    def abort(self) -> None:
        """Abort trigger execution."""
        self.write(":ABOR")

    def prepare_single_reading(self, *, trigger_delay: float = 0.0) -> None:
        """Configure one fresh immediate measurement without buffered storage.

        Keyword Parameters:
            trigger_delay (float): Delay before conversion in seconds, 0..999.999.

        Raises:
            ValueError: If the trigger delay is negative, non-finite or too large.
        """
        if not np.isfinite(trigger_delay) or not 0 <= trigger_delay <= 999.999:
            raise ValueError("Electrometer trigger delay must be between 0 and 999.999 seconds.")
        self.write(":INIT:CONT OFF")
        self.abort()
        self.write(":TRAC:FEED:CONT NEV")
        self.write(":FORM:ELEM READ")
        self.set_data_format(ElectrometerDataFormat.ASCII)
        self.configure_trigger_model(ElectrometerTriggerConfiguration(trigger_delay=trigger_delay))

    def read_measurement(self) -> float:
        """Trigger and return one fresh reading in the configured function's SI unit.

        Call ``prepare_single_reading()`` and configure the input first. The
        READ query performs the conversion; it does not return a cached sample.

        Returns:
            (float): The measured current, voltage, resistance or charge.

        Raises:
            ValueError: If the instrument returns an empty or multi-reading response.
        """
        readings = self._parse_csv_floats(self.query(":READ?"))
        if len(readings) != 1:
            raise ValueError(f"Expected one electrometer reading, received {len(readings)}.")
        return readings[0]

    def set_buffer_size(self, size: int) -> None:
        """Set trace buffer size."""
        if size <= 0:
            raise ValueError("Buffer size must be positive.")
        self.write(f":TRAC:POIN {size}")

    def get_buffer_size(self) -> int:
        """Return trace buffer size."""
        return int(float(self.query(":TRAC:POIN?")))

    def clear_buffer(self) -> None:
        """Clear trace buffer data."""
        self.write(":TRAC:CLE")

    def read_buffer(self, count: int | None = None) -> tuple[float, ...]:
        """Read the complete trace buffer in the selected transfer format.

        The hardware query has no start/count arguments. A requested count
        limits the returned vector, including for binary transfers. Call
        ``prepare_buffer()`` first to select reading-only elements.

        Args:
            count (int | None):
                Maximum readings to return, or None for the entire buffer.

        Returns:
            (tuple[float, ...]): Numeric readings in the selected function's units.

        Raises:
            ValueError: If count is non-positive or binary framing is malformed.
        """
        if count is not None and count <= 0:
            raise ValueError("Requested buffer count must be positive.")
        if self._buffer_data_format is ElectrometerDataFormat.ASCII:
            readings = self._parse_csv_floats(self.query(":TRAC:DATA?"))
        else:
            with self._lock:
                payload = self.transport.query(self.protocol.format_query(":TRAC:DATA?"))
            readings = tuple(KeithleyScpiDataFormatMixin.parse_binary_floats(
                payload, data_format=self._buffer_data_format,
                byte_order=KeithleyByteOrder.NORMAL,
            ))
            if self.auto_check_errors:
                self.check_for_errors(command=":TRAC:DATA?")
        return readings if count is None else readings[:count]

    def get_data_format(self) -> ElectrometerDataFormat:
        """Return configured response data format."""
        token = self.query(":FORM:DATA?").strip().upper()
        if token.startswith("ASC"):
            return ElectrometerDataFormat.ASCII
        if token.startswith("SRE"):
            return ElectrometerDataFormat.SREAL
        if token.startswith("DRE"):
            return ElectrometerDataFormat.DREAL
        return ElectrometerDataFormat(token)

    def set_data_format(self, data_format: ElectrometerDataFormat) -> None:
        """Set response data format."""
        if data_format not in self.DATA_FORMATS:
            raise ValueError(f"{type(self).__name__} does not support {data_format}.")
        self.write(f":FORM:DATA {data_format.value}")
        self._buffer_data_format = data_format

    def configure_input(
        self, function: ElectrometerFunction, *, autorange: bool, input_range: float,
        nplc: float, filter_enabled: bool, filter_count: int, zero_check: bool = False,
    ) -> None:
        """Configure the selected function's range, integration and filter.

        Only one function is measured at a time. Range, NPLC and averaging
        commands address that function rather than the legacy current-only API.

        Args:
            function (ElectrometerFunction): Measurement function supported by this model.

        Keyword Parameters:
            autorange (bool): Whether to select the input range automatically.
            input_range (float): Fixed range in the function's SI unit; ignored in autorange.
            nplc (float): Integration time in power-line cycles, 0.01 to 10.
            filter_enabled (bool): Whether to enable digital averaging.
            filter_count (int): Averaging count, 1 to 100.
            zero_check (bool): Whether to enable input zero check; defaults to False.

        Raises:
            ValueError: If the function or numeric settings are unsupported.
        """
        if function not in self.MEASURE_FUNCTIONS:
            raise ValueError(f"{type(self).__name__} does not support {function.name}.")
        if not np.isfinite(nplc) or not _NPLC_MIN <= nplc <= _NPLC_MAX:
            raise ValueError("Electrometer NPLC must be between 0.01 and 10.")
        if not autorange and (not np.isfinite(input_range) or input_range <= 0):
            raise ValueError("Electrometer range must be positive and finite.")
        if not 1 <= filter_count <= 100:
            raise ValueError("Electrometer filter count must be between 1 and 100.")
        if len(self.MEASURE_FUNCTIONS) > 1:
            self.set_measure_functions((function,))
        stem = f":SENS:{function.value}"
        self.write(f"{stem}:RANG:AUTO {int(autorange)}")
        if not autorange:
            self.write(f"{stem}:RANG {input_range}")
        self.write(f"{stem}:NPLC {nplc}")
        self.write(f"{stem}:AVER:STAT {int(filter_enabled)}")
        self.write(f"{stem}:AVER:COUN {filter_count}")
        self.write(f":SYST:ZCH {int(zero_check)}")

    def prepare_buffer(self, size: int) -> None:
        """Select numeric readings and sense-buffer storage for one sweep."""
        if not 2 <= size <= self.MAX_BUFFER_POINTS:
            raise ValueError(f"Electrometer buffer size must be 2..{self.MAX_BUFFER_POINTS}.")
        self.write(":INIT:CONT OFF")
        self.abort()
        self.write(":TRAC:FEED:CONT NEV")
        self.clear_buffer()
        self.set_buffer_size(size)
        self.write(":FORM:ELEM READ")
        if self.HAS_BYTE_ORDER:
            self.write(":FORM:BORD NORM")
        self.write(":TRAC:FEED SENS")

    def start_buffer(self) -> None:
        """Clear and arm the configured buffer for external reading triggers."""
        self.abort()
        self.write(":TRAC:FEED:CONT NEV")
        self.clear_buffer()
        self.write(":TRAC:FEED:CONT NEXT")
        self.initiate()

    def wait_for_buffer_complete(self, timeout: float) -> None:
        """Wait for the triggered acquisition to return to idle, within timeout."""
        with self._lock:
            previous_timeout = self.transport.timeout
            self.transport.timeout = timeout
            try:
                if self.query("*OPC?").strip() != "1":
                    raise RuntimeError("Electrometer did not confirm acquisition completion.")
            finally:
                self.transport.timeout = previous_timeout

    def configure_trigger_link(self, *, input_line: int, output_line: int) -> None:
        """Wait for each input pulse and emit a pulse after each measurement."""
        if not 1 <= input_line <= 6 or not 1 <= output_line <= 6 or input_line == output_line:
            raise ValueError("Electrometer Trigger Link lines must be distinct and within 1..6.")
        if self.HAS_TRIGGER_OUTPUT_CONTROL:
            self.write(":TRIG:CLE")
            self.write(":ARM:TCON:OUTP NONE")
        else:
            self.write(":ARM:TCON:DIR ACC")
            self.write(":TRIG:TCON:PROT ASYN")
        self.write(":TRIG:TCON:DIR ACC")
        # Move the input temporarily so routing works after any previous
        # front-panel assignment, including an exchange of input/output lines.
        current_output = int(self.query(":TRIG:TCON:OLIN?"))
        temporary_input = next(line for line in range(1, 7) if line not in (current_output, output_line))
        self.write(f":TRIG:TCON:ILIN {temporary_input}")
        self.write(f":TRIG:TCON:OLIN {output_line}")
        self.write(f":TRIG:TCON:ILIN {input_line}")
        if self.HAS_TRIGGER_OUTPUT_CONTROL:
            self.write(":TRIG:TCON:OUTP SENS")

    def get_capabilities(self) -> ElectrometerCapabilities:
        """Return static capabilities for this driver family."""
        return ElectrometerCapabilities(
            has_function_selection=len(self.MEASURE_FUNCTIONS) > 1,
            has_filter=True,
            has_trigger_model=True,
            has_buffer=True,
            has_data_format=True,
        )


class Keithley6485(_KeithleyElectrometerBase):
    """Driver for the Keithley 6485 picoammeter."""

    MEASURE_FUNCTIONS = (ElectrometerFunction.CURR,)
    HAS_BYTE_ORDER = True


# Preserve imports from scripts written before the model-number correction.
Keithley6845 = Keithley6485


class Keithley6514(_KeithleyElectrometerBase):
    """Driver for the Keithley 6514 electrometer."""


class Keithley6517(_KeithleyElectrometerBase):
    """Driver for the Keithley 6517 electrometer."""

    DATA_FORMATS = tuple(ElectrometerDataFormat)
    MAX_BUFFER_POINTS = 50000
    HAS_BYTE_ORDER = True
    HAS_TRIGGER_OUTPUT_CONTROL = False
