"""Lakeshore M81 SSM voltage-measurement module operating in LIA mode."""

from __future__ import annotations

from stoner_measurement.instruments.lockin_amplifier import (
    LockInAmplifier,
    LockInAmplifierCapabilities,
    LockInInputCoupling,
    LockInReferenceSource,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

_FILTER_POLES = (1, 2, 3, 4)
_FILTER_SLOPES = (6, 12, 18, 24)


class LakeshoreM81LockIn(LockInAmplifier):
    """Driver for the Lakeshore M81 SSM voltage-measurement module in LIA mode.

    The Lakeshore M81 Synchronous Source Measure (SSM) system performs
    lock-in detection via its VM (voltage-measurement) module.  Each module
    occupies a numbered slot on the mainframe.  When operating in LIA mode
    the VM module demodulates against a reference that may come from either
    an internal AC source module occupying another slot (``source_slot``) or
    an external TTL/sine reference routed to the rear panel.

    Notes:
        Setting the reference frequency programmatically requires an AC source
        module connected to the same mainframe.  Pass its slot number as
        ``source_slot`` at construction time.  Without ``source_slot`` the
        reference frequency can still be *read* (the instrument reports the
        detected frequency) but cannot be set via this driver.

    Keyword Parameters:
        sense_slot (int):
            Mainframe slot of the VM measurement module.  Defaults to ``1``.
        source_slot (int | None):
            Mainframe slot of the AC source module used as the internal
            reference.  When ``None`` (default) the internal reference
            frequency cannot be set by this driver.

    Attributes:
        transport (BaseTransport):
            Transport layer (GPIB, Ethernet, or USB).
        protocol (BaseProtocol):
            Protocol instance (defaults to :class:`ScpiProtocol`).

    Examples:
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> lia = LakeshoreM81LockIn(NullTransport(), sense_slot=1, source_slot=2)
        >>> lia.set_time_constant(100e-3)
        >>> x, y = lia.measure_xy()
    """

    _MAX_HARMONIC: int = 9999

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
        *,
        sense_slot: int = 1,
        source_slot: int | None = None,
    ) -> None:
        """Initialise the M81 LIA driver.

        Args:
            transport (BaseTransport):
                Transport layer instance.

        Keyword Parameters:
            protocol (BaseProtocol | None):
                Protocol instance.  Defaults to :class:`ScpiProtocol`.
            sense_slot (int):
                Mainframe slot of the VM measurement module.  Defaults to ``1``.
            source_slot (int | None):
                Mainframe slot of the AC source module.  Defaults to ``None``.
        """
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )
        self._sense_slot = sense_slot
        self._source_slot = source_slot

    def measure_xy(self) -> tuple[float, float]:
        """Measure and return the in-phase (X) and quadrature (Y) outputs.

        Returns:
            (tuple[float, float]):
                ``(x, y)`` values in volts.
        """
        x = float(self.query(f":SENS{self._sense_slot}:LIA:X?"))
        y = float(self.query(f":SENS{self._sense_slot}:LIA:Y?"))
        return x, y

    def measure_rt(self) -> tuple[float, float]:
        """Measure and return the magnitude (R) and phase (theta) outputs.

        Returns:
            (tuple[float, float]):
                ``(r, theta)`` where ``r`` is in volts and ``theta`` is in degrees.
        """
        r = float(self.query(f":SENS{self._sense_slot}:LIA:R?"))
        theta = float(self.query(f":SENS{self._sense_slot}:LIA:THE?"))
        return r, theta

    def get_sensitivity(self) -> float:
        """Return the active input range (sensitivity) in volts.

        Returns:
            (float):
                Sensitivity in volts as reported by the instrument.
        """
        return float(self.query(f":SENS{self._sense_slot}:LIA:RANG?"))

    def set_sensitivity(self, value: float) -> None:
        """Set the input range (sensitivity) in volts.

        Args:
            value (float):
                Sensitivity in volts.  Must be positive.

        Raises:
            ValueError:
                If *value* is not positive.
        """
        if value <= 0.0:
            raise ValueError("Sensitivity must be positive.")
        self.write(f":SENS{self._sense_slot}:LIA:RANG {value}")

    def get_time_constant(self) -> float:
        """Return the output filter time constant in seconds.

        Returns:
            (float):
                Time constant in seconds.
        """
        return float(self.query(f":SENS{self._sense_slot}:LIA:TC?"))

    def set_time_constant(self, value: float) -> None:
        """Set the output filter time constant in seconds.

        Args:
            value (float):
                Time constant in seconds.  Must be positive.

        Raises:
            ValueError:
                If *value* is not positive.
        """
        if value <= 0.0:
            raise ValueError("Time constant must be positive.")
        self.write(f":SENS{self._sense_slot}:LIA:TC {value}")

    def get_reference_source(self) -> LockInReferenceSource:
        """Return the active reference source.

        Returns:
            (LockInReferenceSource):
                :attr:`~LockInReferenceSource.INTERNAL` or
                :attr:`~LockInReferenceSource.EXTERNAL`.
        """
        token = self.query(f":SENS{self._sense_slot}:LIA:RSRC?").strip().upper()
        return LockInReferenceSource.INTERNAL if token == "INT" else LockInReferenceSource.EXTERNAL

    def set_reference_source(self, source: LockInReferenceSource) -> None:
        """Set the reference source.

        Args:
            source (LockInReferenceSource):
                Reference source to select.
        """
        token = "INT" if source is LockInReferenceSource.INTERNAL else "EXT"
        self.write(f":SENS{self._sense_slot}:LIA:RSRC {token}")

    def get_reference_frequency(self) -> float:
        """Return the reference frequency in hertz.

        When a source slot is configured the frequency is queried from the AC
        source module; otherwise it is read from the VM sense module.

        Returns:
            (float):
                Reference frequency in hertz.
        """
        if self._source_slot is not None:
            return float(self.query(f":SOUR{self._source_slot}:FREQ?"))
        return float(self.query(f":SENS{self._sense_slot}:LIA:FREQ?"))

    def set_reference_frequency(self, value: float) -> None:
        """Set the reference frequency via the M81 AC source module.

        Args:
            value (float):
                Frequency in hertz.  Must be positive.

        Raises:
            NotImplementedError:
                If no ``source_slot`` was provided at construction time.
            ValueError:
                If *value* is not positive.
        """
        if self._source_slot is None:
            raise NotImplementedError(
                "Supply source_slot at construction to set the reference frequency "
                "via the M81 source module."
            )
        if value <= 0.0:
            raise ValueError("Reference frequency must be positive.")
        self.write(f":SOUR{self._source_slot}:FREQ {value}")

    def get_reference_phase(self) -> float:
        """Return the reference phase offset in degrees.

        Returns:
            (float):
                Reference phase in degrees.
        """
        return float(self.query(f":SENS{self._sense_slot}:LIA:PHAS?"))

    def set_reference_phase(self, value: float) -> None:
        """Set the reference phase offset in degrees.

        Args:
            value (float):
                Phase offset in degrees.
        """
        self.write(f":SENS{self._sense_slot}:LIA:PHAS {value}")

    def get_harmonic(self) -> int:
        """Return the detection harmonic.

        Returns:
            (int):
                Active detection harmonic (1 to :attr:`_MAX_HARMONIC`).
        """
        return int(float(self.query(f":SENS{self._sense_slot}:LIA:HARM?")))

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
        self.write(f":SENS{self._sense_slot}:LIA:HARM {harmonic}")

    def get_filter_slope(self) -> int:
        """Return the output low-pass filter roll-off slope in dB/octave.

        Returns:
            (int):
                Filter slope in dB/octave, one of ``(6, 12, 18, 24)``.

        Raises:
            ValueError:
                If the instrument returns an unrecognised filter-poles value.
        """
        poles = int(float(self.query(f":SENS{self._sense_slot}:LIA:FILP?")))
        if poles not in _FILTER_POLES:
            raise ValueError(f"Unexpected filter poles value: {poles}")
        return _FILTER_SLOPES[_FILTER_POLES.index(poles)]

    def set_filter_slope(self, slope: int) -> None:
        """Set the output low-pass filter roll-off slope.

        Args:
            slope (int):
                Slope in dB/octave.  Must be one of ``(6, 12, 18, 24)``.

        Raises:
            ValueError:
                If *slope* is not a valid filter-slope value.
        """
        if slope not in _FILTER_SLOPES:
            raise ValueError(f"Filter slope must be one of {_FILTER_SLOPES!r} dB/oct.")
        poles = _FILTER_POLES[_FILTER_SLOPES.index(slope)]
        self.write(f":SENS{self._sense_slot}:LIA:FILP {poles}")

    def get_input_coupling(self) -> LockInInputCoupling:
        """Return the input coupling mode.

        Returns:
            (LockInInputCoupling):
                :attr:`~LockInInputCoupling.AC` or :attr:`~LockInInputCoupling.DC`.
        """
        token = self.query(f":SENS{self._sense_slot}:LIA:CPLS?").strip().upper()
        return LockInInputCoupling.DC if token == "DC" else LockInInputCoupling.AC

    def set_input_coupling(self, coupling: LockInInputCoupling) -> None:
        """Set the input coupling mode.

        Args:
            coupling (LockInInputCoupling):
                Coupling mode to select.
        """
        token = "DC" if coupling is LockInInputCoupling.DC else "AC"
        self.write(f":SENS{self._sense_slot}:LIA:CPLS {token}")

    def auto_phase(self) -> None:
        """Execute the M81 auto-phase routine for the sense slot."""
        self.write(f":SENS{self._sense_slot}:LIA:APHS")

    def get_capabilities(self) -> LockInAmplifierCapabilities:
        """Return static capability metadata for the M81 LIA driver.

        Returns:
            (LockInAmplifierCapabilities):
                Capability descriptor.  Reference-frequency control is only
                available when a ``source_slot`` was supplied at construction.
        """
        return LockInAmplifierCapabilities(
            has_reference_source_selection=True,
            has_reference_frequency_control=self._source_slot is not None,
            has_reference_phase_control=True,
            has_harmonic_selection=True,
            has_filter_slope_control=True,
            has_input_coupling_control=True,
            has_reserve_mode_control=False,
            has_auto_gain=False,
            has_auto_phase=True,
            has_auto_reserve=False,
            has_output_offset=False,
            has_internal_oscillator=False,
            has_input_source_selection=False,
            has_input_shielding_control=False,
            has_line_filter_control=False,
            has_sync_filter=False,
            max_harmonic=self._MAX_HARMONIC,
        )
