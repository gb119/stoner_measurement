"""Abstract base class for magnet controller instruments.

Defines the common interface for superconducting magnet power supply
controllers.  Concrete subclasses (e.g. Oxford IPS 120-10) implement the
abstract methods for the specific instrument's command set.

Magnetic field values are in Tesla and ramp rates in Tesla per minute unless
otherwise stated.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class MagnetController(BaseInstrument):
    """Abstract base class for magnet power supply controller instruments.

    Provides a uniform interface for reading and controlling the magnetic
    field produced by a superconducting solenoid.  All field values are
    in Tesla and ramp rates in Tesla per minute.

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol instance.

    Examples:
        >>> # Demonstrate interface using a minimal concrete implementation
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import OxfordProtocol
        >>> from stoner_measurement.instruments.magnet_controller import MagnetController
        >>> class _MC(MagnetController):
        ...     def get_field(self): return 1.5
        ...     def get_field_setpoint(self): return 1.5
        ...     def set_field_setpoint(self, value): pass
        ...     def get_ramp_rate(self): return 0.1
        ...     def set_ramp_rate(self, rate): pass
        ...     def go_to_setpoint(self): pass
        ...     def go_to_zero(self): pass
        ...     def hold(self): pass
        >>> mc = _MC(NullTransport(), OxfordProtocol())
        >>> mc.get_field()
        1.5
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        """Initialise the magnet controller.

        Args:
            transport (BaseTransport):
                Transport layer instance.
            protocol (BaseProtocol):
                Protocol instance.
        """
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def get_field(self) -> float:
        """Return the current magnetic field in Tesla.

        Returns:
            (float):
                Measured field in Tesla.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def get_field_setpoint(self) -> float:
        """Return the target field setpoint in Tesla.

        Returns:
            (float):
                Target field in Tesla.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_field_setpoint(self, value: float) -> None:
        """Set the target field in Tesla.

        Args:
            value (float):
                Desired field in Tesla.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *value* exceeds the instrument's maximum rated field.
        """

    @abstractmethod
    def get_ramp_rate(self) -> float:
        """Return the field ramp rate in Tesla per minute.

        Returns:
            (float):
                Current ramp rate in T/min.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_ramp_rate(self, rate: float) -> None:
        """Set the field ramp rate in Tesla per minute.

        Args:
            rate (float):
                Desired ramp rate in T/min.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *rate* exceeds the instrument's maximum rated ramp rate.
        """

    @abstractmethod
    def go_to_setpoint(self) -> None:
        """Begin ramping the field towards the current setpoint.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def go_to_zero(self) -> None:
        """Begin ramping the field to zero.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def hold(self) -> None:
        """Hold the field at its current value (stop ramping).

        Raises:
            ConnectionError:
                If the transport is not open.
        """
