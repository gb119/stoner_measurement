"""Keithley 2400 Series SourceMeter driver.

The Keithley 2400 is a SCPI-compliant source-measure unit (SMU) capable of
sourcing voltage (±210 V) or current (±1.05 A) while simultaneously measuring
the complementary quantity with high precision.

This driver implements the :class:`~stoner_measurement.instruments.source_meter.SourceMeter`
abstract interface using the :class:`~stoner_measurement.instruments.protocol.scpi.ScpiProtocol`
for all communication.

References:
    Keithley 2400 Series SourceMeter Reference Manual (2400S-900-01).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.source_meter import (
    MeasureFunction,
    SourceMeter,
    SourceMeterCapabilities,
    SourceMode,
    SourceSweepConfiguration,
    SweepSpacing,
    TriggerModelConfiguration,
)
from stoner_measurement.instruments.transport.base import BaseTransport

#: Valid measurement functions for Keithley 24xx SMUs.
_VALID_MEASURE_FUNCTIONS = frozenset({"VOLT", "CURR", "RES"})

#: NPLC range supported by the Keithley 2400.
_NPLC_MIN = 0.01
_NPLC_MAX = 10.0

_VALID_FORMAT_ELEMENTS = frozenset({"VOLT", "CURR", "RES", "TIME", "STAT"})


class FilterType(Enum):
    """Digital reading-filter type supported by the Keithley 2400."""

    REPEAT = "REP"
    MOVING = "MOV"


class TerminalSelection(Enum):
    """Source/output terminal selection for the Keithley 2400."""

    FRONT = "FRON"
    REAR = "REAR"


class SenseWiringMode(Enum):
    """2-wire or 4-wire remote-sense configuration."""

    TWO_WIRE = "2W"
    FOUR_WIRE = "4W"



@dataclass(frozen=True)
class BufferReading:
    """Parsed reading-buffer record from a Keithley 2400 trace transfer."""

    voltage: float | None = None
    current: float | None = None
    resistance: float | None = None
    time: float | None = None
    status: float | None = None


class Keithley2400(SourceMeter):
    """Driver for the Keithley 2400 Series SourceMeter.

    Implements :class:`~stoner_measurement.instruments.source_meter.SourceMeter`
    using SCPI commands specific to the Keithley 2400 instrument family.
    A :class:`~stoner_measurement.instruments.protocol.scpi.ScpiProtocol`
    instance is used by default; the transport must be supplied by the caller.

    Attributes:
        transport (BaseTransport):
            Transport layer (serial, GPIB, or Ethernet).
        protocol (BaseProtocol):
            Protocol instance (defaults to :class:`ScpiProtocol`).

    Examples:
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import ScpiProtocol
        >>> from stoner_measurement.instruments.keithley import Keithley2400
        >>> t = NullTransport(responses=[
        ...     b"KEITHLEY INSTRUMENTS INC.,MODEL 2400,1234567,C32 Mar  4 2011\\n",
        ... ])
        >>> k = Keithley2400(transport=t)
        >>> k.connect()
        >>> k.identify()
        'KEITHLEY INSTRUMENTS INC.,MODEL 2400,1234567,C32 Mar  4 2011'
        >>> k.disconnect()
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
    ) -> None:
        """Initialise the Keithley 2400 driver.

        Args:
            transport (BaseTransport):
                Transport layer for the physical connection.

        Keyword Parameters:
            protocol (BaseProtocol | None):
                Protocol to use.  Defaults to a :class:`ScpiProtocol` instance
                if ``None`` is supplied.
        """
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_measure_function(function_name: str) -> MeasureFunction:
        """Normalise a function token returned by SCPI into a MeasureFunction enum value.

        Args:
            function_name (str):
                Raw function token returned by the instrument.

        Returns:
            (MeasureFunction):
                Normalised measurement function.

        Raises:
            ValueError:
                If the token does not map to a known MeasureFunction value.
        """
        token = function_name.strip().strip("'\"").upper()
        if ":" in token:
            token = token.split(":", 1)[0]
        return MeasureFunction(token)

    @staticmethod
    def _parse_csv_floats(values: str) -> tuple[float, ...]:
        """Parse a comma-separated float response payload.

        Args:
            values (str):
                Comma-separated numeric payload.

        Returns:
            (tuple[float, ...]):
                Parsed numeric values.

        Raises:
            ValueError:
                If the payload is malformed or cannot be parsed as floats.
        """
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

    def _source_prefix(self, source_mode: SourceMode | None = None) -> str:
        """Return :SOUR command prefix for the selected source mode.

        Args:
            source_mode (SourceMode | None):
                Optional source mode. If ``None``, query the instrument.

        Returns:
            (str):
                ``":SOUR:VOLT"`` for voltage source mode, otherwise
                ``":SOUR:CURR"``.
        """
        mode = source_mode if source_mode is not None else self.get_source_mode()
        return ":SOUR:VOLT" if mode == SourceMode.VOLT else ":SOUR:CURR"

    @staticmethod
    def _normalise_format_element(element: str) -> str:
        """Normalise a :FORM:ELEM token to the instrument's canonical short name.

        Args:
            element (str):
                Raw format-element token.

        Returns:
            (str):
                Canonical short-format element name accepted by the driver.

        Raises:
            ValueError:
                If *element* is not one of the supported trace-format fields.
        """
        token = element.strip().strip("'\"").upper()
        if ":" in token:
            token = token.split(":", 1)[0]
        if token not in _VALID_FORMAT_ELEMENTS:
            raise ValueError(
                f"Invalid format element {element!r}; "
                f"must be drawn from {sorted(_VALID_FORMAT_ELEMENTS)!r}."
            )
        return token

    @staticmethod
    def _coerce_optional_float(value: float | None) -> float | None:
        """Return *value* as ``float`` when present, otherwise ``None``.

        Args:
            value (float | None):
                Value to normalise.

        Returns:
            (float | None):
                ``None`` if *value* is ``None``, otherwise ``float(value)``.
        """
        if value is None:
            return None
        return float(value)

    def _parse_buffer_records(
        self,
        payload: str,
        elements: tuple[str, ...],
    ) -> tuple[BufferReading, ...]:
        """Parse a trace-buffer payload into structured reading records.

        Args:
            payload (str):
                Raw comma-separated buffer payload returned by the instrument.
            elements (tuple[str, ...]):
                Ordered format-element names describing each record.

        Returns:
            (tuple[BufferReading, ...]):
                Parsed structured reading records.

        Raises:
            ValueError:
                If *elements* is empty or the payload width does not match the
                configured record format.
        """
        values = self._parse_csv_floats(payload)
        width = len(elements)
        if width == 0:
            raise ValueError("At least one format element must be configured.")
        if len(values) % width:
            raise ValueError(
                f"Malformed buffer payload with {len(values)} values for format width {width}."
            )

        records: list[BufferReading] = []
        for index in range(0, len(values), width):
            row = dict(zip(elements, values[index : index + width], strict=False))
            records.append(
                BufferReading(
                    voltage=self._coerce_optional_float(row.get("VOLT")),
                    current=self._coerce_optional_float(row.get("CURR")),
                    resistance=self._coerce_optional_float(row.get("RES")),
                    time=self._coerce_optional_float(row.get("TIME")),
                    status=self._coerce_optional_float(row.get("STAT")),
                )
            )
        return tuple(records)

    def _compliance_prefix(self, source_mode: SourceMode | None = None) -> str:
        """Return the sense compliance prefix for the selected source mode.

        Args:
            source_mode (SourceMode | None):
                Source mode to evaluate. If ``None``, use the driver's
                backward-compatible default interpretation.

        Returns:
            (str):
                ``":SENS:CURR:PROT"`` for voltage source mode, otherwise
                ``":SENS:VOLT:PROT"``.
        """
        mode = source_mode if source_mode is not None else SourceMode.VOLT
        return ":SENS:CURR:PROT" if mode == SourceMode.VOLT else ":SENS:VOLT:PROT"

    def _source_prefix_for_mode(self, source_mode: SourceMode | None = None) -> str:
        """Return the source subsystem prefix for the selected source mode.

        Args:
            source_mode (SourceMode | None):
                Optional source mode. If ``None``, query the instrument.

        Returns:
            (str):
                ``":SOUR:VOLT"`` for voltage source mode, otherwise
                ``":SOUR:CURR"``.
        """
        mode = source_mode if source_mode is not None else self.get_source_mode()
        return ":SOUR:VOLT" if mode == SourceMode.VOLT else ":SOUR:CURR"

    def _sense_prefix_for_mode(self, source_mode: SourceMode | None = None) -> str:
        """Return the sensed quantity prefix complementary to the source mode.

        Args:
            source_mode (SourceMode | None):
                Optional source mode. If ``None``, query the instrument.

        Returns:
            (str):
                ``":SENS:CURR"`` for voltage source mode, otherwise
                ``":SENS:VOLT"``.
        """
        mode = source_mode if source_mode is not None else self.get_source_mode()
        return ":SENS:CURR" if mode == SourceMode.VOLT else ":SENS:VOLT"

    def _parse_error_response(self, response: str) -> tuple[int | None, str]:
        """Parse a ``:SYST:ERR?`` response into numeric code and message.

        Args:
            response (str):
                Raw error-queue response string from the instrument.

        Returns:
            (tuple[int | None, str]):
                Parsed numeric error code, if available, and the associated
                message text.
        """
        text = response.strip()
        if "," not in text:
            return None, text
        code_text, message = text.split(",", 1)
        try:
            code = int(code_text.strip())
        except ValueError:
            code = None
        return code, message.strip().strip('"')

    # ------------------------------------------------------------------
    # Source mode
    # ------------------------------------------------------------------

    def get_source_mode(self) -> SourceMode:
        """Return the active source mode.

        Returns:
            (SourceMode):
                :attr:`~SourceMode.VOLT` if the instrument is sourcing voltage,
                :attr:`~SourceMode.CURR` if it is sourcing current.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> from stoner_measurement.instruments.source_meter import SourceMode
            >>> t = NullTransport(responses=[b"VOLT\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.get_source_mode()
            <SourceMode.VOLT: 'VOLT'>
            >>> k.disconnect()
        """
        return SourceMode(self.query(":SOUR:FUNC:MODE?"))

    def set_source_mode(self, mode: SourceMode) -> None:
        """Set the source mode.

        Args:
            mode (SourceMode):
                :attr:`~SourceMode.VOLT` for voltage source or
                :attr:`~SourceMode.CURR` for current source.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> from stoner_measurement.instruments.source_meter import SourceMode
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.set_source_mode(SourceMode.VOLT)
            >>> t.write_log[-1]
            b':SOUR:FUNC:MODE VOLT\\n'
            >>> k.disconnect()
        """
        self.write(f":SOUR:FUNC:MODE {mode.value}")

    # ------------------------------------------------------------------
    # Source level
    # ------------------------------------------------------------------

    def get_source_level(self) -> float:
        """Return the programmed source level in volts or amps.

        Returns:
            (float):
                Source amplitude in the unit corresponding to the active
                source mode.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"1.000000E+00\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.get_source_level()
            1.0
            >>> k.disconnect()
        """
        return float(self.query(":SOUR:AMPL?"))

    def set_source_level(self, value: float) -> None:
        """Set the source output level.

        Args:
            value (float):
                Output amplitude in volts (voltage mode) or amps (current mode).

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.set_source_level(1.5)
            >>> t.write_log[-1]
            b':SOUR:AMPL 1.5\\n'
            >>> k.disconnect()
        """
        self.write(f":SOUR:AMPL {value}")

    # ------------------------------------------------------------------
    # Compliance
    # ------------------------------------------------------------------

    def get_compliance(self, source_mode: SourceMode | None = None) -> float:
        """Return the compliance limit in amps (voltage mode) or volts (current mode).

        Returns:
            (float):
                Compliance value.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"1.000000E-01\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.get_compliance()
            0.1
            >>> k.disconnect()
        """
        return float(self.query(f"{self._compliance_prefix(source_mode)}?"))

    def set_compliance(self, value: float, source_mode: SourceMode | None = None) -> None:
        """Set the compliance limit.

        Args:
            value (float):
                Compliance in amps (voltage mode) or volts (current mode).

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.set_compliance(0.05)
            >>> t.write_log[-1]
            b':SENS:CURR:PROT 0.05\\n'
            >>> k.disconnect()
        """
        self.write(f"{self._compliance_prefix(source_mode)} {value}")

    def get_compliance_from_resistance(self, source_level: float | None = None) -> float:
        """Return the effective compliance derived from a resistance threshold.

        In voltage-source mode this returns the current compliance corresponding
        to a minimum allowed resistance. In current-source mode it returns the
        voltage compliance corresponding to a maximum allowed resistance.
        """
        level = self.get_source_level() if source_level is None else float(source_level)
        return self.get_compliance() / abs(level) if abs(level) > 0.0 else float("inf")

    def set_compliance_from_resistance(
        self,
        resistance: float,
        *,
        source_level: float | None = None,
        source_mode: SourceMode | None = None,
    ) -> float:
        """Set compliance from a resistance threshold and return the set limit.

        For current-source mode, ``compliance = |I| * resistance`` so the
        resistance is interpreted as a maximum allowed resistance.

        For voltage-source mode, ``compliance = |V| / resistance`` so the
        resistance is interpreted as a minimum allowed resistance.
        """
        if resistance <= 0.0:
            raise ValueError("Resistance threshold must be positive.")
        mode = source_mode if source_mode is not None else self.get_source_mode()
        level = self.get_source_level() if source_level is None else float(source_level)
        if mode == SourceMode.CURR:
            compliance = abs(level) * resistance
        else:
            compliance = abs(level) / resistance
        self.set_compliance(compliance, mode)
        return compliance

    # ------------------------------------------------------------------
    # NPLC
    # ------------------------------------------------------------------

    def get_nplc(self) -> float:
        """Return the integration time in power-line cycles.

        Returns:
            (float):
                Integration time in power-line cycles.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"1.000000E+00\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.get_nplc()
            1.0
            >>> k.disconnect()
        """
        return float(self.query(":SENS:VOLT:NPLC?"))

    def set_nplc(self, value: float) -> None:
        """Set the integration time in power-line cycles.

        Args:
            value (float):
                Integration time (0.01–10 PLC).

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *value* is outside [0.01, 10].

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.set_nplc(5.0)
            >>> t.write_log  # two writes: voltage sense then current sense
            [b':SENS:VOLT:NPLC 5.0\\n', b':SENS:CURR:NPLC 5.0\\n']
            >>> k.disconnect()
        """
        if not _NPLC_MIN <= value <= _NPLC_MAX:
            raise ValueError(f"NPLC {value} out of range [{_NPLC_MIN}, {_NPLC_MAX}].")
        self.write(f":SENS:VOLT:NPLC {value}")
        self.write(f":SENS:CURR:NPLC {value}")

    # ------------------------------------------------------------------
    # Source / sense ranges and advanced measurement options
    # ------------------------------------------------------------------

    def set_source_range(self, value: float, source_mode: SourceMode | None = None) -> None:
        """Set the fixed source range for the selected source function.

        Args:
            value (float):
                Positive source range in volts or amps.
            source_mode (SourceMode | None):
                Optional explicit source mode. If ``None``, the active mode is
                queried from the instrument.

        Raises:
            ValueError:
                If *value* is not positive.
        """
        if value <= 0.0:
            raise ValueError("Source range must be positive.")
        self.write(f"{self._source_prefix(source_mode)}:RANG {value}")

    def set_sense_range(self, value: float, source_mode: SourceMode | None = None) -> None:
        """Set the fixed measurement range for the sensed quantity.

        Args:
            value (float):
                Positive sense range in volts or amps.
            source_mode (SourceMode | None):
                Optional explicit source mode. If ``None``, the active mode is
                queried from the instrument.

        Raises:
            ValueError:
                If *value* is not positive.
        """
        if value <= 0.0:
            raise ValueError("Sense range must be positive.")
        self.write(f"{self._sense_prefix_for_mode(source_mode)}:RANG {value}")

    def set_source_autorange(self, enabled: bool, source_mode: SourceMode | None = None) -> None:
        """Enable or disable source autoranging for the selected source function.

        Args:
            enabled (bool):
                ``True`` to enable autorange, ``False`` for fixed range mode.
            source_mode (SourceMode | None):
                Optional explicit source mode. If ``None``, the active mode is
                queried from the instrument.
        """
        self.write(f"{self._source_prefix(source_mode)}:RANG:AUTO {1 if enabled else 0}")

    def set_sense_autorange(self, enabled: bool, source_mode: SourceMode | None = None) -> None:
        """Enable or disable measurement autoranging for the sensed quantity.

        Args:
            enabled (bool):
                ``True`` to enable autorange, ``False`` for fixed range mode.
            source_mode (SourceMode | None):
                Optional explicit source mode. If ``None``, the active mode is
                queried from the instrument.
        """
        self.write(f"{self._sense_prefix_for_mode(source_mode)}:RANG:AUTO {1 if enabled else 0}")

    def set_remote_sense(self, enabled: bool) -> None:
        """Enable or disable 4-wire remote sensing.

        Args:
            enabled (bool):
                ``True`` for 4-wire sensing, ``False`` for 2-wire sensing.
        """
        self.write(f":SYST:RSEN {1 if enabled else 0}")

    def set_terminal_selection(self, terminal: TerminalSelection) -> None:
        """Select the front or rear source/output terminals.

        Args:
            terminal (TerminalSelection):
                Terminal selection enum value.
        """
        self.write(f":ROUT:TERM {terminal.value}")

    def set_filter_enabled(self, enabled: bool, source_mode: SourceMode | None = None) -> None:
        """Enable or disable the digital averaging filter on the sensed quantity.

        Args:
            enabled (bool):
                ``True`` to enable the filter, ``False`` to disable it.
            source_mode (SourceMode | None):
                Optional explicit source mode. If ``None``, the active mode is
                queried from the instrument.
        """
        self.write(f"{self._sense_prefix_for_mode(source_mode)}:AVER:STAT {1 if enabled else 0}")

    def set_filter_count(self, count: int, source_mode: SourceMode | None = None) -> None:
        """Set the digital averaging-filter count for the sensed quantity.

        Args:
            count (int):
                Number of readings in the digital filter window.
            source_mode (SourceMode | None):
                Optional explicit source mode. If ``None``, the active mode is
                queried from the instrument.

        Raises:
            ValueError:
                If *count* is not positive.
        """
        if count <= 0:
            raise ValueError("Filter count must be positive.")
        self.write(f"{self._sense_prefix_for_mode(source_mode)}:AVER:COUN {count}")

    def set_filter_type(self, filter_type: FilterType, source_mode: SourceMode | None = None) -> None:
        """Set the digital filter type for the sensed quantity.

        Args:
            filter_type (FilterType):
                Filter type enum value.
            source_mode (SourceMode | None):
                Optional explicit source mode. If ``None``, the active mode is
                queried from the instrument.
        """
        self.write(f"{self._sense_prefix_for_mode(source_mode)}:AVER:TCON {filter_type.value}")

    def set_median_filter_enabled(self, enabled: bool, source_mode: SourceMode | None = None) -> None:
        """Enable or disable the median filter on the sensed quantity.

        Args:
            enabled (bool):
                ``True`` to enable the median filter, ``False`` to disable it.
            source_mode (SourceMode | None):
                Optional explicit source mode. If ``None``, the active mode is
                queried from the instrument.
        """
        self.write(f"{self._sense_prefix_for_mode(source_mode)}:MED:STAT {1 if enabled else 0}")

    # ------------------------------------------------------------------
    # Measurements
    # ------------------------------------------------------------------

    def get_measure_functions(self) -> tuple[MeasureFunction, ...]:
        """Return enabled measurement functions."""
        payload = self.query(":SENS:FUNC?")
        return tuple(
            self._normalise_measure_function(function_name)
            for function_name in payload.split(",")
            if function_name.strip()
        )

    def set_measure_functions(self, functions: tuple[MeasureFunction, ...]) -> None:
        """Enable one or more measurement functions."""
        if not functions:
            raise ValueError("At least one measurement function must be provided.")
        invalid = [f for f in functions if f.value not in _VALID_MEASURE_FUNCTIONS]
        if invalid:
            raise ValueError(
                f"Invalid measurement function(s) {[f.value for f in invalid]!r}; "
                f"must be drawn from {_VALID_MEASURE_FUNCTIONS}."
            )
        quoted = ",".join(f"'{f.value}'" for f in functions)
        self.write(f":SENS:FUNC {quoted}")

    def measure_voltage(self) -> float:
        """Trigger a voltage measurement and return the result in volts.

        Configures the sense function to voltage, triggers a single reading,
        and returns the parsed floating-point result.

        Returns:
            (float):
                Measured voltage in volts.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"+1.234567E+00\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.measure_voltage()
            1.234567
            >>> k.disconnect()
        """
        self.write(":SENS:FUNC 'VOLT'")
        return float(self.query(":READ?").split(",")[0])

    def measure_current(self) -> float:
        """Trigger a current measurement and return the result in amps.

        Configures the sense function to current, triggers a single reading,
        and returns the parsed floating-point result.

        Returns:
            (float):
                Measured current in amps.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"+1.000000E-03\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.measure_current()
            0.001
            >>> k.disconnect()
        """
        self.write(":SENS:FUNC 'CURR'")
        return float(self.query(":READ?").split(",")[0])

    def measure_resistance(self) -> float:
        """Trigger a resistance measurement and return the result in ohms.

        Returns:
            (float):
                Measured resistance in ohms.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"+1.200000E+03\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.measure_resistance()
            1200.0
            >>> k.disconnect()
        """
        self.write(":SENS:FUNC 'RES'")
        return float(self.query(":READ?").split(",")[0])

    def measure_power(self) -> float:
        """Trigger simultaneous voltage/current measurements and return power in watts.

        Returns:
            (float):
                Measured power in watts.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If the instrument response does not include both voltage and current.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"+2.000000E+00,+5.000000E-01\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.measure_power()
            1.0
            >>> k.disconnect()
        """
        self.write(":SENS:FUNC 'VOLT','CURR'")
        values = self._parse_csv_floats(self.query(":READ?"))
        if len(values) < 2:
            raise ValueError("Instrument did not return both voltage and current readings for power calculation.")
        return values[0] * values[1]

    # ------------------------------------------------------------------
    # Sweep, source delay, triggering, and buffer control
    # ------------------------------------------------------------------

    def configure_source_sweep(self, config: SourceSweepConfiguration) -> None:
        """Configure linear, logarithmic, or list source sweeps.

        Args:
            config (SourceSweepConfiguration):
                Sweep configuration payload.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If the delay, point count, or list values are invalid.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> from stoner_measurement.instruments.source_meter import (
            ...     SourceSweepConfiguration, SweepSpacing,
            ... )
            >>> t = NullTransport(responses=[b"VOLT\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.configure_source_sweep(
            ...     SourceSweepConfiguration(
            ...         start=0.0, stop=1.0, points=5,
            ...         spacing=SweepSpacing.LIN, delay=0.01,
            ...     )
            ... )
            >>> t.write_log[-1]
            b':SOUR:DEL 0.01\\n'
            >>> k.disconnect()
        """
        if config.delay < 0.0:
            raise ValueError("Sweep delay must be non-negative.")

        if config.spacing is SweepSpacing.LOG and (config.points is None or config.points < 2):
            raise ValueError("LOG sweep requires at least 2 points.")

        source_mode = self.get_source_mode()
        source_prefix = self._source_prefix(source_mode)
        self.write(f":SOUR:FUNC:MODE {source_mode.value}")

        if config.spacing in (SweepSpacing.LIN, SweepSpacing.LOG):
            spacing_str = config.spacing.value
            if config.points < 2:
                raise ValueError(f"{spacing_str} sweep requires at least 2 points.")
            self.write(f"{source_prefix}:MODE SWE")
            self.write(f"{source_prefix}:STAR {config.start}")
            self.write(f"{source_prefix}:STOP {config.stop}")
            self.write(f":SOUR:SWE:POIN {config.points}")
            self.write(f":SOUR:SWE:SPAC {spacing_str}")
            self.set_source_delay(config.delay)
            return

        if config.values is None or len(config.values) == 0:
            raise ValueError("Custom/list sweep requires at least one value.")
        values = ",".join(str(value) for value in config.values)
        self.write(f"{source_prefix}:MODE LIST")
        self.write(f":SOUR:LIST:{source_mode.value} {values}")
        self.write(f":SOUR:SWE:POIN {len(config.values)}")
        self.set_source_delay(config.delay)

    def set_source_delay(self, delay: float) -> None:
        """Set source delay before each measurement trigger.

        Args:
            delay (float):
                Source delay in seconds.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *delay* is negative.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.set_source_delay(0.01)
            >>> t.write_log[-1]
            b':SOUR:DEL 0.01\\n'
            >>> k.disconnect()
        """
        if delay < 0.0:
            raise ValueError("Source delay must be non-negative.")
        self.write(f":SOUR:DEL {delay}")

    def get_source_delay(self) -> float:
        """Return source delay before each measurement trigger.

        Returns:
            (float):
                Source delay in seconds.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"1.000000E-02\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.get_source_delay()
            0.01
            >>> k.disconnect()
        """
        return float(self.query(":SOUR:DEL?"))

    def configure_trigger_model(self, config: TriggerModelConfiguration) -> None:
        """Configure trigger and arm model settings.

        Args:
            config (TriggerModelConfiguration):
                Trigger and arm model configuration.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If trigger or arm counts are not positive, or trigger delay is
                negative.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> from stoner_measurement.instruments.source_meter import (
            ...     TriggerModelConfiguration, TriggerSource,
            ... )
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.configure_trigger_model(
            ...     TriggerModelConfiguration(
            ...         trigger_source=TriggerSource.BUS,
            ...         trigger_count=2,
            ...         trigger_delay=0.1,
            ...     )
            ... )
            >>> t.write_log[0]
            b':TRIG:SOUR BUS\\n'
            >>> k.disconnect()
        """
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
        """Arm and start the trigger model.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.initiate()
            >>> t.write_log[-1]
            b':INIT\\n'
            >>> k.disconnect()
        """
        self.write(":INIT")

    def abort(self) -> None:
        """Abort trigger execution.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.abort()
            >>> t.write_log[-1]
            b':ABOR\\n'
            >>> k.disconnect()
        """
        self.write(":ABOR")

    def wait_for_operation_complete(self) -> None:
        """Block until prior instrument operations have completed."""
        self.query("*OPC?")

    def reset_timestamp(self) -> None:
        """Reset the instrument's absolute timestamp counter."""
        self.write(":SYST:TIME:RES")

    def set_format_data_ascii(self) -> None:
        """Select ASCII transfer format for reading data."""
        self.write(":FORM:DATA ASC")

    def set_format_elements(self, elements: tuple[str, ...]) -> None:
        """Set the reading elements returned by READ/FETCH/TRACE queries."""
        if not elements:
            raise ValueError("At least one format element must be provided.")
        normalised = tuple(self._normalise_format_element(element) for element in elements)
        self.write(f":FORM:ELEM {','.join(normalised)}")

    def set_trace_feed_sense(self) -> None:
        """Configure the trace buffer to store raw sense readings."""
        self.write(":TRAC:FEED SENS")

    def set_trace_feed_continuous_next(self) -> None:
        """Enable trace-buffer fill on the next initiated acquisition."""
        self.write(":TRAC:FEED:CONT NEXT")

    def set_trace_feed_continuous_never(self) -> None:
        """Disable trace-buffer filling."""
        self.write(":TRAC:FEED:CONT NEV")

    def get_buffer_count(self) -> int:
        """Return the actual number of readings currently stored in the buffer."""
        return int(float(self.query(":TRAC:POIN:ACT?")))

    def get_error(self) -> tuple[int | None, str]:
        """Return the oldest queued system error."""
        return self._parse_error_response(self.query(":SYST:ERR?"))

    def drain_error_queue(self) -> tuple[tuple[int | None, str], ...]:
        """Drain the system error queue until the terminating no-error entry."""
        errors: list[tuple[int | None, str]] = []
        while True:
            error = self.get_error()
            errors.append(error)
            code, message = error
            if code == 0 or message.lower() == "no error":
                break
        return tuple(errors)

    def check_error_queue(self, *, raise_on_error: bool = True) -> tuple[tuple[int | None, str], ...]:
        """Drain the error queue and optionally raise if instrument errors exist."""
        errors = self.drain_error_queue()
        real_errors = tuple(error for error in errors if error[0] != 0 and error[1].lower() != "no error")
        if raise_on_error and real_errors:
            formatted = "; ".join(
                f"{code if code is not None else '?'}:{message}" for code, message in real_errors
            )
            raise RuntimeError(f"Keithley 2400 reported SCPI errors: {formatted}")
        return errors

    def read_buffer_records(
        self,
        elements: tuple[str, ...],
        count: int | None = None,
    ) -> tuple[BufferReading, ...]:
        """Read and parse trace-buffer readings according to explicit format elements.

        Args:
            elements (tuple[str, ...]):
                Ordered :FORM:ELEM configuration used for the transfer.
            count (int | None):
                Optional number of readings to read from the start of the buffer.

        Returns:
            (tuple[BufferReading, ...]):
                Parsed buffer records.
        """
        normalised = tuple(self._normalise_format_element(element) for element in elements)
        self.set_format_data_ascii()
        self.set_format_elements(normalised)
        if count is None:
            payload = self.query(":TRAC:DATA?")
        else:
            if count <= 0:
                raise ValueError("Requested buffer count must be positive.")
            payload = self.query(f":TRAC:DATA? 1,{count}")
        return self._parse_buffer_records(payload, normalised)

    def configure_buffer(
        self,
        size: int,
        *,
        elements: tuple[str, ...] = ("VOLT", "CURR", "RES", "TIME", "STAT"),
    ) -> None:
        """Configure the trace buffer and transfer format for buffered acquisition."""
        self.set_format_data_ascii()
        self.set_format_elements(elements)
        self.clear_buffer()
        self.set_buffer_size(size)
        self.set_trace_feed_sense()
        self.set_trace_feed_continuous_next()

    def safe_output_off(self) -> None:
        """Best-effort output disable helper for cleanup paths."""
        try:
            source_mode = self.get_source_mode()
            self.set_source_level(0.0)
            self.write(f"{self._source_prefix(source_mode)}:MODE FIX")
        except Exception:
            pass
        self.enable_output(False)

    def set_buffer_size(self, size: int) -> None:
        """Set reading buffer capacity.

        Args:
            size (int):
                Number of readings for the buffer to retain.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *size* is not positive.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.set_buffer_size(100)
            >>> t.write_log[-1]
            b':TRAC:POIN 100\\n'
            >>> k.disconnect()
        """
        if size <= 0:
            raise ValueError("Buffer size must be positive.")
        self.write(f":TRAC:POIN {size}")

    def get_buffer_size(self) -> int:
        """Return reading buffer capacity.

        Returns:
            (int):
                Number of readings that can be stored.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"250\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.get_buffer_size()
            250
            >>> k.disconnect()

        Notes:
            Some instruments may return the buffer size in exponential format.
            The response is therefore parsed as ``float`` before conversion to
            ``int``.
        """
        return int(float(self.query(":TRAC:POIN?")))

    def clear_buffer(self) -> None:
        """Clear the reading buffer.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.clear_buffer()
            >>> t.write_log[-1]
            b':TRAC:CLE\\n'
            >>> k.disconnect()
        """
        self.write(":TRAC:CLE")

    def read_buffer(self, count: int | None = None) -> tuple[float, ...]:
        """Read buffered readings from the internal trace buffer.

        Args:
            count (int | None):
                Optional number of readings to return from the start of the buffer.

        Returns:
            (tuple[float, ...]):
                Flat tuple of numeric readings.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *count* is provided and is not positive.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"1.0,2.0\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.read_buffer()
            (1.0, 2.0)
            >>> k.disconnect()
        """
        if count is None:
            response = self.query(":TRAC:DATA?")
            return self._parse_csv_floats(response)
        if count <= 0:
            raise ValueError("Requested buffer count must be positive.")
        response = self.query(f":TRAC:DATA? 1,{count}")
        return self._parse_csv_floats(response)

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def get_capabilities(self) -> SourceMeterCapabilities:
        """Return the capability descriptor for the Keithley 2400 driver.

        Returns:
            (SourceMeterCapabilities):
                Descriptor indicating that this driver supports measurement
                function selection, source sweeps, source delay, trigger/arm
                model configuration, and reading buffer control.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> caps = Keithley2400(transport=NullTransport()).get_capabilities()
            >>> caps.has_sweep
            True
            >>> caps.has_buffer
            True
        """
        return SourceMeterCapabilities(
            has_function_selection=True,
            has_sweep=True,
            has_source_delay=True,
            has_trigger_model=True,
            has_buffer=True,
        )

    # ------------------------------------------------------------------
    # Output control
    # ------------------------------------------------------------------

    def output_enabled(self) -> bool:
        """Return ``True`` if the source output is currently enabled.

        Returns:
            (bool):
                ``True`` when the output is active.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"0\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.output_enabled()
            False
            >>> k.disconnect()
        """
        return self.query(":OUTP:STAT?") == "1"

    def enable_output(self, state: bool) -> None:
        """Enable or disable the source output.

        Args:
            state (bool):
                ``True`` to turn the output on, ``False`` to turn it off.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.enable_output(True)
            >>> t.write_log[-1]
            b':OUTP:STAT 1\\n'
            >>> k.enable_output(False)
            >>> t.write_log[-1]
            b':OUTP:STAT 0\\n'
            >>> k.disconnect()
        """
        self.write(f":OUTP:STAT {1 if state else 0}")


class Keithley2410(Keithley2400):
    """Driver for the Keithley 2410 SourceMeter.

    This model uses command-level compatibility with the Keithley 2400
    implementation for core source/measure, sweep, trigger, and buffer features.
    """


class Keithley2450(Keithley2400):
    """Driver for the Keithley 2450 SourceMeter.

    This model supports a SCPI command subset that is compatible with the
    Keithley 2400 implementation exposed by this class hierarchy.
    """
