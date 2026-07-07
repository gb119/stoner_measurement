"""Eurotherm temperature controller drivers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from struct import pack, unpack
from typing import ClassVar

from stoner_measurement.instruments.base_instrument import BaseInstrument
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.modbus import ModbusRtuProtocol
from stoner_measurement.instruments.temperature_controller import (
    ControllerCapabilities,
    ControlMode,
    PIDParameters,
    SensorStatus,
    TemperatureController,
    TemperatureStatus,
)
from stoner_measurement.instruments.transport.base import BaseTransport

_READ_HOLDING_REGISTERS = 0x03
_WRITE_SINGLE_REGISTER = 0x06

_REMOTE_SETPOINT_SELECTION = 1

_ADDRESS_PV = 1
_ADDRESS_TARGET_SETPOINT = 2
_ADDRESS_MANUAL_OUTPUT = 3
_ADDRESS_WORKING_OUTPUT = 4
_ADDRESS_WORKING_SETPOINT = 5
_ADDRESS_PROPORTIONAL_BAND = 6
_ADDRESS_CONTROL_ACTION = 7
_ADDRESS_INTEGRAL_TIME = 8
_ADDRESS_DERIVATIVE_TIME = 9
_ADDRESS_SETPOINT_SELECT = 15
_ADDRESS_DEADBAND = 16
_ADDRESS_CUTBACK_LOW = 17
_ADDRESS_CUTBACK_HIGH = 18
_ADDRESS_RELATIVE_COOL_GAIN = 19
_ADDRESS_TIMER_STATUS = 23
_ADDRESS_SP1 = 24
_ADDRESS_SP2 = 25
_ADDRESS_REMOTE_SETPOINT_2200 = 26
_ADDRESS_REMOTE_SETPOINT_2400 = 485
_ADDRESS_LOCAL_TRIM = 27
_ADDRESS_MANUAL_RESET = 28
_ADDRESS_OUTPUT_HIGH_LIMIT = 30
_ADDRESS_OUTPUT_LOW_LIMIT = 31
_ADDRESS_SAFE_OUTPUT = 34
_ADDRESS_SETPOINT_RATE = 35
_ADDRESS_OUTPUT_RATE_LIMIT = 37
_ADDRESS_ERROR = 39
_ADDRESS_PID2_PROPORTIONAL_BAND = 48
_ADDRESS_PID2_INTEGRAL_TIME = 49
_ADDRESS_PID2_MANUAL_RESET = 50
_ADDRESS_PID2_DERIVATIVE_TIME = 51
_ADDRESS_PID2_RELATIVE_COOL_GAIN = 52
_ADDRESS_HOLDBACK_VALUE = 65
_ADDRESS_HOLDBACK_TYPE = 70
_ADDRESS_STATUS = 75
_ADDRESS_CONTROL_STATUS = 76
_ADDRESS_INSTRUMENT_STATUS = 77
_ADDRESS_LOOP_BREAK_TIME = 83
_ADDRESS_FORCED_OUTPUT = 84
_ADDRESS_HEAT_HYSTERESIS = 86
_ADDRESS_COOL_HYSTERESIS = 88
_ADDRESS_ADAPTIVE_TUNE_TRIGGER = 100
_ADDRESS_INPUT_FILTER = 101
_ADDRESS_VERSION = 107
_ADDRESS_SP1_HIGH_LIMIT = 111
_ADDRESS_SP1_LOW_LIMIT = 112
_ADDRESS_SP2_HIGH_LIMIT = 113
_ADDRESS_SP2_LOW_LIMIT = 114
_ADDRESS_PID2_CUTBACK_LOW = 117
_ADDRESS_PID2_CUTBACK_HIGH = 118
_ADDRESS_IDENTIFIER = 122
_ADDRESS_COMMS_ADDRESS = 131
_ADDRESS_PV_OFFSET = 141
_ADDRESS_PROGRAMMER_SETPOINT = 163
_ADDRESS_INSTRUMENT_MODE = 199
_ADDRESS_COMMS_PV = 203
_ADDRESS_SENSOR_BREAK_STATUS = 258
_ADDRESS_NEW_ALARM_STATUS = 260
_ADDRESS_LOOP_BREAK_STATUS = 263
_ADDRESS_AUTOTUNE_ENABLE = 270
_ADDRESS_ADAPTIVE_TUNE_ENABLE = 271
_ADDRESS_DROOP_COMPENSATION = 272
_ADDRESS_AUTO_MANUAL_MODE = 273
_ADDRESS_ACKNOWLEDGE_ALARMS = 274
_ADDRESS_LOCAL_REMOTE_SELECT = 276
_ADDRESS_HEAT_CONTROL_TYPE = 512
_ADDRESS_COOL_CONTROL_TYPE = 513

_ALARM_STATUS_3200 = {1: 294, 2: 295, 3: 296, 4: 297}

_STATUS_ALARM_BITS = {1: 0, 2: 1, 3: 2, 4: 3}
_STATUS_MANUAL_MODE_BIT = 4
_STATUS_SENSOR_BREAK_BIT = 5
_STATUS_LOOP_BREAK_BIT = 6
_STATUS_OVERRANGE_BIT = 10
_STATUS_NEW_ALARM_BIT = 12
_STATUS_RAMP_RUNNING_BIT = 13
_STATUS_REMOTE_SP_FAIL_BIT = 14
_STATUS_AUTOTUNE_ACTIVE_BIT = 15

_CONTROL_STATUS_SENSOR_BREAK_BIT = 1
_CONTROL_STATUS_OVERRANGE_BIT = 2
_CONTROL_STATUS_LOOP_BREAK_BIT = 6
_CONTROL_STATUS_AUTOTUNE_COMPLETE_BIT = 8

_INSTRUMENT_STATUS_RAMP_RUNNING_BIT = 2
_INSTRUMENT_STATUS_REMOTE_ACTIVE_BIT = 3

_HEAT_CONTROL_TYPES = {"off": 0, "onoff": 1, "pid": 2, "motor": 3}
_COOL_CONTROL_TYPES = {"off": 0, "onoff": 1, "pid": 2}
_EUROTHERM_2000_IDENTIFIER_MODELS = {
    0x2240: "2204",
    0x2260: "2216",
    0x2280: "2208",
    0x2440: "2404",
    0x2442: "2404",
    0x2460: "2416",
    0x2462: "2416",
    0x2480: "2408",
    0x2482: "2408",
}
_EUROTHERM_3200_IDENTIFIER_PREFIX = "32"


def _crc16_modbus(data: bytes) -> int:
    """Return the Modbus RTU CRC16 of *data*."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def _append_crc(data: bytes) -> bytes:
    """Return *data* with its Modbus RTU CRC trailer appended."""
    return data + pack("<H", _crc16_modbus(data))


@dataclass(frozen=True)
class _UnitScaling:
    """Temperature-unit conversion helpers."""

    absolute_offset_kelvin: float

    def to_kelvin(self, value: float) -> float:
        """Convert an instrument absolute temperature to Kelvin."""
        return value + self.absolute_offset_kelvin

    def from_kelvin(self, value: float) -> float:
        """Convert a Kelvin absolute temperature to instrument units."""
        return value - self.absolute_offset_kelvin


class _EurothermModbusTemperatureControllerBase(TemperatureController):
    """Shared Modbus RTU implementation for Eurotherm temperature controllers."""

    _CAPABILITIES: ClassVar[ControllerCapabilities]
    _REMOTE_SETPOINT_ADDRESS: ClassVar[int | None] = _ADDRESS_REMOTE_SETPOINT_2200
    _STATUS_HAS_REMOTE_FAIL_BIT: ClassVar[bool] = False
    _STATUS_HAS_RAMP_RUNNING_BIT: ClassVar[bool] = False
    _HAS_INSTRUMENT_STATUS_WORD: ClassVar[bool] = False
    _LOOP_BREAK_STATUS_ADDRESS: ClassVar[int | None] = _ADDRESS_LOOP_BREAK_STATUS
    _ALARM_STATUS_ADDRESSES: ClassVar[dict[int, int]] = _ALARM_STATUS_3200

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
        *,
        unit_id: int = 1,
        decimal_places: int = 1,
        temperature_unit: str = "C",
        use_remote_setpoint: bool = True,
        output_decimal_places: int = 1,
        pid_decimal_places: int = 1,
        ramp_decimal_places: int = 1,
        default_ramp_rate: float = 1.0,
    ) -> None:
        """Initialise the shared Eurotherm Modbus driver state."""
        super().__init__(transport=transport, protocol=protocol or ModbusRtuProtocol())
        if not 1 <= int(unit_id) <= 254:
            raise ValueError("unit_id must be in the range 1..254.")
        normalised_units = temperature_unit.strip().upper()
        if normalised_units not in {"K", "C"}:
            raise ValueError("temperature_unit must be 'K' or 'C'.")
        self._unit_id = int(unit_id)
        self._decimal_places = int(decimal_places)
        self._output_decimal_places = int(output_decimal_places)
        self._pid_decimal_places = int(pid_decimal_places)
        self._ramp_decimal_places = int(ramp_decimal_places)
        self._use_remote_setpoint = bool(use_remote_setpoint)
        self._default_ramp_rate = float(default_ramp_rate)
        self._cached_ramp_rate = float(default_ramp_rate)
        self._remote_setpoint_selected: bool | None = None
        self._temperature_scale = _UnitScaling(
            absolute_offset_kelvin=273.15 if normalised_units == "C" else 0.0
        )

    def connect(self) -> None:
        """Open the transport without identity verification."""
        BaseInstrument.connect(self)

    def read_raw(self, address: int) -> int:
        """Read one signed 16-bit holding register."""
        return self.read_registers(address, count=1)[0]

    def write_raw(self, address: int, value: int) -> None:
        """Write one signed 16-bit holding register."""
        self._write_single_register(address, value)

    def read_scaled(self, address: int, dp: int | None = None) -> float:
        """Read one scaled decimal register."""
        decimals = self._decimal_places if dp is None else int(dp)
        return self.read_raw(address) / (10**decimals)

    def write_scaled(self, address: int, value: float, dp: int | None = None) -> None:
        """Write one scaled decimal register."""
        decimals = self._decimal_places if dp is None else int(dp)
        scaled = int(round(float(value) * (10**decimals)))
        self.write_raw(address, scaled)

    def read_registers(self, address: int, *, count: int = 1) -> list[int]:
        """Read *count* holding registers starting at *address*."""
        payload = bytes(
            (
                self._unit_id,
                _READ_HOLDING_REGISTERS,
                (int(address) >> 8) & 0xFF,
                int(address) & 0xFF,
                (int(count) >> 8) & 0xFF,
                int(count) & 0xFF,
            )
        )
        response = self._transact(_append_crc(payload), expected_length=5 + 2 * int(count))
        byte_count = response[2]
        expected_byte_count = 2 * int(count)
        if byte_count != expected_byte_count:
            raise ValueError(
                f"Unexpected byte count {byte_count} for Modbus read of {count} register(s)."
            )
        data = response[3 : 3 + byte_count]
        return [unpack(">h", data[index : index + 2])[0] for index in range(0, len(data), 2)]

    def get_pv(self) -> float:
        """Return the process value in Kelvin."""
        return self.get_temperature("PV")

    def get_working_setpoint(self) -> float:
        """Return the active working setpoint in Kelvin."""
        return self.get_setpoint(1)

    def get_working_output(self) -> float:
        """Return the working output percentage."""
        return self.get_heater_output(1)

    def get_status(self) -> dict[str, bool | int]:
        """Return the decoded main status bitmap."""
        raw = self.read_raw(_ADDRESS_STATUS) & 0xFFFF
        return {
            "raw": raw,
            "alarm_1": self._status_bit(raw, _STATUS_ALARM_BITS[1]),
            "alarm_2": self._status_bit(raw, _STATUS_ALARM_BITS[2]),
            "alarm_3": self._status_bit(raw, _STATUS_ALARM_BITS[3]),
            "alarm_4": self._status_bit(raw, _STATUS_ALARM_BITS[4]),
            "manual_mode": self._status_bit(raw, _STATUS_MANUAL_MODE_BIT),
            "sensor_break": self._status_bit(raw, _STATUS_SENSOR_BREAK_BIT),
            "loop_break": self._status_bit(raw, _STATUS_LOOP_BREAK_BIT),
            "pv_overrange": self._status_bit(raw, _STATUS_OVERRANGE_BIT),
            "new_alarm": self._status_bit(raw, _STATUS_NEW_ALARM_BIT),
            "ramp_running": self._get_ramp_running_from_status(raw),
            "remote_setpoint_fail": (
                self._status_bit(raw, _STATUS_REMOTE_SP_FAIL_BIT)
                if self._STATUS_HAS_REMOTE_FAIL_BIT
                else False
            ),
            "autotune_active": self._status_bit(raw, _STATUS_AUTOTUNE_ACTIVE_BIT),
        }

    def get_temperature(self, channel: str) -> float:
        """Return the current process temperature in Kelvin."""
        self._normalise_channel(channel)
        return self._read_absolute_temperature_register(_ADDRESS_PV)

    def get_sensor_status(self, channel: str) -> SensorStatus:
        """Return the process-input status."""
        self._normalise_channel(channel)
        status = self.get_status()
        if bool(status["sensor_break"]):
            return SensorStatus.FAULT
        if bool(status["pv_overrange"]):
            return SensorStatus.OVERRANGE
        sensor_break_address = self._sensor_break_status_address()
        if sensor_break_address is not None and self.read_raw(sensor_break_address) != 0:
            return SensorStatus.FAULT
        return SensorStatus.OK

    def get_input_channel(self, loop: int) -> str:
        """Return the fixed process-input channel for the only loop."""
        self._normalise_loop(loop)
        return "PV"

    def set_input_channel(self, loop: int, channel: str) -> None:
        """Validate the only supported input channel."""
        self._normalise_loop(loop)
        self._normalise_channel(channel)

    def get_setpoint(self, loop: int) -> float:
        """Return the active working setpoint in Kelvin."""
        self._normalise_loop(loop)
        return self._read_absolute_temperature_register(_ADDRESS_WORKING_SETPOINT)

    def set_setpoint(self, loop: int, value: float) -> None:
        """Set the control setpoint in Kelvin."""
        self._normalise_loop(loop)
        if self._use_remote_setpoint:
            remote_address = self._remote_setpoint_address()
            if remote_address is not None:
                self.enable_remote_setpoint()
                self.write_remote_setpoint(value)
                return
        self._write_absolute_temperature_register(_ADDRESS_TARGET_SETPOINT, value)

    def get_loop_mode(self, loop: int) -> ControlMode:
        """Return the effective control mode."""
        self._normalise_loop(loop)
        instrument_mode = self.read_raw(_ADDRESS_INSTRUMENT_MODE)
        if instrument_mode != 0:
            return ControlMode.OFF
        manual_mode = self.read_raw(_ADDRESS_AUTO_MANUAL_MODE)
        return ControlMode.OPEN_LOOP if manual_mode == 1 else ControlMode.CLOSED_LOOP

    def set_loop_mode(self, loop: int, mode: ControlMode) -> None:
        """Set the effective control mode."""
        self._normalise_loop(loop)
        if mode is ControlMode.CLOSED_LOOP:
            self.set_standby(False)
            self.set_auto()
            return
        if mode is ControlMode.OPEN_LOOP:
            self.set_standby(False)
            self.write_raw(_ADDRESS_AUTO_MANUAL_MODE, 1)
            return
        if mode is ControlMode.OFF:
            self.set_standby(True)
            return
        raise ValueError(f"{type(self).__name__} does not support loop mode {mode.value!r}.")

    def get_heater_output(self, loop: int) -> float:
        """Return the working output percentage."""
        self._normalise_loop(loop)
        return self.read_scaled(_ADDRESS_WORKING_OUTPUT, self._output_decimal_places)

    def set_manual_heater_output(self, loop: int, output: float) -> None:
        """Set the manual heater/output demand percentage."""
        self._normalise_loop(loop)
        if not 0.0 <= float(output) <= 100.0:
            raise ValueError("Manual heater output must be between 0 and 100 percent.")
        self.write_scaled(_ADDRESS_MANUAL_OUTPUT, float(output), self._output_decimal_places)

    def set_heater_range(self, loop: int, range_: int) -> None:
        """Eurotherm controllers do not expose a heater-range register."""
        self._normalise_loop(loop)
        raise NotImplementedError(
            f"{type(self).__name__} does not support a heater-range setting."
        )

    def get_pid(self, loop: int) -> PIDParameters:
        """Return the configured PID parameters."""
        self._normalise_loop(loop)
        return PIDParameters(
            p=self.read_scaled(_ADDRESS_PROPORTIONAL_BAND, self._pid_decimal_places),
            i=self.read_scaled(_ADDRESS_INTEGRAL_TIME, self._pid_decimal_places),
            d=self.read_scaled(_ADDRESS_DERIVATIVE_TIME, self._pid_decimal_places),
        )

    def set_pid(self, loop: int, p: float, i: float, d: float) -> None:
        """Set the configured PID parameters."""
        self._normalise_loop(loop)
        self.write_scaled(_ADDRESS_PROPORTIONAL_BAND, float(p), self._pid_decimal_places)
        self.write_scaled(_ADDRESS_INTEGRAL_TIME, float(i), self._pid_decimal_places)
        self.write_scaled(_ADDRESS_DERIVATIVE_TIME, float(d), self._pid_decimal_places)

    def get_ramp_rate(self, loop: int) -> float:
        """Return the setpoint-rate limit in K/min."""
        self._normalise_loop(loop)
        rate = self.read_scaled(_ADDRESS_SETPOINT_RATE, self._ramp_decimal_places)
        if rate > 0:
            self._cached_ramp_rate = rate
        return rate

    def set_ramp_rate(self, loop: int, rate: float) -> None:
        """Set the setpoint-rate limit in K/min."""
        self._normalise_loop(loop)
        if float(rate) < 0:
            raise ValueError("Ramp rate must be non-negative.")
        if float(rate) > 0:
            self._cached_ramp_rate = float(rate)
        self.write_scaled(_ADDRESS_SETPOINT_RATE, float(rate), self._ramp_decimal_places)

    def get_ramp_enabled(self, loop: int) -> bool:
        """Return whether setpoint ramping is enabled."""
        self._normalise_loop(loop)
        return self.get_ramp_rate(loop) > 0.0

    def set_ramp_enabled(self, loop: int, enabled: bool) -> None:
        """Enable or disable setpoint ramping."""
        self._normalise_loop(loop)
        if enabled:
            current_rate = self.get_ramp_rate(loop)
            if current_rate <= 0:
                self.set_ramp_rate(loop, self._cached_ramp_rate or self._default_ramp_rate)
            return
        self.set_ramp_rate(loop, 0.0)

    def get_capabilities(self) -> ControllerCapabilities:
        """Return the static capability descriptor."""
        return self._CAPABILITIES

    def get_controller_status(self) -> TemperatureStatus:
        """Return a status snapshot including decoded fault state."""
        status = super().get_controller_status()
        problems = []
        status_bits = self.get_status()
        if bool(status_bits["sensor_break"]):
            problems.append("sensor break")
        if bool(status_bits["loop_break"]):
            problems.append("loop break")
        if bool(status_bits["pv_overrange"]):
            problems.append("PV over-range")
        if bool(status_bits["remote_setpoint_fail"]):
            problems.append("remote setpoint fail")
        loop_break_address = self._loop_break_status_address()
        if loop_break_address is not None and self.read_raw(loop_break_address) != 0:
            if "loop break" not in problems:
                problems.append("loop break")
        status.error_state = ", ".join(problems) if problems else None
        return status

    def start_autotune(self, loop: int, mode: int = 0) -> None:
        """Start the controller autotune function."""
        del mode
        self._normalise_loop(loop)
        self.write_raw(_ADDRESS_AUTOTUNE_ENABLE, 1)

    def stop_autotune(self, loop: int = 1) -> None:
        """Stop the controller autotune function."""
        self._normalise_loop(loop)
        self.write_raw(_ADDRESS_AUTOTUNE_ENABLE, 0)

    def get_autotune_status(self, loop: int) -> str:
        """Return controller autotune state as a string."""
        self._normalise_loop(loop)
        if bool(self.get_status()["autotune_active"]):
            return "running"
        if self._HAS_INSTRUMENT_STATUS_WORD:
            control_status = self.read_raw(_ADDRESS_CONTROL_STATUS) & 0xFFFF
            if self._status_bit(control_status, _CONTROL_STATUS_AUTOTUNE_COMPLETE_BIT):
                return "complete"
        return "idle"

    def set_sp1(self, value: float) -> None:
        """Write retained SP1 in Kelvin."""
        self._write_absolute_temperature_register(_ADDRESS_SP1, value)

    def set_sp2(self, value: float) -> None:
        """Write retained SP2 in Kelvin."""
        self._write_absolute_temperature_register(_ADDRESS_SP2, value)

    def select_sp(self, index: int) -> None:
        """Select SP1 or SP2."""
        if index not in (1, 2):
            raise ValueError("Setpoint index must be 1 or 2.")
        self.write_raw(_ADDRESS_SETPOINT_SELECT, 0 if index == 1 else 1)

    def enable_remote_setpoint(self) -> None:
        """Select the remote/comms setpoint source when needed."""
        if self._remote_setpoint_address() is None:
            raise NotImplementedError(
                f"{type(self).__name__} does not provide a remote-setpoint register."
            )
        if self._remote_setpoint_selected is None:
            self._remote_setpoint_selected = (
                self.read_raw(_ADDRESS_LOCAL_REMOTE_SELECT) == _REMOTE_SETPOINT_SELECTION
            )
        if self._remote_setpoint_selected:
            return
        self.write_raw(_ADDRESS_LOCAL_REMOTE_SELECT, _REMOTE_SETPOINT_SELECTION)
        self._remote_setpoint_selected = True

    def write_remote_setpoint(self, value: float) -> None:
        """Write the volatile remote/comms setpoint in Kelvin."""
        remote_address = self._remote_setpoint_address()
        if remote_address is None:
            raise NotImplementedError(
                f"{type(self).__name__} does not provide a remote-setpoint register."
            )
        self._write_absolute_temperature_register(remote_address, value)

    def set_auto(self) -> None:
        """Switch to automatic closed-loop control."""
        self.write_raw(_ADDRESS_INSTRUMENT_MODE, 0)
        self.write_raw(_ADDRESS_AUTO_MANUAL_MODE, 0)

    def set_manual(self, output_percent: float) -> None:
        """Switch to manual/open-loop control at *output_percent*."""
        self.set_standby(False)
        self.set_manual_heater_output(1, output_percent)
        self.write_raw(_ADDRESS_AUTO_MANUAL_MODE, 1)

    def set_standby(self, enabled: bool) -> None:
        """Enable or disable standby mode."""
        self.write_raw(_ADDRESS_INSTRUMENT_MODE, 1 if enabled else 0)

    def configure_pid(
        self,
        pb: float,
        ti: float,
        td: float,
        *,
        reset: float | None = None,
        r2g: float | None = None,
        cb_low: float | None = None,
        cb_high: float | None = None,
    ) -> None:
        """Configure PID and selected auxiliary tuning terms."""
        self.set_pid(1, pb, ti, td)
        if reset is not None:
            self.write_scaled(_ADDRESS_MANUAL_RESET, reset, self._pid_decimal_places)
        if r2g is not None:
            self.write_scaled(_ADDRESS_RELATIVE_COOL_GAIN, r2g, self._pid_decimal_places)
        if cb_low is not None:
            self.write_scaled(_ADDRESS_CUTBACK_LOW, cb_low, self._pid_decimal_places)
        if cb_high is not None:
            self.write_scaled(_ADDRESS_CUTBACK_HIGH, cb_high, self._pid_decimal_places)

    def set_control_type(self, *, heat: str, cool: str) -> None:
        """Set the configured heat/cool control algorithms."""
        heat_code = _HEAT_CONTROL_TYPES.get(heat.strip().lower())
        cool_code = _COOL_CONTROL_TYPES.get(cool.strip().lower())
        if heat_code is None:
            raise ValueError(f"Unsupported heat control type {heat!r}.")
        if cool_code is None:
            raise ValueError(f"Unsupported cool control type {cool!r}.")
        self.write_raw(_ADDRESS_HEAT_CONTROL_TYPE, heat_code)
        self.write_raw(_ADDRESS_COOL_CONTROL_TYPE, cool_code)

    def acknowledge_alarms(self) -> None:
        """Acknowledge controller alarms."""
        self.write_raw(_ADDRESS_ACKNOWLEDGE_ALARMS, 1)

    def get_alarms(self) -> dict[int, int]:
        """Return raw alarm-status register values."""
        return {
            alarm: self.read_raw(address) for alarm, address in self._ALARM_STATUS_ADDRESSES.items()
        }

    def timer_run(self) -> None:
        """Run the timer/programmer."""
        self.write_raw(_ADDRESS_TIMER_STATUS, 1)

    def timer_hold(self) -> None:
        """Hold the timer/programmer."""
        self.write_raw(_ADDRESS_TIMER_STATUS, 2)

    def timer_reset(self) -> None:
        """Reset the timer/programmer."""
        self.write_raw(_ADDRESS_TIMER_STATUS, 0)

    def _read_absolute_temperature_register(self, address: int) -> float:
        """Read an absolute temperature register and convert to Kelvin."""
        raw_value = self.read_scaled(address, self._decimal_places)
        return self._temperature_scale.to_kelvin(raw_value)

    def _write_absolute_temperature_register(self, address: int, value_kelvin: float) -> None:
        """Write a Kelvin temperature to an absolute-temperature register."""
        self.write_scaled(
            address,
            self._temperature_scale.from_kelvin(float(value_kelvin)),
            self._decimal_places,
        )

    def _transact(self, request: bytes, *, expected_length: int) -> bytes:
        """Exchange one Modbus RTU frame with the instrument."""
        with self._lock:
            response = self.transport.query(request, num_bytes=expected_length)
        if len(response) < 5:
            raise TimeoutError("Incomplete Modbus RTU response frame.")
        frame = self._validate_frame(response)
        if frame[1] & 0x80:
            code = frame[2]
            raise ValueError(
                f"Modbus exception response 0x{code:02X} for function 0x{frame[1] & 0x7F:02X}."
            )
        if len(frame) != expected_length:
            raise TimeoutError(
                f"Incomplete Modbus RTU response frame: expected {expected_length} bytes, "
                f"received {len(frame)}."
            )
        return frame

    def _write_single_register(self, address: int, value: int) -> None:
        """Write one signed 16-bit register and verify the echo."""
        raw_value = self._encode_signed_register(value)
        payload = bytes(
            (
                self._unit_id,
                _WRITE_SINGLE_REGISTER,
                (int(address) >> 8) & 0xFF,
                int(address) & 0xFF,
            )
        ) + raw_value
        response = self._transact(_append_crc(payload), expected_length=8)
        if response[:-2] != payload:
            raise ValueError("Unexpected Modbus write echo from instrument.")

    def _validate_frame(self, frame: bytes) -> bytes:
        """Validate address and CRC on *frame*."""
        if frame[0] != self._unit_id:
            raise ValueError(
                f"Unexpected Modbus unit id {frame[0]}; expected {self._unit_id}."
            )
        expected_crc = _crc16_modbus(frame[:-2])
        received_crc = unpack("<H", frame[-2:])[0]
        if expected_crc != received_crc:
            raise ValueError("Invalid Modbus RTU CRC in response frame.")
        return frame

    @staticmethod
    def _encode_signed_register(value: int | float) -> bytes:
        """Encode *value* as one signed 16-bit Modbus register."""
        integer = int(value)
        if not -32768 <= integer <= 32767:
            raise ValueError("Register value must fit in a signed 16-bit integer.")
        return pack(">h", integer)

    @staticmethod
    def _status_bit(status_word: int, bit: int) -> bool:
        """Return ``True`` when *bit* is set in *status_word*."""
        return bool(status_word & (1 << bit))

    def _get_ramp_running_from_status(self, main_status_word: int) -> bool:
        """Return whether the controller reports an active ramp/program."""
        if self._STATUS_HAS_RAMP_RUNNING_BIT:
            return self._status_bit(main_status_word, _STATUS_RAMP_RUNNING_BIT)
        if self._HAS_INSTRUMENT_STATUS_WORD:
            instrument_status = self.read_raw(_ADDRESS_INSTRUMENT_STATUS) & 0xFFFF
            return self._status_bit(instrument_status, _INSTRUMENT_STATUS_RAMP_RUNNING_BIT)
        return False

    def _remote_setpoint_address(self) -> int | None:
        """Return the volatile remote/comms setpoint register."""
        return self._REMOTE_SETPOINT_ADDRESS

    def _sensor_break_status_address(self) -> int | None:
        """Return the sensor-break status register."""
        return _ADDRESS_SENSOR_BREAK_STATUS

    def _loop_break_status_address(self) -> int | None:
        """Return the loop-break status register, if defined."""
        return self._LOOP_BREAK_STATUS_ADDRESS

    @classmethod
    def _normalise_channel(cls, channel: str) -> str:
        """Validate the single supported sensor channel."""
        candidate = channel.strip().upper()
        if candidate != "PV":
            raise ValueError(f"{cls.__name__} only supports the 'PV' input channel.")
        return candidate

    @classmethod
    def _normalise_loop(cls, loop: int) -> int:
        """Validate the single supported loop number."""
        if int(loop) != 1:
            raise ValueError(f"{cls.__name__} only supports control loop 1.")
        return 1


class Eurotherm3200Series(_EurothermModbusTemperatureControllerBase):
    """Eurotherm 3200-series/32h8 Modbus RTU temperature controller."""

    _CAPABILITIES = ControllerCapabilities(
        num_inputs=1,
        num_loops=1,
        input_channels=("PV",),
        loop_numbers=(1,),
        has_ramp=True,
        has_pid=True,
        has_autotune=True,
        has_manual_heater_output=True,
    )
    _REMOTE_SETPOINT_ADDRESS = _ADDRESS_REMOTE_SETPOINT_2200
    _STATUS_HAS_REMOTE_FAIL_BIT = True
    _STATUS_HAS_RAMP_RUNNING_BIT = True
    _HAS_INSTRUMENT_STATUS_WORD = False

    def identify(self) -> str:
        """Return a descriptive identity string."""
        model = self._identify_model()
        if model is None:
            return f"Eurotherm 3200 Series Modbus RTU (unit {self._unit_id})"
        return f"Eurotherm {model} (3200 Series) Modbus RTU (unit {self._unit_id})"

    def identify_controller(self) -> dict[str, int | str | None]:
        """Return the decoded model information when register 122 is available."""
        try:
            identifier = self.read_raw(_ADDRESS_IDENTIFIER) & 0xFFFF
        except Exception:
            return {"model": None, "model_series": "3200", "identifier": None}
        return {
            "model": self._model_from_identifier(identifier),
            "model_series": "3200",
            "identifier": identifier,
        }

    @classmethod
    def _model_from_identifier(cls, identifier: int) -> str | None:
        """Decode a 3200-series model from register 122."""
        identifier_hex = f"{int(identifier) & 0xFFFF:04X}"
        if not identifier_hex.startswith(_EUROTHERM_3200_IDENTIFIER_PREFIX):
            return None
        return identifier_hex

    def _identify_model(self) -> str | None:
        """Return the specific 3200-series model if available."""
        try:
            identifier = self.read_raw(_ADDRESS_IDENTIFIER) & 0xFFFF
        except Exception:
            return None
        return self._model_from_identifier(identifier)


class Eurotherm2000Series(_EurothermModbusTemperatureControllerBase):
    """Eurotherm 2000-series Modbus RTU temperature controller."""

    _CAPABILITIES = ControllerCapabilities(
        num_inputs=1,
        num_loops=1,
        input_channels=("PV",),
        loop_numbers=(1,),
        has_ramp=True,
        has_pid=True,
        has_autotune=True,
        has_manual_heater_output=True,
    )
    _REMOTE_SETPOINT_ADDRESS = None
    _STATUS_HAS_REMOTE_FAIL_BIT = False
    _STATUS_HAS_RAMP_RUNNING_BIT = False
    _HAS_INSTRUMENT_STATUS_WORD = True

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol | None = None,
        *,
        model_series: str | None = None,
        allow_configuration: bool = False,
        configuration_reset_delay: float = 5.0,
        **kwargs: object,
    ) -> None:
        """Initialise the Eurotherm 2000-series driver.

        Keyword Parameters:
            model_series (str | None):
                Optional explicit model family, typically ``"2200"`` or
                ``"2400"``. When omitted the driver tries to infer it from the
                controller identifier register.
            allow_configuration (bool):
                Whether configuration-mode entry/exit helpers are permitted.
            configuration_reset_delay (float):
                Seconds to wait after exiting configuration mode.
        """
        super().__init__(transport=transport, protocol=protocol, **kwargs)
        self._allow_configuration = bool(allow_configuration)
        self._configuration_reset_delay = float(configuration_reset_delay)
        self._model_series = self._normalise_model_series(model_series) if model_series else None

    def identify(self) -> str:
        """Return a descriptive identity string from version and identifier registers."""
        info = self.identify_controller()
        return (
            f"Eurotherm {info['model']} ({info['model_series']} Series) Modbus RTU "
            f"(unit {self._unit_id}, id=0x{info['identifier']:04X}, version=0x{info['version']:04X})"
        )

    def identify_controller(self) -> dict[str, int | str]:
        """Read controller identification registers and classify the model family."""
        version = self.read_raw(_ADDRESS_VERSION) & 0xFFFF
        identifier = self.read_raw(_ADDRESS_IDENTIFIER) & 0xFFFF
        model_series = self._resolve_model_series(identifier)
        model = self._resolve_model(identifier)
        return {
            "model": model,
            "model_series": model_series,
            "version": version,
            "identifier": identifier,
        }

    def enter_configuration(self) -> None:
        """Enter configuration mode if explicitly permitted."""
        if not self._allow_configuration:
            raise PermissionError(
                "Configuration mode is disabled. Pass allow_configuration=True to enable it."
            )
        self.write_raw(_ADDRESS_INSTRUMENT_MODE, 2)

    def exit_configuration(self) -> None:
        """Leave configuration mode and wait for the controller to restart."""
        if not self._allow_configuration:
            raise PermissionError(
                "Configuration mode is disabled. Pass allow_configuration=True to enable it."
            )
        self.write_raw(_ADDRESS_INSTRUMENT_MODE, 0)
        time.sleep(self._configuration_reset_delay)
        self._remote_setpoint_selected = None

    def _remote_setpoint_address(self) -> int | None:
        """Return the model-dependent remote/comms setpoint register."""
        model_series = self._resolve_model_series()
        if model_series == "2400":
            return _ADDRESS_REMOTE_SETPOINT_2400
        return _ADDRESS_REMOTE_SETPOINT_2200

    def _loop_break_status_address(self) -> int | None:
        """Return the loop-break status register when known."""
        if self._resolve_model_series() == "2400":
            return _ADDRESS_LOOP_BREAK_STATUS
        return None

    def _resolve_model_series(self, identifier: int | None = None) -> str:
        """Return the controller model family, inferring it when needed."""
        if self._model_series is not None:
            return self._model_series
        inferred = self._infer_model_series_from_identifier(
            (self.read_raw(_ADDRESS_IDENTIFIER) if identifier is None else identifier) & 0xFFFF
        )
        self._model_series = inferred
        return self._model_series

    def _resolve_model(self, identifier: int | None = None) -> str:
        """Return the concrete controller model when it is known."""
        identifier_value = (self.read_raw(_ADDRESS_IDENTIFIER) if identifier is None else identifier) & 0xFFFF
        return _EUROTHERM_2000_IDENTIFIER_MODELS.get(
            identifier_value,
            f"{self._resolve_model_series(identifier_value)}xx",
        )

    @staticmethod
    def _normalise_model_series(model_series: str) -> str:
        """Return a normalised 2000-series model family token."""
        digits = "".join(character for character in model_series if character.isdigit())
        if digits not in {"2200", "2400"}:
            raise ValueError("model_series must resolve to '2200' or '2400'.")
        return digits

    @staticmethod
    def _infer_model_series_from_identifier(identifier: int) -> str:
        """Infer a 2200/2400 family from the controller identifier register."""
        exact_model = _EUROTHERM_2000_IDENTIFIER_MODELS.get(int(identifier) & 0xFFFF)
        if exact_model is not None:
            return "2400" if exact_model.startswith("24") else "2200"
        identifier_hex = f"{int(identifier) & 0xFFFF:04X}"
        if identifier_hex.startswith("24"):
            return "2400"
        if identifier_hex.startswith("22"):
            return "2200"
        for shift in (12, 8, 4, 0):
            nibble = (int(identifier) >> shift) & 0xF
            if nibble == 0x4:
                return "2400"
            if nibble == 0x2:
                return "2200"
        return "2400"


Eurotherm32h8 = Eurotherm3200Series
