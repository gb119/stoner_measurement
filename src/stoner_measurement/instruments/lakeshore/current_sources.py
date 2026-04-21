"""Lakeshore current-source drivers."""

from __future__ import annotations

from stoner_measurement.instruments.current_source import (
    CurrentSource,
    CurrentSourceCapabilities,
    CurrentWaveform,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

_M81_DEFAULT_POSITIVE_CHANNEL = 1
_M81_DEFAULT_NEGATIVE_CHANNEL = 2


class LakeshoreM81CurrentSource(CurrentSource):
    """Driver for the Lakeshore M81 balanced current-source outputs."""

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
    ) -> None:
        """Initialise the Lakeshore M81 current-source driver."""
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )

    @staticmethod
    def _validate_channel(channel: int) -> None:
        """Validate M81 channel index."""
        if channel not in (_M81_DEFAULT_POSITIVE_CHANNEL, _M81_DEFAULT_NEGATIVE_CHANNEL):
            raise ValueError("M81 supports balanced current channels 1 and 2.")

    def get_channel_level(self, channel: int) -> float:
        """Return programmed current for a specific channel in amps."""
        self._validate_channel(channel)
        return float(self.query(f":SOUR{channel}:CURR?"))

    def set_channel_level(self, channel: int, value: float) -> None:
        """Set programmed current for a specific channel in amps."""
        self._validate_channel(channel)
        self.write(f":SOUR{channel}:CURR {value}")

    def get_source_level(self) -> float:
        """Return differential source current amplitude in amps."""
        return self.get_channel_level(_M81_DEFAULT_POSITIVE_CHANNEL)

    def set_source_level(self, value: float) -> None:
        """Set differential source current amplitude in amps."""
        self.set_channel_level(_M81_DEFAULT_POSITIVE_CHANNEL, value)
        self.set_channel_level(_M81_DEFAULT_NEGATIVE_CHANNEL, -value)

    def get_compliance_voltage(self) -> float:
        """Return compliance voltage in volts."""
        return float(self.query(":SOUR1:CURR:COMP?"))

    def set_compliance_voltage(self, value: float) -> None:
        """Set compliance voltage in volts for both channels."""
        self.write(f":SOUR1:CURR:COMP {value}")
        self.write(f":SOUR2:CURR:COMP {value}")

    def output_enabled(self) -> bool:
        """Return ``True`` if both balanced outputs are enabled."""
        return self.query(":OUTP1:STAT?") == "1" and self.query(":OUTP2:STAT?") == "1"

    def enable_output(self, state: bool) -> None:
        """Enable or disable both balanced outputs."""
        bit = 1 if state else 0
        self.write(f":OUTP1:STAT {bit}")
        self.write(f":OUTP2:STAT {bit}")

    def get_waveform(self) -> CurrentWaveform:
        """Return waveform mode."""
        token = self.query(":SOUR1:FUNC?").strip().upper()
        if token.startswith("SIN"):
            return CurrentWaveform.SINE
        return CurrentWaveform(token)

    def set_waveform(self, waveform: CurrentWaveform) -> None:
        """Set waveform mode for both channels."""
        token = "SIN" if waveform is CurrentWaveform.SINE else waveform.value
        self.write(f":SOUR1:FUNC {token}")
        self.write(f":SOUR2:FUNC {token}")

    def get_frequency(self) -> float:
        """Return waveform frequency in Hz."""
        return float(self.query(":SOUR1:FREQ?"))

    def set_frequency(self, value: float) -> None:
        """Set waveform frequency in Hz for both channels."""
        if value <= 0.0:
            raise ValueError("Frequency must be positive.")
        self.write(f":SOUR1:FREQ {value}")
        self.write(f":SOUR2:FREQ {value}")

    def get_offset_current(self) -> float:
        """Return waveform offset current in amps."""
        return float(self.query(":SOUR1:CURR:OFFS?"))

    def set_offset_current(self, value: float) -> None:
        """Set waveform offset current in amps for both channels."""
        self.write(f":SOUR1:CURR:OFFS {value}")
        self.write(f":SOUR2:CURR:OFFS {-value}")

    def get_capabilities(self) -> CurrentSourceCapabilities:
        """Return static capabilities for Lakeshore M81 current source."""
        return CurrentSourceCapabilities(
            has_waveform_selection=True,
            has_frequency_control=True,
            has_offset_current=True,
            has_balanced_outputs=True,
            channel_count=2,
        )
