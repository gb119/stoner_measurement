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
from stoner_measurement.instruments.source_meter import SourceMeter, SourceMode
from stoner_measurement.instruments.transport.base import BaseTransport

#: Valid source modes accepted by the Keithley 2400.
_VALID_MODES = frozenset({"VOLT", "CURR"})

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
