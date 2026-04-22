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
        x = float(self.query(f":SENS{self._sense_slot}:LIA:X?"))
        y = float(self.query(f":SENS{self._sense_slot}:LIA:Y?"))
        return x, y

    def measure_rt(self) -> tuple[float, float]:
        r = float(self.query(f":SENS{self._sense_slot}:LIA:R?"))
        theta = float(self.query(f":SENS{self._sense_slot}:LIA:THE?"))
        return r, theta

    def get_sensitivity(self) -> float:
        return float(self.query(f":SENS{self._sense_slot}:LIA:RANG?"))

    def set_sensitivity(self, value: float) -> None:
        if value <= 0.0:
            raise ValueError("Sensitivity must be positive.")
        self.write(f":SENS{self._sense_slot}:LIA:RANG {value}")

    def get_time_constant(self) -> float:
        return float(self.query(f":SENS{self._sense_slot}:LIA:TC?"))

    def set_time_constant(self, value: float) -> None:
        if value <= 0.0:
            raise ValueError("Time constant must be positive.")
        self.write(f":SENS{self._sense_slot}:LIA:TC {value}")

    def get_reference_source(self) -> LockInReferenceSource:
        token = self.query(f":SENS{self._sense_slot}:LIA:RSRC?").strip().upper()
        return LockInReferenceSource.INTERNAL if token == "INT" else LockInReferenceSource.EXTERNAL

    def set_reference_source(self, source: LockInReferenceSource) -> None:
        token = "INT" if source is LockInReferenceSource.INTERNAL else "EXT"
        self.write(f":SENS{self._sense_slot}:LIA:RSRC {token}")

    def get_reference_frequency(self) -> float:
        if self._source_slot is not None:
            return float(self.query(f":SOUR{self._source_slot}:FREQ?"))
        return float(self.query(f":SENS{self._sense_slot}:LIA:FREQ?"))

    def set_reference_frequency(self, value: float) -> None:
        if value <= 0.0:
            raise ValueError("Reference frequency must be positive.")
        if self._source_slot is None:
            raise NotImplementedError(
                "Supply source_slot at construction to set the reference frequency "
                "via the M81 source module."
            )
        self.write(f":SOUR{self._source_slot}:FREQ {value}")

    def get_reference_phase(self) -> float:
        return float(self.query(f":SENS{self._sense_slot}:LIA:PHAS?"))

    def set_reference_phase(self, value: float) -> None:
        self.write(f":SENS{self._sense_slot}:LIA:PHAS {value}")

    def get_harmonic(self) -> int:
        return int(float(self.query(f":SENS{self._sense_slot}:LIA:HARM?")))

    def set_harmonic(self, harmonic: int) -> None:
        if not (1 <= harmonic <= self._MAX_HARMONIC):
            raise ValueError(f"Harmonic must be an integer between 1 and {self._MAX_HARMONIC}.")
        self.write(f":SENS{self._sense_slot}:LIA:HARM {harmonic}")

    def get_filter_slope(self) -> int:
        poles = int(float(self.query(f":SENS{self._sense_slot}:LIA:FILP?")))
        if poles not in _FILTER_POLES:
            raise ValueError(f"Unexpected filter poles value: {poles}")
        return _FILTER_SLOPES[_FILTER_POLES.index(poles)]

    def set_filter_slope(self, slope: int) -> None:
        if slope not in _FILTER_SLOPES:
            raise ValueError(f"Filter slope must be one of {_FILTER_SLOPES!r} dB/oct.")
        poles = _FILTER_POLES[_FILTER_SLOPES.index(slope)]
        self.write(f":SENS{self._sense_slot}:LIA:FILP {poles}")

    def get_input_coupling(self) -> LockInInputCoupling:
        token = self.query(f":SENS{self._sense_slot}:LIA:CPLS?").strip().upper()
        return LockInInputCoupling.DC if token == "DC" else LockInInputCoupling.AC

    def set_input_coupling(self, coupling: LockInInputCoupling) -> None:
        token = "DC" if coupling is LockInInputCoupling.DC else "AC"
        self.write(f":SENS{self._sense_slot}:LIA:CPLS {token}")

    def auto_phase(self) -> None:
        self.write(f":SENS{self._sense_slot}:LIA:APHS")

    def get_capabilities(self) -> LockInAmplifierCapabilities:
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
