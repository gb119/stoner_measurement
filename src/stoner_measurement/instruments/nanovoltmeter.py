"""Abstract base class for nanovoltmeter instruments.

Defines the common interface for high-precision voltmeter instruments.
Concrete subclasses (e.g. Keithley 2182A, Keithley 182) implement the
abstract methods for the specific instrument's command set.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


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
