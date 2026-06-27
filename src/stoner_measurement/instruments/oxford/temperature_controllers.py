"""Oxford temperature controller drivers."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import ClassVar

import numpy as np
from scipy.interpolate import interp1d

from stoner_measurement.config_utils import deep_merge, load_yaml_mapping
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.oxford import OxfordProtocol
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.temperature_controller import (
    ControllerCapabilities,
    ControlMode,
    PIDParameters,
    SensorStatus,
    TemperatureController,
    ZoneEntry,
)
from stoner_measurement.instruments.transport.base import BaseTransport
from stoner_measurement.resources import bundled_resource_path, user_resource_file

logger = logging.getLogger(__name__)

_MODE_TO_CODE = {
    ControlMode.OFF: 0,
    ControlMode.CLOSED_LOOP: 1,
    ControlMode.OPEN_LOOP: 2,
    ControlMode.MONITOR: 3,
}
_CODE_TO_MODE = {value: key for key, value in _MODE_TO_CODE.items()}
_STATUS_TOKEN_REGEX = re.compile(r"([A-Za-z])(\d+)")
_ITC503_TEMPERATURE_RESOLUTION_K = 0.001


class _BoundedTemperatureMap:
    """Temperature map that falls back to identity outside its input range."""

    def __init__(self, x_values: Sequence[float], y_values: Sequence[float], *, kind: str) -> None:
        """Initialise a bounded interpolation from *x_values* to *y_values*."""
        x_array = np.asarray(x_values, dtype=float)
        y_array = np.asarray(y_values, dtype=float)
        order = np.argsort(x_array)
        self._x = x_array[order]
        self._interpolator = interp1d(self._x, y_array[order], kind=kind, assume_sorted=True)

    def __call__(self, value: float) -> float:
        """Return the interpolated value, or *value* outside the interpolation range."""
        candidate = float(value)
        if candidate < self._x[0] or candidate > self._x[-1]:
            return _round_itc503_temperature(candidate)
        mapped = float(self._interpolator(candidate))
        if np.isclose(mapped, candidate, rtol=1e-12, atol=1e-12):
            return _round_itc503_temperature(candidate)
        return _round_itc503_temperature(mapped)


def _identity_temperature_map(value: float) -> float:
    """Return *value* unchanged."""
    return _round_itc503_temperature(value)


def _round_itc503_temperature(value: float) -> float:
    """Round *value* to the ITC503's practical 1 mK temperature resolution."""
    return round(float(value), 3)


def _load_itc503_temperature_calibration_config() -> dict[str, object]:
    """Load merged bundled and user ITC503 instrument configuration."""
    bundled = load_yaml_mapping(
        bundled_resource_path("instruments", "oxford_itc503.yaml") or Path("__missing__")
    )
    machine = load_yaml_mapping(user_resource_file("instruments", "oxford_itc503.yaml"))
    return deep_merge(bundled, machine)


def _parse_temperature_lookup_table(config: Mapping[str, object]) -> tuple[list[float], list[float]]:
    """Return ``(true_temperatures, itc503_temperatures)`` from *config*."""
    calibration = config.get("temperature_calibration")
    if not isinstance(calibration, Mapping):
        return [], []
    raw_table = calibration.get("lookup_table")
    if not isinstance(raw_table, Sequence) or isinstance(raw_table, (str, bytes)):
        return [], []

    true_temperatures: list[float] = []
    itc503_temperatures: list[float] = []
    for row in raw_table:
        try:
            pair = _parse_temperature_lookup_row(row)
        except (TypeError, ValueError):
            pair = None
        if pair is None:
            logger.warning("Ignoring invalid ITC503 temperature calibration row: %r", row)
            return [], []
        true_temperature, itc503_temperature = pair
        true_temperatures.append(true_temperature)
        itc503_temperatures.append(itc503_temperature)
    return true_temperatures, itc503_temperatures


def _parse_temperature_lookup_row(row: object) -> tuple[float, float] | None:
    """Parse one lookup-table row as ``(true_temperature, itc503_temperature)``."""
    if isinstance(row, Mapping):
        true_value = row.get("true_temperature", row.get("true"))
        itc503_value = row.get("itc503_temperature", row.get("itc503", row.get("nominal")))
        if true_value is None or itc503_value is None:
            return None
        return float(true_value), float(itc503_value)
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes)) and len(row) == 2:
        return float(row[0]), float(row[1])
    return None


def _build_temperature_maps(
    true_temperatures: Sequence[float],
    itc503_temperatures: Sequence[float],
) -> tuple[Callable[[float], float], Callable[[float], float]]:
    """Build ``(forward, reverse)`` maps for ITC503 temperature calibration."""
    if len(true_temperatures) < 2:
        return _identity_temperature_map, _identity_temperature_map
    true_array = np.asarray(true_temperatures, dtype=float)
    itc503_array = np.asarray(itc503_temperatures, dtype=float)
    if not _has_unique_values(true_array) or not _has_unique_values(itc503_array):
        logger.warning("Ignoring ITC503 temperature calibration because lookup temperatures are not unique.")
        return _identity_temperature_map, _identity_temperature_map
    interpolation_kind = "cubic" if len(true_temperatures) >= 4 else "linear"
    return (
        _BoundedTemperatureMap(itc503_array, true_array, kind=interpolation_kind),
        _BoundedTemperatureMap(true_array, itc503_array, kind=interpolation_kind),
    )


def _has_unique_values(values: np.ndarray) -> bool:
    """Return ``True`` when *values* are finite and unique."""
    return bool(np.isfinite(values).all() and np.unique(values).size == values.size)


class _OxfordTemperatureControllerBase(TemperatureController):
    """Common command implementation for Oxford temperature controllers."""

    _CAPABILITIES: ClassVar[ControllerCapabilities]

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol) -> None:
        """Initialise the Oxford temperature controller driver."""
        super().__init__(transport=transport, protocol=protocol)
        self._loop_input: dict[int, str] = {
            loop: self._CAPABILITIES.input_channels[0] for loop in self._CAPABILITIES.loop_numbers
        }
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
            # Some Oxford replies include an echoed command letter where the
            # instrument uppercases the echo (e.g. ``Q10.0`` for query ``q``).
            # Accept a single leading alphabetic prefix when present.
            if len(token) > 1 and token[:1].isalpha():
                try:
                    return float(token[1:])
                except ValueError:
                    pass
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

    _EXPECTED_IDENTITY_TOKENS = ("ITC503",)
    _PID_TABLE_ROWS = 16
    _ITC503_HEATER_RANGES = ("Off", "On")
    _CAPABILITIES = ControllerCapabilities(
        num_inputs=3,
        num_loops=1,
        input_channels=("A", "B", "C"),
        loop_numbers=(1,),
        has_ramp=True,
        has_pid=True,
        has_zone=True,
        has_cryogen_control=True,
        has_gas_auto_mode=True,
        heater_range_labels={1: _ITC503_HEATER_RANGES},
    )

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol | None = None) -> None:
        """Initialise the ITC503 driver."""
        super().__init__(transport=transport, protocol=protocol if protocol is not None else OxfordProtocol())
        config = _load_itc503_temperature_calibration_config()
        true_temperatures, itc503_temperatures = _parse_temperature_lookup_table(config)
        self._itc503_to_true_temperature, self._true_to_itc503_temperature = _build_temperature_maps(
            true_temperatures,
            itc503_temperatures,
        )
        # The ITC503 does not expose a Chapter 9 register for a continuous
        # temperature ramp rate, so a software-side value is maintained for
        # API compatibility.
        self._ramp_rate: float = 0.0

    def identify(self) -> str:
        """Return identity string."""
        return self.query("V")

    def get_temperature(self, channel: str) -> float:
        """Return calibrated channel temperature in Kelvin."""
        return self._itc503_to_true_temperature(super().get_temperature(channel))

    def get_setpoint(self, loop: int) -> float:
        """Return calibrated setpoint in Kelvin."""
        return self._itc503_to_true_temperature(super().get_setpoint(loop))

    def set_setpoint(self, loop: int, value: float) -> None:
        """Set true setpoint in Kelvin, applying ITC503 calibration when available."""
        itc503_value = self._true_to_itc503_temperature(value)
        super().set_setpoint(loop, itc503_value)

    def get_heater_range(self, loop: int) -> int:
        """Return the current heater range index from the ``X`` status ``H`` token for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (int):
                Integer value of the ``H`` status token: 0 means the heater is off;
                higher values select progressively higher power ranges (e.g. 1, 2, …
                up to the instrument maximum). The exact number of ranges depends on
                the heater fitted to the instrument.
        """
        self._normalise_loop(loop)
        status_tokens = self._read_status_tokens()
        return int(status_tokens.get("H", 0))

    def get_gas_flow(self) -> float:
        """Return the gas-flow needle valve position as a percentage."""
        return self._query_float("R7")

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
        """Return ``True`` if gas flow is under automatic control.

        Returns:
            (bool):
                The last value set via :meth:`set_gas_auto`.  The ITC503
                does not expose a read-back command for the auto/manual mode
                flag, so the returned value reflects the last software-set
                state rather than a live hardware query.  The value defaults
                to ``False`` on first connection.
        """
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
        channel_code = {"A": 0, "B": 1, "C": 2}[channel]
        return f"C{channel_code}"

    def _setpoint_query(self, loop: int) -> str:
        """Return the ITC503 query command for reading the setpoint."""
        return "R0"

    def _setpoint_command(self, loop: int, value: float) -> str:
        """Return the ITC503 command that sets the setpoint to *value* K."""
        return f"T{value}"

    def get_loop_mode(self, loop: int) -> ControlMode:
        """Return control mode for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (ControlMode):
                Current control mode decoded from the ITC503 ``X`` status
                response ``A`` token.
        """
        self._normalise_loop(loop)
        status_tokens = self._read_status_tokens()
        return _CODE_TO_MODE.get(status_tokens.get("A", 1), ControlMode.CLOSED_LOOP)

    def _mode_command(self, loop: int, mode_code: int) -> str:
        """Return the ITC503 command that sets the control mode."""
        return f"A{mode_code}"

    def _heater_output_query(self, loop: int) -> str:
        """Return the ITC503 query command for reading heater output percentage."""
        return "R5"

    def _heater_range_command(self, loop: int, range_: int) -> str:
        """Return the ITC503 command that sets the heater range index."""
        return f"H{range_}"

    def set_pid(self, loop: int, p: float, i: float, d: float) -> None:
        """Set PID parameters for *loop*."""
        self._normalise_loop(loop)
        self.write(f"P{p}")
        self.write(f"I{i}")
        self.write(f"D{d}")

    def get_pid(self, loop: int) -> PIDParameters:
        """Return PID parameters for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (PIDParameters):
                PID parameters read via separate ITC503 ``R8``, ``R9``, and
                ``R10`` queries.
        """
        self._normalise_loop(loop)
        return PIDParameters(
            p=self._query_float("R8"),
            i=self._query_float("R9"),
            d=self._query_float("R10"),
        )

    def _pid_command(self, loop: int, p: float, i: float, d: float) -> str:
        """Return the legacy base-hook for PID command composition.

        This base hook is not supported for ITC503.

        ITC503 PID updates require three separate commands (``P``, ``I``,
        ``D``). This method intentionally raises because :meth:`set_pid`
        must be used for correct command sequencing.

        Raises:
            NotImplementedError:
                Always raised because ITC503 requires three separate PID
                commands emitted by :meth:`set_pid`.
        """
        raise NotImplementedError("ITC503 PID set requires separate P, I and D commands; use set_pid() instead.")

    def get_ramp_rate(self, loop: int) -> float:
        """Return ramp rate in Kelvin per minute for *loop*.

        The ITC503 does not expose a readback register for a continuous ramp
        rate; this returns the last value set via :meth:`set_ramp_rate`.
        """
        self._normalise_loop(loop)
        return self._ramp_rate

    def set_ramp_rate(self, loop: int, rate: float) -> None:
        """Set ramp rate in Kelvin per minute for *loop*.

        ITC503 sweep start/stop is controlled via ``S`` commands, without a
        direct ramp-rate command in Chapter 9.
        """
        self._normalise_loop(loop)
        self._ramp_rate = float(rate)

    def get_ramp_enabled(self, loop: int) -> bool:
        """Return whether sweep/ramp execution is active for *loop*."""
        self._normalise_loop(loop)
        status_tokens = self._read_status_tokens()
        return int(status_tokens.get("S", 0)) > 0

    def set_ramp_enabled(self, loop: int, enabled: bool) -> None:
        """Enable or disable sweep/ramp execution for *loop*."""
        self._normalise_loop(loop)
        self.write("S1" if enabled else "S0")

    def get_num_zones(self, loop: int) -> int:
        """Return the number of ITC503 auto-PID table rows for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (int):
                Number of auto-PID table rows supported by the ITC503.
        """
        self._normalise_loop(loop)
        return self._PID_TABLE_ROWS

    def get_zone(self, loop: int, zone_index: int) -> ZoneEntry:
        """Return auto-PID table row *zone_index* for *loop*.

        The ITC503 Chapter 10 auto-PID table is addressed through the ``x``
        (row) and ``y`` (column) pointer commands, read back via ``q``.
        Fields not present in the ITC503 table (ramp rate, heater range and
        heater output) are returned as ``0`` for API compatibility.

        Args:
            loop (int):
                Control loop number (1-based).
            zone_index (int):
                Auto-PID table row index (1-based, 1–16).

        Returns:
            (ZoneEntry):
                Zone entry populated from the ITC503 auto-PID table row.
        """
        self._normalise_loop(loop)
        row = self._normalise_pid_table_row(zone_index)
        return ZoneEntry(
            upper_bound=self._itc503_to_true_temperature(self._query_pid_table_value(row, 1)),
            p=self._query_pid_table_value(row, 2),
            i=self._query_pid_table_value(row, 3),
            d=self._query_pid_table_value(row, 4),
            ramp_rate=0.0,
            heater_range=0,
            heater_output=0.0,
        )

    def set_zone(self, loop: int, zone_index: int, entry: ZoneEntry) -> None:
        """Write auto-PID table row *zone_index* for *loop*.

        Only the ITC503 auto-PID table fields are programmable here: upper
        boundary, P, I and D.

        Args:
            loop (int):
                Control loop number (1-based).
            zone_index (int):
                Auto-PID table row index (1-based, 1–16).
            entry (ZoneEntry):
                Zone parameters to write. Only ``upper_bound``, ``p``, ``i``,
                and ``d`` are written by the ITC503 auto-PID table commands.
        """
        self._normalise_loop(loop)
        row = self._normalise_pid_table_row(zone_index)
        self._write_pid_table_value(row, 1, self._true_to_itc503_temperature(entry.upper_bound))
        self._write_pid_table_value(row, 2, entry.p)
        self._write_pid_table_value(row, 3, entry.i)
        self._write_pid_table_value(row, 4, entry.d)

    def _ramp_query(self, loop: int) -> str:
        """Return the legacy base-hook for ramp-state query composition.

        This base hook is not supported for ITC503.

        ITC503 reports sweep state through ``X`` status tokens. Use
        :meth:`get_ramp_enabled` instead of this base hook.

        Raises:
            NotImplementedError:
                Always raised because ITC503 ramp state is read from ``X``
                status tokens via :meth:`get_ramp_enabled`.
        """
        raise NotImplementedError("ITC503 ramp state is reported in X status tokens; use get_ramp_enabled() instead.")

    def _ramp_command(self, loop: int, enabled: bool, rate: float) -> str:
        """Return the legacy base-hook for ramp command composition.

        This base hook is not supported for ITC503.

        ITC503 sweep control uses direct ``S0``/``S1`` commands emitted by
        :meth:`set_ramp_enabled`; there is no combined ``enabled,rate`` form.

        Raises:
            NotImplementedError:
                Always raised because ITC503 ramp enable/disable is sent via
                :meth:`set_ramp_enabled`.
        """
        raise NotImplementedError("ITC503 ramp control uses S0/S1 commands; use set_ramp_enabled() instead.")

    def _read_status_tokens(self) -> dict[str, int]:
        """Query ``X`` and parse status tokens into a dictionary.

        Returns:
            (dict[str, int]):
                Mapping from token letters to their parsed integer values.
        """
        status_reply = self.query("X").strip()
        status_tokens: dict[str, int] = {}
        for letter, value in _STATUS_TOKEN_REGEX.findall(status_reply):
            status_tokens[letter.upper()] = int(value)
        return status_tokens

    def _normalise_pid_table_row(self, row: int) -> int:
        """Validate ITC503 auto-PID table row index."""
        if not 1 <= row <= self._PID_TABLE_ROWS:
            raise ValueError(f"Invalid PID-table row {row}; expected 1-{self._PID_TABLE_ROWS}.")
        return row

    def _set_pid_table_pointer(self, row: int, column: int) -> None:
        """Set ITC503 auto-PID table pointer to *row*/*column*."""
        self.write(f"x{row}")
        self.write(f"y{column}")

    def _query_pid_table_value(self, row: int, column: int) -> float:
        """Read one ITC503 auto-PID table value addressed by *row*/*column*.

        Args:
            row (int):
                Auto-PID table row index.
            column (int):
                Auto-PID table column index.

        Returns:
            (float):
                Parsed numeric value from the selected table cell.
        """
        self._set_pid_table_pointer(row, column)
        return self._query_float("q")

    def _write_pid_table_value(self, row: int, column: int, value: float) -> None:
        """Write one ITC503 auto-PID table value addressed by *row*/*column*.

        Args:
            row (int):
                Auto-PID table row index.
            column (int):
                Auto-PID table column index.
            value (float):
                Value to write to the selected table cell.
        """
        self._set_pid_table_pointer(row, column)
        self.write(f"p{value}")


class OxfordMercuryTemperatureController(_OxfordTemperatureControllerBase):
    """Concrete driver for the Oxford Instruments Mercury Temperature Controller."""

    _EXPECTED_IDENTITY_TOKENS = ("MERCURY",)
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
        """Return the current heater range index (0=off, 1=on) for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (int):
                0 when the loop range is ``OFF``, 1 otherwise.
        """
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
