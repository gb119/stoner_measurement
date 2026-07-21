"""Lakeshore 625 superconducting magnet power supply driver."""

from __future__ import annotations

import time

from stoner_measurement.instruments.magnet_controller import (
    HeaterState,
    MagnetController,
    MagnetLimits,
    MagnetState,
    MagnetStatus,
    MagnetSupply,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.lakeshore import LakeshoreProtocol
from stoner_measurement.instruments.transport.base import BaseTransport

# OPST? returns the Operation Condition register: bit 0 = compliance,
# bit 1 = ramp done, bit 2 = persistent-switch heater stable.
_OPST_COMPLIANCE_BIT = 0x01
_OPST_RAMP_DONE_BIT = 0x02
_OPST_PSH_STABLE_BIT = 0x04
_OPST_KNOWN_BITS = _OPST_COMPLIANCE_BIT | _OPST_RAMP_DONE_BIT | _OPST_PSH_STABLE_BIT

_ACTIVE_RAMP_STATES = {MagnetState.RAMPING}
_TERMINAL_RAMP_STATES = {
    MagnetState.AT_TARGET,
    MagnetState.STANDBY,
    MagnetState.PERSISTENT,
    MagnetState.QUIESCENT,
}

_SECONDS_PER_MINUTE = 60.0


class Lakeshore625(MagnetController, MagnetSupply):
    """Driver for a Lakeshore 625 superconducting magnet power supply.

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
        >>> from stoner_measurement.instruments.lakeshore import Lakeshore625
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> t = NullTransport(responses=[b"LAKESHORE,MODEL625,SN001,1.0\\r\\n"])
        >>> mps = Lakeshore625(transport=t)
        >>> mps.connect()
        >>> mps.identify()
        'LAKESHORE,MODEL625,SN001,1.0'
        >>> mps.disconnect()
    """

    _EXPECTED_IDENTITY_TOKENS = ("MODEL625",)

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the Lakeshore 625 driver.

        Args:
            transport (BaseTransport):
                Physical transport for instrument communication.

        Keyword Parameters:
            protocol (BaseProtocol | None):
                Protocol instance. Uses :class:`LakeshoreProtocol` when omitted.
        """
        transport._use_mav=False
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

        Queries ``OPST?`` which returns a numeric bit-coded operating status.

        Returns:
            (MagnetStatus):
                Snapshot of controller state and key readings.
        """
        raw = self.query("OPST?").strip()
        try:
            bits = int(raw)
        except ValueError:
            self._comms_logger.warning("OPST? returned unexpected response %r; marking status UNKNOWN", raw)
            state = MagnetState.UNKNOWN
        else:
            if bits & ~_OPST_KNOWN_BITS:
                self._comms_logger.warning("OPST? returned unhandled status bits 0x%X; marking status UNKNOWN", bits)
                state = MagnetState.UNKNOWN
            elif bits & _OPST_COMPLIANCE_BIT:
                state = MagnetState.FAULT
            elif bits & _OPST_RAMP_DONE_BIT:
                state = MagnetState.AT_TARGET
            else:
                state = MagnetState.RAMPING
        at_target = state in _TERMINAL_RAMP_STATES
        heater_state = self._read_heater_state()
        return MagnetStatus(
            state=state,
            current=self.current,
            field=self.field,
            voltage=self.voltage,
            persistent=False,
            heater_on=heater_state is HeaterState.ON,
            heater_state=heater_state,
            at_target=at_target,
            message=raw,
        )

    @property
    def magnet_constant(self) -> float:
        """Return the cached instrument field constant in tesla per amp.

        Returns:
            (float):
                Magnet constant in tesla per amp.
        """
        return self._magnet_constant

    def refresh_magnet_constant(self) -> float:
        """Query and cache the instrument field constant in tesla per amp."""
        try:
            units, constant = _parse_csv(self.query("FLDS?"), expected=2)
            value = float(constant)
            # Manual: FLDS units 0 = T/A, 1 = kG/A.
            self._magnet_constant = value if int(float(units)) == 0 else value * 0.1
        except Exception:
            self._comms_logger.warning("FLDS? returned unexpected response; using cached magnet constant", exc_info=True)
        return self._magnet_constant

    @property
    def limits(self) -> MagnetLimits:
        """Return output limits read from the instrument.

        Returns:
            (MagnetLimits):
                Current, derived field, and current-ramp limits. The Model 625
                reports ramp-rate limits in A/s, which are converted to T/min.
        """
        try:
            current, _voltage, rate = _parse_csv(self.query("LIMIT?"), expected=3)
            max_current = float(current)
            ramp_rate_current_s = float(rate)
            constant = self._magnet_constant
            self._limits = MagnetLimits(
                max_current=max_current,
                max_field=max_current * constant,
                max_ramp_rate=ramp_rate_current_s * constant * 60.0,
            )
        except Exception:
            self._comms_logger.warning("LIMIT? returned unexpected response; using cached limits", exc_info=True)
        return self._limits

    @property
    def heater(self) -> bool:
        """Return persistent switch heater state.

        Returns:
            (bool):
                ``True`` when the heater is stably on.
        """
        return self._read_heater_state() is HeaterState.ON

    @property
    def target_current(self) -> float | None:
        """Return the programmed current target in amps."""
        return self._query_float("SETI?")

    @property
    def target_field(self) -> float | None:
        """Return the programmed field target in tesla."""
        return self._query_float("SETF?")

    @property
    def ramp_rate_current(self) -> float | None:
        """Return the programmed current ramp rate in amps per minute."""
        rate = self._query_float("RATE?")
        return None if rate is None else rate * _SECONDS_PER_MINUTE

    @property
    def ramp_rate_field(self) -> float | None:
        """Return the programmed field ramp rate in tesla per minute."""
        rate = self._query_float("RATE?")
        return None if rate is None else rate * self.magnet_constant * _SECONDS_PER_MINUTE

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
        self.write(f"RATE {rate / _SECONDS_PER_MINUTE}")

    def set_ramp_rate_field(self, rate: float) -> None:
        """Set the field ramp rate in tesla per minute.

        Args:
            rate (float):
                Ramp rate in tesla per minute.
        """
        if self._magnet_constant <= 0.0:
            raise ValueError("Magnet constant must be positive to convert field ramp rates.")
        self.write(f"RATE {rate / self._magnet_constant / _SECONDS_PER_MINUTE}")

    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        """Set the software magnet constant used for conversion.

        Args:
            tesla_per_amp (float):
                Magnet constant in tesla per amp.
        """
        if tesla_per_amp <= 0.0:
            raise ValueError(f"Magnet constant must be positive, got {tesla_per_amp}.")
        self.write(f"FLDS 0,{tesla_per_amp}")
        self._magnet_constant = tesla_per_amp

    def set_limits(self, limits: MagnetLimits) -> None:
        """Set software limits used by higher-level sequence logic.

        Args:
            limits (MagnetLimits):
                Limit configuration to cache for runtime checks.
        """
        max_ramp_rate_field = limits.max_ramp_rate
        if max_ramp_rate_field is None:
            max_ramp_rate_current_s = 99.999
        else:
            if self._magnet_constant <= 0.0:
                raise ValueError("Magnet constant must be positive to convert field ramp limits.")
            max_ramp_rate_current_s = max_ramp_rate_field / self._magnet_constant / _SECONDS_PER_MINUTE
        compliance_voltage = self._query_float("SETV?")
        self.write(f"LIMIT {limits.max_current},{compliance_voltage},{max_ramp_rate_current_s}")
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
        self.write("STOP")

    def hold(self) -> None:
        """Hold the present output without changing field."""
        self.write("STOP")

    def go_to_zero(self) -> None:
        """Ramp the supply output to zero."""
        self.write("ZERO")

    def abort_ramp(self) -> None:
        """Stop ramping immediately.

        The Model 625 command set does not provide a dedicated abort command,
        so this maps to the supported ``STOP`` action.
        """
        self.write("STOP")

    def heater_on(self) -> None:
        """Enable the persistent switch heater."""
        self.write("PSH 1")

    def heater_off(self) -> None:
        """Disable the persistent switch heater."""
        self.write("PSH 0")

    def return_to_local(self) -> None:
        """No-op for the Lakeshore 625, which has no Oxford-style local handoff command."""
        return

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
        raise TimeoutError("Timed out waiting for Lakeshore 625 ramp to complete.")

    def _read_heater_state(self) -> HeaterState:
        """Read and decode the persistent-switch heater state.

        The ``PSH?`` response is interpreted as a two-bit flag:
        bit 0 is the nominal heater state (1 = on, 0 = off), and
        bit 1 indicates the state is transitioning.

        Returns:
            (HeaterState):
                Decoded shared heater-state enum.
        """
        raw = self.query("PSH?").strip()
        try:
            value = int(raw)
        except ValueError:
            return HeaterState.UNKNOWN
        return {
            0: HeaterState.OFF,
            1: HeaterState.ON,
            2: HeaterState.COOLING,
            3: HeaterState.WARMING,
        }.get(value, HeaterState.UNKNOWN)


def _parse_csv(response: str, *, expected: int) -> list[str]:
    """Split a comma-separated 625 response and validate field count."""
    parts = [part.strip() for part in response.split(",")]
    if len(parts) != expected:
        raise ValueError(f"Expected {expected} comma-separated fields, got {len(parts)}: {response!r}")
    return parts
