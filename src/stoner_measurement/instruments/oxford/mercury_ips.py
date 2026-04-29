"""Oxford Instruments Mercury iPS superconducting magnet power supply driver.

Implements the text-based protocol used by the Mercury iPS over Ethernet or
USB.  Commands follow the ``READ:DEV:<uid>:PSU:SIG:*`` and
``SET:DEV:<uid>:PSU:*`` pattern; responses carry a ``STAT:DEV:<uid>:PSU:…``
prefix with the value appended after the final colon.
"""

from __future__ import annotations

import re
import time

from stoner_measurement.instruments.magnet_controller import (
    MagnetController,
    MagnetLimits,
    MagnetState,
    MagnetStatus,
    MagnetSupply,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

_ACTIVE_RAMP_STATES = {MagnetState.RAMPING}
_TERMINAL_RAMP_STATES = {
    MagnetState.AT_TARGET,
    MagnetState.STANDBY,
    MagnetState.PERSISTENT,
    MagnetState.QUIESCENT,
}

#: Maps Mercury iPS ACTN tokens to the shared MagnetState enum.
_ACTION_STATE_MAP: dict[str, MagnetState] = {
    "RTOS": MagnetState.RAMPING,
    "RTOZ": MagnetState.RAMPING,
    "HOLD": MagnetState.STANDBY,
    "CLMP": MagnetState.QUIESCENT,
}

#: Field tolerance in tesla for determining whether the output is at setpoint.
_AT_TARGET_FIELD_TOLERANCE = 1e-4

#: Strips a trailing SI unit (e.g. ``T``, ``A``, ``V``, ``T/m``) from a value token.
_UNIT_STRIP_RE = re.compile(r"[A-Za-z/]+\s*$")


class OxfordMercuryIPS(MagnetController, MagnetSupply):
    """Driver for an Oxford Instruments Mercury iPS magnet power supply.

    The Mercury iPS uses a text-based protocol over Ethernet or USB.
    Commands and queries follow the pattern::

        READ:DEV:<uid>:PSU:SIG:<signal>
        SET:DEV:<uid>:PSU:SIG:<signal>:<value>

    Responses carry a ``STAT:DEV:<uid>:PSU:…`` prefix with the value
    appended after the final colon (e.g.
    ``STAT:DEV:PSU.M1:PSU:SIG:FLD:+1.23456T``).

    All field values are in tesla and ramp rates in tesla per minute.

    Attributes:
        transport (BaseTransport):
            Transport used for instrument I/O.
        protocol (BaseProtocol):
            Protocol used to format and parse instrument messages.
        device_uid (str):
            Mercury iPS device UID used in all ``READ``/``SET`` commands.
            Defaults to ``"PSU.M1"``.

    Examples:
        >>> from stoner_measurement.instruments.oxford import OxfordMercuryIPS
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> t = NullTransport(
        ...     responses=[b"Oxford Instruments,Mercury iPS,12345,2.7.0\\n"],
        ... )
        >>> mps = OxfordMercuryIPS(transport=t)
        >>> mps.connect()
        >>> mps.identify()
        'Oxford Instruments,Mercury iPS,12345,2.7.0'
        >>> mps.disconnect()
    """

    _DEFAULT_UID = "PSU.M1"

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
        *,
        device_uid: str = _DEFAULT_UID,
    ) -> None:
        """Initialise the Oxford Mercury iPS driver.

        Args:
            transport (BaseTransport):
                Physical transport for instrument communication.

        Keyword Parameters:
            protocol (BaseProtocol | None):
                Protocol instance.  Uses :class:`~stoner_measurement.instruments.protocol.ScpiProtocol`
                when omitted.
            device_uid (str):
                Device UID used in Mercury ``READ``/``SET`` commands.
                Defaults to ``"PSU.M1"``.
        """
        super().__init__(transport=transport, protocol=protocol if protocol is not None else ScpiProtocol())
        self._uid = device_uid
        self._magnet_constant = 1.0
        self._limits = MagnetLimits(max_current=0.0, max_field=None, max_ramp_rate=None)

    def identify(self) -> str:
        """Return the instrument identity string.

        Returns:
            (str):
                Comma-separated identity string as returned by the ``*IDN?``
                query, e.g.
                ``"Oxford Instruments,Mercury iPS,<serial>,<firmware>"``.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> mps.identify()  # doctest: +SKIP
            'Oxford Instruments,Mercury iPS,12345,2.7.0'
        """
        return self.query("*IDN?")

    def get_model(self) -> str:
        """Return the model name from the identity string.

        Returns:
            (str):
                Second field of the ``*IDN?`` response (e.g.
                ``"Mercury iPS"``), or an empty string if not parseable.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> mps.get_model()  # doctest: +SKIP
            'Mercury iPS'
        """
        parts = self.identify().split(",")
        return parts[1].strip() if len(parts) > 1 else ""

    def get_firmware_version(self) -> str:
        """Return the firmware version from the identity string.

        Returns:
            (str):
                Fourth field of the ``*IDN?`` response (e.g. ``"2.7.0"``),
                or an empty string if not parseable.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> mps.get_firmware_version()  # doctest: +SKIP
            '2.7.0'
        """
        parts = self.identify().split(",")
        return parts[3].strip() if len(parts) > 3 else ""

    @property
    def current(self) -> float:
        """Return output current in amps.

        Returns:
            (float):
                Measured magnet supply current in amps.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        return self._read_sig_float("CURR")

    @property
    def field(self) -> float:
        """Return output field in tesla.

        Returns:
            (float):
                Measured magnetic field in tesla as reported by the instrument.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        return self._read_sig_float("FLD")

    @property
    def voltage(self) -> float:
        """Return output voltage in volts.

        Returns:
            (float):
                Measured output voltage in volts.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        return self._read_sig_float("VOLT")

    @property
    def status(self) -> MagnetStatus:
        """Return consolidated magnet status.

        Queries the action state, field, current, voltage, field setpoint, and
        switch heater state in sequence to build the snapshot.  The output is
        considered *at target* when the action is ``HOLD`` and the measured
        field is within ``1×10⁻⁴ T`` of the programmed setpoint.  The
        *persistent* flag reflects the switch heater state: the supply is
        treated as persistent when the heater is off.

        Returns:
            (MagnetStatus):
                Snapshot of controller state and key readings.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        action = self._read_action()
        state = _ACTION_STATE_MAP.get(action, MagnetState.UNKNOWN)
        fld = self._read_sig_float("FLD")
        cur = self._read_sig_float("CURR")
        volt = self._read_sig_float("VOLT")
        fset = self._read_sig_float("FSET")
        heater = self._read_heater_state()
        persistent = not heater
        at_target = state in _TERMINAL_RAMP_STATES and abs(fld - fset) < _AT_TARGET_FIELD_TOLERANCE
        if at_target and state == MagnetState.STANDBY:
            state = MagnetState.AT_TARGET
        return MagnetStatus(
            state=state,
            current=cur,
            field=fld,
            voltage=volt,
            persistent=persistent,
            heater_on=heater,
            at_target=at_target,
        )

    @property
    def magnet_constant(self) -> float:
        """Return the software magnet constant in tesla per amp.

        Returns:
            (float):
                Field-to-current conversion factor in T A⁻¹ held by this
                driver instance.
        """
        return self._magnet_constant

    @property
    def limits(self) -> MagnetLimits:
        """Return the configured software operating limits.

        Returns:
            (MagnetLimits):
                Cached current/field/ramp limits set via :meth:`set_limits`.
        """
        return self._limits

    @property
    def heater(self) -> bool:
        """Return the persistent switch heater state.

        Returns:
            (bool):
                ``True`` when the switch heater is on, ``False`` when it is
                off.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        return self._read_heater_state()

    def set_target_current(self, current: float) -> None:
        """Set the target output current.

        Converts *current* to a field setpoint using the configured magnet
        constant and sends a ``SET:DEV:<uid>:PSU:SIG:FSET`` command.

        Args:
            current (float):
                Desired target current in amps.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        self.set_target_field(current * self._magnet_constant)

    def set_target_field(self, field: float) -> None:
        """Set the target magnetic field.

        Args:
            field (float):
                Desired target field in tesla.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        self.write(f"SET:DEV:{self._uid}:PSU:SIG:FSET:{field:.6f}")

    def set_ramp_rate_current(self, rate: float) -> None:
        """Set the current ramp rate.

        Converts *rate* in amps per minute to tesla per minute using the
        configured magnet constant, then calls :meth:`set_ramp_rate_field`.

        Args:
            rate (float):
                Ramp rate in amps per minute.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *rate* is negative.
        """
        if rate < 0.0:
            raise ValueError(f"Ramp rate must be non-negative, got {rate}.")
        self.set_ramp_rate_field(rate * self._magnet_constant)

    def set_ramp_rate_field(self, rate: float) -> None:
        """Set the field ramp rate.

        Args:
            rate (float):
                Ramp rate in tesla per minute.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *rate* is negative.
        """
        if rate < 0.0:
            raise ValueError(f"Ramp rate must be non-negative, got {rate}.")
        self.write(f"SET:DEV:{self._uid}:PSU:SIG:RSET:{rate:.6f}")

    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        """Set the software magnet constant used for current/field conversions.

        Args:
            tesla_per_amp (float):
                Field-to-current conversion factor in T A⁻¹.

        Raises:
            ValueError:
                If *tesla_per_amp* is not positive.
        """
        if tesla_per_amp <= 0.0:
            raise ValueError(f"Magnet constant must be positive, got {tesla_per_amp}.")
        self._magnet_constant = tesla_per_amp

    def set_limits(self, limits: MagnetLimits) -> None:
        """Set software operating limits for this driver instance.

        Args:
            limits (MagnetLimits):
                Limit configuration to cache for runtime checks.
        """
        self._limits = limits

    def ramp_to_target(self) -> None:
        """Start ramping to the currently programmed field setpoint.

        Sends ``SET:DEV:<uid>:PSU:ACTN:RTOS`` to the instrument.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        self.write(f"SET:DEV:{self._uid}:PSU:ACTN:RTOS")

    def ramp_to_current(self, current: float, *, wait: bool = False) -> None:
        """Programme a current target and begin ramping.

        Args:
            current (float):
                Target current in amps.

        Keyword Parameters:
            wait (bool):
                When ``True``, block until the ramp completes.  Defaults to
                ``False``.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        self.set_target_current(current)
        self.ramp_to_target()
        if wait:
            self._wait_for_ramp_complete()

    def ramp_to_field(self, field: float, *, wait: bool = False) -> None:
        """Programme a field target and begin ramping.

        Args:
            field (float):
                Target field in tesla.

        Keyword Parameters:
            wait (bool):
                When ``True``, block until the ramp completes.  Defaults to
                ``False``.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        self.set_target_field(field)
        self.ramp_to_target()
        if wait:
            self._wait_for_ramp_complete()

    def pause_ramp(self) -> None:
        """Pause an active ramp, holding the output at its current value.

        Sends ``SET:DEV:<uid>:PSU:ACTN:HOLD`` to the instrument.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        self.write(f"SET:DEV:{self._uid}:PSU:ACTN:HOLD")

    def abort_ramp(self) -> None:
        """Abort an active ramp, holding the output at its current value.

        Sends ``SET:DEV:<uid>:PSU:ACTN:HOLD`` to immediately stop any active
        ramp.  To ramp to zero instead, use :meth:`ramp_to_field` with a
        target of ``0.0``.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        self.write(f"SET:DEV:{self._uid}:PSU:ACTN:HOLD")

    def heater_on(self) -> None:
        """Energise the persistent switch heater.

        Sends ``SET:DEV:<uid>:PSU:SIG:SWHT:ON`` to the instrument.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        self.write(f"SET:DEV:{self._uid}:PSU:SIG:SWHT:ON")

    def heater_off(self) -> None:
        """De-energise the persistent switch heater.

        Sends ``SET:DEV:<uid>:PSU:SIG:SWHT:OFF`` to the instrument.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        self.write(f"SET:DEV:{self._uid}:PSU:SIG:SWHT:OFF")

    def _read_sig_float(self, signal: str) -> float:
        """Query a numeric signal value from the Mercury iPS.

        Sends ``READ:DEV:<uid>:PSU:SIG:<signal>`` and parses the trailing
        value token from the ``STAT:…:<value><unit>`` response, stripping any
        SI unit suffix.

        Args:
            signal (str):
                Signal name (e.g. ``"FLD"``, ``"CURR"``, ``"VOLT"``).

        Returns:
            (float):
                Parsed floating-point signal value.

        Raises:
            ValueError:
                If the response cannot be parsed as a number.
        """
        raw = self.query(f"READ:DEV:{self._uid}:PSU:SIG:{signal}").strip()
        value_str = raw.rsplit(":", maxsplit=1)[-1]
        value_str = _UNIT_STRIP_RE.sub("", value_str).strip()
        try:
            return float(value_str)
        except ValueError as exc:
            raise ValueError(f"Invalid numeric response for {signal}: {raw!r}") from exc

    def _read_heater_state(self) -> bool:
        """Read the switch heater state from the instrument.

        Returns:
            (bool):
                ``True`` when the heater is on, ``False`` when off.
        """
        raw = self.query(f"READ:DEV:{self._uid}:PSU:SIG:SWHT").strip()
        return raw.rsplit(":", maxsplit=1)[-1].upper() == "ON"

    def _read_action(self) -> str:
        """Read the current action state token from the instrument.

        Returns:
            (str):
                Uppercase action token, e.g. ``"RTOS"``, ``"HOLD"``,
                ``"RTOZ"``, or ``"CLMP"``.
        """
        raw = self.query(f"READ:DEV:{self._uid}:PSU:ACTN").strip()
        return raw.rsplit(":", maxsplit=1)[-1].upper()

    def _wait_for_ramp_complete(self, *, timeout: float = 600.0, poll_period: float = 0.25) -> None:
        """Wait for the ramp to reach a terminal state, timing out if unsuccessful.

        Keyword Parameters:
            timeout (float):
                Maximum wait time in seconds before aborting.  Defaults to
                ``600.0``.
            poll_period (float):
                Delay between status polls in seconds.  Defaults to ``0.25``.

        Raises:
            TimeoutError:
                If the ramp does not reach a terminal state before *timeout*.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.status.state
            if state in _TERMINAL_RAMP_STATES:
                return
            if state not in _ACTIVE_RAMP_STATES:
                return
            time.sleep(poll_period)
        raise TimeoutError("Timed out waiting for Oxford Mercury iPS ramp to complete.")
