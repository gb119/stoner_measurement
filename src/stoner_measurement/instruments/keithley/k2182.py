"""Keithley 2182A/182 nanovoltmeter drivers."""

from __future__ import annotations

from stoner_measurement.instruments.nanovoltmeter import (
    Nanovoltmeter,
    NanovoltmeterCapabilities,
    NanovoltmeterFunction,
    NanovoltmeterTriggerSource,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport


class Keithley2182A(Nanovoltmeter):
    """Driver for the Keithley 2182A nanovoltmeter."""

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

    def measure_voltage(self) -> float:
        return float(self.query(":READ?"))

    def get_range(self) -> float:
        return float(self.query(":SENS:VOLT:RANG?"))

    def set_range(self, value: float) -> None:
        if value <= 0.0:
            raise ValueError("Range must be positive.")
        self.write(f":SENS:VOLT:RANG {value}")

    def get_autorange(self) -> bool:
        return self.query(":SENS:VOLT:RANG:AUTO?") == "1"

    def set_autorange(self, state: bool) -> None:
        self.write(f":SENS:VOLT:RANG:AUTO {1 if state else 0}")

    def get_nplc(self) -> float:
        return float(self.query(":SENS:VOLT:NPLC?"))

    def set_nplc(self, value: float) -> None:
        if value <= 0.0:
            raise ValueError("NPLC must be positive.")
        self.write(f":SENS:VOLT:NPLC {value}")

    def get_measure_function(self) -> NanovoltmeterFunction:
        token = self.query(":SENS:FUNC?").strip().strip("'\"").upper()
        return NanovoltmeterFunction(token)

    def set_measure_function(self, function: NanovoltmeterFunction) -> None:
        self.write(f':SENS:FUNC "{function.value}"')

    def get_filter_enabled(self) -> bool:
        return self.query(":SENS:VOLT:DFIL:STAT?") == "1"

    def set_filter_enabled(self, state: bool) -> None:
        self.write(f":SENS:VOLT:DFIL:STAT {1 if state else 0}")

    def get_filter_count(self) -> int:
        return int(float(self.query(":SENS:VOLT:DFIL:COUN?")))

    def set_filter_count(self, count: int) -> None:
        if count <= 0:
            raise ValueError("Filter count must be positive.")
        self.write(f":SENS:VOLT:DFIL:COUN {count}")

    def get_trigger_source(self) -> NanovoltmeterTriggerSource:
        return NanovoltmeterTriggerSource(self.query(":TRIG:SOUR?").strip().upper())

    def set_trigger_source(self, source: NanovoltmeterTriggerSource) -> None:
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

    def get_capabilities(self) -> NanovoltmeterCapabilities:
        return NanovoltmeterCapabilities(
            has_function_selection=True,
            has_filter=True,
            has_trigger=True,
            has_buffer=True,
            supported_functions=(NanovoltmeterFunction.VOLT, NanovoltmeterFunction.TEMP),
        )


class Keithley182(Keithley2182A):
    """Driver for the Keithley 182 nanovoltmeter."""
