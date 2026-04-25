"""Oxford temperature controller drivers."""

from __future__ import annotations

from typing import ClassVar

from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.oxford import OxfordProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.temperature_controller import (
    ControllerCapabilities,
    ControlMode,
    PIDParameters,
    SensorStatus,
    TemperatureController,
)
from stoner_measurement.instruments.transport.base import BaseTransport

_MODE_TO_CODE = {
    ControlMode.OFF: 0,
    ControlMode.CLOSED_LOOP: 1,
    ControlMode.OPEN_LOOP: 2,
    ControlMode.MONITOR: 3,
}
_CODE_TO_MODE = {value: key for key, value in _MODE_TO_CODE.items()}


class _OxfordTemperatureControllerBase(TemperatureController):
    """Common command implementation for Oxford temperature controllers."""

    _CAPABILITIES: ClassVar[ControllerCapabilities]

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol) -> None:
        """Initialise the Oxford temperature controller driver."""
        super().__init__(transport=transport, protocol=protocol)
        self._loop_input: dict[int, str] = {loop: self._CAPABILITIES.input_channels[0] for loop in self._CAPABILITIES.loop_numbers}
        self._gas_auto: bool = False

    def get_temperature(self, channel: str) -> float:
        """Return channel temperature in Kelvin."""
        normalised = self._normalise_channel(channel)
        return self._query_float(self._temperature_query(normalised))

    def get_sensor_status(self, channel: str) -> SensorStatus:
        """Return sensor status for *channel*."""
        _ = self._normalise_channel(channel)
        return SensorStatus.OK

    def get_input_channel(self, loop: int) -> str:
        """Return sensor channel assigned to *loop*."""
        return self._loop_input[self._normalise_loop(loop)]

    def set_input_channel(self, loop: int, channel: str) -> None:
        """Assign a channel to *loop*."""
        loop_number = self._normalise_loop(loop)
        normalised = self._normalise_channel(channel)
        self._loop_input[loop_number] = normalised
        self.write(self._input_command(loop_number, normalised))

    def get_setpoint(self, loop: int) -> float:
        """Return setpoint in Kelvin."""
        return self._query_float(self._setpoint_query(self._normalise_loop(loop)))

    def set_setpoint(self, loop: int, value: float) -> None:
        """Set setpoint in Kelvin."""
        self.write(self._setpoint_command(self._normalise_loop(loop), value))

    def get_loop_mode(self, loop: int) -> ControlMode:
        """Return control mode for *loop*."""
        mode_code = int(self._query_float(self._mode_query(self._normalise_loop(loop))))
        return _CODE_TO_MODE.get(mode_code, ControlMode.CLOSED_LOOP)

    def set_loop_mode(self, loop: int, mode: ControlMode) -> None:
        """Set control mode for *loop*."""
        self.write(self._mode_command(self._normalise_loop(loop), _MODE_TO_CODE.get(mode, 1)))

    def get_heater_output(self, loop: int) -> float:
        """Return heater output percentage for *loop*."""
        return self._query_float(self._heater_output_query(self._normalise_loop(loop)))

    def set_heater_range(self, loop: int, range_: int) -> None:
        """Set heater range index for *loop*."""
        self.write(self._heater_range_command(self._normalise_loop(loop), int(range_)))

    def get_pid(self, loop: int) -> PIDParameters:
        """Return PID parameters for *loop*."""
        values = self._parse_csv_floats(self.query(self._pid_query(self._normalise_loop(loop))), minimum_length=3)
        return PIDParameters(p=values[0], i=values[1], d=values[2])

    def set_pid(self, loop: int, p: float, i: float, d: float) -> None:
        """Set PID parameters for *loop*."""
        self.write(self._pid_command(self._normalise_loop(loop), p, i, d))

    def get_ramp_rate(self, loop: int) -> float:
        """Return ramp rate in Kelvin per minute for *loop*."""
        _, rate = self._get_ramp(loop)
        return rate

    def set_ramp_rate(self, loop: int, rate: float) -> None:
        """Set ramp rate in Kelvin per minute for *loop*."""
        enabled, _ = self._get_ramp(loop)
        self.write(self._ramp_command(self._normalise_loop(loop), enabled, rate))

    def get_ramp_enabled(self, loop: int) -> bool:
        """Return whether ramping is enabled for *loop*."""
        enabled, _ = self._get_ramp(loop)
        return enabled

    def set_ramp_enabled(self, loop: int, enabled: bool) -> None:
        """Enable or disable ramping for *loop*."""
        _, rate = self._get_ramp(loop)
        self.write(self._ramp_command(self._normalise_loop(loop), enabled, rate))

    def get_capabilities(self) -> ControllerCapabilities:
        """Return static driver capabilities."""
        return self._CAPABILITIES

    def _normalise_channel(self, channel: str) -> str:
        """Validate and normalise channel labels."""
        available = self._CAPABILITIES.input_channels
        candidate = channel.strip().upper()
        if candidate not in available:
            raise ValueError(f"Invalid channel {channel!r}; expected one of {available}.")
        return candidate

    def _normalise_loop(self, loop: int) -> int:
        """Validate loop numbers."""
        if loop not in self._CAPABILITIES.loop_numbers:
            raise ValueError(f"Invalid loop {loop}; expected one of {self._CAPABILITIES.loop_numbers}.")
        return loop

    def _query_float(self, command: str) -> float:
        """Query and parse a single numeric token."""
        token = self.query(command).split(",", maxsplit=1)[0].strip()
        try:
            return float(token)
        except ValueError as exc:
            raise ValueError(f"Invalid numeric response for {command!r}: {token!r}.") from exc

    def _parse_csv_floats(self, response: str, *, minimum_length: int) -> list[float]:
        """Parse a comma-separated float payload."""
        tokens = [item.strip() for item in response.split(",") if item.strip()]
        if len(tokens) < minimum_length:
            raise ValueError(f"Expected at least {minimum_length} values, got {response!r}.")
        return [float(token) for token in tokens]

    def _get_ramp(self, loop: int) -> tuple[bool, float]:
        """Return ``(enabled, rate)`` for *loop*."""
        values = self._parse_csv_floats(
            self.query(self._ramp_query(self._normalise_loop(loop))),
            minimum_length=2,
        )
        return bool(int(values[0])), values[1]

    def _temperature_query(self, channel: str) -> str:
        """Return the instrument query command for reading temperature on *channel*."""
        raise NotImplementedError

    def _input_command(self, loop: int, channel: str) -> str:
        """Return the instrument command that assigns *channel* to *loop*."""
        raise NotImplementedError

    def _setpoint_query(self, loop: int) -> str:
        """Return the instrument query command for reading the setpoint of *loop*."""
        raise NotImplementedError

    def _setpoint_command(self, loop: int, value: float) -> str:
        """Return the instrument command that sets the setpoint of *loop* to *value* K."""
        raise NotImplementedError

    def _mode_query(self, loop: int) -> str:
        """Return the instrument query command for reading the control mode of *loop*."""
        raise NotImplementedError

    def _mode_command(self, loop: int, mode_code: int) -> str:
        """Return the instrument command that sets the control mode of *loop*."""
        raise NotImplementedError

    def _heater_output_query(self, loop: int) -> str:
        """Return the instrument query command for reading heater output percentage of *loop*."""
        raise NotImplementedError

    def _heater_range_command(self, loop: int, range_: int) -> str:
        """Return the instrument command that sets the heater range index for *loop*."""
        raise NotImplementedError

    def _pid_query(self, loop: int) -> str:
        """Return the instrument query command for reading PID parameters of *loop*."""
        raise NotImplementedError

    def _pid_command(self, loop: int, p: float, i: float, d: float) -> str:
        """Return the instrument command that sets PID parameters for *loop*."""
        raise NotImplementedError

    def _ramp_query(self, loop: int) -> str:
        """Return the instrument query command for reading ramp state and rate of *loop*."""
        raise NotImplementedError

    def _ramp_command(self, loop: int, enabled: bool, rate: float) -> str:
        """Return the instrument command that sets the ramp state and rate for *loop*."""
        raise NotImplementedError


class OxfordITC503(_OxfordTemperatureControllerBase):
    """Concrete driver for the Oxford Instruments ITC503 temperature controller."""

    _ITC503_HEATER_RANGES = ("Off", "On")
    _CAPABILITIES = ControllerCapabilities(
        num_inputs=3,
        num_loops=1,
        input_channels=("A", "B", "C"),
        loop_numbers=(1,),
        has_ramp=True,
        has_pid=True,
        has_cryogen_control=True,
        has_gas_auto_mode=True,
        heater_range_labels={1: _ITC503_HEATER_RANGES},
    )

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the ITC503 driver."""
        super().__init__(transport=transport, protocol=protocol if protocol is not None else OxfordProtocol())

    def identify(self) -> str:
        """Return identity string."""
        return self.query("V")

    def get_heater_range(self, loop: int) -> int:
        """Return the current heater range index (0=off, 1=on) for *loop*."""
        self._normalise_loop(loop)
        # ITC503 does not have a dedicated range-read command; infer from
        # the heater output: zero output implies off, any non-zero implies on.
        output = self._query_float("R5")
        return 0 if output == 0.0 else 1

    def get_gas_flow(self) -> float:
        """Return the gas-flow needle valve position as a percentage."""
        return self._query_float("R6")

    def set_gas_flow(self, percent: float) -> None:
        """Set the gas-flow needle valve position to *percent* open."""
        self.write(f"G{percent:.1f}")

    def get_needle_valve(self) -> float:
        """Return the needle-valve position as a percentage."""
        return self.get_gas_flow()

    def set_needle_valve(self, position: float) -> None:
        """Set the needle-valve position to *position* percent open."""
        self.set_gas_flow(position)

    def get_gas_auto(self) -> bool:
        """Return ``True`` if gas flow is under automatic control."""
        return self._gas_auto

    def set_gas_auto(self, auto: bool) -> None:
        """Enable or disable automatic gas-flow control.

        The ITC503 ``A`` command controls the combined heater/gas auto mode.
        Bit 0 = auto heater, bit 1 = auto gas.  This implementation preserves
        the current heater-auto state when toggling gas auto mode.
        """
        self._gas_auto = auto
        # Bit 0 would be set if we also want auto-heater. Since loop mode
        # already controls the heater, only set bit 1 for gas auto.
        mode_code = 2 if auto else 0
        self.write(f"A{mode_code}")

    def _temperature_query(self, channel: str) -> str:
        """Return the ITC503 query command for reading temperature on *channel*."""
        return {"A": "R1", "B": "R2", "C": "R3"}[channel]

    def _input_command(self, loop: int, channel: str) -> str:
        """Return the ITC503 command that assigns *channel* to the heater loop."""
        channel_code = {"A": 1, "B": 2, "C": 3}[channel]
        return f"C{channel_code}"

    def _setpoint_query(self, loop: int) -> str:
        """Return the ITC503 query command for reading the setpoint."""
        return "R0"

    def _setpoint_command(self, loop: int, value: float) -> str:
        """Return the ITC503 command that sets the setpoint to *value* K."""
        return f"T{value}"

    def _mode_query(self, loop: int) -> str:
        """Return the ITC503 query command for reading the control mode."""
        return "R20"

    def _mode_command(self, loop: int, mode_code: int) -> str:
        """Return the ITC503 command that sets the control mode."""
        return f"A{mode_code}"

    def _heater_output_query(self, loop: int) -> str:
        """Return the ITC503 query command for reading heater output percentage."""
        return "R5"

    def _heater_range_command(self, loop: int, range_: int) -> str:
        """Return the ITC503 command that sets the heater range index."""
        return f"H{range_}"

    def _pid_query(self, loop: int) -> str:
        """Return the ITC503 query command for reading PID parameters."""
        return "R8,R9,R10"

    def _pid_command(self, loop: int, p: float, i: float, d: float) -> str:
        """Return the ITC503 command that sets PID parameters."""
        return f"P{p},I{i},D{d}"

    def _ramp_query(self, loop: int) -> str:
        """Return the ITC503 query command for reading ramp state and rate."""
        return "R21"

    def _ramp_command(self, loop: int, enabled: bool, rate: float) -> str:
        """Return the ITC503 command that sets the ramp state and rate."""
        return f"S{int(enabled)},{rate}"


class OxfordMercuryTemperatureController(_OxfordTemperatureControllerBase):
    """Concrete driver for the Oxford Instruments Mercury Temperature Controller."""

    _MERCURY_HEATER_RANGES = ("Off", "On")
    _CAPABILITIES = ControllerCapabilities(
        num_inputs=4,
        num_loops=2,
        input_channels=("A", "B", "C", "D"),
        loop_numbers=(1, 2),
        has_ramp=True,
        has_pid=True,
        has_cryogen_control=True,
        has_gas_auto_mode=True,
        heater_range_labels={1: _MERCURY_HEATER_RANGES, 2: _MERCURY_HEATER_RANGES},
    )

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the Mercury temperature controller driver."""
        super().__init__(transport=transport, protocol=protocol if protocol is not None else ScpiProtocol())

    def get_heater_range(self, loop: int) -> int:
        """Return the current heater range index (0=off, 1=on) for *loop*."""
        loop_n = self._normalise_loop(loop)
        raw = self.query(f"READ:LOOP{loop_n}:RANGE?").strip()
        return 0 if raw in ("OFF", "0", "") else 1

    def get_gas_flow(self) -> float:
        """Return the gas-flow needle valve position as a percentage."""
        return self._query_float("READ:NEEDLEVALVE:FLOW?")

    def set_gas_flow(self, percent: float) -> None:
        """Set the gas-flow needle valve position to *percent* open."""
        self.write(f"SET:NEEDLEVALVE:FLOW {percent:.1f}")

    def get_needle_valve(self) -> float:
        """Return the needle-valve position as a percentage."""
        return self.get_gas_flow()

    def set_needle_valve(self, position: float) -> None:
        """Set the needle-valve position to *position* percent open."""
        self.set_gas_flow(position)

    def get_gas_auto(self) -> bool:
        """Return ``True`` if the needle valve is under automatic control."""
        raw = self.query("READ:NEEDLEVALVE:MODE?").strip().upper()
        return raw == "AUTO"

    def set_gas_auto(self, auto: bool) -> None:
        """Enable or disable automatic needle-valve control."""
        self._gas_auto = auto
        mode = "AUTO" if auto else "MANUAL"
        self.write(f"SET:NEEDLEVALVE:MODE {mode}")

    def _temperature_query(self, channel: str) -> str:
        """Return the Mercury query command for reading temperature on *channel*."""
        return f"READ:TEMP? {channel}"

    def _input_command(self, loop: int, channel: str) -> str:
        """Return the Mercury command that assigns *channel* to *loop*."""
        return f"CONF:LOOP{loop}:INPUT {channel}"

    def _setpoint_query(self, loop: int) -> str:
        """Return the Mercury query command for reading the setpoint of *loop*."""
        return f"READ:LOOP{loop}:SETP?"

    def _setpoint_command(self, loop: int, value: float) -> str:
        """Return the Mercury command that sets the setpoint of *loop* to *value* K."""
        return f"SET:LOOP{loop}:SETP {value}"

    def _mode_query(self, loop: int) -> str:
        """Return the Mercury query command for reading the control mode of *loop*."""
        return f"READ:LOOP{loop}:MODE?"

    def _mode_command(self, loop: int, mode_code: int) -> str:
        """Return the Mercury command that sets the control mode of *loop*."""
        return f"SET:LOOP{loop}:MODE {mode_code}"

    def _heater_output_query(self, loop: int) -> str:
        """Return the Mercury query command for reading heater output of *loop*."""
        return f"READ:LOOP{loop}:HTR?"

    def _heater_range_command(self, loop: int, range_: int) -> str:
        """Return the Mercury command that sets the heater range for *loop*."""
        return f"SET:LOOP{loop}:RANGE {range_}"

    def _pid_query(self, loop: int) -> str:
        """Return the Mercury query command for reading PID parameters of *loop*."""
        return f"READ:LOOP{loop}:PID?"

    def _pid_command(self, loop: int, p: float, i: float, d: float) -> str:
        """Return the Mercury command that sets PID parameters for *loop*."""
        return f"SET:LOOP{loop}:PID {p},{i},{d}"

    def _ramp_query(self, loop: int) -> str:
        """Return the Mercury query command for reading ramp state and rate of *loop*."""
        return f"READ:LOOP{loop}:RAMP?"

    def _ramp_command(self, loop: int, enabled: bool, rate: float) -> str:
        """Return the Mercury command that sets the ramp state and rate for *loop*."""
        return f"SET:LOOP{loop}:RAMP {int(enabled)},{rate}"
