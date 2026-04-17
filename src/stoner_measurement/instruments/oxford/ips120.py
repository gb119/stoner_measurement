"""Oxford Instruments IPS120 superconducting magnet power supply driver."""

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
from stoner_measurement.instruments.protocol.oxford import OxfordProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

_ACTIVE_RAMP_STATES = {MagnetState.RAMPING}
_TERMINAL_RAMP_STATES = {
    MagnetState.AT_TARGET,
    MagnetState.STANDBY,
    MagnetState.PERSISTENT,
    MagnetState.QUIESCENT,
}
_STATUS_TOKEN_RE = re.compile(r"([A-Za-z])(\d+)")
_ACTIVITY_STATE_MAP = {
    0: MagnetState.STANDBY,
    1: MagnetState.RAMPING,
    2: MagnetState.RAMPING,
    4: MagnetState.FAULT,
}


class OxfordIPS120(MagnetController, MagnetSupply):
    """Driver for an Oxford Instruments IPS120 magnet power supply.

    Attributes:
        transport (BaseTransport):
            Transport used for instrument I/O.
        protocol (BaseProtocol):
            Protocol used to format and parse instrument messages.

    Examples:
        >>> from stoner_measurement.instruments.oxford import OxfordIPS120
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> t = NullTransport(responses=[b"VIPS120-10 3.07\\r"])
        >>> mps = OxfordIPS120(transport=t)
        >>> mps.connect()
        >>> mps.identify()
        'IPS120-10 3.07'
        >>> mps.disconnect()
    """

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the Oxford IPS120 driver.

        Args:
            transport (BaseTransport):
                Physical transport for instrument communication.

        Keyword Parameters:
            protocol (BaseProtocol | None):
                Protocol instance. Uses :class:`OxfordProtocol` when omitted.
        """
        super().__init__(transport=transport, protocol=protocol if protocol is not None else OxfordProtocol())
        self._magnet_constant = 1.0
        self._limits = MagnetLimits(max_current=0.0, max_field=None, max_ramp_rate=None)

    def identify(self) -> str:
        """Return the instrument identity string.

        Returns:
            (str):
                Identity payload from the instrument.
        """
        return self.query("V")

    def get_model(self) -> str:
        """Return the model name from the identity string.

        Returns:
            (str):
                Instrument model token when available, otherwise an empty string.
        """
        identity = self.identify()
        primary = identity.replace(",", " ").split()
        return primary[0] if primary else ""

    def get_firmware_version(self) -> str:
        """Return the firmware version from the identity string.

        Returns:
            (str):
                Firmware token when available, otherwise an empty string.
        """
        identity = self.identify()
        primary = identity.replace(",", " ").split()
        return primary[1] if len(primary) > 1 else ""

    @property
    def current(self) -> float:
        """Return output current in amps.

        Returns:
            (float):
                Measured magnet supply current in amps.
        """
        return self._query_float("R1")

    @property
    def field(self) -> float:
        """Return output field in tesla.

        Returns:
            (float):
                Measured magnetic field in tesla.
        """
        return self._query_float("R7")

    @property
    def voltage(self) -> float:
        """Return output voltage in volts.

        Returns:
            (float):
                Measured output voltage in volts.
        """
        return self._query_float("R5")

    @property
    def status(self) -> MagnetStatus:
        """Return consolidated magnet status.

        Returns:
            (MagnetStatus):
                Snapshot of controller state and key readings.
        """
        status_reply = self.query("X").strip()
        tokens = {letter.upper(): int(value) for letter, value in _STATUS_TOKEN_RE.findall(status_reply)}
        activity = tokens.get("A", 0)
        state = _ACTIVITY_STATE_MAP.get(activity, MagnetState.UNKNOWN)
        persistent = tokens.get("P", 0) > 0
        heater_on = tokens.get("H", 0) > 0
        at_target = state in _TERMINAL_RAMP_STATES
        return MagnetStatus(
            state=state,
            current=self.current,
            field=self.field,
            voltage=self.voltage,
            persistent=persistent,
            heater_on=heater_on,
            at_target=at_target,
            message=status_reply,
        )

    @property
    def magnet_constant(self) -> float:
        """Return the magnet constant in tesla per amp.

        Returns:
            (float):
                Magnet constant in tesla per amp.
        """
        return self._magnet_constant

    @property
    def limits(self) -> MagnetLimits:
        """Return configured software limits for this driver instance.

        Returns:
            (MagnetLimits):
                Cached configured current/field/ramp limits.
        """
        return self._limits

    @property
    def heater(self) -> bool:
        """Return persistent switch heater state.

        Returns:
            (bool):
                ``True`` when the heater is enabled.
        """
        status_reply = self.query("X").strip()
        tokens = {letter.upper(): int(value) for letter, value in _STATUS_TOKEN_RE.findall(status_reply)}
        return tokens.get("H", 0) > 0

    def set_target_current(self, current: float) -> None:
        """Set the target current in amps.

        Args:
            current (float):
                Target current in amps.
        """
        self.write(f"J{current}")

    def set_target_field(self, field: float) -> None:
        """Set the target field in tesla.

        Args:
            field (float):
                Target magnetic field in tesla.
        """
        self.set_target_current(field / self._magnet_constant)

    def set_ramp_rate_current(self, rate: float) -> None:
        """Set the current ramp rate in amps per minute.

        Args:
            rate (float):
                Ramp rate in amps per minute.
        """
        self.write(f"T{rate}")

    def set_ramp_rate_field(self, rate: float) -> None:
        """Set the field ramp rate in tesla per minute.

        Args:
            rate (float):
                Ramp rate in tesla per minute.
        """
        self.set_ramp_rate_current(rate / self._magnet_constant)

    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        """Set the software magnet constant used for conversion.

        Args:
            tesla_per_amp (float):
                Magnet constant in tesla per amp.
        """
        if tesla_per_amp <= 0.0:
            raise ValueError(f"Magnet constant must be positive, got {tesla_per_amp}.")
        self._magnet_constant = tesla_per_amp

    def set_limits(self, limits: MagnetLimits) -> None:
        """Set software limits used by higher-level sequence logic.

        Args:
            limits (MagnetLimits):
                Limit configuration to cache for runtime checks.
        """
        self._limits = limits

    def ramp_to_target(self) -> None:
        """Start ramping to the current programmed target."""
        self.write("A1")

    def ramp_to_current(self, current: float, *, wait: bool = False) -> None:
        """Program current target and ramp.

        Args:
            current (float):
                Target current in amps.

        Keyword Parameters:
            wait (bool):
                When ``True``, block until ramp completes.
        """
        self.set_target_current(current)
        self.ramp_to_target()
        if wait:
            self._wait_for_ramp_complete()

    def ramp_to_field(self, field: float, *, wait: bool = False) -> None:
        """Program field target and ramp.

        Args:
            field (float):
                Target field in tesla.

        Keyword Parameters:
            wait (bool):
                When ``True``, block until ramp completes.
        """
        self.set_target_field(field)
        self.ramp_to_target()
        if wait:
            self._wait_for_ramp_complete()

    def pause_ramp(self) -> None:
        """Pause an active ramp."""
        self.write("A0")

    def abort_ramp(self) -> None:
        """Abort ramping immediately."""
        self.write("A4")

    def heater_on(self) -> None:
        """Enable the persistent switch heater."""
        self.write("H1")

    def heater_off(self) -> None:
        """Disable the persistent switch heater."""
        self.write("H0")

    def _query_float(self, command: str) -> float:
        """Query the instrument and parse a numeric response.

        Args:
            command (str):
                Instrument query command expected to return a numeric value.

        Returns:
            (float):
                Parsed floating-point value from the response.
        """
        reply = self.query(command)
        return float(reply.split(",", maxsplit=1)[0].strip())

    def _wait_for_ramp_complete(self, *, timeout: float = 600.0, poll_period: float = 0.25) -> None:
        """Wait for ramp to reach a terminal or inactive state, timing out if unsuccessful.

        Keyword Parameters:
            timeout (float):
                Maximum wait time in seconds before aborting.
            poll_period (float):
                Delay between status polls in seconds.

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
        raise TimeoutError("Timed out waiting for Oxford IPS120 ramp to complete.")
