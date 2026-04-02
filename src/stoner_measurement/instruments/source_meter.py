"""Abstract base class for source-meter instruments.

Defines the common interface for combined voltage/current source and
measurement instruments (SMUs).  Concrete subclasses (e.g. Keithley 2400,
Keithley 2450) implement the abstract methods for the specific instrument.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport

#: Possible source modes for an SMU.
SourceMode = str  # Literal["VOLT", "CURR"]


class SourceMeter(BaseInstrument):
    """Abstract base class for source-measure unit (SMU) instruments.

    A source-meter can source voltage or current while simultaneously
    measuring the complementary quantity, making it suitable for
    current-voltage (I–V) characterisation.

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol instance.

    Examples:
        >>> # Demonstrate interface using a minimal concrete implementation
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import ScpiProtocol
        >>> from stoner_measurement.instruments.source_meter import SourceMeter
        >>> class _SM(SourceMeter):
        ...     def get_source_mode(self): return "VOLT"
        ...     def set_source_mode(self, mode): pass
        ...     def get_source_level(self): return 1.0
        ...     def set_source_level(self, value): pass
        ...     def get_compliance(self): return 0.1
        ...     def set_compliance(self, value): pass
        ...     def get_nplc(self): return 1.0
        ...     def set_nplc(self, value): pass
        ...     def measure_voltage(self): return 1.0
        ...     def measure_current(self): return 0.001
        ...     def output_enabled(self): return False
        ...     def enable_output(self, state): pass
        >>> sm = _SM(NullTransport(), ScpiProtocol())
        >>> sm.get_source_mode()
        'VOLT'
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        """Initialise the source meter.

        Args:
            transport (BaseTransport):
                Transport layer instance.
            protocol (BaseProtocol):
                Protocol instance.
        """
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def get_source_mode(self) -> SourceMode:
        """Return the current source mode (``"VOLT"`` or ``"CURR"``).

        Returns:
            (str):
                Source mode: ``"VOLT"`` for voltage source or ``"CURR"`` for
                current source.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_source_mode(self, mode: SourceMode) -> None:
        """Set the source mode.

        Args:
            mode (str):
                ``"VOLT"`` for voltage source or ``"CURR"`` for current source.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *mode* is not ``"VOLT"`` or ``"CURR"``.
        """

    @abstractmethod
    def get_source_level(self) -> float:
        """Return the programmed source level (V or A).

        Returns:
            (float):
                Source amplitude in volts or amps depending on
                :meth:`get_source_mode`.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_source_level(self, value: float) -> None:
        """Set the source output level (V or A).

        Args:
            value (float):
                Source amplitude in volts (voltage mode) or amps (current mode).

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def get_compliance(self) -> float:
        """Return the compliance limit (A in voltage mode, V in current mode).

        Returns:
            (float):
                Compliance value in amps or volts.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_compliance(self, value: float) -> None:
        """Set the compliance limit.

        Args:
            value (float):
                Compliance in amps (voltage mode) or volts (current mode).

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *value* exceeds the instrument's maximum compliance.
        """

    @abstractmethod
    def get_nplc(self) -> float:
        """Return the integration time in power-line cycles (NPLC).

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
                Integration time in power-line cycles.  Typical range is
                0.01–10.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *value* is outside the valid range.
        """

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
    def measure_current(self) -> float:
        """Trigger a current measurement and return the result in amps.

        Returns:
            (float):
                Measured current in amps.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def output_enabled(self) -> bool:
        """Return ``True`` if the source output is currently enabled.

        Returns:
            (bool):
                ``True`` when the output is on, ``False`` when off.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def enable_output(self, state: bool) -> None:
        """Enable or disable the source output.

        Args:
            state (bool):
                ``True`` to enable the output, ``False`` to disable it.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
