"""Oxford temperature controller drivers."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import ClassVar

import numpy as np
from scipy.interpolate import interp1d

from stoner_measurement.config_utils import deep_merge, load_yaml_mapping
from stoner_measurement.instruments.oxford.mercury_itc import (
    OxfordMercuryTemperatureController as OxfordMercuryTemperatureController,
)
from stoner_measurement.instruments.protocol.base import BaseProtocol
from stoner_measurement.instruments.protocol.oxford import OxfordProtocol
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

__all__ = ["OxfordITC503", "OxfordMercuryTemperatureController"]

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
    """Oxford ITC503 control using the Issue 4 handbook's command set.

    Connection selects remote control with the front panel unlocked. Actions
    consume their acknowledgements. Heater and gas automatic modes are
    independent. PID uses native kelvin/minute units. The generic continuous
    ramp and heater-range APIs are unavailable; stored sweeps have explicit
    start/stop methods. OFF is manual heater control with zero output and
    consequently reads back as OPEN_LOOP.
    """

    _EXPECTED_IDENTITY_TOKENS = ("ITC503",)
    _PID_TABLE_ROWS = 32
    _CAPABILITIES = ControllerCapabilities(
        num_inputs=3,
        num_loops=1,
        input_channels=("A", "B", "C"),
        loop_numbers=(1,),
        has_ramp=False,
        has_pid=True,
        has_zone=True,
        has_cryogen_control=True,
        has_gas_auto_mode=True,
        has_manual_heater_output=True,
        has_heater_range=False,
        control_modes=(ControlMode.OFF, ControlMode.OPEN_LOOP, ControlMode.CLOSED_LOOP, ControlMode.ZONE),
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

    def confirm_identity(self) -> str:
        """Verify the ITC503 and select remote control with the front panel unlocked.

        Returns:
            (str): Verified identity returned by the instrument.
        """
        with self._lock:
            identity = super().confirm_identity()
            self.write("C3")
            return identity

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
        self._validate_value(value, 0.0, math.inf, "setpoint in kelvin")
        itc503_value = self._true_to_itc503_temperature(value)
        super().set_setpoint(loop, itc503_value)

    def get_heater_range(self, loop: int) -> int:
        """Reject heater-range readback: ITC503 has a voltage limit, not ranges."""
        self._normalise_loop(loop)
        raise NotImplementedError("ITC503 has no heater ranges; use set_maximum_heater_voltage().")

    def set_heater_range(self, loop: int, range_: int) -> None:
        """Reject heater-range changes rather than issuing a sensor command."""
        self._normalise_loop(loop)
        raise NotImplementedError("ITC503 has no heater ranges; use set_maximum_heater_voltage().")

    def get_input_channel(self, loop: int) -> str:
        """Read the selected heater sensor from the hardware H status field."""
        self._normalise_loop(loop)
        return {1: "A", 2: "B", 3: "C"}[self._read_status_tokens()["H"]]

    def set_input_channel(self, loop: int, channel: str) -> None:
        """Assign the heater sensor with H1, H2 or H3."""
        self._normalise_loop(loop)
        channel = self._normalise_channel(channel)
        self.write(self._input_command(loop, channel))

    def get_gas_flow(self) -> float:
        """Return the gas-flow needle valve position as a percentage."""
        return self._query_float("R7")

    def set_gas_flow(self, percent: float) -> None:
        """Set the gas-flow needle valve position to *percent* open."""
        self._validate_value(percent, 0.0, 99.9, "gas flow percentage")
        self.write(f"G{percent:.1f}")

    def get_needle_valve(self) -> float:
        """Return the needle-valve position as a percentage."""
        return self.get_gas_flow()

    def set_needle_valve(self, position: float) -> None:
        """Set the needle-valve position to *position* percent open."""
        self.set_gas_flow(position)

    def get_gas_auto(self) -> bool:
        """Return the gas-auto bit from the hardware A status field.

        Returns:
            (bool): Whether automatic gas control is active.
        """
        return bool(self._read_status_tokens()["A"] & 2)

    def set_gas_auto(self, auto: bool) -> None:
        """Enable or disable automatic gas-flow control.

        The ITC503 ``A`` command controls the combined heater/gas auto mode.
        Bit 0 = auto heater, bit 1 = auto gas.  This implementation preserves
        the current heater-auto state when toggling gas auto mode.
        """
        with self._lock:
            heater_auto = self._read_status_tokens()["A"] & 1
            self.write(f"A{heater_auto | (2 if auto else 0)}")

    def _temperature_query(self, channel: str) -> str:
        """Return the ITC503 query command for reading temperature on *channel*."""
        return {"A": "R1", "B": "R2", "C": "R3"}[channel]

    def _input_command(self, loop: int, channel: str) -> str:
        """Return the ITC503 command that assigns *channel* to the heater loop."""
        channel_code = {"A": 1, "B": 2, "C": 3}[channel]
        return f"H{channel_code}"

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
        if not status_tokens["A"] & 1:
            return ControlMode.OPEN_LOOP
        return ControlMode.ZONE if status_tokens["L"] else ControlMode.CLOSED_LOOP

    def set_loop_mode(self, loop: int, mode: ControlMode) -> None:
        """Set heater control and Auto-PID while preserving gas automatic control.

        OFF selects manual heater control and zero output. Hardware reports
        this as OPEN_LOOP because it has no separate off status bit.
        """
        self._normalise_loop(loop)
        if mode not in self._CAPABILITIES.control_modes:
            raise ValueError(f"Unsupported ITC503 control mode {mode!r}.")
        with self._lock:
            gas_auto = self._read_status_tokens()["A"] & 2
            self.write("L1" if mode is ControlMode.ZONE else "L0")
            heater_auto = int(mode in (ControlMode.CLOSED_LOOP, ControlMode.ZONE))
            self.write(f"A{gas_auto | heater_auto}")
            if mode is ControlMode.OFF:
                self.set_manual_heater_output(loop, 0.0)

    def set_manual_heater_output(self, loop: int, output: float) -> None:
        """Set manual heater output with O; the heater must already be manual.

        Args:
            loop (int): Control loop number (1).
            output (float): Percentage of the configured voltage limit, 0–99.9.

        Raises:
            ValueError: The loop or output is invalid.
            InstrumentError: The controller rejects the command.
        """
        self._normalise_loop(loop)
        self._validate_value(output, 0.0, 99.9, "heater output percentage")
        self.write(f"O{output:.1f}")

    def set_maximum_heater_voltage(self, voltage: float) -> None:
        """Set the maximum heater voltage using M.

        Args:
            voltage (float): Non-negative voltage in volts. Zero selects dynamic
                limiting; the instrument enforces the fitted heater's limit.

        Raises:
            ValueError: The voltage is negative or non-finite.
            InstrumentError: The controller rejects the limit.
        """
        self._validate_value(voltage, 0.0, math.inf, "maximum heater voltage")
        self.write(f"M{voltage:.1f}")

    @staticmethod
    def _validate_value(value: float, minimum: float, maximum: float, name: str) -> None:
        """Reject non-finite or out-of-range settings before any command is sent."""
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"ITC503 {name} must be between {minimum} and {maximum}.")

    def _mode_command(self, loop: int, mode_code: int) -> str:
        """Reject generic mode encoding, which cannot preserve the gas-auto bit."""
        raise NotImplementedError("Use set_loop_mode() to preserve ITC503 gas control.")

    def _heater_output_query(self, loop: int) -> str:
        """Return the ITC503 query command for reading heater output percentage."""
        return "R5"

    def _heater_range_command(self, loop: int, range_: int) -> str:
        """Reject range encoding: H selects the heater sensor on ITC503."""
        raise NotImplementedError("ITC503 has no heater ranges.")

    def set_pid(self, loop: int, p: float, i: float, d: float) -> None:
        """Disable Auto-PID and set native PID terms for *loop*.

        Args:
            loop (int): Control loop number (1).
            p (float): Non-negative proportional band in kelvin.
            i (float): Integral action time in minutes, 0–140.
            d (float): Derivative action time in minutes, 0–273.

        Raises:
            ValueError: A loop or PID value is invalid.
            InstrumentError: The controller rejects a command.
        """
        self._normalise_loop(loop)
        self._validate_value(p, 0.0, math.inf, "proportional band")
        self._validate_value(i, 0.0, 140.0, "integral time in minutes")
        self._validate_value(d, 0.0, 273.0, "derivative time in minutes")
        with self._lock:
            self.write("L0")
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
        with self._lock:
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

        Continuous ramp rates are not supported; use the programmed sweep API.
        """
        self._normalise_loop(loop)
        raise NotImplementedError("ITC503 has programmed sweeps, not a continuous ramp-rate register.")

    def set_ramp_rate(self, loop: int, rate: float) -> None:
        """Set ramp rate in Kelvin per minute for *loop*.

        ITC503 sweep start/stop is controlled via ``S`` commands, without a
        direct ramp-rate command in Chapter 9.
        """
        self._normalise_loop(loop)
        raise NotImplementedError("ITC503 has programmed sweeps, not a continuous ramp-rate register.")

    def get_ramp_enabled(self, loop: int) -> bool:
        """Return whether sweep/ramp execution is active for *loop*."""
        self._normalise_loop(loop)
        status_tokens = self._read_status_tokens()
        return int(status_tokens.get("S", 0)) > 0

    def set_ramp_enabled(self, loop: int, enabled: bool) -> None:
        """Reject generic ramp control; use start_sweep() or stop_sweep()."""
        self._normalise_loop(loop)
        raise NotImplementedError("Use start_sweep() or stop_sweep() for an ITC503 programmed sweep.")

    def start_sweep(self) -> None:
        """Start the existing hardware sweep programme with S1."""
        self.write("S1")

    def stop_sweep(self) -> None:
        """Stop hardware sweep execution with S0."""
        self.write("S0")

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
                Auto-PID table row index (1-based, 1–32).

        Returns:
            (ZoneEntry):
                Zone entry populated from the ITC503 auto-PID table row.
        """
        self._normalise_loop(loop)
        row = self._normalise_pid_table_row(zone_index)
        with self._lock:
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
                Auto-PID table row index (1-based, 1–32).
            entry (ZoneEntry):
                Zone parameters to write. Only ``upper_bound``, ``p``, ``i``,
                and ``d`` are written by the ITC503 auto-PID table commands.
        """
        self._normalise_loop(loop)
        row = self._normalise_pid_table_row(zone_index)
        self._validate_value(entry.upper_bound, 0.0, math.inf, "PID-table upper temperature")
        self._validate_value(entry.p, 0.0, math.inf, "proportional band")
        self._validate_value(entry.i, 0.0, 140.0, "integral time in minutes")
        self._validate_value(entry.d, 0.0, 273.0, "derivative time in minutes")
        with self._lock:
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
        if re.fullmatch(r"0A[0-7]C[0-3]S\d{1,2}H[1-3]L[01]", status_reply) is None:
            raise ValueError(f"OxfordITC503: invalid X status response {status_reply!r}.")
        status_tokens: dict[str, int] = {}
        for letter, value in _STATUS_TOKEN_REGEX.findall(status_reply):
            status_tokens[letter.upper()] = int(value)
        if status_tokens["S"] > 32:
            raise ValueError(f"OxfordITC503: invalid X status response {status_reply!r}.")
        return status_tokens

    def _normalise_pid_table_row(self, row: int) -> int:
        """Validate ITC503 auto-PID table row index."""
        if not isinstance(row, int) or not 1 <= row <= self._PID_TABLE_ROWS:
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
