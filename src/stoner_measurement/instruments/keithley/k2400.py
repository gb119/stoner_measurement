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

from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.source_meter import (
    MeasureFunction,
    SourceMeter,
    SourceMode,
    SourceSweepConfiguration,
    SweepSpacing,
    TriggerModelConfiguration,
)
from stoner_measurement.instruments.transport.base import BaseTransport

#: Valid source modes accepted by the Keithley 2400.
_VALID_MODES = frozenset({"VOLT", "CURR"})

#: Valid measurement functions for Keithley 24xx SMUs.
_VALID_MEASURE_FUNCTIONS = frozenset({"VOLT", "CURR", "RES"})

#: Supported sweep spacing modes for Keithley 24xx SMUs.
_VALID_SWEEP_SPACING = frozenset({"LIN", "LOG", "LIST"})

#: Supported trigger sources for Keithley 24xx SMUs.
_VALID_TRIGGER_SOURCES = frozenset({"IMM", "BUS", "EXT", "TLIN", "TIM"})

#: NPLC range supported by the Keithley 2400.
_NPLC_MIN = 0.01
_NPLC_MAX = 10.0


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
        """Normalise a function token returned by SCPI into API form."""
        token = function_name.strip().strip("'\"").upper()
        if ":" in token:
            token = token.split(":", 1)[0]
        return token

    @staticmethod
    def _parse_csv_floats(values: str) -> tuple[float, ...]:
        """Parse a comma-separated float response payload."""
        stripped = values.strip()
        if not stripped:
            return ()
        return tuple(float(token.strip()) for token in stripped.split(",") if token.strip())

    def _source_prefix(self) -> str:
        """Return :SOUR command prefix for the currently active source mode."""
        return ":SOUR:VOLT" if self.get_source_mode() == "VOLT" else ":SOUR:CURR"

    # ------------------------------------------------------------------
    # Source mode
    # ------------------------------------------------------------------

    def get_source_mode(self) -> SourceMode:
        """Return the active source mode (``"VOLT"`` or ``"CURR"``).

        Returns:
            (str):
                ``"VOLT"`` if the instrument is sourcing voltage, or
                ``"CURR"`` if it is sourcing current.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport(responses=[b"VOLT\\n"])
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.get_source_mode()
            'VOLT'
            >>> k.disconnect()
        """
        return self.query(":SOUR:FUNC:MODE?")

    def set_source_mode(self, mode: SourceMode) -> None:
        """Set the source mode.

        Args:
            mode (str):
                ``"VOLT"`` for voltage source or ``"CURR"`` for current source.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *mode* is not ``"VOLT"`` or ``"CURR"``.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.keithley import Keithley2400
            >>> t = NullTransport()
            >>> k = Keithley2400(transport=t)
            >>> k.connect()
            >>> k.set_source_mode("VOLT")
            >>> t.write_log[-1]
            b':SOUR:FUNC:MODE VOLT\\n'
            >>> k.disconnect()
        """
        if mode not in _VALID_MODES:
            raise ValueError(f"Invalid source mode {mode!r}; must be one of {_VALID_MODES}.")
        self.write(f":SOUR:FUNC:MODE {mode}")

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

    def get_compliance(self) -> float:
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
        return float(self.query(":SENS:CURR:PROT?"))

    def set_compliance(self, value: float) -> None:
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
        self.write(f":SENS:CURR:PROT {value}")

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
            >>> t.write_log[-1]
            b':SENS:VOLT:NPLC 5.0\\n'
            >>> k.disconnect()
        """
        if not (_NPLC_MIN <= value <= _NPLC_MAX):
            raise ValueError(f"NPLC {value} out of range [{_NPLC_MIN}, {_NPLC_MAX}].")
        self.write(f":SENS:VOLT:NPLC {value}")
        self.write(f":SENS:CURR:NPLC {value}")

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
        normalised = tuple(self._normalise_measure_function(function_name) for function_name in functions)
        invalid = [function_name for function_name in normalised if function_name not in _VALID_MEASURE_FUNCTIONS]
        if invalid:
            raise ValueError(
                f"Invalid measurement function(s) {invalid!r}; must be drawn from {_VALID_MEASURE_FUNCTIONS}."
            )
        quoted = ",".join(f"'{function_name}'" for function_name in normalised)
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
        """Trigger a resistance measurement and return the result in ohms."""
        self.write(":SENS:FUNC 'RES'")
        return float(self.query(":READ?").split(",")[0])

    def measure_power(self) -> float:
        """Trigger simultaneous voltage/current measurements and return power in watts."""
        self.write(":SENS:FUNC 'VOLT','CURR'")
        values = self._parse_csv_floats(self.query(":READ?"))
        if len(values) < 2:
            raise ValueError("Instrument did not return both voltage and current readings for power calculation.")
        return values[0] * values[1]

    # ------------------------------------------------------------------
    # Sweep, source delay, triggering, and buffer control
    # ------------------------------------------------------------------

    def configure_source_sweep(self, config: SourceSweepConfiguration) -> None:
        """Configure linear, logarithmic, or list source sweeps."""
        spacing = config.spacing.upper()
        if spacing not in _VALID_SWEEP_SPACING:
            raise ValueError(f"Invalid sweep spacing {config.spacing!r}; must be one of {_VALID_SWEEP_SPACING}.")
        if config.delay < 0.0:
            raise ValueError("Sweep delay must be non-negative.")

        source_mode = self.get_source_mode()
        source_prefix = self._source_prefix()
        self.write(f":SOUR:FUNC:MODE {source_mode}")

        if spacing in {"LIN", "LOG"}:
            if config.points < 2:
                raise ValueError("Linear/log sweeps require at least 2 points.")
            self.write(f"{source_prefix}:MODE SWE")
            self.write(f"{source_prefix}:STAR {config.start}")
            self.write(f"{source_prefix}:STOP {config.stop}")
            self.write(f":SOUR:SWE:POIN {config.points}")
            self.write(f":SOUR:SWE:SPAC {spacing}")
            self.set_source_delay(config.delay)
            return

        if config.values is None or len(config.values) == 0:
            raise ValueError("Custom/list sweep requires at least one value.")
        values = ",".join(str(value) for value in config.values)
        self.write(f"{source_prefix}:MODE LIST")
        self.write(f":SOUR:LIST:{source_mode} {values}")
        self.write(f":SOUR:SWE:POIN {len(config.values)}")
        self.set_source_delay(config.delay)

    def set_source_delay(self, delay: float) -> None:
        """Set source delay before each measurement trigger."""
        if delay < 0.0:
            raise ValueError("Source delay must be non-negative.")
        self.write(f":SOUR:DEL {delay}")

    def get_source_delay(self) -> float:
        """Return source delay before each measurement trigger."""
        return float(self.query(":SOUR:DEL?"))

    def configure_trigger_model(self, config: TriggerModelConfiguration) -> None:
        """Configure trigger and arm model settings."""
        trigger_source = config.trigger_source.upper()
        arm_source = config.arm_source.upper()
        if trigger_source not in _VALID_TRIGGER_SOURCES:
            raise ValueError(
                f"Invalid trigger source {config.trigger_source!r}; must be one of {_VALID_TRIGGER_SOURCES}."
            )
        if arm_source not in _VALID_TRIGGER_SOURCES:
            raise ValueError(f"Invalid arm source {config.arm_source!r}; must be one of {_VALID_TRIGGER_SOURCES}.")
        if config.trigger_count <= 0:
            raise ValueError("Trigger count must be positive.")
        if config.arm_count <= 0:
            raise ValueError("Arm count must be positive.")
        if config.trigger_delay < 0.0:
            raise ValueError("Trigger delay must be non-negative.")

        self.write(f":TRIG:SOUR {trigger_source}")
        self.write(f":TRIG:COUN {config.trigger_count}")
        self.write(f":TRIG:DEL {config.trigger_delay}")
        self.write(f":ARM:SOUR {arm_source}")
        self.write(f":ARM:COUN {config.arm_count}")

    def initiate(self) -> None:
        """Arm and start the trigger model."""
        self.write(":INIT")

    def abort(self) -> None:
        """Abort trigger execution."""
        self.write(":ABOR")

    def set_buffer_size(self, size: int) -> None:
        """Set reading buffer capacity."""
        if size <= 0:
            raise ValueError("Buffer size must be positive.")
        self.write(f":TRAC:POIN {size}")

    def get_buffer_size(self) -> int:
        """Return reading buffer capacity."""
        return int(float(self.query(":TRAC:POIN?")))

    def clear_buffer(self) -> None:
        """Clear the reading buffer."""
        self.write(":TRAC:CLE")

    def read_buffer(self, count: int | None = None) -> tuple[float, ...]:
        """Read buffered readings from the internal trace buffer."""
        if count is None:
            response = self.query(":TRAC:DATA?")
            return self._parse_csv_floats(response)
        if count <= 0:
            raise ValueError("Requested buffer count must be positive.")
        response = self.query(f":TRAC:DATA? 1,{count}")
        return self._parse_csv_floats(response)

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
