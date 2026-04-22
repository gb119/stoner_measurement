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
        super().__init__(transport=transport, protocol=protocol if protocol is not None else ScpiProtocol())

    @staticmethod
    def _parse_csv_floats(values: str) -> tuple[float, ...]:
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
        cleaned = token.strip().strip("'\"").upper()
        if cleaned == "VOLT":
            return DmmFunction.VOLT_DC
        if cleaned == "CURR":
            return DmmFunction.CURR_DC
        return DmmFunction(cleaned)

    def _sense_prefix(self, function: DmmFunction | None = None) -> str:
        active = function if function is not None else self.get_measure_function()
        return active.value.split(":", 1)[0]

    def measure(self) -> float:
        return float(self.query(":READ?"))

    def get_measure_function(self) -> DmmFunction:
        return self._normalise_function(self.query(":SENS:FUNC?"))

    def set_measure_function(self, function: DmmFunction) -> None:
        self.write(f':SENS:FUNC "{function.value}"')

    def get_range(self) -> float:
        return float(self.query(f":SENS:{self._sense_prefix()}:RANG?"))

    def set_range(self, value: float) -> None:
        if value <= 0.0:
            raise ValueError("Range must be positive.")
        self.write(f":SENS:{self._sense_prefix()}:RANG {value}")

    def get_autorange(self) -> bool:
        return self.query(f":SENS:{self._sense_prefix()}:RANG:AUTO?") == "1"

    def set_autorange(self, state: bool) -> None:
        self.write(f":SENS:{self._sense_prefix()}:RANG:AUTO {1 if state else 0}")

    def get_nplc(self) -> float:
        return float(self.query(f":SENS:{self._sense_prefix()}:NPLC?"))

    def set_nplc(self, value: float) -> None:
        if value <= 0.0:
            raise ValueError("NPLC must be positive.")
        self.write(f":SENS:{self._sense_prefix()}:NPLC {value}")

    def get_filter_enabled(self) -> bool:
        return self.query(f":SENS:{self._sense_prefix()}:AVER:STAT?") == "1"

    def set_filter_enabled(self, state: bool) -> None:
        self.write(f":SENS:{self._sense_prefix()}:AVER:STAT {1 if state else 0}")

    def get_filter_count(self) -> int:
        return int(float(self.query(f":SENS:{self._sense_prefix()}:AVER:COUN?")))

    def set_filter_count(self, count: int) -> None:
        if count <= 0:
            raise ValueError("Filter count must be positive.")
        self.write(f":SENS:{self._sense_prefix()}:AVER:COUN {count}")

    def get_trigger_source(self) -> DmmTriggerSource:
        return DmmTriggerSource(self.query(":TRIG:SOUR?").strip().upper())

    def set_trigger_source(self, source: DmmTriggerSource) -> None:
        self.write(f":TRIG:SOUR {source.value}")

    def get_trigger_count(self) -> int:
        return int(float(self.query(":TRIG:COUN?")))

    def set_trigger_count(self, count: int) -> None:
        if count <= 0:
            raise ValueError("Trigger count must be positive.")
        self.write(f":TRIG:COUN {count}")

    def initiate(self) -> None:
        self.write(":INIT")

    def abort(self) -> None:
        self.write(":ABOR")

    def clear_buffer(self) -> None:
        self.write(":TRAC:CLE")

    def get_buffer_count(self) -> int:
        return int(float(self.query(":TRAC:POIN:ACT?")))

    def read_buffer(self, count: int | None = None) -> tuple[float, ...]:
        if count is None:
            payload = self.query(":TRAC:DATA?")
            return self._parse_csv_floats(payload)
        if count <= 0:
            raise ValueError("count must be a positive integer.")
        payload = self.query(f":TRAC:DATA? 1,{count}")
        return self._parse_csv_floats(payload)

    def get_capabilities(self) -> DmmCapabilities:
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
