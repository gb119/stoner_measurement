"""Abstract base class for electrometer and picoammeter instruments."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class ElectrometerFunction(Enum):
    """Measurement function selected on an electrometer."""

    CURR = "CURR"
    VOLT = "VOLT"
    RES = "RES"
    CHARGE = "CHAR"


class ElectrometerDataFormat(Enum):
    """Data transfer format used for query responses."""

    ASCII = "ASC"
    SREAL = "SRE"
    DREAL = "DRE"


class ElectrometerTriggerSource(Enum):
    """Trigger source for a simple trigger model."""

    IMM = "IMM"
    BUS = "BUS"
    EXT = "EXT"
    TLIN = "TLIN"
    TIM = "TIM"


@dataclass(frozen=True)
class ElectrometerTriggerConfiguration:
    """Configuration for trigger and arm model settings."""

    trigger_source: ElectrometerTriggerSource = ElectrometerTriggerSource.IMM
    trigger_count: int = 1
    trigger_delay: float = 0.0
    arm_source: ElectrometerTriggerSource = ElectrometerTriggerSource.IMM
    arm_count: int = 1


@dataclass(frozen=True)
class ElectrometerCapabilities:
    """Static capability descriptor for an electrometer driver."""

    has_function_selection: bool = False
    has_filter: bool = False
    has_trigger_model: bool = False
    has_buffer: bool = False
    has_data_format: bool = False


class Electrometer(BaseInstrument):
    """Abstract base class for electrometer and picoammeter instruments."""

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def measure_current(self) -> float:
        """Trigger a current measurement and return the value in amps."""

    @abstractmethod
    def get_range(self) -> float:
        """Return the active current range in amps."""

    @abstractmethod
    def set_range(self, value: float) -> None:
        """Set the current range in amps."""

    @abstractmethod
    def get_autorange(self) -> bool:
        """Return ``True`` if autorange is enabled."""

    @abstractmethod
    def set_autorange(self, state: bool) -> None:
        """Enable or disable autorange."""

    @abstractmethod
    def get_nplc(self) -> float:
        """Return integration time in power-line cycles."""

    @abstractmethod
    def set_nplc(self, value: float) -> None:
        """Set integration time in power-line cycles."""

    @abstractmethod
    def get_capabilities(self) -> ElectrometerCapabilities:
        """Return static feature capabilities for the driver."""

    def get_measure_functions(self) -> tuple[ElectrometerFunction, ...]:
        """Return enabled measurement functions."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support measurement function selection. "
            "Check get_capabilities().has_function_selection before calling this method."
        )

    def set_measure_functions(self, functions: tuple[ElectrometerFunction, ...]) -> None:
        """Enable one or more measurement functions."""
        _ = functions
        raise NotImplementedError(
            f"{type(self).__name__} does not support measurement function selection. "
            "Check get_capabilities().has_function_selection before calling this method."
        )

    def get_filter_enabled(self) -> bool:
        """Return ``True`` if digital averaging filter is enabled."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support filter control. "
            "Check get_capabilities().has_filter before calling this method."
        )

    def set_filter_enabled(self, state: bool) -> None:
        """Enable or disable digital averaging filter."""
        _ = state
        raise NotImplementedError(
            f"{type(self).__name__} does not support filter control. "
            "Check get_capabilities().has_filter before calling this method."
        )

    def get_filter_count(self) -> int:
        """Return averaging filter count."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support filter control. "
            "Check get_capabilities().has_filter before calling this method."
        )

    def set_filter_count(self, count: int) -> None:
        """Set averaging filter count."""
        _ = count
        raise NotImplementedError(
            f"{type(self).__name__} does not support filter control. "
            "Check get_capabilities().has_filter before calling this method."
        )

    def configure_trigger_model(self, config: ElectrometerTriggerConfiguration) -> None:
        """Configure trigger and arm model settings."""
        _ = config
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger model configuration. "
            "Check get_capabilities().has_trigger_model before calling this method."
        )

    def initiate(self) -> None:
        """Start trigger execution."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger model configuration. "
            "Check get_capabilities().has_trigger_model before calling this method."
        )

    def abort(self) -> None:
        """Abort trigger execution."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger model configuration. "
            "Check get_capabilities().has_trigger_model before calling this method."
        )

    def set_buffer_size(self, size: int) -> None:
        """Set trace buffer size."""
        _ = size
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer control. "
            "Check get_capabilities().has_buffer before calling this method."
        )

    def get_buffer_size(self) -> int:
        """Return trace buffer size."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer control. "
            "Check get_capabilities().has_buffer before calling this method."
        )

    def clear_buffer(self) -> None:
        """Clear trace buffer data."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer control. "
            "Check get_capabilities().has_buffer before calling this method."
        )

    def read_buffer(self, count: int | None = None) -> tuple[float, ...]:
        """Return trace buffer readings."""
        _ = count
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer control. "
            "Check get_capabilities().has_buffer before calling this method."
        )

    def get_data_format(self) -> ElectrometerDataFormat:
        """Return configured response data format."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support data format control. "
            "Check get_capabilities().has_data_format before calling this method."
        )

    def set_data_format(self, data_format: ElectrometerDataFormat) -> None:
        """Set response data format."""
        _ = data_format
        raise NotImplementedError(
            f"{type(self).__name__} does not support data format control. "
            "Check get_capabilities().has_data_format before calling this method."
        )
