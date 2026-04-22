"""Abstract base class for digital multimeter instruments."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class DmmFunction(Enum):
    """Measurement functions for digital multimeters."""

    VOLT_DC = "VOLT:DC"
    VOLT_AC = "VOLT:AC"
    CURR_DC = "CURR:DC"
    CURR_AC = "CURR:AC"
    RES = "RES"
    FRES = "FRES"
    FREQ = "FREQ"
    PER = "PER"
    TEMP = "TEMP"


class DmmTriggerSource(Enum):
    """Trigger-source selection for digital multimeters."""

    IMM = "IMM"
    BUS = "BUS"
    EXT = "EXT"
    TIM = "TIM"
    MAN = "MAN"


@dataclass(frozen=True)
class DmmCapabilities:
    """Static capability descriptor for a DMM driver."""

    has_function_selection: bool = True
    has_filter: bool = False
    has_trigger: bool = False
    has_buffer: bool = False
    supported_functions: tuple[DmmFunction, ...] = (DmmFunction.VOLT_DC,)


class DigitalMultimeter(BaseInstrument):
    """Abstract base class for digital multimeter instruments.

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol instance.
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        """Initialise the multimeter.

        Args:
            transport (BaseTransport):
                Transport layer instance.
            protocol (BaseProtocol):
                Protocol instance.
        """
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def measure(self) -> float:
        """Trigger a measurement and return its value.

        Returns:
            (float):
                Measured scalar value in units of the active function.
        """

    @abstractmethod
    def get_measure_function(self) -> DmmFunction:
        """Return the active measurement function.

        Returns:
            (DmmFunction):
                Active measurement function.
        """

    @abstractmethod
    def set_measure_function(self, function: DmmFunction) -> None:
        """Set the active measurement function.

        Args:
            function (DmmFunction):
                Function to select.
        """

    @abstractmethod
    def get_range(self) -> float:
        """Return the active measurement range.

        Returns:
            (float):
                Range value in units of the active function.
        """

    @abstractmethod
    def set_range(self, value: float) -> None:
        """Set the active measurement range.

        Args:
            value (float):
                Range value in units of the active function.
        """

    @abstractmethod
    def get_autorange(self) -> bool:
        """Return ``True`` if autorange is enabled.

        Returns:
            (bool):
                ``True`` when autorange is enabled.
        """

    @abstractmethod
    def set_autorange(self, state: bool) -> None:
        """Enable or disable autorange.

        Args:
            state (bool):
                ``True`` to enable autorange.
        """

    @abstractmethod
    def get_nplc(self) -> float:
        """Return the integration time in line cycles.

        Returns:
            (float):
                Integration time in power-line cycles.
        """

    @abstractmethod
    def set_nplc(self, value: float) -> None:
        """Set the integration time in line cycles.

        Args:
            value (float):
                Integration time in power-line cycles.
        """

    @abstractmethod
    def get_capabilities(self) -> DmmCapabilities:
        """Return static capability metadata.

        Returns:
            (DmmCapabilities):
                Capability descriptor.
        """

    def get_filter_enabled(self) -> bool:
        """Return whether filtering is enabled.

        Raises:
            NotImplementedError:
                If filtering is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support filtering. "
            "Check get_capabilities().has_filter before calling this method."
        )

    def set_filter_enabled(self, state: bool) -> None:
        """Enable or disable measurement filtering.

        Raises:
            NotImplementedError:
                If filtering is not supported by the instrument.
        """
        _ = state
        raise NotImplementedError(
            f"{type(self).__name__} does not support filtering. "
            "Check get_capabilities().has_filter before calling this method."
        )

    def get_filter_count(self) -> int:
        """Return the configured filter averaging count.

        Raises:
            NotImplementedError:
                If filtering is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support filtering. "
            "Check get_capabilities().has_filter before calling this method."
        )

    def set_filter_count(self, count: int) -> None:
        """Set the filter averaging count.

        Raises:
            NotImplementedError:
                If filtering is not supported by the instrument.
        """
        _ = count
        raise NotImplementedError(
            f"{type(self).__name__} does not support filtering. "
            "Check get_capabilities().has_filter before calling this method."
        )

    def get_trigger_source(self) -> DmmTriggerSource:
        """Return the trigger source selection.

        Raises:
            NotImplementedError:
                If trigger configuration is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger configuration. "
            "Check get_capabilities().has_trigger before calling this method."
        )

    def set_trigger_source(self, source: DmmTriggerSource) -> None:
        """Set the trigger source selection.

        Raises:
            NotImplementedError:
                If trigger configuration is not supported by the instrument.
        """
        _ = source
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger configuration. "
            "Check get_capabilities().has_trigger before calling this method."
        )

    def get_trigger_count(self) -> int:
        """Return the configured trigger count.

        Raises:
            NotImplementedError:
                If trigger configuration is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger configuration. "
            "Check get_capabilities().has_trigger before calling this method."
        )

    def set_trigger_count(self, count: int) -> None:
        """Set the trigger count.

        Raises:
            NotImplementedError:
                If trigger configuration is not supported by the instrument.
        """
        _ = count
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger configuration. "
            "Check get_capabilities().has_trigger before calling this method."
        )

    def initiate(self) -> None:
        """Arm the trigger system and begin measurements.

        Raises:
            NotImplementedError:
                If trigger configuration is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger configuration. "
            "Check get_capabilities().has_trigger before calling this method."
        )

    def abort(self) -> None:
        """Abort a running measurement sequence.

        Raises:
            NotImplementedError:
                If trigger configuration is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger configuration. "
            "Check get_capabilities().has_trigger before calling this method."
        )

    def clear_buffer(self) -> None:
        """Clear the instrument reading buffer.

        Raises:
            NotImplementedError:
                If buffer operations are not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer operations. "
            "Check get_capabilities().has_buffer before calling this method."
        )

    def get_buffer_count(self) -> int:
        """Return the number of readings currently stored in the buffer.

        Raises:
            NotImplementedError:
                If buffer operations are not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer operations. "
            "Check get_capabilities().has_buffer before calling this method."
        )

    def read_buffer(self, count: int | None = None) -> tuple[float, ...]:
        """Read values from the instrument buffer.

        Keyword Parameters:
            count (int | None):
                Optional number of points to read from the start of the buffer.
                If ``None``, read all available points.

        Returns:
            (tuple[float, ...]):
                Parsed buffer values.

        Raises:
            NotImplementedError:
                If buffer operations are not supported by the instrument.
        """
        _ = count
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading buffer operations. "
            "Check get_capabilities().has_buffer before calling this method."
        )
