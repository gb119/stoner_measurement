"""Abstract base class for temperature controller instruments.

Defines the common interface for all temperature controller drivers.
Concrete subclasses (e.g. Lakeshore 336, Oxford ITC 503) implement the
abstract methods for the specific instrument's command set.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class TemperatureController(BaseInstrument):
    """Abstract base class for temperature controller instruments.

    Provides a uniform interface for reading temperatures, managing setpoints,
    and controlling heater output.  All temperature values are in Kelvin unless
    otherwise stated.

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol instance.

    Examples:
        >>> # Demonstrate interface using a minimal concrete implementation
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import LakeshoreProtocol
        >>> from stoner_measurement.instruments.temperature_controller import TemperatureController
        >>> class _TC(TemperatureController):
        ...     def get_temperature(self, channel): return 300.0
        ...     def get_setpoint(self, loop): return 300.0
        ...     def set_setpoint(self, loop, value): pass
        ...     def get_heater_output(self, loop): return 50.0
        ...     def set_heater_range(self, loop, range_): pass
        >>> tc = _TC(NullTransport(), LakeshoreProtocol())
        >>> tc.get_temperature("A")
        300.0
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        """Initialise the temperature controller.

        Args:
            transport (BaseTransport):
                Transport layer instance.
            protocol (BaseProtocol):
                Protocol instance.
        """
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def get_temperature(self, channel: str) -> float:
        """Return the current temperature for *channel* in Kelvin.

        Args:
            channel (str):
                Sensor channel identifier (instrument-specific, e.g. ``"A"``).

        Returns:
            (float):
                Current temperature in Kelvin.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def get_setpoint(self, loop: int) -> float:
        """Return the current setpoint for control *loop* in Kelvin.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (float):
                Setpoint temperature in Kelvin.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_setpoint(self, loop: int, value: float) -> None:
        """Set the target temperature for control *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            value (float):
                Desired setpoint in Kelvin.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *value* is outside the instrument's valid range.
        """

    @abstractmethod
    def get_heater_output(self, loop: int) -> float:
        """Return the heater output percentage for control *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (float):
                Heater output as a percentage (0–100 %).

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_heater_range(self, loop: int, range_: int) -> None:
        """Set the heater range for control *loop*.

        The meaning of *range_* is instrument-specific.  A value of ``0``
        conventionally means "heater off".

        Args:
            loop (int):
                Control loop number (1-based).
            range_ (int):
                Heater range index (instrument-specific).

        Raises:
            ConnectionError:
                If the transport is not open.
        """
