"""Keithley 6221 AC/DC precision current-source driver."""

from __future__ import annotations

from stoner_measurement.instruments.current_source import (
    CurrentSource,
    CurrentSourceCapabilities,
    CurrentWaveform,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport


class Keithley6221(CurrentSource):
    """Driver for the Keithley 6221 precision AC/DC current source."""

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
    ) -> None:
        """Initialise the Keithley 6221 driver."""
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )

    def get_source_level(self) -> float:
        """Return programmed source current in amps."""
        return float(self.query(":SOUR:CURR?"))

    def set_source_level(self, value: float) -> None:
        """Set source current in amps."""
        self.write(f":SOUR:CURR {value}")

    def get_compliance_voltage(self) -> float:
        """Return compliance voltage in volts."""
        return float(self.query(":SOUR:CURR:COMP?"))

    def set_compliance_voltage(self, value: float) -> None:
        """Set compliance voltage in volts."""
        self.write(f":SOUR:CURR:COMP {value}")

    def output_enabled(self) -> bool:
        """Return ``True`` if source output is enabled."""
        return self.query(":OUTP:STAT?") == "1"

    def enable_output(self, state: bool) -> None:
        """Enable or disable source output."""
        self.write(f":OUTP:STAT {1 if state else 0}")

    def get_waveform(self) -> CurrentWaveform:
        """Return waveform mode."""
        token = self.query(":SOUR:WAVE:FUNC?").strip().upper()
        if token.startswith("SIN"):
            return CurrentWaveform.SINE
        return CurrentWaveform(token)

    def set_waveform(self, waveform: CurrentWaveform) -> None:
        """Set waveform mode."""
        token = "SIN" if waveform is CurrentWaveform.SINE else waveform.value
        self.write(f":SOUR:WAVE:FUNC {token}")

    def get_frequency(self) -> float:
        """Return AC waveform frequency in Hz."""
        return float(self.query(":SOUR:WAVE:FREQ?"))

    def set_frequency(self, value: float) -> None:
        """Set AC waveform frequency in Hz."""
        if value <= 0.0:
            raise ValueError("Frequency must be positive.")
        self.write(f":SOUR:WAVE:FREQ {value}")

    def get_offset_current(self) -> float:
        """Return AC waveform DC offset current in amps."""
        return float(self.query(":SOUR:WAVE:OFFS?"))

    def set_offset_current(self, value: float) -> None:
        """Set AC waveform DC offset current in amps."""
        self.write(f":SOUR:WAVE:OFFS {value}")

    def get_capabilities(self) -> CurrentSourceCapabilities:
        """Return static capabilities for Keithley 6221."""
        return CurrentSourceCapabilities(
            has_waveform_selection=True,
            has_frequency_control=True,
            has_offset_current=True,
            has_balanced_outputs=False,
            channel_count=1,
        )
