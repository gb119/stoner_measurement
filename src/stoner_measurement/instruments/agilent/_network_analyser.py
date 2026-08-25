"""Shared SCPI behaviour for Agilent/Keysight network analysers."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

import numpy as np

from stoner_measurement.instruments.network_analyser import (
    ByteOrder,
    DataEncoding,
    NetworkAnalyser,
    SweepConfiguration,
    SweepType,
)
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


_SWEEP_TO_SCPI = {
    SweepType.LINEAR: "LIN",
    SweepType.LOGARITHMIC: "LOG",
    SweepType.CW: "CW",
    SweepType.POWER: "POW",
    SweepType.SEGMENTED: "SEGM",
}
_SCPI_TO_SWEEP = {
    "LIN": SweepType.LINEAR,
    "LINEAR": SweepType.LINEAR,
    "LOG": SweepType.LOGARITHMIC,
    "LOGARITHMIC": SweepType.LOGARITHMIC,
    "CW": SweepType.CW,
    "POW": SweepType.POWER,
    "POWER": SweepType.POWER,
    "SEGM": SweepType.SEGMENTED,
    "SEGMENT": SweepType.SEGMENTED,
}


class _AgilentNetworkAnalyser(NetworkAnalyser):
    """Common scalar SCPI operations shared by the two Agilent VNAs."""

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
        *,
        auto_check_errors: bool = True,
    ) -> None:
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else ScpiProtocol(),
            auto_check_errors=auto_check_errors,
        )

    @staticmethod
    def _parse_bool(response: str) -> bool:
        token = response.strip().upper()
        if token in {"1", "ON"}:
            return True
        if token in {"0", "OFF"}:
            return False
        raise ValueError(f"Malformed SCPI boolean response: {response!r}")

    @staticmethod
    def _parse_csv_floats(response: str) -> np.ndarray:
        stripped = response.strip()
        if not stripped:
            return np.array([], dtype=np.float64)
        tokens = [token.strip() for token in stripped.split(",")]
        if "" in tokens:
            raise ValueError(f"Malformed numeric response: {response!r}")
        try:
            values = np.asarray([float(token) for token in tokens], dtype=np.float64)
        except ValueError as exc:
            raise ValueError(f"Malformed numeric response: {response!r}") from exc
        if not np.all(np.isfinite(values)):
            raise ValueError("Network analyser returned non-finite numeric data.")
        return values

    @staticmethod
    def _parse_options(response: str) -> tuple[str, ...]:
        stripped = response.strip().strip('"')
        if not stripped or stripped.upper() in {"0", "NONE"}:
            return ()
        return tuple(token.strip() for token in stripped.split(",") if token.strip())

    @staticmethod
    def _parse_identity(identity: str) -> tuple[str, str, str, str]:
        fields = tuple(field.strip() for field in identity.split(","))
        if len(fields) < 4:
            raise ValueError(f"Malformed *IDN? response: {identity!r}")
        return fields[0], fields[1], fields[2], ",".join(fields[3:])

    def confirm_identity(self) -> str:
        """Validate the exact model field in the instrument identity response."""
        identity = self.identify()
        _, model, _, _ = self._parse_identity(identity)
        expected = str(getattr(self, "_MODEL", ""))
        if model.upper() != expected.upper():
            from stoner_measurement.instruments.errors import InstrumentError

            raise InstrumentError(
                f"Unexpected instrument model {model!r}; expected {expected!r}."
            )
        return identity

    def get_sweep_configuration(self, channel: int = 1) -> SweepConfiguration:
        self._validate_channel(channel)
        sweep_token = self.query(f":SENS{channel}:SWE:TYPE?").strip().upper()
        try:
            sweep_type = _SCPI_TO_SWEEP[sweep_token]
        except KeyError as exc:
            raise ValueError(f"Unsupported sweep type returned by instrument: {sweep_token!r}") from exc
        if sweep_type in {SweepType.CW, SweepType.POWER}:
            start = stop = self.get_cw_frequency(channel)
        else:
            start = float(self.query(f":SENS{channel}:FREQ:STAR?"))
            stop = float(self.query(f":SENS{channel}:FREQ:STOP?"))
        points = int(float(self.query(f":SENS{channel}:SWE:POIN?")))
        if_bandwidth = self.get_if_bandwidth(channel)
        power = self.get_source_power(channel)
        _, average_count = self.get_averaging(channel)
        return SweepConfiguration(
            sweep_type=sweep_type,
            start_hz=start,
            stop_hz=stop,
            points=points,
            if_bandwidth_hz=if_bandwidth,
            source_power_dbm=power,
            averaging_count=average_count,
        )

    def set_sweep_configuration(
        self, configuration: SweepConfiguration, channel: int = 1
    ) -> None:
        self._validate_channel(channel)
        if configuration.points < 1:
            raise ValueError("Sweep point count must be positive.")
        if configuration.sweep_type not in {SweepType.CW, SweepType.POWER} and (
            configuration.stop_hz <= configuration.start_hz
        ):
            raise ValueError("Sweep stop frequency must exceed start frequency.")
        self.write(f":SENS{channel}:SWE:TYPE {_SWEEP_TO_SCPI[configuration.sweep_type]}")
        if configuration.sweep_type is SweepType.CW:
            self.set_cw_frequency(configuration.start_hz, channel)
        elif configuration.sweep_type is not SweepType.POWER:
            self.write(f":SENS{channel}:FREQ:STAR {configuration.start_hz}")
            self.write(f":SENS{channel}:FREQ:STOP {configuration.stop_hz}")
        self.write(f":SENS{channel}:SWE:POIN {configuration.points}")
        if configuration.if_bandwidth_hz is not None:
            self.set_if_bandwidth(configuration.if_bandwidth_hz, channel)
        if configuration.source_power_dbm is not None:
            self.set_source_power(configuration.source_power_dbm, channel)
        if configuration.averaging_count is not None:
            self.set_averaging(True, configuration.averaging_count, channel)

    def get_if_bandwidth(self, channel: int = 1) -> float:
        self._validate_channel(channel)
        return float(self.query(f":SENS{channel}:BAND?"))

    def set_if_bandwidth(self, value_hz: float, channel: int = 1) -> None:
        self._validate_channel(channel)
        if not np.isfinite(value_hz) or value_hz <= 0:
            raise ValueError("IF bandwidth must be a positive finite value.")
        self.write(f":SENS{channel}:BAND {value_hz}")

    def get_source_power(self, channel: int = 1, port: int | None = None) -> float:
        self._validate_channel(channel)
        self._validate_port(port)
        if port is not None:
            raise NotImplementedError("Independent per-port source power is not yet verified.")
        return float(self.query(f":SOUR{channel}:POW?"))

    def set_source_power(
        self, value_dbm: float, channel: int = 1, port: int | None = None
    ) -> None:
        self._validate_channel(channel)
        self._validate_port(port)
        if port is not None:
            raise NotImplementedError("Independent per-port source power is not yet verified.")
        if not np.isfinite(value_dbm):
            raise ValueError("Source power must be finite.")
        self.write(f":SOUR{channel}:POW {value_dbm}")

    def get_cw_frequency(self, channel: int = 1) -> float:
        """Return the channel frequency used for a power sweep."""
        self._validate_channel(channel)
        return float(self.query(f":SENS{channel}:FREQ:CW?"))

    def set_cw_frequency(self, value_hz: float, channel: int = 1) -> None:
        """Set the channel frequency used for a power sweep."""
        self._validate_channel(channel)
        if not np.isfinite(value_hz) or value_hz <= 0:
            raise ValueError("CW frequency must be a positive finite value.")
        self.write(f":SENS{channel}:FREQ:CW {value_hz}")

    def get_power_sweep_range(self, channel: int = 1) -> tuple[float, float]:
        """Return the coupled start and stop powers for a power sweep."""
        self._validate_channel(channel)
        return (
            float(self.query(f":SOUR{channel}:POW:STAR?")),
            float(self.query(f":SOUR{channel}:POW:STOP?")),
        )

    def set_power_sweep_range(
        self, start_dbm: float, stop_dbm: float, channel: int = 1
    ) -> None:
        """Set the coupled start and stop powers for a power sweep."""
        self._validate_channel(channel)
        if not np.isfinite(start_dbm) or not np.isfinite(stop_dbm):
            raise ValueError("Power-sweep limits must be finite.")
        if start_dbm == stop_dbm:
            raise ValueError("Power-sweep start and stop levels must differ.")
        self.write(f":SOUR{channel}:POW:STAR {start_dbm}")
        self.write(f":SOUR{channel}:POW:STOP {stop_dbm}")

    def get_averaging(self, channel: int = 1) -> tuple[bool, int]:
        self._validate_channel(channel)
        enabled = self._parse_bool(self.query(f":SENS{channel}:AVER?"))
        count = int(float(self.query(f":SENS{channel}:AVER:COUN?")))
        return enabled, count

    def set_averaging(
        self, enabled: bool, count: int | None = None, channel: int = 1
    ) -> None:
        self._validate_channel(channel)
        if count is not None:
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                raise ValueError("Averaging count must be a positive integer.")
            self.write(f":SENS{channel}:AVER:COUN {count}")
        self.write(f":SENS{channel}:AVER {1 if enabled else 0}")

    def get_continuous(self, channel: int = 1) -> bool:
        self._validate_channel(channel)
        return self._parse_bool(self.query(f":INIT{channel}:CONT?"))

    def set_continuous(self, enabled: bool, channel: int = 1) -> None:
        self._validate_channel(channel)
        self.write(f":INIT{channel}:CONT {1 if enabled else 0}")

    def initiate(self, channel: int = 1) -> None:
        self._validate_channel(channel)
        self.write(f":INIT{channel}:IMM")

    def trigger(self) -> None:
        self.write("*TRG")

    def abort(self) -> None:
        self.write(":ABOR")

    def get_correction_enabled(self, channel: int = 1) -> bool:
        self._validate_channel(channel)
        return self._parse_bool(self.query(f":SENS{channel}:CORR?"))

    def set_correction_enabled(self, enabled: bool, channel: int = 1) -> None:
        self._validate_channel(channel)
        self.write(f":SENS{channel}:CORR {1 if enabled else 0}")

    def get_data_encoding(self) -> DataEncoding:
        """Return the instrument's active numeric transfer encoding."""
        token = self.query(":FORM:DATA?").strip().upper().replace(" ", "")
        if token.startswith("ASC"):
            return DataEncoding.ASCII
        if token in {"REAL32", "REAL,32"}:
            return DataEncoding.REAL32
        if token in {"REAL", "REAL64", "REAL,64"}:
            return DataEncoding.REAL64
        raise ValueError(f"Unsupported data encoding returned by instrument: {token!r}")

    def set_data_encoding(self, encoding: DataEncoding) -> None:
        """Set the numeric transfer encoding."""
        self.write(f":FORM:DATA {self._data_encoding_token(encoding)}")

    def get_byte_order(self) -> ByteOrder:
        """Return the active binary byte order."""
        token = self.query(":FORM:BORD?").strip().upper()
        if token.startswith("NORM"):
            return ByteOrder.NORMAL
        if token.startswith("SWAP"):
            return ByteOrder.SWAPPED
        raise ValueError(f"Unsupported byte order returned by instrument: {token!r}")

    def set_byte_order(self, order: ByteOrder) -> None:
        """Set the binary transfer byte order."""
        token = "NORM" if order is ByteOrder.NORMAL else "SWAP"
        self.write(f":FORM:BORD {token}")

    def _query_numeric_data(self, command: str) -> np.ndarray:
        encoding = self.get_data_encoding()
        if encoding is DataEncoding.ASCII:
            return self._parse_csv_floats(self.query(command))
        order = self.get_byte_order()
        payload = self.query_ieee_block(command)
        width = 4 if encoding is DataEncoding.REAL32 else 8
        if len(payload) % width:
            raise ValueError(
                f"Binary payload length {len(payload)} is not divisible by {width}."
            )
        endian = ">" if order is ByteOrder.NORMAL else "<"
        dtype = np.dtype(f"{endian}f{width}")
        values = np.frombuffer(payload, dtype=dtype).astype(np.float64)
        if not np.all(np.isfinite(values)):
            raise ValueError("Network analyser returned non-finite numeric data.")
        return values

    def _query_complex_data(self, command: str) -> np.ndarray:
        values = self._query_numeric_data(command)
        if len(values) % 2:
            raise ValueError("Complex trace data must contain real/imaginary pairs.")
        return values[0::2] + 1j * values[1::2]

    @abstractmethod
    def _data_encoding_token(self, encoding: DataEncoding) -> str:
        """Return the model-specific SCPI token for *encoding*."""
