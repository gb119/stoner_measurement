"""Lakeshore temperature controller drivers."""

from __future__ import annotations

from typing import ClassVar

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

_MODE_TO_CODE = {
    ControlMode.OFF: 0,
    ControlMode.CLOSED_LOOP: 1,
    ControlMode.ZONE: 2,
    ControlMode.OPEN_LOOP: 3,
    ControlMode.MONITOR: 4,
}
_CODE_TO_MODE = {value: key for key, value in _MODE_TO_CODE.items()}


class _LakeshoreTemperatureControllerBase(TemperatureController):
    """Common command implementation for Lakeshore temperature controllers."""

    _CAPABILITIES: ClassVar[ControllerCapabilities]
    _MODEL: ClassVar[str]

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the Lakeshore temperature controller driver."""
        super().__init__(
            transport=transport,
            protocol=protocol if protocol is not None else LakeshoreProtocol(),
        )

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
            minimum_length=6,
        )
        return ZoneEntry(
            upper_bound=values[0],
            p=values[1],
            i=values[2],
            d=values[3],
            heater_output=values[4],
            heater_range=int(values[5]),
            ramp_rate=0.0,
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
            >>> zone = ZoneEntry(upper_bound=100.0, p=50.0, i=10.0, d=0.0, ramp_rate=0.0, heater_range=1, heater_output=0.0)
            >>> # ctrl.set_zone(1, 1, zone)  # requires live instrument
        """
        self.write(
            f"ZONE {self._normalise_loop(loop)},{zone_index},"
            f"{entry.upper_bound},{entry.p},{entry.i},{entry.d},"
            f"{entry.heater_output},{int(entry.heater_range)}"
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
                compensation = settings.compensation if settings.compensation is not None else bool(int(current_vals[3]))
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
                filter_enabled = settings.filter_enabled if settings.filter_enabled is not None else bool(int(current_f[0]))
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
    """Concrete driver for the Lakeshore 336 temperature controller."""

    _MODEL = "MODEL336"
    _LS336_RANGES = ("Off", "Low", "Medium", "High")
    _CAPABILITIES = ControllerCapabilities(
        num_inputs=4,
        num_loops=2,
        input_channels=("A", "B", "C", "D"),
        loop_numbers=(1, 2),
        has_ramp=True,
        has_pid=True,
        has_zone=True,
        has_input_settings=True,
        heater_range_labels={1: _LS336_RANGES, 2: _LS336_RANGES},
    )


class Lakeshore340(_LakeshoreTemperatureControllerBase):
    """Concrete driver for the Lakeshore 340 temperature controller."""

    _MODEL = "MODEL340"
    _LS340_LOOP1_RANGES = ("Off", "0.5 W", "5 W", "50 W", "500 W", "5 kW")
    _LS340_LOOP2_RANGES = ("Off", "On")
    _CAPABILITIES = ControllerCapabilities(
        num_inputs=2,
        num_loops=2,
        input_channels=("A", "B"),
        loop_numbers=(1, 2),
        has_ramp=True,
        has_pid=True,
        has_zone=True,
        has_input_settings=True,
        heater_range_labels={1: _LS340_LOOP1_RANGES, 2: _LS340_LOOP2_RANGES},
    )
