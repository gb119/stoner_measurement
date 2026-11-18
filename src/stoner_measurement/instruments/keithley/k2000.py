"""Keithley 2000/2700 digital multimeter drivers."""

from __future__ import annotations

import math

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

    RANGED_FUNCTIONS = frozenset({
        DmmFunction.VOLT_DC, DmmFunction.VOLT_AC, DmmFunction.CURR_DC,
        DmmFunction.CURR_AC, DmmFunction.RES, DmmFunction.FRES,
    })
    AC_FUNCTIONS = frozenset({DmmFunction.VOLT_AC, DmmFunction.CURR_AC})
    GATED_FUNCTIONS = frozenset({DmmFunction.FREQ, DmmFunction.PER})
    SUPPORTED_FUNCTIONS = tuple(DmmFunction)

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
        """Convert a SCPI function token to the corresponding :class:`DmmFunction` enum.

        Args:
            token (str):
                Raw SCPI response token (e.g. ``"VOLT"``, ``'"VOLT:DC"'``).

        Returns:
            (DmmFunction):
                Matching :class:`DmmFunction` enum member.
        """
        cleaned = token.strip().strip("'\"").upper()
        if cleaned == "VOLT":
            return DmmFunction.VOLT_DC
        if cleaned == "CURR":
            return DmmFunction.CURR_DC
        return DmmFunction(cleaned)

    def _sense_prefix(self, function: DmmFunction | None = None) -> str:
        """Return the SCPI sense subsystem prefix for the given (or active) function.

        Keyword Parameters:
            function (DmmFunction | None):
                Function whose prefix to return. If ``None``, the active
                measurement function is queried from the instrument.

        Returns:
            (str):
                SCPI prefix string (e.g. ``"VOLT:DC"`` → ``"VOLT"``).
        """
        active = function if function is not None else self.get_measure_function()
        # DC is the optional default subsystem; AC must retain its qualifier.
        return active.value.removesuffix(":DC")

    @classmethod
    def uses_nplc(cls, function: DmmFunction, ac_bandwidth: float = 300.0) -> bool:
        """Return whether NPLC controls integration for this function and bandwidth."""
        return function not in cls.GATED_FUNCTIONS and (
            function not in cls.AC_FUNCTIONS or ac_bandwidth == 300.0
        )

    def configure_single_reading(
        self, function: DmmFunction, *, autorange: bool = True, input_range: float = 10.0,
        nplc: float = 1.0, filter_enabled: bool = False, filter_count: int = 10,
        filter_type: str = "REP", trigger_delay: float = 0.0,
        ac_bandwidth: float = 300.0, gate_time: float = 0.1,
    ) -> None:
        """Configure one immediate DMM reading without operating scanner relays.

        Args:
            function (DmmFunction): Active measurement function.

        Keyword Parameters:
            autorange (bool): Select automatic ranging for ranged functions.
            input_range (float): Fixed input range in the function's SI unit.
            nplc (float): Integration time in PLC, 0.01..10 where applicable.
            filter_enabled (bool): Enable digital averaging where supported.
            filter_count (int): Averaging count, 1..100.
            filter_type (str): REPeating (REP) or MOVing averaging.
            trigger_delay (float): Delay before conversion, in seconds.
            ac_bandwidth (float): AC lower bandwidth: 3, 30 or 300 Hz.
            gate_time (float): Frequency/period gate time, 0.01..1 seconds.

        Temperature readings use kelvin and the instrument's existing sensor
        configuration. The method sends no reset, route, scan-list or relay
        commands. No channel lists are used on the 2700.

        Raises:
            ValueError: If the function or applicable settings are invalid.
        """
        self._validate_single_input(function, autorange, input_range, filter_type, filter_count)
        self._validate_single_timing(function, trigger_delay, ac_bandwidth, nplc, gate_time)
        self.abort()
        self.write(":INIT:CONT OFF")
        self.write(":TRAC:FEED:CONT NEV")
        self.write(":FORM:DATA ASC")
        self.write(":FORM:ELEM READ")
        self.set_measure_function(function)
        self.write(":CALC:STAT OFF")
        prefix = f":SENS:{function.value}"
        if function in (DmmFunction.VOLT_DC, DmmFunction.VOLT_AC):
            self.write(f":UNIT:{function.value} V")
        if function is DmmFunction.TEMP:
            self.write(":UNIT:TEMP K")
        if function not in self.GATED_FUNCTIONS:
            self.write(f"{prefix}:REF:STAT OFF")
        if function in self.RANGED_FUNCTIONS:
            self.write(f"{prefix}:RANG:AUTO {int(autorange)}")
            if not autorange:
                self.write(f"{prefix}:RANG {input_range}")
        if function in self.AC_FUNCTIONS:
            self.write(f"{prefix}:DET:BAND {ac_bandwidth}")
        if self.uses_nplc(function, ac_bandwidth):
            self.write(f"{prefix}:NPLC {nplc}")
        if function in self.GATED_FUNCTIONS:
            self.write(f"{prefix}:APER {gate_time}")
        else:
            self.write(f"{prefix}:AVER:STAT {int(filter_enabled)}")
            self.write(f"{prefix}:AVER:COUN {filter_count}")
            self.write(f"{prefix}:AVER:TCON {filter_type}")
        self.set_trigger_source(DmmTriggerSource.IMM)
        self.set_trigger_count(1)
        self.write(":SAMP:COUN 1")
        self.write(":TRIG:DEL:AUTO OFF")
        self.write(f":TRIG:DEL {trigger_delay}")

    @staticmethod
    def _within_limits(value: float, lower: float, upper: float) -> bool:
        """Return whether a finite value falls within inclusive bounds."""
        return math.isfinite(value) and lower <= value <= upper

    def _validate_single_input(self, function, autorange, input_range, filter_type, filter_count):
        """Validate the measurement function and applicable input/filter settings."""
        if function not in self.get_capabilities().supported_functions:
            raise ValueError("Unsupported multimeter function.")
        if function in self.RANGED_FUNCTIONS and not autorange:
            if not math.isfinite(input_range) or input_range <= 0:
                raise ValueError("Multimeter range must be positive and finite.")
        if function not in self.GATED_FUNCTIONS:
            if filter_type not in ("REP", "MOV") or not 1 <= filter_count <= 100:
                raise ValueError("Multimeter filter requires REP or MOV and a count of 1..100.")

    def _validate_single_timing(self, function, trigger_delay, ac_bandwidth, nplc, gate_time):
        """Validate delay, AC bandwidth and the function's integration control."""
        if not self._within_limits(trigger_delay, 0, 999999.999):
            raise ValueError("Multimeter trigger delay must be between 0 and 999999.999 seconds.")
        if function in self.AC_FUNCTIONS and ac_bandwidth not in (3.0, 30.0, 300.0):
            raise ValueError("AC bandwidth must be 3, 30 or 300 Hz.")
        if self.uses_nplc(function, ac_bandwidth) and not self._within_limits(nplc, 0.01, 10):
            raise ValueError("Multimeter NPLC must be between 0.01 and 10.")
        if function in self.GATED_FUNCTIONS and not self._within_limits(gate_time, 0.01, 1):
            raise ValueError("Frequency/period gate time must be between 0.01 and 1 second.")

    def read_single_snapshot(self, function: DmmFunction) -> tuple[float, dict[str, float]]:
        """Read one fresh value and applicable numeric settings from the instrument.

        Args:
            function (DmmFunction): Expected configured function.

        Returns:
            (tuple[float, dict[str, float]]): Reading and queried settings. Filter
                type is encoded as 0 for repeating and 1 for moving. Timeout
                is the actual transport timeout, not an instrument readback.

        Raises:
            RuntimeError: If the function changed outside the plugin.
            ValueError: If the response is empty, malformed or has multiple readings.
        """
        with self._lock:
            if self.get_measure_function() is not function:
                raise RuntimeError("Multimeter function changed; reconfigure before reading.")
            readings = self._parse_csv_floats(self.query(":READ?"))
            if len(readings) != 1:
                raise ValueError(f"Expected one multimeter reading, received {len(readings)}.")
            prefix = f":SENS:{function.value}"
            settings = {
                "trigger_delay": float(self.query(":TRIG:DEL?")),
                "timeout": float(self.transport.timeout),
            }
            if function in self.RANGED_FUNCTIONS:
                settings["range"] = float(self.query(f"{prefix}:RANG?"))
                settings["autorange"] = float(self.query(f"{prefix}:RANG:AUTO?"))
            bandwidth = 300.0
            if function in self.AC_FUNCTIONS:
                bandwidth = float(self.query(f"{prefix}:DET:BAND?"))
                settings["ac_bandwidth"] = bandwidth
            if self.uses_nplc(function, bandwidth):
                settings["nplc"] = float(self.query(f"{prefix}:NPLC?"))
            if function in self.GATED_FUNCTIONS:
                settings["gate_time"] = float(self.query(f"{prefix}:APER?"))
            else:
                settings["filter_enabled"] = float(self.query(f"{prefix}:AVER:STAT?"))
                settings["filter_count"] = float(self.query(f"{prefix}:AVER:COUN?"))
                filter_type = self.query(f"{prefix}:AVER:TCON?").strip().upper()
                if not filter_type.startswith(("REP", "MOV")):
                    raise ValueError(f"Unexpected multimeter filter type: {filter_type!r}.")
                settings["filter_type"] = float(filter_type.startswith("MOV"))
            return readings[0], settings

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
