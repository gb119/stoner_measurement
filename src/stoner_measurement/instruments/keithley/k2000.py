"""Keithley 2000/2700 digital multimeter drivers."""

from __future__ import annotations

from stoner_measurement.instruments.dmm import (
    DigitalMultimeter,
    DmmCapabilities,
    DmmFunction,
    DmmTriggerSource,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport


class Keithley2000(DigitalMultimeter):
    """Driver for the Keithley 2000 digital multimeter.

    Attributes:
        transport (BaseTransport):
            Transport layer (serial, GPIB, or Ethernet).
        protocol (BaseProtocol):
            Protocol instance (defaults to :class:`ScpiProtocol`).
    """

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the Keithley 2000 driver, defaulting to :class:`ScpiProtocol`."""
        super().__init__(transport=transport, protocol=protocol if protocol is not None else ScpiProtocol())

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
    def _normalise_function(token: str) -> DmmFunction:
        """Convert a SCPI function token to the corresponding :class:`DmmFunction` enum."""
        cleaned = token.strip().strip("'\"").upper()
        if cleaned == "VOLT":
            return DmmFunction.VOLT_DC
        if cleaned == "CURR":
            return DmmFunction.CURR_DC
        return DmmFunction(cleaned)

    def _sense_prefix(self, function: DmmFunction | None = None) -> str:
        """Return the SCPI sense subsystem prefix for the given (or active) function."""
        active = function if function is not None else self.get_measure_function()
        return active.value.split(":", 1)[0]

    def measure(self) -> float:
        """Trigger a measurement and return its value.

        Returns:
            (float):
                Measured scalar value in units of the active function.
        """
        return float(self.query(":READ?"))

    def get_measure_function(self) -> DmmFunction:
        """Return the active measurement function.

        Returns:
            (DmmFunction):
                Active measurement function.
        """
        return self._normalise_function(self.query(":SENS:FUNC?"))

    def set_measure_function(self, function: DmmFunction) -> None:
        """Set the active measurement function.

        Args:
            function (DmmFunction):
                Function to select.
        """
        self.write(f':SENS:FUNC "{function.value}"')

    def get_range(self) -> float:
        """Return the active measurement range in units of the active function.

        Returns:
            (float):
                Active measurement range.
        """
        return float(self.query(f":SENS:{self._sense_prefix()}:RANG?"))

    def set_range(self, value: float) -> None:
        """Set the measurement range.

        Args:
            value (float):
                Range value in units of the active function.  Must be positive.

        Raises:
            ValueError:
                If *value* is not positive.
        """
        if value <= 0.0:
            raise ValueError("Range must be positive.")
        self.write(f":SENS:{self._sense_prefix()}:RANG {value}")

    def get_autorange(self) -> bool:
        """Return ``True`` if autorange is enabled.

        Returns:
            (bool):
                ``True`` when autorange is active.
        """
        return self.query(f":SENS:{self._sense_prefix()}:RANG:AUTO?") == "1"

    def set_autorange(self, state: bool) -> None:
        """Enable or disable autorange.

        Args:
            state (bool):
                ``True`` to enable autorange.
        """
        self.write(f":SENS:{self._sense_prefix()}:RANG:AUTO {1 if state else 0}")

    def get_nplc(self) -> float:
        """Return the integration time in power-line cycles.

        Returns:
            (float):
                Integration time in power-line cycles.
        """
        return float(self.query(f":SENS:{self._sense_prefix()}:NPLC?"))

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
        self.write(f":SENS:{self._sense_prefix()}:NPLC {value}")

    def get_filter_enabled(self) -> bool:
        """Return ``True`` if digital averaging filter is enabled.

        Returns:
            (bool):
                ``True`` when the averaging filter is active.
        """
        return self.query(f":SENS:{self._sense_prefix()}:AVER:STAT?") == "1"

    def set_filter_enabled(self, state: bool) -> None:
        """Enable or disable the digital averaging filter.

        Args:
            state (bool):
                ``True`` to enable filtering.
        """
        self.write(f":SENS:{self._sense_prefix()}:AVER:STAT {1 if state else 0}")

    def get_filter_count(self) -> int:
        """Return the averaging filter count.

        Returns:
            (int):
                Configured number of readings averaged per sample.
        """
        return int(float(self.query(f":SENS:{self._sense_prefix()}:AVER:COUN?")))

    def set_filter_count(self, count: int) -> None:
        """Set the averaging filter count.

        Args:
            count (int):
                Number of readings to average.  Must be positive.

        Raises:
            ValueError:
                If *count* is not positive.
        """
        if count <= 0:
            raise ValueError("Filter count must be positive.")
        self.write(f":SENS:{self._sense_prefix()}:AVER:COUN {count}")

    def get_trigger_source(self) -> DmmTriggerSource:
        """Return the trigger source selection.

        Returns:
            (DmmTriggerSource):
                Active trigger source.
        """
        return DmmTriggerSource(self.query(":TRIG:SOUR?").strip().upper())

    def set_trigger_source(self, source: DmmTriggerSource) -> None:
        """Set the trigger source.

        Args:
            source (DmmTriggerSource):
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
        """Return the number of readings currently stored in the buffer.

        Returns:
            (int):
                Number of readings in the trace buffer.
        """
        return int(float(self.query(":TRAC:POIN:ACT?")))

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
        payload = self.query(f":TRAC:DATA? 1,{count}")
        return self._parse_csv_floats(payload)

    def get_capabilities(self) -> DmmCapabilities:
        """Return static capability metadata for the Keithley 2000.

        Returns:
            (DmmCapabilities):
                Capability descriptor.
        """
        return DmmCapabilities(
            has_function_selection=True,
            has_filter=True,
            has_trigger=True,
            has_buffer=True,
            supported_functions=(
                DmmFunction.VOLT_DC,
                DmmFunction.VOLT_AC,
                DmmFunction.CURR_DC,
                DmmFunction.CURR_AC,
                DmmFunction.RES,
                DmmFunction.FRES,
                DmmFunction.FREQ,
                DmmFunction.PER,
                DmmFunction.TEMP,
            ),
        )


class Keithley2700(Keithley2000):
    """Driver for the Keithley 2700 multimeter/data-acquisition system."""
