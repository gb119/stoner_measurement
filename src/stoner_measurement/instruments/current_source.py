"""Abstract base class for current-source instruments.

Defines a common API for precision current sources, including DC sourcing and
optional AC waveform features. Drivers can also expose balanced multi-channel
behaviour via capability flags and channel helper methods.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class CurrentWaveform(Enum):
    """Output waveform mode of a current source."""

    DC = "DC"
    SINE = "SINE"


@dataclass(frozen=True)
class CurrentSourceCapabilities:
    """Static capability descriptor for a current-source driver.

    Attributes:
        has_waveform_selection (bool):
            ``True`` if the source can select waveform mode.
        has_frequency_control (bool):
            ``True`` if AC waveform frequency can be configured.
        has_offset_current (bool):
            ``True`` if waveform DC offset current can be configured.
        has_balanced_outputs (bool):
            ``True`` if the source supports balanced multi-channel output pairs.
        channel_count (int):
            Number of independently addressable output channels.
    """

    has_waveform_selection: bool = False
    has_frequency_control: bool = False
    has_offset_current: bool = False
    has_balanced_outputs: bool = False
    channel_count: int = 1


class CurrentSource(BaseInstrument):
    """Abstract base class for precision current-source instruments."""

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        """Initialise the current source."""
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def get_source_level(self) -> float:
        """Return programmed source current in amps."""

    @abstractmethod
    def set_source_level(self, value: float) -> None:
        """Set source current in amps."""

    @abstractmethod
    def get_compliance_voltage(self) -> float:
        """Return compliance voltage in volts."""

    @abstractmethod
    def set_compliance_voltage(self, value: float) -> None:
        """Set compliance voltage in volts."""

    @abstractmethod
    def output_enabled(self) -> bool:
        """Return ``True`` if source output is enabled."""

    @abstractmethod
    def enable_output(self, state: bool) -> None:
        """Enable or disable source output."""

    @abstractmethod
    def get_capabilities(self) -> CurrentSourceCapabilities:
        """Return the static capability descriptor for this driver."""

    def get_waveform(self) -> CurrentWaveform:
        """Return the configured output waveform."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support waveform selection. "
            "Check get_capabilities().has_waveform_selection before calling this method."
        )

    def set_waveform(self, waveform: CurrentWaveform) -> None:
        """Set output waveform mode."""
        _ = waveform
        raise NotImplementedError(
            f"{type(self).__name__} does not support waveform selection. "
            "Check get_capabilities().has_waveform_selection before calling this method."
        )

    def get_frequency(self) -> float:
        """Return AC waveform frequency in Hz."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support frequency control. "
            "Check get_capabilities().has_frequency_control before calling this method."
        )

    def set_frequency(self, value: float) -> None:
        """Set AC waveform frequency in Hz."""
        _ = value
        raise NotImplementedError(
            f"{type(self).__name__} does not support frequency control. "
            "Check get_capabilities().has_frequency_control before calling this method."
        )

    def get_offset_current(self) -> float:
        """Return AC waveform DC offset current in amps."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support offset-current control. "
            "Check get_capabilities().has_offset_current before calling this method."
        )

    def set_offset_current(self, value: float) -> None:
        """Set AC waveform DC offset current in amps."""
        _ = value
        raise NotImplementedError(
            f"{type(self).__name__} does not support offset-current control. "
            "Check get_capabilities().has_offset_current before calling this method."
        )

    def get_channel_level(self, channel: int) -> float:
        """Return programmed current for a specific output channel."""
        _ = channel
        raise NotImplementedError(
            f"{type(self).__name__} does not support per-channel current control. "
            "Check get_capabilities().has_balanced_outputs before calling this method."
        )

    def set_channel_level(self, channel: int, value: float) -> None:
        """Set current for a specific output channel."""
        _ = (channel, value)
        raise NotImplementedError(
            f"{type(self).__name__} does not support per-channel current control. "
            "Check get_capabilities().has_balanced_outputs before calling this method."
        )
