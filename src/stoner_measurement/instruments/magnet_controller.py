"""Abstract interfaces for superconducting magnet power supply instruments.

Defines shared types and abstract interfaces for magnet controller drivers.
Magnetic field values are in tesla and ramp rates in tesla per minute unless
otherwise stated.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class MagnetState(Enum):
    """Operational state of a superconducting magnet power supply.

    Attributes:
        STANDBY:
            The supply is powered but not actively ramping.
        RAMPING:
            The output is being ramped towards the programmed target.
        AT_TARGET:
            The output has reached the programmed target field or current.
        PERSISTENT:
            The magnet is in persistent mode (heater off, leads de-energised).
        QUIESCENT:
            The supply is in a low-power idle state.
        FAULT:
            A recoverable fault condition has been detected.
        QUENCH:
            A quench has been detected; the magnet protection circuit has
            discharged the stored energy.
        UNKNOWN:
            The state cannot be determined from the instrument response.
    """

    STANDBY = "standby"
    RAMPING = "ramping"
    AT_TARGET = "at_target"
    PERSISTENT = "persistent"
    QUIESCENT = "quiescent"
    FAULT = "fault"
    QUENCH = "quench"
    UNKNOWN = "unknown"


@dataclass
class MagnetLimits:
    """Operating limits for a superconducting magnet power supply.

    Attributes:
        max_current (float):
            Maximum permitted output current in amps.
        max_field (float | None):
            Maximum permitted field in tesla, or ``None`` if not configured.
        max_ramp_rate (float | None):
            Maximum permitted ramp rate in amps per second or tesla per
            minute (instrument-specific units), or ``None`` if not
            configured.
    """

    max_current: float
    max_field: float | None = None
    max_ramp_rate: float | None = None


@dataclass
class MagnetStatus:
    """Consolidated status snapshot of a magnet power supply.

    Attributes:
        state (MagnetState):
            Current operational state of the supply.
        current (float):
            Output current in amps.
        field (float | None):
            Estimated magnetic field in tesla, or ``None`` if the magnet
            constant is not configured.
        voltage (float | None):
            Output voltage in volts, or ``None`` if not reported by the
            instrument.
        persistent (bool):
            ``True`` when the supply is operating in persistent mode.
        heater_on (bool | None):
            ``True`` when the persistent switch heater is energised,
            ``False`` when it is off, or ``None`` if the state is unknown.
        at_target (bool):
            ``True`` when the output has reached the programmed target.
        message (str | None):
            Optional human-readable status or error message from the
            instrument, or ``None`` if no message is available.
    """

    state: MagnetState
    current: float
    field: float | None
    voltage: float | None
    persistent: bool
    heater_on: bool | None
    at_target: bool
    message: str | None = None


class MagnetSupply(Protocol):
    """Protocol describing the expected interface of a magnet supply driver.

    Defines the minimum lifecycle, configuration, readback, and ramp-control
    operations required by code that interacts with magnet supply objects.
    """

    # --- lifecycle ---
    def connect(self) -> None:
        ...

    def disconnect(self) -> None:
        ...

    def is_connected(self) -> bool:
        ...

    # context manager sugar
    def __enter__(self) -> MagnetSupply:
        ...

    def __exit__(self, exc_type, exc, tb) -> None:
        ...

    # --- identity & configuration ---
    def identify(self) -> str:
        ...

    def get_model(self) -> str:
        ...

    def get_firmware_version(self) -> str:
        ...

    # --- readings as properties ---
    @property
    def current(self) -> float:
        ...

    @property
    def field(self) -> float:
        ...

    @property
    def voltage(self) -> float:
        ...

    @property
    def status(self) -> MagnetStatus:
        ...

    @property
    def magnet_constant(self) -> float:
        ...

    @property
    def limits(self) -> MagnetLimits:
        ...

    @property
    def heater(self) -> bool:
        ...

    # --- configuration as methods ---
    def set_target_current(self, current: float) -> None:
        ...

    def set_target_field(self, field: float) -> None:
        ...

    def set_ramp_rate_current(self, rate: float) -> None:
        ...

    def set_ramp_rate_field(self, rate: float) -> None:
        ...

    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        ...

    def set_limits(self, limits: MagnetLimits) -> None:
        ...

    # --- actions as methods ---
    def ramp_to_target(self) -> None:
        ...

    def ramp_to_current(self, current: float, *, wait: bool = False) -> None:
        ...

    def ramp_to_field(self, field: float, *, wait: bool = False) -> None:
        ...

    def pause_ramp(self) -> None:
        ...

    def abort_ramp(self) -> None:
        ...

    # --- persistent switch ---
    def heater_on(self) -> None:
        ...

    def heater_off(self) -> None:
        ...


class MagnetController(BaseInstrument):
    """Abstract base class for superconducting magnet power supply drivers.

    Provides a uniform interface for controlling superconducting magnet power
    supplies such as the Oxford Instruments IPS120-10.  All field values are
    in tesla and ramp rates in tesla per minute unless otherwise stated.

    Subclasses must implement all abstract methods.

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol layer instance.

    Examples:
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import OxfordProtocol
        >>> from stoner_measurement.instruments.magnet_controller import (
        ...     MagnetController, MagnetState, MagnetStatus, MagnetLimits,
        ... )
        >>> class _MC(MagnetController):
        ...     def get_model(self): return "TestMagnet"
        ...     def get_firmware_version(self): return "1.0"
        ...     @property
        ...     def current(self): return 0.0
        ...     @property
        ...     def field(self): return 0.0
        ...     @property
        ...     def voltage(self): return 0.0
        ...     @property
        ...     def status(self):
        ...         return MagnetStatus(
        ...             state=MagnetState.STANDBY, current=0.0, field=0.0,
        ...             voltage=0.0, persistent=False, heater_on=False,
        ...             at_target=True,
        ...         )
        ...     @property
        ...     def magnet_constant(self): return 0.1
        ...     @property
        ...     def limits(self): return MagnetLimits(max_current=100.0)
        ...     @property
        ...     def heater(self): return False
        ...     def set_target_current(self, current): pass
        ...     def set_target_field(self, field): pass
        ...     def set_ramp_rate_current(self, rate): pass
        ...     def set_ramp_rate_field(self, rate): pass
        ...     def set_magnet_constant(self, tesla_per_amp): pass
        ...     def set_limits(self, limits): pass
        ...     def ramp_to_target(self): pass
        ...     def ramp_to_current(self, current, *, wait=False): pass
        ...     def ramp_to_field(self, field, *, wait=False): pass
        ...     def pause_ramp(self): pass
        ...     def abort_ramp(self): pass
        ...     def heater_on(self): pass
        ...     def heater_off(self): pass
        >>> mc = _MC(NullTransport(), OxfordProtocol())
        >>> mc.get_model()
        'TestMagnet'
        >>> mc.status.state
        <MagnetState.STANDBY: 'standby'>
    """

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol) -> None:
        """Initialise the magnet controller.

        Args:
            transport (BaseTransport):
                Transport layer used for physical I/O.
            protocol (BaseProtocol):
                Protocol layer used for command formatting/parsing.
        """
        super().__init__(transport=transport, protocol=protocol)

    @abstractmethod
    def get_model(self) -> str:
        """Return the instrument model identifier string.

        Returns:
            (str):
                Instrument model identifier as reported by the device.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> mc.get_model()  # doctest: +SKIP
            'TestMagnet'
        """

    @abstractmethod
    def get_firmware_version(self) -> str:
        """Return the firmware version string.

        Returns:
            (str):
                Firmware version as reported by the device.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> mc.get_firmware_version()  # doctest: +SKIP
            '1.0'
        """

    @property
    @abstractmethod
    def current(self) -> float:
        """Return the current output in amps.

        Returns:
            (float):
                Instantaneous output current in amps.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @property
    @abstractmethod
    def field(self) -> float:
        """Return the magnetic field output in tesla.

        Returns:
            (float):
                Estimated magnetic field in tesla derived from the output
                current and the configured magnet constant.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @property
    @abstractmethod
    def voltage(self) -> float:
        """Return the output voltage in volts.

        Returns:
            (float):
                Instantaneous output voltage in volts.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @property
    @abstractmethod
    def status(self) -> MagnetStatus:
        """Return a consolidated status snapshot.

        Returns:
            (MagnetStatus):
                Current operational state, output readings, and heater status.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @property
    @abstractmethod
    def magnet_constant(self) -> float:
        """Return the magnet constant in tesla per amp.

        Returns:
            (float):
                Field-to-current conversion factor in T A⁻¹.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @property
    @abstractmethod
    def limits(self) -> MagnetLimits:
        """Return the configured operating limits.

        Returns:
            (MagnetLimits):
                Maximum permitted current, field, and ramp rate.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @property
    @abstractmethod
    def heater(self) -> bool:
        """Return the persistent switch heater state.

        Returns:
            (bool):
                ``True`` when the persistent switch heater is energised,
                ``False`` when it is off.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def set_target_current(self, current: float) -> None:
        """Set the target output current.

        Args:
            current (float):
                Desired target current in amps.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *current* exceeds the configured maximum.
        """

    @abstractmethod
    def set_target_field(self, field: float) -> None:
        """Set the target magnetic field.

        Args:
            field (float):
                Desired target field in tesla.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *field* exceeds the configured maximum.
        """

    @abstractmethod
    def set_ramp_rate_current(self, rate: float) -> None:
        """Set the current ramp rate.

        Args:
            rate (float):
                Ramp rate in amps per second.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *rate* exceeds the configured maximum or is negative.
        """

    @abstractmethod
    def set_ramp_rate_field(self, rate: float) -> None:
        """Set the field ramp rate.

        Args:
            rate (float):
                Ramp rate in tesla per minute.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *rate* exceeds the configured maximum or is negative.
        """

    @abstractmethod
    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        """Set the magnet constant used for field calculations.

        Args:
            tesla_per_amp (float):
                Field-to-current conversion factor in T A⁻¹.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *tesla_per_amp* is not positive.
        """

    @abstractmethod
    def set_limits(self, limits: MagnetLimits) -> None:
        """Set operating limits for the controller.

        Args:
            limits (MagnetLimits):
                Maximum current, field, and ramp rate limits to apply.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def ramp_to_target(self) -> None:
        """Start ramping the output towards the currently programmed target.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def ramp_to_current(self, current: float, *, wait: bool = False) -> None:
        """Set a new target current and begin ramping.

        Args:
            current (float):
                Desired target current in amps.

        Keyword Parameters:
            wait (bool):
                If ``True``, block until the target is reached.  Defaults to
                ``False``.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *current* exceeds the configured maximum.
        """

    @abstractmethod
    def ramp_to_field(self, field: float, *, wait: bool = False) -> None:
        """Set a new target field and begin ramping.

        Args:
            field (float):
                Desired target field in tesla.

        Keyword Parameters:
            wait (bool):
                If ``True``, block until the target is reached.  Defaults to
                ``False``.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *field* exceeds the configured maximum.
        """

    @abstractmethod
    def pause_ramp(self) -> None:
        """Pause an active ramp, holding the output at its current value.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def abort_ramp(self) -> None:
        """Abort ramping immediately and hold the output at its current value.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def heater_on(self) -> None:
        """Energise the persistent switch heater.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    @abstractmethod
    def heater_off(self) -> None:
        """De-energise the persistent switch heater.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
