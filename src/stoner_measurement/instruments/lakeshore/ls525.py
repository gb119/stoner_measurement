"""Lakeshore 525 superconducting magnet power supply driver."""

from __future__ import annotations

import time

from stoner_measurement.instruments.magnet_controller import (
    MagnetController,
    MagnetLimits,
    MagnetState,
    MagnetStatus,
    MagnetSupply,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.lakeshore import LakeshoreProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

_STATE_MAP = {
    "standby": MagnetState.STANDBY,
    "ramping": MagnetState.RAMPING,
    "at_target": MagnetState.AT_TARGET,
    "persistent": MagnetState.PERSISTENT,
    "fault": MagnetState.FAULT,
    "quench": MagnetState.QUENCH,
}

_ACTIVE_RAMP_STATES = {MagnetState.RAMPING}
_TERMINAL_RAMP_STATES = {
    MagnetState.AT_TARGET,
    MagnetState.STANDBY,
    MagnetState.PERSISTENT,
    MagnetState.QUIESCENT,
}


class Lakeshore525(MagnetController, MagnetSupply):
    """Driver for a Lakeshore 525 superconducting magnet power supply.

    The driver composes :class:`~stoner_measurement.instruments.base_instrument.BaseInstrument`
    communication behaviour with the
    :class:`~stoner_measurement.instruments.magnet_controller.MagnetSupply`
    interface for magnet supplies.

    Attributes:
        transport (BaseTransport):
            Transport used for instrument I/O.
        protocol (BaseProtocol):
            Protocol used to format and parse instrument messages.

    Examples:
        >>> from stoner_measurement.instruments.lakeshore import Lakeshore525
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> t = NullTransport(responses=[b"LAKESHORE,MODEL525,SN001,1.0\\r\\n"])
        >>> mps = Lakeshore525(transport=t)
        >>> mps.connect()
        >>> mps.identify()
        'LAKESHORE,MODEL525,SN001,1.0'
        >>> mps.disconnect()
    """

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the Lakeshore 525 driver.

        Args:
            transport (BaseTransport):
                Physical transport for instrument communication.

        Keyword Parameters:
            protocol (BaseProtocol | None):
                Protocol instance. Uses :class:`LakeshoreProtocol` when omitted.
        """
        super().__init__(transport=transport, protocol=protocol if protocol is not None else LakeshoreProtocol())
        self._magnet_constant = 1.0
        self._limits = MagnetLimits(max_current=0.0, max_field=None, max_ramp_rate=None)

    def get_model(self) -> str:
        """Return the model name from the identification string.

        Returns:
            (str):
                Instrument model token when available, otherwise an empty string.
        """
        parts = [part.strip() for part in self.identify().split(",")]
        return parts[1] if len(parts) > 1 else ""

    def get_firmware_version(self) -> str:
        """Return the firmware version from the identification string.

        Returns:
            (str):
                Firmware version token when available, otherwise an empty string.
        """
        parts = [part.strip() for part in self.identify().split(",")]
        return parts[3] if len(parts) > 3 else ""

    @property
    def current(self) -> float:
        """Return output current in amps.

        Returns:
            (float):
                Measured magnet supply current in amps.
        """
        return self._query_float("RDGI?")

    @property
    def field(self) -> float:
        """Return output field in tesla.

        Returns:
            (float):
                Measured magnetic field in tesla.
        """
        return self._query_float("RDGF?")

    @property
    def voltage(self) -> float:
        """Return output voltage in volts.

        Returns:
            (float):
                Measured output voltage in volts.
        """
        return self._query_float("RDGV?")

    @property
    def status(self) -> MagnetStatus:
        """Return consolidated magnet status.

        Returns:
            (MagnetStatus):
                Snapshot of controller state and key readings.
        """
        state_reply = self.query("STATE?").strip().lower()
        state = _STATE_MAP.get(state_reply, MagnetState.UNKNOWN)
        at_target = state in _TERMINAL_RAMP_STATES
        return MagnetStatus(
            state=state,
            current=self.current,
            field=self.field,
            voltage=self.voltage,
            persistent=False,
            heater_on=self.heater,
            at_target=at_target,
            message=state_reply,
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
        value = self.query("HEATER?").strip()
        return value in {"1", "ON", "on", "True", "true"}

    def set_target_current(self, current: float) -> None:
        """Set the target current in amps.

        Args:
            current (float):
                Target current in amps.
        """
        self.write(f"SETI {current}")

    def set_target_field(self, field: float) -> None:
        """Set the target field in tesla.

        Args:
            field (float):
                Target magnetic field in tesla.
        """
        self.write(f"SETF {field}")

    def set_ramp_rate_current(self, rate: float) -> None:
        """Set the current ramp rate in amps per minute.

        Args:
            rate (float):
                Ramp rate in amps per minute.
        """
        self.write(f"RATEI {rate}")

    def set_ramp_rate_field(self, rate: float) -> None:
        """Set the field ramp rate in tesla per minute.

        Args:
            rate (float):
                Ramp rate in tesla per minute.
        """
        self.write(f"RATEF {rate}")

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
        self.write("RAMP")

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
        self.write("PAUSE")

    def abort_ramp(self) -> None:
        """Abort ramping immediately."""
        self.write("ABORT")

    def heater_on(self) -> None:
        """Enable the persistent switch heater."""
        self.write("HEATER 1")

    def heater_off(self) -> None:
        """Disable the persistent switch heater."""
        self.write("HEATER 0")

    def _query_float(self, command: str) -> float:
        """Query the instrument and parse a numeric response.

        Args:
            command (str):
                Instrument query command expected to return a numeric value.

        Returns:
            (float):
                Parsed floating-point value from the response. If the response
                contains comma-separated tokens, the first token is used.
        """
        reply = self.query(command)
        token = reply.split(",", maxsplit=1)[0].strip()
        return float(token)

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
        raise TimeoutError("Timed out waiting for Lakeshore 525 ramp to complete.")
