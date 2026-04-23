"""Keithley electrometer and picoammeter drivers."""

from __future__ import annotations

from stoner_measurement.instruments.electrometer import (
    Electrometer,
    ElectrometerCapabilities,
    ElectrometerDataFormat,
    ElectrometerFunction,
    ElectrometerTriggerConfiguration,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

_NPLC_MIN = 0.01
_NPLC_MAX = 10.0


class _KeithleyElectrometerBase(Electrometer):
    """Common SCPI implementation for Keithley electrometers."""

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
    ) -> None:
        """Initialise the Keithley electrometer base driver, defaulting to :class:`ScpiProtocol`."""
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )

    @staticmethod
    def _parse_csv_floats(values: str) -> tuple[float, ...]:
        """Parse a comma-separated numeric payload."""
        stripped = values.strip()
        if not stripped:
            return ()
        return tuple(float(token.strip()) for token in stripped.split(",") if token.strip())

    @staticmethod
    def _normalise_function(function_name: str) -> ElectrometerFunction:
        """Convert a SCPI function token to an enum value."""
        token = function_name.strip().strip("'\"").upper()
        if ":" in token:
            token = token.split(":", 1)[0]
        return ElectrometerFunction(token)

    def measure_current(self) -> float:
        """Trigger a current measurement and return current in amps."""
        self.write(":SENS:FUNC 'CURR'")
        return float(self.query(":READ?").split(",")[0])

    def get_range(self) -> float:
        """Return active current range in amps."""
        return float(self.query(":SENS:CURR:RANG?"))

    def set_range(self, value: float) -> None:
        """Set current range in amps."""
        if value <= 0.0:
            raise ValueError("Range must be positive.")
        self.write(f":SENS:CURR:RANG {value}")

    def get_autorange(self) -> bool:
        """Return ``True`` if autorange is enabled."""
        return self.query(":SENS:CURR:RANG:AUTO?") == "1"

    def set_autorange(self, state: bool) -> None:
        """Enable or disable autorange."""
        self.write(f":SENS:CURR:RANG:AUTO {1 if state else 0}")

    def get_nplc(self) -> float:
        """Return integration time in power-line cycles."""
        return float(self.query(":SENS:CURR:NPLC?"))

    def set_nplc(self, value: float) -> None:
        """Set integration time in power-line cycles."""
        if not (_NPLC_MIN <= value <= _NPLC_MAX):
            raise ValueError(f"NPLC {value} out of range [{_NPLC_MIN}, {_NPLC_MAX}].")
        self.write(f":SENS:CURR:NPLC {value}")

    def get_measure_functions(self) -> tuple[ElectrometerFunction, ...]:
        """Return enabled measurement functions."""
        payload = self.query(":SENS:FUNC?")
        return tuple(self._normalise_function(token) for token in payload.split(",") if token.strip())

    def set_measure_functions(self, functions: tuple[ElectrometerFunction, ...]) -> None:
        """Enable one or more measurement functions."""
        if not functions:
            raise ValueError("At least one measurement function must be provided.")
        quoted = ",".join(f"'{function_name.value}'" for function_name in functions)
        self.write(f":SENS:FUNC {quoted}")

    def get_filter_enabled(self) -> bool:
        """Return ``True`` if digital averaging filter is enabled."""
        return self.query(":SENS:CURR:AVER:STAT?") == "1"

    def set_filter_enabled(self, state: bool) -> None:
        """Enable or disable digital averaging filter."""
        self.write(f":SENS:CURR:AVER:STAT {1 if state else 0}")

    def get_filter_count(self) -> int:
        """Return averaging filter count."""
        return int(float(self.query(":SENS:CURR:AVER:COUN?")))

    def set_filter_count(self, count: int) -> None:
        """Set averaging filter count."""
        if count <= 0:
            raise ValueError("Filter count must be positive.")
        self.write(f":SENS:CURR:AVER:COUN {count}")

    def configure_trigger_model(self, config: ElectrometerTriggerConfiguration) -> None:
        """Configure trigger and arm model settings."""
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
        """Start trigger execution."""
        self.write(":INIT")

    def abort(self) -> None:
        """Abort trigger execution."""
        self.write(":ABOR")

    def set_buffer_size(self, size: int) -> None:
        """Set trace buffer size."""
        if size <= 0:
            raise ValueError("Buffer size must be positive.")
        self.write(f":TRAC:POIN {size}")

    def get_buffer_size(self) -> int:
        """Return trace buffer size."""
        return int(float(self.query(":TRAC:POIN?")))

    def clear_buffer(self) -> None:
        """Clear trace buffer data."""
        self.write(":TRAC:CLE")

    def read_buffer(self, count: int | None = None) -> tuple[float, ...]:
        """Return trace buffer readings."""
        if count is None:
            return self._parse_csv_floats(self.query(":TRAC:DATA?"))
        if count <= 0:
            raise ValueError("Requested buffer count must be positive.")
        return self._parse_csv_floats(self.query(f":TRAC:DATA? 1,{count}"))

    def get_data_format(self) -> ElectrometerDataFormat:
        """Return configured response data format."""
        token = self.query(":FORM:DATA?").strip().upper()
        if token.startswith("ASC"):
            return ElectrometerDataFormat.ASCII
        if token.startswith("SRE"):
            return ElectrometerDataFormat.SREAL
        if token.startswith("DRE"):
            return ElectrometerDataFormat.DREAL
        return ElectrometerDataFormat(token)

    def set_data_format(self, data_format: ElectrometerDataFormat) -> None:
        """Set response data format."""
        self.write(f":FORM:DATA {data_format.value}")

    def get_capabilities(self) -> ElectrometerCapabilities:
        """Return static capabilities for this driver family."""
        return ElectrometerCapabilities(
            has_function_selection=True,
            has_filter=True,
            has_trigger_model=True,
            has_buffer=True,
            has_data_format=True,
        )


class Keithley6845(_KeithleyElectrometerBase):
    """Driver for the Keithley 6845 picoammeter/electrometer command set."""


class Keithley6514(_KeithleyElectrometerBase):
    """Driver for the Keithley 6514 electrometer."""


class Keithley6517(_KeithleyElectrometerBase):
    """Driver for the Keithley 6517 electrometer."""
