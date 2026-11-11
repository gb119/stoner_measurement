"""Lakeshore temperature controller drivers."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from typing import ClassVar

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.lakeshore import LakeshoreProtocol
from stoner_measurement.instruments.temperature_controller import (
    ControllerCapabilities,
    ControlMode,
    InputChannelSettings,
    PIDParameters,
    SensorStatus,
    TemperatureController,
    ZoneEntry,
)
from stoner_measurement.instruments.transport.base import BaseTransport

_STATUS_OVERRANGE_BIT = 0x20
_STATUS_UNDERRANGE_BIT = 0x10
_STATUS_FAULT_BIT = 0x80

# 335/336 OUTMODE control mode codes (0-based, 0=Off)
_MODE_TO_CODE = {
    ControlMode.OFF: 0,
    ControlMode.CLOSED_LOOP: 1,
    ControlMode.ZONE: 2,
    ControlMode.OPEN_LOOP: 3,
    ControlMode.MONITOR: 4,
}
_CODE_TO_MODE = {value: key for key, value in _MODE_TO_CODE.items()}

# 340 CMODE control mode codes (1-based, no Off mode)
_LS340_MODE_TO_CODE = {
    ControlMode.CLOSED_LOOP: 1,
    ControlMode.ZONE: 2,
    ControlMode.OPEN_LOOP: 3,
}
_LS340_CODE_TO_MODE = {value: key for key, value in _LS340_MODE_TO_CODE.items()}


class _LakeshoreTemperatureControllerBase(TemperatureController):
    """Common command implementation for Lakeshore temperature controllers."""

    _CAPABILITIES: ClassVar[ControllerCapabilities]
    _MODEL: ClassVar[str]

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the Lakeshore temperature controller driver."""
        transport._use_mav=False
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else LakeshoreProtocol(),
        )
        self._calibration_curve_names_cache: dict[int, str] | None = None

    def identify(self) -> str:
        """Return the instrument identity string."""
        return self.query("*IDN?")

    def get_model(self) -> str:
        """Return the model token from ``*IDN?``."""
        tokens = [token.strip() for token in self.identify().split(",")]
        return tokens[1] if len(tokens) > 1 else self._MODEL

    def get_firmware_version(self) -> str:
        """Return the firmware token from ``*IDN?``."""
        tokens = [token.strip() for token in self.identify().split(",")]
        return tokens[3] if len(tokens) > 3 else ""

    def get_temperature(self, channel: str) -> float:
        """Return channel temperature in Kelvin."""
        return self._query_float(f"KRDG? {self._normalise_channel(channel)}")

    def get_sensor_status(self, channel: str) -> SensorStatus:
        """Return Lakeshore sensor-status flags mapped to :class:`SensorStatus`."""
        raw = self.query(f"RDGST? {self._normalise_channel(channel)}")
        status_code = self._parse_int_token(raw)
        if status_code == 0:
            return SensorStatus.OK
        if status_code & _STATUS_FAULT_BIT:
            return SensorStatus.FAULT
        if status_code & _STATUS_OVERRANGE_BIT:
            return SensorStatus.OVERRANGE
        if status_code & _STATUS_UNDERRANGE_BIT:
            return SensorStatus.UNDERRANGE
        return SensorStatus.INVALID

    def get_input_channel(self, loop: int) -> str:
        """Return the channel assigned to *loop*."""
        _, input_index, _ = self._get_outmode(loop)
        return self._channel_from_index(input_index)

    def set_input_channel(self, loop: int, channel: str) -> None:
        """Assign a channel to *loop* while preserving mode flags."""
        mode, _, powerup_enable = self._get_outmode(loop)
        self.write(
            f"OUTMODE {self._normalise_loop(loop)},{mode},{self._channel_to_index(channel)},{powerup_enable}"
        )

    def get_setpoint(self, loop: int) -> float:
        """Return setpoint in Kelvin."""
        return self._query_float(f"SETP? {self._normalise_loop(loop)}")

    def set_setpoint(self, loop: int, value: float) -> None:
        """Set temperature setpoint in Kelvin."""
        self.write(f"SETP {self._normalise_loop(loop)},{value}")

    def get_loop_mode(self, loop: int) -> ControlMode:
        """Return the control mode for *loop*."""
        mode_code, _, _ = self._get_outmode(loop)
        return _CODE_TO_MODE.get(mode_code, ControlMode.CLOSED_LOOP)

    def set_loop_mode(self, loop: int, mode: ControlMode) -> None:
        """Set the control mode for *loop*."""
        _, input_index, powerup_enable = self._get_outmode(loop)
        mode_code = _MODE_TO_CODE.get(mode, _MODE_TO_CODE[ControlMode.CLOSED_LOOP])
        self.write(f"OUTMODE {self._normalise_loop(loop)},{mode_code},{input_index},{powerup_enable}")

    def get_heater_output(self, loop: int) -> float:
        """Return heater output percentage for *loop*."""
        return self._query_float(f"HTR? {self._normalise_loop(loop)}")

    def get_heater_range(self, loop: int) -> int:
        """Return the current heater range index for *loop*."""
        return self._parse_int_token(self.query(f"RANGE? {self._normalise_loop(loop)}"))

    def set_heater_range(self, loop: int, range_: int) -> None:
        """Set heater range index for *loop*."""
        self.write(f"RANGE {self._normalise_loop(loop)},{int(range_)}")

    def get_pid(self, loop: int) -> PIDParameters:
        """Return PID parameters for *loop*."""
        values = self._parse_csv_floats(self.query(f"PID? {self._normalise_loop(loop)}"), minimum_length=3)
        return PIDParameters(p=values[0], i=values[1], d=values[2])

    def set_pid(self, loop: int, p: float, i: float, d: float) -> None:
        """Set PID parameters for *loop*."""
        self.write(f"PID {self._normalise_loop(loop)},{p},{i},{d}")

    def get_ramp_rate(self, loop: int) -> float:
        """Return ramp rate in Kelvin per minute for *loop*."""
        _, rate = self._get_ramp(loop)
        return rate

    def set_ramp_rate(self, loop: int, rate: float) -> None:
        """Set ramp rate in Kelvin per minute for *loop*."""
        enabled, _ = self._get_ramp(loop)
        self.write(f"RAMP {self._normalise_loop(loop)},{int(enabled)},{rate}")

    def get_ramp_enabled(self, loop: int) -> bool:
        """Return whether ramping is enabled for *loop*."""
        enabled, _ = self._get_ramp(loop)
        return enabled

    def set_ramp_enabled(self, loop: int, enabled: bool) -> None:
        """Enable or disable ramping for *loop*."""
        _, rate = self._get_ramp(loop)
        self.write(f"RAMP {self._normalise_loop(loop)},{int(enabled)},{rate}")

    def get_capabilities(self) -> ControllerCapabilities:
        """Return static driver capabilities."""
        return self._CAPABILITIES

    def get_calibration_curve_names(self) -> dict[int, str]:
        """Return calibration-curve names reported by the controller.

        On first call this queries ``CRVHDR?`` for curve numbers 1–60 and
        extracts the human-readable curve name from each response until the
        controller reports an unsupported curve. The discovered mapping is
        cached and reused on subsequent calls.

        Returns:
            (dict[int, str]):
                Mapping from curve number to curve name.
        """
        if self._calibration_curve_names_cache is not None:
            return self._calibration_curve_names_cache

        names: dict[int, str] = {}
        for curve_number in range(1, 61):
            try:
                response = self.query(f"CRVHDR? {curve_number}")
            except Exception:
                break
            name = self._parse_curve_header_name(response)
            if name:
                names[curve_number] = name
        self._calibration_curve_names_cache = names
        return self._calibration_curve_names_cache

    def get_num_zones(self, loop: int) -> int:
        """Return the number of zone-table entries for *loop*.

        Lakeshore controllers support exactly 10 zones per output loop.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (int):
                Always 10 for Lakeshore controllers.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.lakeshore import Lakeshore336
            >>> ctrl = Lakeshore336(transport=NullTransport())
            >>> ctrl.get_num_zones(1)
            10
        """
        self._normalise_loop(loop)
        return 10

    def get_zone(self, loop: int, zone_index: int) -> ZoneEntry:
        """Return zone-table entry *zone_index* for output *loop*.

        Sends the ``ZONE? <loop>,<zone>`` query and parses the response.

        Args:
            loop (int):
                Control loop number (1-based).
            zone_index (int):
                Zone entry index (1-based, 1–10).

        Returns:
            (ZoneEntry):
                Zone parameters read from the instrument.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.lakeshore import Lakeshore336
            >>> ctrl = Lakeshore336(transport=NullTransport())
            >>> # ctrl.get_zone(1, 1)  # requires live instrument
        """
        values = self._parse_csv_floats(
            self.query(f"ZONE? {self._normalise_loop(loop)},{zone_index}"),
            minimum_length=8,
        )
        return ZoneEntry(
            upper_bound=values[0],
            p=values[1],
            i=values[2],
            d=values[3],
            heater_output=values[4],
            heater_range=int(values[5]),
            input_channel=int(values[6]),
            ramp_rate=values[7],
        )

    def set_zone(self, loop: int, zone_index: int, entry: ZoneEntry) -> None:
        """Write zone-table entry *zone_index* for output *loop*.

        Sends the ``ZONE <loop>,<zone>,<upper>,<P>,<I>,<D>,<mout>,<range>``
        command.

        Args:
            loop (int):
                Control loop number (1-based).
            zone_index (int):
                Zone entry index (1-based, 1–10).
            entry (ZoneEntry):
                Zone parameters to write.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.lakeshore import Lakeshore336
            >>> from stoner_measurement.instruments.temperature_controller import ZoneEntry
            >>> ctrl = Lakeshore336(transport=NullTransport())
            >>> zone = ZoneEntry(
            ...     upper_bound=100.0, p=50.0, i=10.0, d=0.0, ramp_rate=0.0, heater_range=1, heater_output=0.0
            ... )
            >>> # ctrl.set_zone(1, 1, zone)  # requires live instrument
        """
        self.write(
            f"ZONE {self._normalise_loop(loop)},{zone_index},"
            f"{entry.upper_bound},{entry.p},{entry.i},{entry.d},"
            f"{entry.heater_output},{int(entry.heater_range)},"
            f"{int(entry.input_channel)},{entry.ramp_rate}"
        )

    def get_input_channel_settings(self, channel: str) -> InputChannelSettings:
        """Return sensor-input configuration for *channel*.

        Reads sensor type / range (``INTYPE?``), digital filter (``FILTER?``),
        and curve assignment (``INCRV?``) in three separate queries.

        Args:
            channel (str):
                Sensor channel identifier (e.g. ``"A"``).

        Returns:
            (InputChannelSettings):
                Current configuration of the input channel.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.lakeshore import Lakeshore336
            >>> ctrl = Lakeshore336(transport=NullTransport())
            >>> # ctrl.get_input_channel_settings("A")  # requires live instrument
        """
        ch = self._normalise_channel(channel)

        # INTYPE? returns: <type>,<autorange>,<range>,<compensation>,<units>
        intype_vals = self._parse_csv_floats(self.query(f"INTYPE? {ch}"), minimum_length=5)
        sensor_type = int(intype_vals[0])
        autorange = bool(int(intype_vals[1]))
        range_ = int(intype_vals[2])
        compensation = bool(int(intype_vals[3]))
        units = int(intype_vals[4])

        # FILTER? returns: <on/off>,<settle_time>,<window>
        filter_vals = self._parse_csv_floats(self.query(f"FILTER? {ch}"), minimum_length=3)
        filter_enabled = bool(int(filter_vals[0]))
        filter_points = int(filter_vals[1])
        filter_window = filter_vals[2]

        # INCRV? returns the calibration curve number
        curve_number = self._parse_int_token(self.query(f"INCRV? {ch}"))

        return InputChannelSettings(
            sensor_type=sensor_type,
            autorange=autorange,
            range_=range_,
            compensation=compensation,
            units=units,
            filter_enabled=filter_enabled,
            filter_points=filter_points,
            filter_window=filter_window,
            curve_number=curve_number,
        )

    def set_input_channel_settings(self, channel: str, settings: InputChannelSettings) -> None:
        """Apply sensor-input configuration for *channel*.

        Issues ``INTYPE``, ``FILTER``, and ``INCRV`` commands as appropriate.
        Only fields that are not ``None`` in *settings* are applied; fields that
        are ``None`` are left unchanged on the instrument by first reading the
        current values.

        Args:
            channel (str):
                Sensor channel identifier (e.g. ``"A"``).
            settings (InputChannelSettings):
                Configuration to apply.  ``None`` fields are preserved from
                current hardware state.

        Examples:
            >>> from stoner_measurement.instruments.transport import NullTransport
            >>> from stoner_measurement.instruments.lakeshore import Lakeshore336
            >>> from stoner_measurement.instruments.temperature_controller import InputChannelSettings
            >>> ctrl = Lakeshore336(transport=NullTransport())
            >>> s = InputChannelSettings(filter_enabled=True, filter_points=10, filter_window=2.0)
            >>> # ctrl.set_input_channel_settings("A", s)  # requires live instrument
        """
        ch = self._normalise_channel(channel)

        # Determine if any INTYPE field is being changed.
        intype_fields = (
            settings.sensor_type,
            settings.autorange,
            settings.range_,
            settings.compensation,
            settings.units,
        )
        if any(f is not None for f in intype_fields):
            # Read current INTYPE values only for fields not explicitly set.
            if any(f is None for f in intype_fields):
                current_vals = self._parse_csv_floats(self.query(f"INTYPE? {ch}"), minimum_length=5)
                sensor_type = settings.sensor_type if settings.sensor_type is not None else int(current_vals[0])
                autorange = settings.autorange if settings.autorange is not None else bool(int(current_vals[1]))
                range_ = settings.range_ if settings.range_ is not None else int(current_vals[2])
                compensation = (
                    settings.compensation if settings.compensation is not None else bool(int(current_vals[3]))
                )
                units = settings.units if settings.units is not None else int(current_vals[4])
            else:
                # All INTYPE fields are explicitly provided; no hardware read needed.
                sensor_type = settings.sensor_type
                autorange = settings.autorange
                range_ = settings.range_
                compensation = settings.compensation
                units = settings.units
            self.write(
                f"INTYPE {ch},{sensor_type},{int(autorange)},{range_},{int(compensation)},{units}"
            )

        # Determine if any FILTER field is being changed.
        filter_fields = (settings.filter_enabled, settings.filter_points, settings.filter_window)
        if any(f is not None for f in filter_fields):
            # Read current FILTER values only for fields not explicitly set.
            if any(f is None for f in filter_fields):
                current_f = self._parse_csv_floats(self.query(f"FILTER? {ch}"), minimum_length=3)
                filter_enabled = (
                    settings.filter_enabled if settings.filter_enabled is not None else bool(int(current_f[0]))
                )
                filter_points = settings.filter_points if settings.filter_points is not None else int(current_f[1])
                filter_window = settings.filter_window if settings.filter_window is not None else current_f[2]
            else:
                # All FILTER fields are explicitly provided; no hardware read needed.
                filter_enabled = settings.filter_enabled
                filter_points = settings.filter_points
                filter_window = settings.filter_window
            self.write(f"FILTER {ch},{int(filter_enabled)},{filter_points},{filter_window}")

        # Apply curve assignment if specified.
        if settings.curve_number is not None:
            self.write(f"INCRV {ch},{settings.curve_number}")

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

    def _channel_to_index(self, channel: str) -> int:
        """Convert channel label to one-based channel index."""
        normalised = self._normalise_channel(channel)
        return self._CAPABILITIES.input_channels.index(normalised) + 1

    def _channel_from_index(self, index: int) -> str:
        """Convert one-based channel index to label."""
        channels = self._CAPABILITIES.input_channels
        if index < 1 or index > len(channels):
            return channels[0]
        return channels[index - 1]

    def _query_float(self, command: str) -> float:
        """Query and parse a single numeric token."""
        token = self.query(command).split(",", maxsplit=1)[0].strip()
        try:
            return float(token)
        except ValueError as exc:
            raise ValueError(f"Invalid numeric response for {command!r}: {token!r}.") from exc

    def _parse_int_token(self, response: str) -> int:
        """Parse the first integer token from a response string."""
        token = response.split(",", maxsplit=1)[0].strip()
        return int(float(token))

    def _parse_csv_floats(self, response: str, *, minimum_length: int) -> list[float]:
        """Parse a comma-separated float payload."""
        tokens = [item.strip() for item in response.split(",") if item.strip()]
        if len(tokens) < minimum_length:
            raise ValueError(f"Expected at least {minimum_length} values, got {response!r}.")
        return [float(token) for token in tokens]

    def _parse_curve_header_name(self, response: str) -> str:
        """Extract the curve-name field from a ``CRVHDR?`` response.

        Args:
            response (str):
                Raw ``CRVHDR?`` response string containing CSV fields with the
                curve name in the first field.
        """
        payload = response.strip()
        if not payload:
            return ""
        try:
            row = next(csv.reader([payload], skipinitialspace=True), [])
        except csv.Error:
            return ""
        if row:
            return row[0].strip()
        return ""

    def _get_outmode(self, loop: int) -> tuple[int, int, int]:
        """Return ``(mode, input_channel_index, powerup_enable)`` for *loop*."""
        values = self._parse_csv_floats(
            self.query(f"OUTMODE? {self._normalise_loop(loop)}"),
            minimum_length=3,
        )
        return int(values[0]), int(values[1]), int(values[2])

    def _get_ramp(self, loop: int) -> tuple[bool, float]:
        """Return ``(enabled, rate)`` for *loop*."""
        values = self._parse_csv_floats(
            self.query(f"RAMP? {self._normalise_loop(loop)}"),
            minimum_length=2,
        )
        return bool(int(values[0])), values[1]


class Lakeshore335(_LakeshoreTemperatureControllerBase):
    """Concrete driver for the Lakeshore 335 temperature controller."""

    _MODEL = "MODEL335"
    _LS335_RANGES = ("Off", "Low", "Medium", "High")
    _CAPABILITIES = ControllerCapabilities(
        num_inputs=2,
        num_loops=2,
        input_channels=("A", "B"),
        loop_numbers=(1, 2),
        has_ramp=True,
        has_pid=True,
        has_zone=True,
        has_input_settings=True,
        heater_range_labels={1: _LS335_RANGES, 2: _LS335_RANGES},
    )


class Lakeshore336(_LakeshoreTemperatureControllerBase):
    """Concrete driver for the Lakeshore 336 temperature controller.

    The 336 has four sensor inputs (A-D) and four independently controlled
    outputs (1-4).  Outputs 1 and 2 are warm heater outputs; outputs 3 and 4
    are analog/auxiliary warm outputs.  Zone control is fully supported via the
    ``ZONE`` / ``ZONE?`` commands.
    """

    _MODEL = "MODEL336"
    _LS336_WARM_RANGES = ("Off", "Low", "Medium", "High")
    _LS336_AUX_RANGES = ("Off", "On")
    _CAPABILITIES = ControllerCapabilities(
        num_inputs=4,
        num_loops=4,
        input_channels=("A", "B", "C", "D"),
        loop_numbers=(1, 2, 3, 4),
        has_ramp=True,
        has_pid=True,
        has_zone=True,
        has_input_settings=True,
        heater_range_labels={
            1: _LS336_WARM_RANGES,
            2: _LS336_WARM_RANGES,
            3: _LS336_AUX_RANGES,
            4: _LS336_AUX_RANGES,
        },
    )


@dataclass(frozen=True)
class Lakeshore340InputSettings(InputChannelSettings):
    """Native Model 340 input parameters, distinct from the 335 INTYPE layout.

    Attributes:
        sensor_units (int | None): Native sensor units: 1 volts, 2 ohms.
        coefficient (int | None): Sensor coefficient: 1 negative, 2 positive.
        excitation (int | None): Native excitation code, 0–12.
        input_enabled (bool | None): Whether hardware input readings are enabled.
        compensation_mode (int | None): Compensation: 0 off, 1 on, 2 paused.
    """

    sensor_units: int | None = None
    coefficient: int | None = None
    excitation: int | None = None
    input_enabled: bool | None = None
    compensation_mode: int | None = None


class _Lakeshore340Protocol(LakeshoreProtocol):
    """Use Model 340 status bits (manual section 9.1.3.1)."""

    status_error_mask = 0x10
    gpib_use_mav = False


class Lakeshore340(_LakeshoreTemperatureControllerBase):
    """Model 340 native control commands for the standard A/B input hardware.

    Loop 1 drives the heater; Loop 2 drives analog output 2, which must already
    be configured for loop control on the instrument. Only Loop 1 has heater
    ranges. Zone tables contain six values, unlike the 335's eight. Native
    input setup uses Lakeshore340InputSettings and a dedicated native editor.
    """

    _MODEL = "MODEL340"

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Select native status handling while permitting an explicit protocol."""
        super().__init__(transport, protocol if protocol is not None else _Lakeshore340Protocol())

    _CAPABILITIES = ControllerCapabilities(
        num_inputs=2, num_loops=2, input_channels=("A", "B"), loop_numbers=(1, 2),
        has_ramp=True, has_pid=True, has_zone=True, has_manual_heater_output=True,
        has_input_settings=True, input_settings_model="lakeshore340", heater_range_loops=(1,),
        setpoint_after_configuration=True,
        heater_range_labels={1: ("Off", "Range 1", "Range 2", "Range 3", "Range 4", "Range 5")},
        control_modes=(ControlMode.OFF, ControlMode.CLOSED_LOOP, ControlMode.ZONE, ControlMode.OPEN_LOOP),
    )

    def write(self, command: str, slow: int | None = None) -> None:
        """Write a native action and check the documented event-status register.

        Args:
            command (str): Model 340 action without a terminator.

        Keyword Parameters:
            slow (int | None): Optional transport delay in milliseconds.

        Raises:
            InstrumentError: Command, execution, device or query error is reported.
        """
        with self._lock:
            super().write(command, slow=slow)
            if self.auto_check_errors:
                status = int(self.query("*ESR?"))
                if not 0 <= status <= 255:
                    raise ValueError(f"Invalid Model 340 event status {status}.")
                if status & 60:
                    raise InstrumentError("Model 340 event register reports an error", command=command,
                                          error_code=status)

    @staticmethod
    def _bounded(value, low, high, name):
        """Validate a finite native numeric setting before writing."""
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Lakeshore340 {name} must be between {low} and {high}.")

    def _get_cset(self, loop: int) -> tuple[str, int, int, int]:
        """Read lettered input, setpoint units, enable and power-up flags."""
        fields = [item.strip() for item in self.query(f"CSET? {self._normalise_loop(loop)}").split(",")]
        if len(fields) != 4:
            raise ValueError(f"Invalid Model 340 CSET response: {fields!r}.")
        channel = self._normalise_channel(fields[0])
        units, enabled, powerup = (int(item) for item in fields[1:])
        if units not in (1, 2, 3) or enabled not in (0, 1) or powerup not in (0, 1):
            raise ValueError(f"Invalid Model 340 CSET response: {fields!r}.")
        return channel, units, enabled, powerup

    def get_input_channel(self, loop: int) -> str:
        """Return the hardware control sensor label from CSET?."""
        return self._get_cset(loop)[0]

    def set_input_channel(self, loop: int, channel: str) -> None:
        """Select an A/B sensor, preserving units and enable flags."""
        channel = self._normalise_channel(channel)
        with self._lock:
            _, units, enabled, powerup = self._get_cset(loop)
            self.write(f"CSET {loop},{channel},{units},{enabled},{powerup}")

    def get_setpoint(self, loop: int) -> float:
        """Return a kelvin setpoint, converting native Celsius when necessary."""
        with self._lock:
            units = self._get_cset(loop)[1]
            if units == 3:
                raise NotImplementedError("Model 340 sensor-unit setpoints cannot be converted to kelvin.")
            value = super().get_setpoint(loop)
            return value + 273.15 if units == 2 else value

    def set_setpoint(self, loop: int, value: float) -> None:
        """Write a kelvin target in the loop's configured temperature units."""
        self._bounded(value, 0, math.inf, "setpoint")
        with self._lock:
            units = self._get_cset(loop)[1]
            if units == 3:
                raise NotImplementedError("Select kelvin or Celsius setpoint units on the Model 340 first.")
            super().set_setpoint(loop, value - 273.15 if units == 2 else value)

    def get_loop_mode(self, loop: int) -> ControlMode:
        """Read loop enable from CSET and control algorithm from CMODE."""
        with self._lock:
            if not self._get_cset(loop)[2]:
                return ControlMode.OFF
            code = int(self.query(f"CMODE? {loop}"))
            if code not in _LS340_CODE_TO_MODE:
                raise ValueError(f"Unsupported Model 340 control mode {code}; autotune is not a generic mode.")
            return _LS340_CODE_TO_MODE[code]

    def set_loop_mode(self, loop: int, mode: ControlMode) -> None:
        """Enable the selected control algorithm, or disable the loop with CSET."""
        self._normalise_loop(loop)
        if mode not in self._CAPABILITIES.control_modes:
            raise ValueError(f"Unsupported Model 340 mode {mode!r}.")
        with self._lock:
            channel, units, _, powerup = self._get_cset(loop)
            if mode is not ControlMode.OFF:
                self.write(f"CMODE {loop},{_LS340_MODE_TO_CODE[mode]}")
            self.write(f"CSET {loop},{channel},{units},{int(mode is not ControlMode.OFF)},{powerup}")

    def get_heater_output(self, loop: int) -> float:
        """Read heater percent for Loop 1 or actual analog-output percent for Loop 2."""
        self._normalise_loop(loop)
        raw = self.query("HTR?" if loop == 1 else "AOUT? 2")
        return float(raw.strip().removesuffix("%"))

    def get_heater_range(self, loop: int) -> int:
        """Read the single heater range; Loop 2 has no heater ranges."""
        self._normalise_loop(loop)
        if loop != 1:
            raise NotImplementedError("Model 340 Loop 2 is an analog output without heater ranges.")
        value = int(self.query("RANGE?"))
        if value not in range(6):
            raise ValueError(f"Invalid Model 340 heater range {value}.")
        return value

    def set_heater_range(self, loop: int, range_: int) -> None:
        """Set Loop 1's heater range using RANGE without a loop argument."""
        self._normalise_loop(loop)
        if loop != 1:
            raise NotImplementedError("Model 340 Loop 2 is an analog output without heater ranges.")
        if not isinstance(range_, int) or range_ not in range(6):
            raise ValueError("Model 340 heater range must be an integer from 0 to 5.")
        self.write(f"RANGE {range_}")

    def set_manual_heater_output(self, loop: int, output: float) -> None:
        """Set native manual output in percent, including bipolar analog control."""
        self._normalise_loop(loop)
        self._bounded(output, -100, 100, "manual output")
        self.write(f"MOUT {loop},{output}")

    def set_pid(self, loop: int, p: float, i: float, d: float) -> None:
        """Set native gain/reset/rate values; I is reset, not an integral time."""
        for value, name in ((p, "P"), (i, "I"), (d, "D")):
            self._bounded(value, 0, 1000, name)
        super().set_pid(loop, p, i, d)

    def set_ramp_rate(self, loop: int, rate: float) -> None:
        """Set a 0–100 K/min ramp rate while retaining enable state atomically."""
        self._bounded(rate, 0, 100, "ramp rate")
        with self._lock:
            super().set_ramp_rate(loop, rate)

    def set_ramp_enabled(self, loop: int, enabled: bool) -> None:
        """Toggle ramping while retaining its rate under the shared lock."""
        with self._lock:
            super().set_ramp_enabled(loop, enabled)

    def _get_ramp(self, loop: int) -> tuple[bool, float]:
        """Reject malformed native ramp state before any read-modify-write action."""
        values = self._parse_csv_floats(self.query(f"RAMP? {self._normalise_loop(loop)}"), minimum_length=2)
        if len(values) != 2 or values[0] not in (0, 1):
            raise ValueError("Invalid Model 340 RAMP response.")
        self._bounded(values[1], 0, 100, "ramp readback")
        return bool(values[0]), values[1]

    def get_sensor_status(self, channel: str) -> SensorStatus:
        """Decode the Model 340 reading-status bit definitions."""
        status = int(self.query(f"RDGST? {self._normalise_channel(channel)}"))
        if not 0 <= status <= 255:
            raise ValueError(f"Invalid Model 340 reading status {status}.")
        if status & (1 | 2 | 64):
            return SensorStatus.INVALID
        if status & (32 | 128):
            return SensorStatus.OVERRANGE
        if status & 16:
            return SensorStatus.UNDERRANGE
        return SensorStatus.OK if status == 0 else SensorStatus.INVALID

    def get_zone(self, loop: int, zone_index: int) -> ZoneEntry:
        """Read a native six-field Model 340 zone entry."""
        self._validate_zone(loop, zone_index)
        values = self._parse_csv_floats(self.query(f"ZONE? {loop},{zone_index}"), minimum_length=6)
        if len(values) != 6:
            raise ValueError("Model 340 ZONE? must return six fields.")
        return ZoneEntry(values[0], values[1], values[2], values[3], 0.0, int(values[5]), values[4])

    def set_zone(self, loop: int, zone_index: int, entry: ZoneEntry) -> None:
        """Write the six native zone fields, excluding 335-only input and ramp fields."""
        self._validate_zone(loop, zone_index)
        if entry.ramp_rate or entry.input_channel:
            raise ValueError("Model 340 zones have no input-channel or ramp-rate fields.")
        self._bounded(entry.upper_bound, 0, math.inf, "zone upper temperature")
        for value, name in ((entry.p, "P"), (entry.i, "I"), (entry.d, "D")):
            self._bounded(value, 0, 1000, name)
        self._bounded(entry.heater_output, -100, 100, "zone manual output")
        if not isinstance(entry.heater_range, int) or entry.heater_range not in range(6):
            raise ValueError("Model 340 zone range must be 0–5.")
        self.write(f"ZONE {loop},{zone_index},{entry.upper_bound},{entry.p},{entry.i},{entry.d},"
                   f"{entry.heater_output},{entry.heater_range}")

    def _validate_zone(self, loop, index):
        """Validate zone addressing before I/O."""
        self._normalise_loop(loop)
        if not isinstance(index, int) or not 1 <= index <= 10:
            raise ValueError("Model 340 zone index must be 1–10.")

    def get_input_channel_settings(self, channel: str) -> Lakeshore340InputSettings:
        """Read the native INTYPE, INSET, FILTER and curve layouts."""
        ch = self._normalise_channel(channel)
        with self._lock:
            native = [int(item) for item in self.query(f"INTYPE? {ch}").split(",")]
            inset = [int(item) for item in self.query(f"INSET? {ch}").split(",")]
            filt = self._parse_csv_floats(self.query(f"FILTER? {ch}"), minimum_length=3)
            curve = int(self.query(f"INCRV? {ch}"))
        if len(native) != 5 or len(inset) != 2 or len(filt) != 3:
            raise ValueError("Malformed Model 340 input setup response.")
        return Lakeshore340InputSettings(
            sensor_type=native[0], sensor_units=native[1], coefficient=native[2],
            excitation=native[3], range_=native[4], input_enabled=bool(inset[0]),
            compensation_mode=inset[1], compensation=inset[1] == 1,
            filter_enabled=bool(filt[0]), filter_points=int(filt[1]), filter_window=filt[2],
            curve_number=curve,
        )

    def set_input_channel_settings(self, channel: str, settings: InputChannelSettings) -> None:
        """Write only supplied native fields; blanks preserve hardware defaults.

        Temperature-unit and autorange fields from the 335 schema are rejected.
        Supplying native overrides to INTYPE can select the hardware Special
        sensor type, as documented by the Model 340 manual.
        """
        ch = self._normalise_channel(channel)
        if settings.autorange is not None or settings.units is not None:
            raise ValueError("Model 340 INTYPE has sensor units, not autorange or temperature-unit fields.")
        native = [settings.sensor_type, getattr(settings, "sensor_units", None),
                  getattr(settings, "coefficient", None), getattr(settings, "excitation", None), settings.range_]
        limits = [(0, 12), (1, 2), (1, 2), (0, 12), (1, 13)]
        for value, (low, high) in zip(native, limits, strict=True):
            if value is not None and (not isinstance(value, int) or not low <= value <= high):
                raise ValueError("Invalid Model 340 INTYPE setting.")
        enabled = getattr(settings, "input_enabled", None)
        compensation = getattr(settings, "compensation_mode", None)
        if compensation is None and settings.compensation is not None:
            compensation = int(settings.compensation)
        if compensation is not None and compensation not in (0, 1, 2):
            raise ValueError("Invalid Model 340 compensation mode.")
        fields = [settings.filter_enabled, settings.filter_points, settings.filter_window]
        if settings.filter_points is not None:
            self._bounded(settings.filter_points, 2, 64, "filter points")
        if settings.filter_window is not None:
            self._bounded(settings.filter_window, 1, 10, "filter window")
        if settings.curve_number is not None and settings.curve_number not in range(61):
            raise ValueError("Model 340 curve number must be 0–60.")
        def csv_fields(values):
            return ",".join("" if v is None else str(int(v) if isinstance(v, bool) else v) for v in values)
        with self._lock:
            if any(v is not None for v in native):
                self.write(f"INTYPE {ch},{csv_fields(native)}")
            if enabled is not None or compensation is not None:
                self.write(f"INSET {ch},{csv_fields([enabled, compensation])}")
            if any(v is not None for v in fields):
                self.write(f"FILTER {ch},{csv_fields(fields)}")
            if settings.curve_number is not None:
                self.write(f"INCRV {ch},{settings.curve_number}")
