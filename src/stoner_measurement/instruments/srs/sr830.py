"""Stanford Research Systems SRS830 lock-in amplifier driver."""

from __future__ import annotations

from stoner_measurement.instruments.lockin_amplifier import (
    LockInAmplifier,
    LockInAmplifierCapabilities,
    LockInExpandFactor,
    LockInInputCoupling,
    LockInInputShielding,
    LockInInputSource,
    LockInLineFilter,
    LockInOutputChannel,
    LockInReferenceSource,
    LockInReserveMode,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport


class SRS830(LockInAmplifier):
    """Driver for the Stanford Research Systems SR830 lock-in amplifier.

    Communicates via SCPI over serial, GPIB, or Ethernet. All sensitivity
    and time-constant values are constrained to the lookup tables defined
    in :attr:`_SENSITIVITIES` and :attr:`_TIME_CONSTANTS`; the nearest
    valid entry must be used.

    Keyword Parameters:
        transport (BaseTransport):
            Transport layer (serial, GPIB, or Ethernet).
        protocol (BaseProtocol | None):
            Protocol instance.  Defaults to :class:`ScpiProtocol`.

    Attributes:
        transport (BaseTransport):
            Transport layer (serial, GPIB, or Ethernet).
        protocol (BaseProtocol):
            Protocol instance (defaults to :class:`ScpiProtocol`).

    Examples:
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.srs.sr830 import SRS830
        >>> lia = SRS830(NullTransport())
        >>> caps = lia.get_capabilities()
        >>> caps.has_harmonic_selection
        True
    """

    _TIME_CONSTANTS: tuple[float, ...] = (
        10e-6,
        30e-6,
        100e-6,
        300e-6,
        1e-3,
        3e-3,
        10e-3,
        30e-3,
        100e-3,
        300e-3,
        1.0,
        3.0,
        10.0,
        30.0,
        100.0,
        300.0,
        1e3,
        3e3,
        10e3,
        30e3,
    )
    _SENSITIVITIES: tuple[float, ...] = (
        2e-9,
        5e-9,
        10e-9,
        20e-9,
        50e-9,
        100e-9,
        200e-9,
        500e-9,
        1e-6,
        2e-6,
        5e-6,
        10e-6,
        20e-6,
        50e-6,
        100e-6,
        200e-6,
        500e-6,
        1e-3,
        2e-3,
        5e-3,
        10e-3,
        20e-3,
        50e-3,
        100e-3,
        200e-3,
        500e-3,
        1.0,
    )
    _FILTER_SLOPES: tuple[int, ...] = (6, 12, 18, 24)
    _OSCILLATOR_AMPLITUDE_MIN: float = 0.004
    _OSCILLATOR_AMPLITUDE_MAX: float = 5.000
    _MAX_HARMONIC: int = 19999

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the SR830 driver, defaulting to :class:`ScpiProtocol`."""
        super().__init__(transport=transport, protocol=protocol if protocol is not None else ScpiProtocol())

    @staticmethod
    def _parse_csv_pair(values: str) -> tuple[float, float]:
        """Parse a comma-separated two-value numeric response."""
        stripped = values.strip()
        tokens = [token.strip() for token in stripped.split(",")]
        if len(tokens) != 2 or "" in tokens:
            raise ValueError(f"Malformed dual-output response: {values!r}")
        try:
            return float(tokens[0]), float(tokens[1])
        except ValueError as exc:
            raise ValueError(f"Malformed dual-output response: {values!r}") from exc

    @staticmethod
    def _decode_indexed_value(index: int, values: tuple[float, ...], *, name: str) -> float:
        """Decode a returned numeric code into a value from a lookup table."""
        if index < 0 or index >= len(values):
            raise ValueError(f"{name} code {index} is out of range.")
        return values[index]

    @staticmethod
    def _encode_indexed_value(value: float, values: tuple[float, ...], *, name: str) -> int:
        """Encode a value to its numeric code using a lookup table."""
        try:
            return values.index(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be one of {values!r}.") from exc

    @staticmethod
    def _decode_bool_token(token: str) -> bool:
        """Parse an instrument boolean token where ``0`` is false and ``1`` is true."""
        value = int(float(token.strip()))
        if value not in (0, 1):
            raise ValueError(f"Expected boolean token, got {token!r}")
        return bool(value)

    def measure_xy(self) -> tuple[float, float]:
        """Measure and return the in-phase (X) and quadrature (Y) outputs.

        Returns:
            (tuple[float, float]):
                ``(x, y)`` values in volts.
        """
        return self._parse_csv_pair(self.query("SNAP?1,2"))

    def measure_rt(self) -> tuple[float, float]:
        """Measure and return the magnitude (R) and phase (theta) outputs.

        Returns:
            (tuple[float, float]):
                ``(r, theta)`` where ``r`` is in volts and ``theta`` is in degrees.
        """
        return self._parse_csv_pair(self.query("SNAP?3,4"))

    def get_sensitivity(self) -> float:
        """Return the active input sensitivity scale in volts.

        Returns:
            (float):
                Sensitivity in volts from :attr:`_SENSITIVITIES`.
        """
        code = int(float(self.query("SENS?")))
        return self._decode_indexed_value(code, self._SENSITIVITIES, name="Sensitivity")

    def set_sensitivity(self, value: float) -> None:
        """Set the input sensitivity scale.

        Args:
            value (float):
                Sensitivity in volts.  Must be an exact value from
                :attr:`_SENSITIVITIES`.

        Raises:
            ValueError:
                If *value* is not a valid sensitivity entry.
        """
        self.write(f"SENS {self._encode_indexed_value(value, self._SENSITIVITIES, name='Sensitivity')}")

    def get_time_constant(self) -> float:
        """Return the active output filter time constant in seconds.

        Returns:
            (float):
                Time constant in seconds from :attr:`_TIME_CONSTANTS`.
        """
        code = int(float(self.query("OFLT?")))
        return self._decode_indexed_value(code, self._TIME_CONSTANTS, name="Time constant")

    def set_time_constant(self, value: float) -> None:
        """Set the output filter time constant.

        Args:
            value (float):
                Time constant in seconds.  Must be an exact value from
                :attr:`_TIME_CONSTANTS`.

        Raises:
            ValueError:
                If *value* is not a valid time-constant entry.
        """
        self.write(f"OFLT {self._encode_indexed_value(value, self._TIME_CONSTANTS, name='Time constant')}")

    def get_reference_source(self) -> LockInReferenceSource:
        """Return the active reference source.

        Returns:
            (LockInReferenceSource):
                :attr:`~LockInReferenceSource.INTERNAL` or
                :attr:`~LockInReferenceSource.EXTERNAL`.
        """
        return LockInReferenceSource.EXTERNAL if not self._decode_bool_token(
            self.query("FMOD?")
        ) else LockInReferenceSource.INTERNAL

    def set_reference_source(self, source: LockInReferenceSource) -> None:
        """Set the reference source.

        Args:
            source (LockInReferenceSource):
                Reference source to select.
        """
        self.write(f"FMOD {1 if source is LockInReferenceSource.INTERNAL else 0}")

    def get_reference_frequency(self) -> float:
        """Return the reference frequency in hertz.

        Returns:
            (float):
                Reference frequency in hertz.
        """
        return float(self.query("FREQ?"))

    def set_reference_frequency(self, value: float) -> None:
        """Set the internal reference frequency in hertz.

        Args:
            value (float):
                Frequency in hertz (0.001 Hz to 102 kHz in internal mode).

        Raises:
            ValueError:
                If *value* is not positive.
        """
        if value <= 0.0:
            raise ValueError("Reference frequency must be positive.")
        # SR830 accepts 0.001 Hz to 102 kHz when in internal reference mode.
        self.write(f"FREQ {value}")

    def get_reference_phase(self) -> float:
        """Return the reference phase in degrees.

        Returns:
            (float):
                Reference phase offset in degrees.
        """
        return float(self.query("PHAS?"))

    def set_reference_phase(self, value: float) -> None:
        """Set the reference phase offset in degrees.

        Args:
            value (float):
                Phase offset in degrees.
        """
        self.write(f"PHAS {value}")

    def get_harmonic(self) -> int:
        """Return the detection harmonic.

        Returns:
            (int):
                Active detection harmonic (1 to :attr:`_MAX_HARMONIC`).
        """
        return int(float(self.query("HARM?")))

    def set_harmonic(self, harmonic: int) -> None:
        """Set the detection harmonic.

        Args:
            harmonic (int):
                Harmonic number between 1 and :attr:`_MAX_HARMONIC`.

        Raises:
            ValueError:
                If *harmonic* is outside the permitted range.
        """
        if not (1 <= harmonic <= self._MAX_HARMONIC):
            raise ValueError(f"Harmonic must be an integer between 1 and {self._MAX_HARMONIC}.")
        self.write(f"HARM {harmonic}")

    def get_filter_slope(self) -> int:
        """Return the output low-pass filter roll-off slope in dB/octave.

        Returns:
            (int):
                Filter slope in dB/octave, one of ``(6, 12, 18, 24)``.
        """
        code = int(float(self.query("OFSL?")))
        if code < 0 or code >= len(self._FILTER_SLOPES):
            raise ValueError(f"Filter slope code {code} is out of range.")
        return self._FILTER_SLOPES[code]

    def set_filter_slope(self, slope: int) -> None:
        """Set the output low-pass filter roll-off slope.

        Args:
            slope (int):
                Slope in dB/octave.  Must be one of ``(6, 12, 18, 24)``.

        Raises:
            ValueError:
                If *slope* is not a valid filter-slope value.
        """
        try:
            code = self._FILTER_SLOPES.index(slope)
        except ValueError as exc:
            raise ValueError(f"Filter slope must be one of {self._FILTER_SLOPES!r}.") from exc
        self.write(f"OFSL {code}")

    def get_input_coupling(self) -> LockInInputCoupling:
        """Return the input coupling mode.

        Returns:
            (LockInInputCoupling):
                :attr:`~LockInInputCoupling.AC` or :attr:`~LockInInputCoupling.DC`.
        """
        return LockInInputCoupling.DC if self._decode_bool_token(self.query("ICPL?")) else LockInInputCoupling.AC

    def set_input_coupling(self, coupling: LockInInputCoupling) -> None:
        """Set the input coupling mode.

        Args:
            coupling (LockInInputCoupling):
                Coupling mode to select.
        """
        self.write(f"ICPL {1 if coupling is LockInInputCoupling.DC else 0}")

    def get_reserve_mode(self) -> LockInReserveMode:
        """Return the dynamic reserve mode.

        Returns:
            (LockInReserveMode):
                Active reserve mode.

        Raises:
            ValueError:
                If the instrument returns an unrecognised reserve code.
        """
        code = int(float(self.query("RMOD?")))
        if code == 0:
            return LockInReserveMode.HIGH_RESERVE
        if code == 1:
            return LockInReserveMode.NORMAL
        if code == 2:
            return LockInReserveMode.LOW_NOISE
        raise ValueError(f"Unexpected reserve mode code: {code}")

    def set_reserve_mode(self, mode: LockInReserveMode) -> None:
        """Set the dynamic reserve mode.

        Args:
            mode (LockInReserveMode):
                Reserve mode to select.
        """
        mapping = {
            LockInReserveMode.HIGH_RESERVE: 0,
            LockInReserveMode.NORMAL: 1,
            LockInReserveMode.LOW_NOISE: 2,
        }
        self.write(f"RMOD {mapping[mode]}")

    def auto_gain(self) -> None:
        """Execute the SR830 auto-gain routine."""
        self.write("AGAN")

    def auto_phase(self) -> None:
        """Execute the SR830 auto-phase routine."""
        self.write("APHS")

    def auto_reserve(self) -> None:
        """Execute the SR830 auto-reserve routine."""
        self.write("ARSV")

    def get_oscillator_amplitude(self) -> float:
        """Return the internal oscillator sine output amplitude in volts.

        Returns:
            (float):
                Sine output amplitude in volts
                (:attr:`_OSCILLATOR_AMPLITUDE_MIN` to :attr:`_OSCILLATOR_AMPLITUDE_MAX`).
        """
        return float(self.query("SLVL?"))

    def set_oscillator_amplitude(self, value: float) -> None:
        """Set the internal oscillator sine output amplitude in volts.

        Args:
            value (float):
                Amplitude in volts, between :attr:`_OSCILLATOR_AMPLITUDE_MIN`
                (4 mV) and :attr:`_OSCILLATOR_AMPLITUDE_MAX` (5 V).

        Raises:
            ValueError:
                If *value* is outside the permitted amplitude range.
        """
        if not (self._OSCILLATOR_AMPLITUDE_MIN <= value <= self._OSCILLATOR_AMPLITUDE_MAX):
            raise ValueError(
                f"Oscillator amplitude must be between {self._OSCILLATOR_AMPLITUDE_MIN} V "
                f"and {self._OSCILLATOR_AMPLITUDE_MAX} V."
            )
        self.write(f"SLVL {value}")

    def get_output_offset(self, channel: LockInOutputChannel) -> tuple[float, LockInExpandFactor]:
        """Return the output offset percentage and expand factor for *channel*.

        Args:
            channel (LockInOutputChannel):
                Output channel to query (X, Y, or R).

        Returns:
            (tuple[float, LockInExpandFactor]):
                ``(offset_pct, expand_factor)`` where *offset_pct* is in the
                range −105 % to +105 %.

        Raises:
            ValueError:
                If the instrument returns an unrecognised expand code.
        """
        channel_codes = {LockInOutputChannel.X: 1, LockInOutputChannel.Y: 2, LockInOutputChannel.R: 3}
        expand_decode = {0: LockInExpandFactor.X1, 1: LockInExpandFactor.X10, 2: LockInExpandFactor.X100}
        offset_pct, expand_code_f = self._parse_csv_pair(self.query(f"OEXP? {channel_codes[channel]}"))
        expand_code = int(expand_code_f)
        if expand_code not in expand_decode:
            raise ValueError(f"Unexpected expand code: {expand_code}")
        return offset_pct, expand_decode[expand_code]

    def set_output_offset(
        self,
        channel: LockInOutputChannel,
        offset_pct: float,
        expand_factor: LockInExpandFactor,
    ) -> None:
        """Set the output offset and expand factor for *channel*.

        Args:
            channel (LockInOutputChannel):
                Output channel to configure (X, Y, or R).
            offset_pct (float):
                Offset percentage in the range −105 to +105.
            expand_factor (LockInExpandFactor):
                Expand factor to apply (×1, ×10, or ×100).

        Raises:
            ValueError:
                If *offset_pct* is outside the range −105 to +105.
        """
        if not (-105.0 <= offset_pct <= 105.0):
            raise ValueError("Offset percentage must be between -105 and 105.")
        channel_codes = {LockInOutputChannel.X: 1, LockInOutputChannel.Y: 2, LockInOutputChannel.R: 3}
        expand_encode = {LockInExpandFactor.X1: 0, LockInExpandFactor.X10: 1, LockInExpandFactor.X100: 2}
        self.write(f"OEXP {channel_codes[channel]},{offset_pct},{expand_encode[expand_factor]}")

    def get_input_source(self) -> LockInInputSource:
        """Return the input source configuration.

        Returns:
            (LockInInputSource):
                Active input source (A, A−B, or current with 1 MΩ / 100 MΩ).

        Raises:
            ValueError:
                If the instrument returns an unrecognised input-source code.
        """
        decode = {
            0: LockInInputSource.A,
            1: LockInInputSource.A_MINUS_B,
            2: LockInInputSource.I_1MOHM,
            3: LockInInputSource.I_100MOHM,
        }
        code = int(float(self.query("ISRC?")))
        if code not in decode:
            raise ValueError(f"Unexpected input source code: {code}")
        return decode[code]

    def set_input_source(self, source: LockInInputSource) -> None:
        """Set the input source configuration.

        Args:
            source (LockInInputSource):
                Input source to select.
        """
        encode = {
            LockInInputSource.A: 0,
            LockInInputSource.A_MINUS_B: 1,
            LockInInputSource.I_1MOHM: 2,
            LockInInputSource.I_100MOHM: 3,
        }
        self.write(f"ISRC {encode[source]}")

    def get_input_shielding(self) -> LockInInputShielding:
        """Return the input shield grounding configuration.

        Returns:
            (LockInInputShielding):
                :attr:`~LockInInputShielding.GROUND` or
                :attr:`~LockInInputShielding.FLOAT`.
        """
        return (
            LockInInputShielding.GROUND
            if self._decode_bool_token(self.query("IGND?"))
            else LockInInputShielding.FLOAT
        )

    def set_input_shielding(self, shielding: LockInInputShielding) -> None:
        """Set the input shield grounding configuration.

        Args:
            shielding (LockInInputShielding):
                Shielding mode to select.
        """
        self.write(f"IGND {1 if shielding is LockInInputShielding.GROUND else 0}")

    def get_line_filter(self) -> LockInLineFilter:
        """Return the line-frequency notch filter configuration.

        Returns:
            (LockInLineFilter):
                Active line-filter setting.

        Raises:
            ValueError:
                If the instrument returns an unrecognised filter code.
        """
        decode = {
            0: LockInLineFilter.NONE,
            1: LockInLineFilter.LINE,
            2: LockInLineFilter.LINE_2X,
            3: LockInLineFilter.BOTH,
        }
        code = int(float(self.query("ILIN?")))
        if code not in decode:
            raise ValueError(f"Unexpected line filter code: {code}")
        return decode[code]

    def set_line_filter(self, filter_config: LockInLineFilter) -> None:
        """Set the line-frequency notch filter configuration.

        Args:
            filter_config (LockInLineFilter):
                Notch filter setting to apply.
        """
        encode = {
            LockInLineFilter.NONE: 0,
            LockInLineFilter.LINE: 1,
            LockInLineFilter.LINE_2X: 2,
            LockInLineFilter.BOTH: 3,
        }
        self.write(f"ILIN {encode[filter_config]}")

    def get_sync_filter_enabled(self) -> bool:
        """Return whether the synchronous output filter is enabled.

        Returns:
            (bool):
                ``True`` when the sync filter is active.
        """
        return self._decode_bool_token(self.query("SYNC?"))

    def set_sync_filter_enabled(self, state: bool) -> None:
        """Enable or disable the synchronous output filter.

        Args:
            state (bool):
                ``True`` to enable the sync filter.
        """
        self.write(f"SYNC {1 if state else 0}")

    def get_capabilities(self) -> LockInAmplifierCapabilities:
        """Return static capability metadata for the SR830.

        Returns:
            (LockInAmplifierCapabilities):
                Capability descriptor reflecting the full SR830 feature set.
        """
        return LockInAmplifierCapabilities(
            has_reference_source_selection=True,
            has_reference_frequency_control=True,
            has_reference_phase_control=True,
            has_harmonic_selection=True,
            has_filter_slope_control=True,
            has_input_coupling_control=True,
            has_reserve_mode_control=True,
            has_auto_gain=True,
            has_auto_phase=True,
            has_auto_reserve=True,
            has_output_offset=True,
            has_internal_oscillator=True,
            has_input_source_selection=True,
            has_input_shielding_control=True,
            has_line_filter_control=True,
            has_sync_filter=True,
            max_harmonic=self._MAX_HARMONIC,
        )

