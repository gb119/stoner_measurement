"""Data-model types for the temperature controller engine.

Defines the published data structures used to communicate state between the
:class:`~stoner_measurement.temperature_control.engine.TemperatureControllerEngine`
and its subscribers (UI panels, sequence plugins, monitoring plugins).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stoner_measurement.instruments.temperature_controller import ControlMode, SensorStatus


class EngineStatus(Enum):
    """Operational status of the :class:`~stoner_measurement.temperature_control.engine.TemperatureControllerEngine`.

    Attributes:
        STOPPED:
            The engine has not been started or has been shut down.
        DISCONNECTED:
            The engine is running but no instrument is connected.
        CONNECTED:
            An instrument is connected but polling has not yet started.
        POLLING:
            The engine is actively polling the instrument and publishing data.
        ERROR:
            A hardware or communication error has been detected.
    """

    STOPPED = "stopped"
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    POLLING = "polling"
    ERROR = "error"


@dataclass
class TemperatureChannelReading:
    """A timestamped snapshot of a single sensor channel reading with derived quantities.

    Attributes:
        channel (str):
            Sensor channel identifier (e.g. ``"A"``).
        value (float):
            Numeric sensor reading in *units*.
        timestamp (datetime):
            UTC timestamp of when the reading was taken.
        units (str):
            Units of *value* (e.g. ``"K"``).  Defaults to ``"K"``.
        status (SensorStatus):
            Validity/range status of the reading.
        rate_of_change (float):
            Estimated rate of change of the temperature in Kelvin per minute.
            Calculated from a rolling window of recent readings.  Defaults to
            ``0.0`` until enough readings have accumulated.

    Examples:
        >>> from datetime import UTC, datetime
        >>> from stoner_measurement.instruments.temperature_controller import SensorStatus
        >>> from stoner_measurement.temperature_control.types import TemperatureChannelReading
        >>> r = TemperatureChannelReading(
        ...     channel="A", value=300.0, timestamp=datetime.now(tz=UTC),
        ...     status=SensorStatus.OK,
        ... )
        >>> r.units
        'K'
        >>> r.rate_of_change
        0.0
    """

    channel: str
    value: float
    timestamp: datetime
    status: SensorStatus
    units: str = "K"
    rate_of_change: float = 0.0


@dataclass
class TemperatureEngineState:
    """A consolidated snapshot of the complete temperature controller state.

    Published by the engine after each polling cycle.

    Attributes:
        readings (dict[str, TemperatureChannelReading]):
            Mapping from channel identifier to the latest channel reading.
        setpoints (dict[int, float]):
            Mapping from control-loop number to its current setpoint in Kelvin.
        heater_outputs (dict[int, float]):
            Mapping from control-loop number to its heater output percentage (0–100 %).
        heater_ranges (dict[int, int]):
            Mapping from control-loop number to its current heater range index.
        needle_valve (float | None):
            Cryogen gas-flow valve position as a percentage (0–100 %), or
            ``None`` if the instrument does not support cryogen control.
        gas_auto_mode (bool | None):
            ``True`` when the gas/needle-valve is under automatic control,
            ``False`` when in manual mode, or ``None`` if the instrument does
            not support querying the gas auto mode.
        loop_modes (dict[int, ControlMode]):
            Mapping from control-loop number to its active :class:`~stoner_measurement.instruments.temperature_controller.ControlMode`.
        input_channels (dict[int, str]):
            Mapping from control-loop number to the identifier of the sensor
            channel currently assigned to that loop.
        at_setpoint (dict[int, bool]):
            ``True`` for each loop whose sensor reading is within the configured
            tolerance of the setpoint.
        stable (dict[int, bool]):
            ``True`` for each loop that has been continuously at setpoint for
            the configured stability window, with a rate of change below the
            configured minimum.
        engine_status (EngineStatus):
            Current operational status of the engine.

    Examples:
        >>> from stoner_measurement.temperature_control.types import (
        ...     EngineStatus, TemperatureEngineState,
        ... )
        >>> state = TemperatureEngineState(engine_status=EngineStatus.DISCONNECTED)
        >>> state.readings
        {}
        >>> state.at_setpoint
        {}
    """

    readings: dict[str, TemperatureChannelReading] = field(default_factory=dict)
    setpoints: dict[int, float] = field(default_factory=dict)
    heater_outputs: dict[int, float] = field(default_factory=dict)
    heater_ranges: dict[int, int] = field(default_factory=dict)
    needle_valve: float | None = None
    gas_auto_mode: bool | None = None
    loop_modes: dict[int, ControlMode] = field(default_factory=dict)
    input_channels: dict[int, str] = field(default_factory=dict)
    at_setpoint: dict[int, bool] = field(default_factory=dict)
    stable: dict[int, bool] = field(default_factory=dict)
    engine_status: EngineStatus = EngineStatus.DISCONNECTED


@dataclass
class StabilityConfig:
    """Configuration parameters defining what "stable at setpoint" means.

    Attributes:
        tolerance_k (float):
            Maximum permissible deviation from the setpoint in Kelvin for the
            temperature to be considered *at setpoint*.  Defaults to ``0.1``.
        window_s (float):
            Minimum time in seconds that the temperature must be continuously
            *at setpoint* before *stable* is declared.  Defaults to ``60.0``.
        min_rate (float):
            Maximum permissible absolute rate of change in Kelvin per minute
            for stability to be declared.  Defaults to ``0.005``.
        unstable_holdoff_s (float):
            Hysteresis: the *stable* flag must remain ``False`` for at least
            this many seconds before it can be set to ``True`` again after
            being cleared.  Defaults to ``5.0``.

    Examples:
        >>> from stoner_measurement.temperature_control.types import StabilityConfig
        >>> cfg = StabilityConfig()
        >>> cfg.tolerance_k
        0.1
        >>> cfg.window_s
        60.0
        >>> cfg.min_rate
        0.005
    """

    tolerance_k: float = 0.1
    window_s: float = 60.0
    min_rate: float = 0.005
    unstable_holdoff_s: float = 5.0


@dataclass
class LoopSettings:
    """A snapshot of one PID control loop's configurable settings.

    Used by the engine's :meth:`~stoner_measurement.temperature_control.engine.TemperatureControllerEngine.get_loop_settings`
    method to read all hardware-settable parameters for a single loop in one
    operation, and to populate the UI "Read" action.

    Attributes:
        setpoint (float):
            Target setpoint in Kelvin.
        mode (ControlMode):
            Active control mode.
        input_channel (str):
            Sensor channel identifier assigned as the control input.
        ramp_enabled (bool):
            ``True`` when automatic setpoint ramping is active.
        ramp_rate (float):
            Setpoint ramp rate in Kelvin per minute.
        pid_p (float):
            Proportional gain.
        pid_i (float):
            Integral gain.
        pid_d (float):
            Derivative gain.
        heater_range (int | None):
            Current heater range index, or ``None`` if the driver does not
            support reading the heater range.

    Examples:
        >>> from stoner_measurement.instruments.temperature_controller import ControlMode
        >>> from stoner_measurement.temperature_control.types import LoopSettings
        >>> s = LoopSettings(
        ...     setpoint=300.0, mode=ControlMode.CLOSED_LOOP,
        ...     input_channel="A", ramp_enabled=False, ramp_rate=5.0,
        ...     pid_p=50.0, pid_i=1.0, pid_d=0.0, heater_range=1,
        ... )
        >>> s.setpoint
        300.0
        >>> s.heater_range
        1
    """

    setpoint: float
    mode: ControlMode
    input_channel: str
    ramp_enabled: bool
    ramp_rate: float
    pid_p: float
    pid_i: float
    pid_d: float
    heater_range: int | None = None
