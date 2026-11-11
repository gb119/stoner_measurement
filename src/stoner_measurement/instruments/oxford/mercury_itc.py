"""Native Oxford Mercury iTC modular device and temperature-loop commands."""

from __future__ import annotations

import math
import re

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.mercury import MercuryProtocol
from stoner_measurement.instruments.temperature_controller import (
    ControllerCapabilities,
    ControlMode,
    PIDParameters,
    SensorStatus,
    TemperatureController,
)
from stoner_measurement.instruments.transport.base import BaseTransport


class OxfordMercuryTemperatureController(TemperatureController):
    """Mercury iTC native protocol, based on the Issue 05 operator's manual.

    Device UIDs and existing heater associations are discovered on connection.
    Sensor aliases A onwards follow sorted sensor UIDs; loops enumerate sensors
    with assigned heaters. Input reassignment is left to the instrument's
    configuration, so each loop exposes only its existing sensor. No heater,
    auxiliary or PID-table association is changed during discovery.

    Gas controls are advertised only when exactly one sensor has an auxiliary
    board assigned. Multiple gas loops need explicit instrument configuration.
    Existing PID tables may be selected, but their file contents are not edited.
    Ramp control requires firmware 1.4.40 or newer. Select the desired remote
    interface on the front panel before connecting.

    Args:
        transport (BaseTransport): Owned instrument transport.
        protocol (BaseProtocol | None): Native Mercury framing; defaults to
            MercuryProtocol. A generic SCPI error-queue protocol is unsuitable.
    """

    _EXPECTED_IDENTITY_TOKENS = ("MERCURY", "ITC")
    _MODES = (ControlMode.OFF, ControlMode.OPEN_LOOP, ControlMode.CLOSED_LOOP, ControlMode.ZONE)

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise without accessing hardware."""
        super().__init__(transport, protocol or MercuryProtocol())
        self._clear_catalogue()

    def _clear_catalogue(self):
        """Discard device references and capabilities from the previous connection."""
        self._sensors = {}
        self._loops = {}
        self._heaters = {}
        self._gas_sensor = None
        self._gas_uid = None
        self._firmware = ()
        self._capabilities = ControllerCapabilities(
            num_inputs=0, num_loops=0, input_channels=(), loop_numbers=(), has_ramp=False,
            has_heater_range=False, has_manual_heater_output=True, control_modes=self._MODES,
        )

    def identify(self) -> str:
        """Read the native Mercury identity using ``*IDN?``."""
        return self.query("*IDN?")

    def confirm_identity(self) -> str:
        """Verify model identity and discover native device associations."""
        with self._lock:
            identity = super().confirm_identity()
            versions = re.findall(r"\d+\.\d+\.\d+(?:\.\d+)?", identity)
            firmware = tuple(int(part) for part in versions[-1].split(".")) if versions else ()
            catalogue = self.query("READ:SYS:CAT")
            self.protocol.check_error(catalogue, command="READ:SYS:CAT")
            if not catalogue.startswith("STAT:"):
                raise ValueError(f"Malformed Mercury catalogue {catalogue!r}.")
            payload = catalogue.removeprefix("STAT:SYS:CAT:").removeprefix("STAT:")
            tokens = payload.removesuffix(":VALID").split(":")
            if not tokens or len(tokens) % 3:
                raise ValueError(f"Malformed Mercury catalogue {catalogue!r}.")
            devices = {}
            for index in range(0, len(tokens), 3):
                marker, uid, kind = (token.strip() for token in tokens[index:index + 3])
                if marker != "DEV" or not re.fullmatch(r"[A-Za-z0-9_.-]+", uid) or uid in devices:
                    raise ValueError(f"Malformed Mercury catalogue {catalogue!r}.")
                devices[uid] = kind
            sensor_uids = sorted(uid for uid, kind in devices.items() if kind == "TEMP")
            if not sensor_uids or len(sensor_uids) > 9:
                raise ValueError("Mercury iTC must report between one and nine temperature inputs.")
            sensors = {chr(65 + index): uid for index, uid in enumerate(sensor_uids)}
            loops, heaters, gas = {}, {}, []
            for channel, uid in sensors.items():
                heater = self._read(f"DEV:{uid}:TEMP:LOOP:HTR")
                auxiliary = self._read(f"DEV:{uid}:TEMP:LOOP:AUX")
                if heater != "0":
                    if devices.get(heater) != "HTR" or heater in heaters.values():
                        raise ValueError(f"Invalid or shared Mercury heater association {heater!r}.")
                    loop = len(loops) + 1
                    loops[loop], heaters[loop] = channel, heater
                if auxiliary != "0":
                    if devices.get(auxiliary) != "AUX":
                        raise ValueError(f"Invalid Mercury auxiliary association {auxiliary!r}.")
                    gas.append((channel, auxiliary))
            self._sensors, self._loops, self._heaters = sensors, loops, heaters
            self._gas_sensor, self._gas_uid = gas[0] if len(gas) == 1 else (None, None)
            self._firmware = firmware
            self._capabilities = ControllerCapabilities(
                num_inputs=len(sensors), num_loops=len(loops), input_channels=tuple(sensors),
                loop_numbers=tuple(loops), has_ramp=firmware >= (1, 4, 40), has_pid=True,
                has_heater_range=False, has_manual_heater_output=True,
                has_cryogen_control=len(gas) == 1, has_gas_auto_mode=len(gas) == 1,
                control_modes=self._MODES, min_temperature=0, max_temperature=2000,
                setpoint_after_configuration=True,
            )
            return identity

    def disconnect(self) -> None:
        """Close the owned transport and discard discovered device references."""
        try:
            super().disconnect()
        finally:
            self._clear_catalogue()

    def get_capabilities(self) -> ControllerCapabilities:
        """Return capabilities discovered for this connection, not assumed boards."""
        return self._capabilities

    def _read(self, path):
        """Read an exact native path and reject mismatched or empty replies."""
        command = f"READ:{path}"
        reply = self.query(command)
        self.protocol.check_error(reply, command=command)
        prefix = f"STAT:{path}:"
        if not reply.startswith(prefix):
            raise InstrumentError(f"Mercury: mismatched reply {reply!r}", command=command)
        value = reply[len(prefix):].removesuffix(":VALID")
        if not value:
            raise InstrumentError("Mercury: empty readback", command=command)
        return value

    def _set(self, path, value, slow=None):
        """Consume and validate an acknowledged SET, without replaying failures."""
        command = f"SET:{path}:{value}"
        reply = self.query(command, slow=slow)
        self.protocol.check_error(reply, command=command)
        prefixes = (f"STAT:SET:{path}:", f"STAT:{path}:")
        suffix = next((reply[len(prefix):] for prefix in prefixes if reply.startswith(prefix)), None)
        if suffix not in ("VALID", f"{value}:VALID", str(value)):
            raise InstrumentError(f"Mercury: invalid SET acknowledgement {reply!r}", command=command)

    def write(self, command: str, slow: int | None = None) -> None:
        """Send a native SET and consume its acknowledgement.

        Args:
            command (str): Complete native SET command without a terminator.

        Keyword Parameters:
            slow (int | None): Optional transport delay in milliseconds.

        Raises:
            ValueError: A non-SET command was supplied; use query for READ.
            InstrumentError: The command is rejected or incorrectly acknowledged.
        """
        if not command.startswith("SET:") or command.count(":") < 2:
            raise ValueError("Mercury write requires a native SET; use query for READ commands.")
        path, value = command[4:].rsplit(":", 1)
        self._set(path, value, slow=slow)

    @staticmethod
    def _number(value, unit=""):
        """Parse finite native numbers and optional SI-scaled units."""
        match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*:?(.*)", value)
        if match is None:
            raise ValueError(f"Invalid Mercury numeric value {value!r}.")
        number, suffix = float(match[1]), match[2]
        scale = 1.0
        if suffix and suffix != unit:
            prefixes = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6}
            if not unit or suffix[0] not in prefixes or suffix[1:] != unit:
                raise ValueError(f"Unexpected Mercury unit {suffix!r}, expected {unit!r}.")
            scale = prefixes[suffix[0]]
        if not math.isfinite(number * scale):
            raise ValueError("Non-finite Mercury readback.")
        return number * scale

    @staticmethod
    def _validate(value, low, high, name):
        """Reject invalid settings before transmission."""
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Mercury {name} must be between {low} and {high}.")

    def _sensor_path(self, channel):
        """Resolve a public sensor alias to a discovered native path."""
        try:
            return f"DEV:{self._sensors[channel.strip().upper()]}:TEMP"
        except KeyError as error:
            raise ValueError(f"Unknown or undiscovered Mercury sensor {channel!r}.") from error

    def _loop_path(self, loop):
        """Resolve an existing configured heater loop."""
        try:
            return self._sensor_path(self._loops[loop]) + ":LOOP"
        except KeyError as error:
            raise ValueError(f"Unknown or undiscovered Mercury loop {loop!r}.") from error

    def get_loop_input_channels(self, loop: int) -> tuple[str, ...]:
        """Return the loop's existing sensor without reassigning hardware boards."""
        self._loop_path(loop)
        return (self._loops[loop],)

    def get_input_channel(self, loop: int) -> str:
        """Return the sensor whose native control loop is being addressed."""
        self._loop_path(loop)
        return self._loops[loop]

    def set_input_channel(self, loop: int, channel: str) -> None:
        """Validate the sensor-owned loop; configure board associations on the instrument."""
        if channel.strip().upper() not in self.get_loop_input_channels(loop):
            raise ValueError("Mercury loop sensor changes require hardware association configuration and reconnect.")

    def get_temperature(self, channel: str) -> float:
        """Read the sensor temperature signal in kelvin."""
        return self._number(self._read(self._sensor_path(channel) + ":SIG:TEMP"), "K")

    def get_sensor_status(self, channel: str) -> SensorStatus:
        """Return INVALID when the temperature signal is unavailable; propagate I/O failures."""
        try:
            self.get_temperature(channel)
        except (InstrumentError, ValueError):
            return SensorStatus.INVALID
        return SensorStatus.OK

    def get_setpoint(self, loop: int) -> float:
        """Read the native loop target in kelvin."""
        return self._number(self._read(self._loop_path(loop) + ":TSET"), "K")

    def set_setpoint(self, loop: int, value: float) -> None:
        """Set a target from 0 to 2000 kelvin, respecting configured hardware limits."""
        self._validate(value, 0, 2000, "setpoint")
        self._set(self._loop_path(loop) + ":TSET", value)

    def get_loop_mode(self, loop: int) -> ControlMode:
        """Read heater automatic control and PID table selection independently of gas."""
        path = self._loop_path(loop)
        with self._lock:
            if not self._on_off(self._read(path + ":ENAB")):
                return ControlMode.OPEN_LOOP
            return ControlMode.ZONE if self._on_off(self._read(path + ":PIDT")) else ControlMode.CLOSED_LOOP

    def set_loop_mode(self, loop: int, mode: ControlMode) -> None:
        """Select heater control without changing gas mode; OFF also zeros manual output."""
        path = self._loop_path(loop)
        if mode not in self._MODES:
            raise ValueError(f"Unsupported Mercury mode {mode!r}.")
        with self._lock:
            self._set(path + ":PIDT", "ON" if mode is ControlMode.ZONE else "OFF")
            self._set(path + ":ENAB", "ON" if mode in (ControlMode.CLOSED_LOOP, ControlMode.ZONE) else "OFF")
            if mode is ControlMode.OFF:
                self.set_manual_heater_output(loop, 0.0)

    @staticmethod
    def _on_off(value):
        """Decode a native boolean without treating malformed data as disabled."""
        if value not in ("ON", "OFF", "Auto", "Manual", "AUTO", "MANUAL"):
            raise ValueError(f"Invalid Mercury boolean {value!r}.")
        return value in ("ON", "Auto", "AUTO")

    def get_heater_output(self, loop: int) -> float:
        """Read measured heater power as a percentage of its reported maximum power."""
        self._loop_path(loop)
        path = f"DEV:{self._heaters[loop]}:HTR"
        with self._lock:
            power = self._number(self._read(path + ":SIG:POWR"), "W")
            maximum = self._number(self._read(path + ":PMAX"), "W")
        if maximum <= 0:
            if power == 0:
                return 0.0
            raise ValueError("Mercury reports nonzero heater power with a non-positive maximum.")
        return power / maximum * 100

    def set_manual_heater_output(self, loop: int, output: float) -> None:
        """Set the manual heater demand in percent, 0–100."""
        self._validate(output, 0, 100, "heater output")
        self._set(self._loop_path(loop) + ":HSET", output)

    def set_heater_range(self, loop: int, range_: int) -> None:
        """Reject the nonexistent Mercury discrete heater-range command."""
        self._loop_path(loop)
        raise NotImplementedError("Mercury heaters have voltage/power limits, not discrete heater ranges.")

    def get_heater_range(self, loop: int) -> int:
        """Reject the nonexistent Mercury discrete heater-range readback."""
        self._loop_path(loop)
        raise NotImplementedError("Mercury heaters have no discrete heater ranges.")

    def get_pid(self, loop: int) -> PIDParameters:
        """Read the three native P/I/D settings."""
        path = self._loop_path(loop)
        with self._lock:
            return PIDParameters(*(self._number(self._read(path + ":" + term)) for term in ("P", "I", "D")))

    def set_pid(self, loop: int, p: float, i: float, d: float) -> None:
        """Disable table selection and write native P/I/D terms."""
        for name, value in (("P", p), ("I", i), ("D", d)):
            self._validate(value, 0, math.inf, name)
        path = self._loop_path(loop)
        with self._lock:
            self._set(path + ":PIDT", "OFF")
            for name, value in (("P", p), ("I", i), ("D", d)):
                self._set(path + ":" + name, value)

    def _ramp_path(self, loop):
        """Require a firmware version with documented continuous ramp support."""
        path = self._loop_path(loop)
        if not self._capabilities.has_ramp:
            raise NotImplementedError("Mercury ramp control requires identified firmware 1.4.40 or newer.")
        return path

    def get_ramp_rate(self, loop: int) -> float:
        """Read the continuous setpoint ramp rate in kelvin per minute."""
        return self._number(self._read(self._ramp_path(loop) + ":RSET"), "K/m")

    def set_ramp_rate(self, loop: int, rate: float) -> None:
        """Set a non-negative continuous setpoint ramp rate in kelvin per minute."""
        self._validate(rate, 0, math.inf, "ramp rate")
        self._set(self._ramp_path(loop) + ":RSET", rate)

    def get_ramp_enabled(self, loop: int) -> bool:
        """Read RENA, independently of stored sweep execution."""
        return self._on_off(self._read(self._ramp_path(loop) + ":RENA"))

    def set_ramp_enabled(self, loop: int, enabled: bool) -> None:
        """Enable or disable continuous setpoint ramping without starting a sweep."""
        self._set(self._ramp_path(loop) + ":RENA", "ON" if enabled else "OFF")

    def _gas_path(self):
        """Resolve the sole configured gas loop; reject ambiguous multi-valve systems."""
        if self._gas_sensor is None:
            raise NotImplementedError("Generic gas control requires exactly one associated Mercury auxiliary board.")
        return self._sensor_path(self._gas_sensor) + ":LOOP"

    def get_gas_flow(self) -> float:
        """Read actual valve position from the associated auxiliary board signal."""
        path = self._gas_path()
        uid = self._read(path + ":AUX")
        if uid != self._gas_uid:
            raise ValueError("Mercury gas association changed; reconnect before controlling it.")
        return self._number(self._read(f"DEV:{uid}:AUX:SIG:OPEN"), "%")

    def set_gas_flow(self, percent: float) -> None:
        """Write the configured gas loop's manual flow demand, 0–100 percent."""
        self._validate(percent, 0, 100, "gas flow")
        self._set(self._gas_path() + ":FSET", percent)

    def get_needle_valve(self) -> float:
        """Return the actual gas-valve opening percentage."""
        return self.get_gas_flow()

    def set_needle_valve(self, position: float) -> None:
        """Set manual gas flow in percent."""
        self.set_gas_flow(position)

    def get_gas_auto(self) -> bool:
        """Read FAUT without inferring heater automatic mode."""
        return self._on_off(self._read(self._gas_path() + ":FAUT"))

    def set_gas_auto(self, auto: bool) -> None:
        """Set FAUT only, preserving heater control."""
        legacy = self._firmware and self._firmware <= (1, 0, 11)
        value = ("Auto" if auto else "Manual") if legacy else ("ON" if auto else "OFF")
        self._set(self._gas_path() + ":FAUT", value)
