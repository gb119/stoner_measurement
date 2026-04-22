"""Abstract base class for nanovoltmeter instruments.

Defines the common interface for high-precision voltmeter instruments.
Concrete subclasses (e.g. Keithley 2182A, Keithley 182) implement the
abstract methods for the specific instrument's command set.
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


class NanovoltmeterFunction(Enum):
    """Measurement functions for nanovoltmeters."""

    VOLT = "VOLT"
    TEMP = "TEMP"


class NanovoltmeterTriggerSource(Enum):
    """Trigger-source selection for nanovoltmeters."""

    IMM = "IMM"
    BUS = "BUS"
    EXT = "EXT"
    TIM = "TIM"
    MAN = "MAN"


@dataclass(frozen=True)
class NanovoltmeterCapabilities:
    """Static capability descriptor for a nanovoltmeter driver."""

    has_function_selection: bool = False
    has_filter: bool = False
    has_trigger: bool = False
    has_buffer: bool = False
    supported_functions: tuple[NanovoltmeterFunction, ...] = (NanovoltmeterFunction.VOLT,)


class Nanovoltmeter(BaseInstrument):
    """Abstract base class for nanovoltmeter instruments.

    Provides a uniform interface for high-sensitivity DC voltage measurements.
    Nanovoltmeters are commonly used in low-resistance measurements, Hall-effect
    measurements, and thermoelectric studies.

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol instance.

    Examples:
        >>> # Demonstrate interface using a minimal concrete implementation
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import ScpiProtocol
        >>> from stoner_measurement.instruments.nanovoltmeter import Nanovoltmeter
        >>> class _NVM(Nanovoltmeter):
        ...     def measure_voltage(self): return 1.23e-6
        ...     def get_range(self): return 0.1
        ...     def set_range(self, value): pass
        ...     def get_autorange(self): return True
        ...     def set_autorange(self, state): pass
        ...     def get_nplc(self): return 5.0
        ...     def set_nplc(self, value): pass
        >>> nvm = _NVM(NullTransport(), ScpiProtocol())
        >>> nvm.measure_voltage()
        1.23e-06
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        """Initialise the nanovoltmeter.

        Args:
            transport (BaseTransport):
                Transport layer instance.
            protocol (BaseProtocol):
                Protocol instance.
        """
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def measure_voltage(self) -> float:
        """Trigger a voltage measurement and return the result in volts.

        Returns:
            (float):
                Measured voltage in volts.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def get_range(self) -> float:
        """Return the current voltage measurement range in volts.

        Returns:
            (float):
                Active measurement range in volts.  ``0.0`` typically
                indicates autorange is active.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_range(self, value: float) -> None:
        """Set the voltage measurement range.

        Args:
            value (float):
                Measurement range in volts.  Pass ``0.0`` to enable autorange
                on instruments that conflate the two settings.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *value* is not a valid range for this instrument.
        """

    @abstractmethod
    def get_autorange(self) -> bool:
        """Return ``True`` if autorange is currently enabled.

        Returns:
            (bool):
                ``True`` when the instrument selects the range automatically.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_autorange(self, state: bool) -> None:
        """Enable or disable automatic range selection.

        Args:
            state (bool):
                ``True`` to enable autorange, ``False`` to use the manually
                set range.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def get_nplc(self) -> float:
        """Return the integration time in power-line cycles.

        Returns:
            (float):
                Integration time in power-line cycles.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_nplc(self, value: float) -> None:
        """Set the integration time in power-line cycles.

        Args:
            value (float):
                Integration time in power-line cycles.  Longer integration
                times improve resolution but reduce throughput.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *value* is outside the valid range for this instrument.
        """

    @abstractmethod
    def get_measure_function(self) -> NanovoltmeterFunction:
        """Return the active measurement function.

        Returns:
            (NanovoltmeterFunction):
                Active measurement function.
        """

    @abstractmethod
    def set_measure_function(self, function: NanovoltmeterFunction) -> None:
        """Set the active measurement function.

        Args:
            function (NanovoltmeterFunction):
                Function to select.
        """

    @abstractmethod
    def get_capabilities(self) -> NanovoltmeterCapabilities:
        """Return static capability metadata.

        Returns:
            (NanovoltmeterCapabilities):
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

    def get_trigger_source(self) -> NanovoltmeterTriggerSource:
        """Return the trigger source selection.

        Raises:
            NotImplementedError:
                If trigger configuration is not supported by the instrument.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support trigger configuration. "
            "Check get_capabilities().has_trigger before calling this method."
        )

    def set_trigger_source(self, source: NanovoltmeterTriggerSource) -> None:
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
