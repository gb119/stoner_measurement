"""Stanford Research Systems SR830 lock-in amplifier driver."""

from __future__ import annotations

from stoner_measurement.instruments.lockin_amplifier import (
    LockInAmplifier,
    LockInAmplifierCapabilities,
    LockInInputCoupling,
    LockInReferenceSource,
    LockInReserveMode,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport


class SRS830(LockInAmplifier):
    """Driver for the Stanford Research Systems SR830 lock-in amplifier.

    Attributes:
        transport (BaseTransport):
            Transport layer (serial, GPIB, or Ethernet).
        protocol (BaseProtocol):
            Protocol instance (defaults to :class:`ScpiProtocol`).
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

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        super().__init__(transport=transport, protocol=protocol if protocol is not None else ScpiProtocol())

    @staticmethod
    def _parse_csv_pair(values: str) -> tuple[float, float]:
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
        if index < 0 or index >= len(values):
            raise ValueError(f"{name} code {index} is out of range.")
        return values[index]

    @staticmethod
    def _encode_indexed_value(value: float, values: tuple[float, ...], *, name: str) -> int:
        try:
            return values.index(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be one of {values!r}.") from exc

    @staticmethod
    def _decode_bool_token(token: str) -> bool:
        value = int(float(token.strip()))
        if value not in (0, 1):
            raise ValueError(f"Expected boolean token, got {token!r}")
        return bool(value)

    def measure_xy(self) -> tuple[float, float]:
        return self._parse_csv_pair(self.query("SNAP?1,2"))

    def measure_rt(self) -> tuple[float, float]:
        return self._parse_csv_pair(self.query("SNAP?3,4"))

    def get_sensitivity(self) -> float:
        code = int(float(self.query("SENS?")))
        return self._decode_indexed_value(code, self._SENSITIVITIES, name="Sensitivity")

    def set_sensitivity(self, value: float) -> None:
        self.write(f"SENS {self._encode_indexed_value(value, self._SENSITIVITIES, name='Sensitivity')}")

    def get_time_constant(self) -> float:
        code = int(float(self.query("OFLT?")))
        return self._decode_indexed_value(code, self._TIME_CONSTANTS, name="Time constant")

    def set_time_constant(self, value: float) -> None:
        self.write(f"OFLT {self._encode_indexed_value(value, self._TIME_CONSTANTS, name='Time constant')}")

    def get_reference_source(self) -> LockInReferenceSource:
        return (
            LockInReferenceSource.INTERNAL
            if self._decode_bool_token(self.query("FMOD?"))
            else LockInReferenceSource.EXTERNAL
        )

    def set_reference_source(self, source: LockInReferenceSource) -> None:
        self.write(f"FMOD {1 if source is LockInReferenceSource.INTERNAL else 0}")

    def get_reference_frequency(self) -> float:
        return float(self.query("FREQ?"))

    def set_reference_frequency(self, value: float) -> None:
        if value <= 0.0:
            raise ValueError("Reference frequency must be positive.")
        self.write(f"FREQ {value}")

    def get_reference_phase(self) -> float:
        return float(self.query("PHAS?"))

    def set_reference_phase(self, value: float) -> None:
        self.write(f"PHAS {value}")

    def get_harmonic(self) -> int:
        return int(float(self.query("HARM?")))

    def set_harmonic(self, harmonic: int) -> None:
        if harmonic <= 0:
            raise ValueError("Harmonic must be a positive integer.")
        self.write(f"HARM {harmonic}")

    def get_filter_slope(self) -> int:
        code = int(float(self.query("OFSL?")))
        return int(self._decode_indexed_value(code, tuple(float(v) for v in self._FILTER_SLOPES), name="Filter slope"))

    def set_filter_slope(self, slope: int) -> None:
        try:
            code = self._FILTER_SLOPES.index(slope)
        except ValueError as exc:
            raise ValueError(f"Filter slope must be one of {self._FILTER_SLOPES!r}.") from exc
        self.write(f"OFSL {code}")

    def get_input_coupling(self) -> LockInInputCoupling:
        return LockInInputCoupling.DC if self._decode_bool_token(self.query("ICPL?")) else LockInInputCoupling.AC

    def set_input_coupling(self, coupling: LockInInputCoupling) -> None:
        self.write(f"ICPL {1 if coupling is LockInInputCoupling.DC else 0}")

    def get_reserve_mode(self) -> LockInReserveMode:
        code = int(float(self.query("RMOD?")))
        if code == 0:
            return LockInReserveMode.HIGH_RESERVE
        if code == 1:
            return LockInReserveMode.NORMAL
        if code == 2:
            return LockInReserveMode.LOW_NOISE
        raise ValueError(f"Unexpected reserve mode code: {code}")

    def set_reserve_mode(self, mode: LockInReserveMode) -> None:
        mapping = {
            LockInReserveMode.HIGH_RESERVE: 0,
            LockInReserveMode.NORMAL: 1,
            LockInReserveMode.LOW_NOISE: 2,
        }
        self.write(f"RMOD {mapping[mode]}")

    def auto_gain(self) -> None:
        self.write("AGAN")

    def auto_phase(self) -> None:
        self.write("APHS")

    def auto_reserve(self) -> None:
        self.write("ARSV")

    def get_capabilities(self) -> LockInAmplifierCapabilities:
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
        )
