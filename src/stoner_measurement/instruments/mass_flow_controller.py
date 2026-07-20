"""Abstract base class for mass-flow and simple pressure-flow controllers."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


@dataclass(frozen=True)
class MassFlowControllerCapabilities:
    """Static capability descriptor for mass-flow-controller drivers."""

    channel_count: int = 1
    supports_unit_control: bool = True
    supports_range_control: bool = True
    supports_valve_control: bool = False
    supports_pressure_control: bool = False
    supports_batch: bool = False
    supports_blend: bool = False


class MassFlowController(BaseInstrument):
    """Abstract base class for mass-flow controllers and readout/controllers."""

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def read_actual_value(self, channel: int = 1) -> float:
        """Return the current measured value for *channel*."""

    @abstractmethod
    def read_setpoint(self, channel: int = 1) -> float:
        """Return the programmed setpoint for *channel*."""

    @abstractmethod
    def set_setpoint(self, value: float, channel: int = 1) -> None:
        """Set the programmed setpoint for *channel*."""

    @abstractmethod
    def read_unit(self, channel: int = 1) -> int | str:
        """Return the configured engineering-unit code for *channel*."""

    @abstractmethod
    def set_unit(self, unit_code: int | str, channel: int = 1) -> None:
        """Set the configured engineering-unit code for *channel*."""

    @abstractmethod
    def read_range(self, channel: int = 1) -> float:
        """Return the configured full-scale/range value for *channel*."""

    @abstractmethod
    def set_range(self, full_scale: float, channel: int = 1) -> None:
        """Set the configured full-scale/range value for *channel*."""

    @abstractmethod
    def get_capabilities(self) -> MassFlowControllerCapabilities:
        """Return the static capability descriptor for this driver."""

    def validate_channel(self, channel: int) -> None:
        """Raise ``ValueError`` if *channel* is unsupported."""
        capabilities = self.get_capabilities()
        if channel < 1 or channel > capabilities.channel_count:
            raise ValueError(
                f"{type(self).__name__} supports channels 1..{capabilities.channel_count}, "
                f"got {channel}."
            )

    def valve_enabled(self, channel: int = 1) -> bool:
        """Return ``True`` if valve/output control is enabled for *channel*."""
        _ = channel
        raise NotImplementedError(
            f"{type(self).__name__} does not support valve-state queries. "
            "Check get_capabilities().supports_valve_control before calling this method."
        )

    def set_valve_enabled(self, enabled: bool, channel: int = 1) -> None:
        """Enable or disable valve/output control for *channel*."""
        _ = (enabled, channel)
        raise NotImplementedError(
            f"{type(self).__name__} does not support valve control. "
            "Check get_capabilities().supports_valve_control before calling this method."
        )

    def configure_batch(self, channel: int, rate: float, quantity: float) -> None:
        """Configure a batch delivery workflow for *channel*."""
        _ = (channel, rate, quantity)
        raise NotImplementedError(
            f"{type(self).__name__} does not support batch workflows. "
            "Check get_capabilities().supports_batch before calling this method."
        )

    def configure_blend(self, master: int, slave: int, ratio_percent: float) -> None:
        """Configure a blend workflow between *master* and *slave*."""
        _ = (master, slave, ratio_percent)
        raise NotImplementedError(
            f"{type(self).__name__} does not support blend workflows. "
            "Check get_capabilities().supports_blend before calling this method."
        )
