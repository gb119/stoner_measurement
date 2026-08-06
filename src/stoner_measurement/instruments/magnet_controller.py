"""Abstract interfaces for superconducting magnet power supply instruments.

Defines shared types and abstract interfaces for magnet controller drivers.
Magnetic field values are in tesla and ramp rates in tesla per minute unless
otherwise stated.
"""

from __future__ import annotations

import math
import time
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


def current_is_at_target(
    current: float,
    target_current: float | None,
    ramp_rate_current: float | None,
) -> bool:
    """Return whether a magnet current is at, or imminently at, its target.

    Current and target are in amps and ramp rate is in amps per minute.  A
    target counts as reached when the error is no more than 1% of the target,
    no more than 1 mA, or would be traversed in no more than two seconds at
    the programmed ramp rate.
    """
    if target_current is None or not math.isfinite(current) or not math.isfinite(target_current):
        return False

    difference = abs(target_current - current)
    if difference <= max(abs(target_current) * 0.01, 0.001):
        return True

    if ramp_rate_current is None or not math.isfinite(ramp_rate_current) or ramp_rate_current == 0.0:
        return False
    return difference / abs(ramp_rate_current) * 60.0 <= 2.0


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
    HOLDING = "standby"
    RAMPING = "ramping"
    AT_TARGET = "at_target"
    PERSISTENT = "persistent"
    QUIESCENT = "quiescent"
    FAULT = "fault"
    QUENCH = "quench"
    UNKNOWN = "unknown"


class HeaterState(Enum):
    """Persistent switch heater state.

    Attributes:
        ON:
            Persistent switch heater is energised and the switch is open.
        OFF:
            Persistent switch heater is de-energised and the switch is closed.
        WARMING:
            Persistent switch heater is transitioning from off to on.
        COOLING:
            Persistent switch heater is transitioning from on to off.
        FAULT:
            Heater state cannot be trusted due to an instrument fault.
        UNKNOWN:
            Heater state is not available from the instrument.
    """

    ON = "on"
    OFF = "off"
    WARMING = "warming"
    COOLING = "cooling"
    FAULT = "fault"
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
        heater_state (HeaterState):
            Rich persistent-switch heater state including transition states.
        at_target (bool):
            ``True`` when the output has reached the programmed target.
        persistent_field (float | None):
            Field trapped when entering persistent mode, if known.
        persistent_current (float | None):
            Current trapped in the persistent magnet circuit, if known.
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
    heater_state: HeaterState = HeaterState.UNKNOWN
    persistent_field: float | None = None
    persistent_current: float | None = None
    message: str | None = None


class MagnetSupply(Protocol):
    """Protocol describing the expected interface of a magnet supply driver.

    Defines the minimum lifecycle, configuration, readback, and ramp-control
    operations required by code that interacts with magnet supply objects.
    """

    # --- lifecycle ---
    def connect(self) -> None:
        """Open the transport connection to the instrument."""
        ...

    def disconnect(self) -> None:
        """Close the transport connection to the instrument."""
        ...

    def is_connected(self) -> bool:
        """Return ``True`` if the transport connection is currently open."""
        ...

    # context manager sugar
    def __enter__(self) -> MagnetSupply:
        ...

    def __exit__(self, exc_type, exc, tb) -> None:
        ...

    # --- identity & configuration ---
    def identify(self) -> str:
        """Return the instrument identity string."""
        ...

    def get_model(self) -> str:
        """Return the instrument model name."""
        ...

    def get_firmware_version(self) -> str:
        """Return the instrument firmware version string."""
        ...

    # --- readings as properties ---
    @property
    def current(self) -> float:
        """Return the output current in amps."""
        ...

    @property
    def field(self) -> float:
        """Return the output magnetic field in tesla."""
        ...

    @property
    def voltage(self) -> float:
        """Return the output voltage in volts."""
        ...

    @property
    def status(self) -> MagnetStatus:
        """Return a consolidated status snapshot of the magnet supply."""
        ...

    @property
    def magnet_constant(self) -> float:
        """Return the magnet constant in tesla per amp."""
        ...

    @property
    def limits(self) -> MagnetLimits:
        """Return the configured software operating limits."""
        ...

    @property
    def heater(self) -> bool:
        """Return the current state of the persistent switch heater."""
        ...

    @property
    def target_current(self) -> float | None:
        """Return the programmed current target in amps when available."""
        ...

    @property
    def target_field(self) -> float | None:
        """Return the programmed field target in tesla when available."""
        ...

    @property
    def ramp_rate_current(self) -> float | None:
        """Return the programmed current ramp rate in amps per minute when available."""
        ...

    @property
    def ramp_rate_field(self) -> float | None:
        """Return the programmed field ramp rate in tesla per minute when available."""
        ...

    # --- configuration as methods ---
    def set_target_current(self, current: float) -> None:
        """Set the target current in amps."""
        ...

    def set_target_field(self, field: float) -> None:
        """Set the target magnetic field in tesla."""
        ...

    def set_ramp_rate_current(self, rate: float) -> None:
        """Set the current ramp rate in amps per minute."""
        ...

    def set_ramp_rate_field(self, rate: float) -> None:
        """Set the field ramp rate in tesla per minute."""
        ...

    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        """Set the magnet constant in tesla per amp."""
        ...

    def set_limits(self, limits: MagnetLimits) -> None:
        """Set the software operating limits for this driver instance."""
        ...

    # --- actions as methods ---
    def ramp_to_target(self) -> None:
        """Begin ramping to the currently programmed target."""
        ...

    def ramp_to_current(self, current: float, *, wait: bool = False) -> None:
        """Programme a current target and begin ramping."""
        ...

    def ramp_to_field(self, field: float, *, wait: bool = False) -> None:
        """Programme a field target and begin ramping."""
        ...

    def pause_ramp(self) -> None:
        """Pause an active ramp."""
        ...

    def hold(self) -> None:
        """Hold the present output without changing field."""
        ...

    def go_to_zero(self) -> None:
        """Ramp the supply output to zero using the instrument zero action."""
        ...

    def abort_ramp(self) -> None:
        """Abort an active ramp immediately."""
        ...

    # --- persistent switch ---
    def heater_on(self) -> None:
        """Enable the persistent switch heater."""
        ...

    def heater_off(self) -> None:
        """Disable the persistent switch heater."""
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

    def connect(self) -> None:
        """Open the connection and verify the controller identity."""
        super().connect()
        try:
            self.confirm_identity()
        except Exception:
            self.disconnect()
            raise

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

    def refresh_magnet_constant(self) -> float:
        """Refresh and return the magnet constant from the controller.

        Drivers whose magnet constant is effectively static or already cached
        may rely on the default implementation. Drivers that need an explicit
        hardware query should override this method.
        """
        return self.magnet_constant

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

    @property
    def target_current(self) -> float | None:
        """Return the programmed current target in amps when available.

        Drivers that do not support direct setpoint readback return ``None``.
        """
        return None

    @property
    def target_field(self) -> float | None:
        """Return the programmed field target in tesla when available.

        Drivers that do not support direct setpoint readback return ``None``.
        """
        return None

    @property
    def ramp_rate_current(self) -> float | None:
        """Return the programmed current ramp rate in amps per minute when available.

        Drivers that do not support direct ramp-rate readback return ``None``.
        """
        return None

    @property
    def ramp_rate_field(self) -> float | None:
        """Return the programmed field ramp rate in tesla per minute when available.

        Drivers that do not support direct ramp-rate readback return ``None``.
        """
        return None

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
                Ramp rate in amps per minute.

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

    @abstractmethod
    def return_to_local(self) -> None:
        """Return the controller front panel to local/manual operation.

        This is intended as a safety-oriented handoff from software control
        back to an in-person operator, for example during disconnect or after
        a quench condition has been detected.

        Implementations should prefer a non-locked local or remote/local mode
        that leaves the instrument operable from the front panel. They should
        not place the controller into a remotely locked-out state.

        Raises:
            ConnectionError:
                If the transport is not open.
        """


_KEPCO_LIST_MIN_DWELL_S = 93e-6
_KEPCO_LIST_MAX_DWELL_S = 0.034
_KEPCO_LIST_MAX_POINTS = 5900
_KEPCO_LIST_COMMAND_LENGTH = 240
_KEPCO_LIST_RUNNING_BIT = 1 << 14
_KEPCO_QUESTIONABLE_FAULT_BITS = (1 << 3) | (1 << 6) | (1 << 12) | (1 << 13)


class KepcoBOPGL(MagnetController, MagnetSupply):
    """Magnet-supply driver for the Kepco BOP-GL 1 kW family.

    The BOP-GL regulates current while voltage protection provides the magnet
    compliance voltage.  Because the supply has no field calibration or ramp
    command, this driver keeps the magnet constant locally and implements
    ramps as temporary current LISTs.  It never enables the output implicitly.
    """

    DISPLAY_NAME = "Kepco BOP-GL"
    _EXPECTED_IDENTITY_TOKENS = ("KEPCO", "BOP")

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise a BOP-GL driver without changing the instrument output."""
        super().__init__(transport=transport, protocol=protocol or ScpiProtocol())
        self._magnet_constant = 1.0
        self._limits = MagnetLimits(max_current=math.inf)
        self._target_current: float | None = None
        self._ramp_rate_current: float | None = None

    def get_model(self) -> str:
        """Return the model token from ``*IDN?``."""
        parts = [part.strip() for part in self.identify().split(",")]
        return parts[1] if len(parts) > 1 else ""

    def get_firmware_version(self) -> str:
        """Return the firmware token from ``*IDN?``."""
        parts = [part.strip() for part in self.identify().split(",")]
        return parts[3] if len(parts) > 3 else ""

    @property
    def current(self) -> float:
        """Return measured output current in amps."""
        return self._query_float("MEAS:CURR?")

    @property
    def field(self) -> float:
        """Return field derived from measured current and the local constant."""
        return self.current * self._magnet_constant

    @property
    def voltage(self) -> float:
        """Return measured output voltage in volts."""
        return self._query_float("MEAS:VOLT?")

    @property
    def status(self) -> MagnetStatus:
        """Return a status snapshot derived from SCPI condition registers."""
        operation = self._query_int("STAT:OPER:COND?")
        questionable = self._query_int("STAT:QUES:COND?")
        output_enabled = self.output_enabled()
        current = self.current
        voltage = self.voltage
        target = self.target_current
        at_target = output_enabled and current_is_at_target(
            current,
            target,
            self._ramp_rate_current,
        )
        if questionable & _KEPCO_QUESTIONABLE_FAULT_BITS:
            state = MagnetState.FAULT
        elif operation & _KEPCO_LIST_RUNNING_BIT:
            state = MagnetState.RAMPING
        elif not output_enabled:
            state = MagnetState.STANDBY
        elif at_target:
            state = MagnetState.AT_TARGET
        else:
            state = MagnetState.STANDBY
        return MagnetStatus(
            state=state,
            current=current,
            field=current * self._magnet_constant,
            voltage=voltage,
            persistent=False,
            heater_on=None,
            heater_state=HeaterState.UNKNOWN,
            at_target=at_target and state is not MagnetState.FAULT,
            message=f"operation=0x{operation:X}, questionable=0x{questionable:X}",
        )

    @property
    def magnet_constant(self) -> float:
        """Return the locally stored field conversion in tesla per amp."""
        return self._magnet_constant

    @property
    def limits(self) -> MagnetLimits:
        """Read the BOP current limits and derive the corresponding field limit."""
        reply = self.query("CURR:LIM?")
        values = _parse_kepco_float_list(reply)
        max_current = max(abs(value) for value in values)
        self._limits = MagnetLimits(
            max_current=max_current,
            max_field=max_current * self._magnet_constant,
            max_ramp_rate=self._limits.max_ramp_rate,
        )
        return self._limits

    @property
    def heater(self) -> bool:
        """Return ``False`` because the BOP-GL has no persistent-switch heater."""
        return False

    @property
    def target_current(self) -> float | None:
        """Return the driver-side final ramp target, or the fixed setpoint."""
        if self._target_current is not None:
            return self._target_current
        return self._query_float("CURR?")

    @property
    def target_field(self) -> float | None:
        """Return the driver-side target converted to tesla."""
        current = self.target_current
        return None if current is None else current * self._magnet_constant

    @property
    def ramp_rate_current(self) -> float | None:
        """Return the locally stored ramp rate in amps per minute."""
        return self._ramp_rate_current

    @property
    def ramp_rate_field(self) -> float | None:
        """Return the locally stored ramp rate converted to tesla per minute."""
        if self._ramp_rate_current is None:
            return None
        return self._ramp_rate_current * self._magnet_constant

    @property
    def compliance_voltage(self) -> float:
        """Return the largest active positive/negative voltage clamp magnitude."""
        return max(abs(value) for value in _parse_kepco_float_list(self.query("VOLT:PROT?")))

    def set_compliance_voltage(self, voltage: float) -> None:
        """Set a symmetric fixed voltage-protection clamp in volts."""
        value = _positive_finite(voltage, name="Compliance voltage")
        self.write("VOLT:PROT:MODE FIX")
        self.write(f"VOLT:PROT {_format_kepco_float(value)}")

    def output_enabled(self) -> bool:
        """Return whether the power-supply output is enabled."""
        return bool(self._query_int("OUTP?"))

    def output_on(self) -> None:
        """Enable software output control without changing load-off behaviour."""
        self.write("OUTP:CONT OFF")
        self.write("OUTP ON")

    def output_off(self) -> None:
        """Disable the output without claiming electrical isolation."""
        self.write("OUTP OFF")

    def set_load_mode(self, mode: str) -> None:
        """Select ACTIVE, RESISTIVE, or BATTERY output-off behaviour."""
        normalized = mode.strip().upper()
        if normalized not in {"ACTIVE", "RESISTIVE", "BATTERY"}:
            raise ValueError(f"Unsupported Kepco load mode: {mode!r}.")
        self.write(f"OUTP:MODE {normalized}")

    def set_target_current(self, current: float) -> None:
        """Cache a final current target without changing the output."""
        value = _finite_float(current, name="Target current")
        if abs(value) > self._limits.max_current:
            raise ValueError(
                f"Target current {value} A exceeds the configured limit "
                f"of {self._limits.max_current} A."
            )
        self._target_current = value

    def set_target_field(self, field: float) -> None:
        """Cache a field target after converting it with the local constant."""
        value = _finite_float(field, name="Target field")
        if self._magnet_constant <= 0.0:
            raise ValueError("Magnet constant must be positive to convert field targets.")
        if self._limits.max_field is not None and abs(value) > self._limits.max_field:
            raise ValueError(
                f"Target field {value} T exceeds the configured limit of "
                f"{self._limits.max_field} T."
            )
        self.set_target_current(value / self._magnet_constant)

    def set_ramp_rate_current(self, rate: float) -> None:
        """Store the current ramp rate used to construct LIST setpoints."""
        value = _positive_finite(rate, name="Current ramp rate")
        if (
            self._limits.max_ramp_rate is not None
            and value * self._magnet_constant > self._limits.max_ramp_rate
        ):
            raise ValueError("Current ramp rate exceeds the configured field ramp-rate limit.")
        self._ramp_rate_current = value

    def set_ramp_rate_field(self, rate: float) -> None:
        """Store a field ramp rate after conversion to amps per minute."""
        value = _positive_finite(rate, name="Field ramp rate")
        if self._magnet_constant <= 0.0:
            raise ValueError("Magnet constant must be positive to convert field ramp rates.")
        if self._limits.max_ramp_rate is not None and value > self._limits.max_ramp_rate:
            raise ValueError("Field ramp rate exceeds the configured ramp-rate limit.")
        self._ramp_rate_current = value / self._magnet_constant

    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        """Store the field conversion locally; the BOP-GL has no field setting."""
        value = _positive_finite(tesla_per_amp, name="Magnet constant")
        self._magnet_constant = value
        if math.isfinite(self._limits.max_current):
            self._limits.max_field = self._limits.max_current * value

    def set_limits(self, limits: MagnetLimits) -> None:
        """Program a symmetric current limit and cache field/ramp limits."""
        max_current = _positive_finite(limits.max_current, name="Maximum current")
        if limits.max_field is not None:
            max_field = _positive_finite(limits.max_field, name="Maximum field")
            max_current = min(max_current, max_field / self._magnet_constant)
        self.write(f"CURR:LIM {_format_kepco_float(max_current)}")
        self._limits = MagnetLimits(
            max_current=max_current,
            max_field=max_current * self._magnet_constant,
            max_ramp_rate=limits.max_ramp_rate,
        )

    def ramp_to_target(self) -> None:
        """Build and execute a one-shot current LIST to the cached target."""
        if self._target_current is None:
            raise RuntimeError("No Kepco current or field target has been configured.")
        if self._ramp_rate_current is None:
            raise RuntimeError("No Kepco current or field ramp rate has been configured.")
        start = self.current
        target = self._target_current
        difference = abs(target - start)
        if difference == 0.0:
            self.write("CURR:MODE FIX")
            self.write(f"CURR {_format_kepco_float(target)}")
            return

        duration = difference / (self._ramp_rate_current / 60.0)
        intervals = max(1, math.ceil(duration / _KEPCO_LIST_MAX_DWELL_S))
        dwell = duration / intervals
        if dwell < _KEPCO_LIST_MIN_DWELL_S:
            raise ValueError("Requested Kepco ramp is faster than the minimum LIST dwell permits.")
        point_count = intervals + 1
        if point_count > _KEPCO_LIST_MAX_POINTS:
            raise ValueError(
                "Requested Kepco ramp needs more than 5900 LIST points; "
                "increase the ramp rate or divide the ramp into shorter targets."
            )
        points = [start + (target - start) * index / intervals for index in range(point_count)]
        self.write("LIST:CLE")
        for command in _kepco_list_commands(points):
            self.write(command)
        self.write(f"LIST:DWEL {_format_kepco_float(dwell)}")
        self.write("LIST:COUN 1")
        self.write("CURR:MODE LIST")

    def ramp_to_current(self, current: float, *, wait: bool = False) -> None:
        """Set a current target and start a LIST ramp."""
        self.set_target_current(current)
        self.ramp_to_target()
        if wait:
            self._wait_for_ramp_complete()

    def ramp_to_field(self, field: float, *, wait: bool = False) -> None:
        """Set a field target and start a LIST ramp."""
        self.set_target_field(field)
        self.ramp_to_target()
        if wait:
            self._wait_for_ramp_complete()

    def pause_ramp(self) -> None:
        """Stop LIST execution immediately while retaining the final target."""
        self.write("CURR:MODE FIX")

    def hold(self) -> None:
        """Stop LIST execution and make the measured current the new target."""
        self.write("CURR:MODE FIX")
        current = self.current
        self.write(f"CURR {_format_kepco_float(current)}")
        self._target_current = current

    def go_to_zero(self) -> None:
        """Ramp to zero using the configured LIST ramp rate."""
        self.ramp_to_current(0.0)

    def abort_ramp(self) -> None:
        """Stop the LIST immediately and hold the measured current."""
        self.hold()

    def heater_on(self) -> None:
        """Raise because the BOP-GL does not support a switch heater."""
        raise NotImplementedError("The Kepco BOP-GL has no persistent-switch heater.")

    def heater_off(self) -> None:
        """Raise because the BOP-GL does not support a switch heater."""
        raise NotImplementedError("The Kepco BOP-GL has no persistent-switch heater.")

    def return_to_local(self) -> None:
        """Return an RS-232 controlled BOP-GL to local operation."""
        self.write("SYST:REM OFF")

    def _query_float(self, command: str) -> float:
        """Query one finite floating-point value."""
        return _finite_float(self.query(command), name=f"Response to {command}")

    def _query_int(self, command: str) -> int:
        """Query an integer-valued SCPI status response."""
        return int(float(self.query(command).strip()))

    def _wait_for_ramp_complete(
        self,
        *,
        timeout: float = 600.0,
        poll_period: float = 0.25,
    ) -> None:
        """Wait until the LIST-running condition bit clears."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._query_int("STAT:OPER:COND?") & _KEPCO_LIST_RUNNING_BIT:
                return
            time.sleep(poll_period)
        raise TimeoutError("Timed out waiting for Kepco BOP-GL LIST ramp to complete.")


def _finite_float(value: float | str, *, name: str) -> float:
    """Return *value* as a finite float."""
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite, got {value!r}.")
    return result


def _positive_finite(value: float, *, name: str) -> float:
    """Return *value* as a positive finite float."""
    result = _finite_float(value, name=name)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive, got {value!r}.")
    return result


def _format_kepco_float(value: float) -> str:
    """Format a finite value with bounded SCPI precision."""
    return f"{_finite_float(value, name='SCPI value'):.8g}"


def _parse_kepco_float_list(response: str) -> list[float]:
    """Parse and validate a non-empty comma-separated numeric response."""
    values = [
        _finite_float(token.strip(), name="Kepco numeric response")
        for token in response.split(",")
        if token.strip()
    ]
    if not values:
        raise ValueError(f"Expected a numeric Kepco response, got {response!r}.")
    return values


def _kepco_list_commands(points: list[float]) -> list[str]:
    """Split LIST values into append commands below the transport-size limit."""
    prefix = "LIST:CURR "
    commands: list[str] = []
    tokens: list[str] = []
    for point in points:
        token = _format_kepco_float(point)
        candidate = prefix + ",".join([*tokens, token])
        if tokens and len(candidate) > _KEPCO_LIST_COMMAND_LENGTH:
            commands.append(prefix + ",".join(tokens))
            tokens = [token]
        else:
            tokens.append(token)
    if tokens:
        commands.append(prefix + ",".join(tokens))
    return commands
