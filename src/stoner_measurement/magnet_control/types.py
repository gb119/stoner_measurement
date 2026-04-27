"""Data-model types for the magnet controller engine.

Defines the published data structures used to communicate state between the
:class:`~stoner_measurement.magnet_control.engine.MagnetControllerEngine`
and its subscribers (UI panels, sequence plugins, monitoring plugins).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stoner_measurement.instruments.magnet_controller import MagnetState


class MagnetEngineStatus(Enum):
    """Operational status of the :class:`~stoner_measurement.magnet_control.engine.MagnetControllerEngine`.

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
class MagnetReading:
    """A timestamped snapshot of a single magnet status reading.

    Attributes:
        timestamp (datetime):
            UTC timestamp of when the reading was taken.
        field (float | None):
            Magnetic field in tesla, or ``None`` if not available.
        current (float):
            Output current in amps.
        voltage (float | None):
            Output voltage in volts, or ``None`` if not available.
        heater_on (bool | None):
            ``True`` when the persistent switch heater is energised,
            ``False`` when it is off, or ``None`` if unknown.
        state (MagnetState):
            Current operational state of the magnet supply.
        at_target (bool):
            ``True`` when the output has reached the programmed target.
        field_rate (float):
            Estimated rate of change of the field in tesla per minute.
            Defaults to ``0.0`` until enough readings have accumulated.

    Examples:
        >>> from datetime import UTC, datetime
        >>> from stoner_measurement.instruments.magnet_controller import MagnetState
        >>> from stoner_measurement.magnet_control.types import MagnetReading
        >>> r = MagnetReading(
        ...     timestamp=datetime.now(tz=UTC),
        ...     field=1.0,
        ...     current=10.0,
        ...     voltage=0.5,
        ...     heater_on=True,
        ...     state=MagnetState.AT_TARGET,
        ...     at_target=True,
        ... )
        >>> r.field_rate
        0.0
    """

    timestamp: datetime
    field: float | None
    current: float
    voltage: float | None
    heater_on: bool | None
    state: MagnetState
    at_target: bool
    field_rate: float = 0.0


@dataclass
class MagnetEngineState:
    """A consolidated snapshot of the complete magnet controller engine state.

    Published by the engine after each polling cycle.

    Attributes:
        reading (MagnetReading | None):
            Latest reading from the magnet supply, or ``None`` if not yet
            available.
        target_field (float | None):
            Currently programmed target field in tesla, or ``None`` if
            unknown.
        target_current (float | None):
            Currently programmed target current in amps, or ``None`` if
            unknown.
        ramp_rate_field (float | None):
            Current field ramp rate in tesla per minute, or ``None`` if
            unknown.
        ramp_rate_current (float | None):
            Current current ramp rate in amps per minute, or ``None`` if
            unknown.
        magnet_constant (float | None):
            Magnet constant in tesla per amp, or ``None`` if not configured.
        at_target (bool):
            ``True`` when the output is at the programmed target.
        engine_status (MagnetEngineStatus):
            Current operational status of the engine.

    Examples:
        >>> from stoner_measurement.magnet_control.types import (
        ...     MagnetEngineState, MagnetEngineStatus,
        ... )
        >>> state = MagnetEngineState(engine_status=MagnetEngineStatus.DISCONNECTED)
        >>> state.reading is None
        True
        >>> state.at_target
        False
    """

    reading: MagnetReading | None = None
    target_field: float | None = None
    target_current: float | None = None
    ramp_rate_field: float | None = None
    ramp_rate_current: float | None = None
    magnet_constant: float | None = None
    at_target: bool = False
    engine_status: MagnetEngineStatus = field(default=MagnetEngineStatus.DISCONNECTED)


@dataclass
class MagnetStabilityConfig:
    """Configuration parameters defining what "at target" means for a magnet.

    Attributes:
        tolerance_t (float):
            Maximum permissible deviation from the target field in tesla for
            the field to be considered *at target*.  Defaults to ``0.001``.
        window_s (float):
            Minimum time in seconds that the field must be continuously *at
            target* before *stable* is declared.  Defaults to ``10.0``.
        min_rate (float):
            Maximum permissible absolute rate of change in tesla per minute
            for stability to be declared.  Defaults to ``0.0001``.
        unstable_holdoff_s (float):
            Hysteresis: the *stable* flag must remain ``False`` for at least
            this many seconds before it can be set to ``True`` again after
            being cleared.  Defaults to ``2.0``.

    Examples:
        >>> from stoner_measurement.magnet_control.types import MagnetStabilityConfig
        >>> cfg = MagnetStabilityConfig()
        >>> cfg.tolerance_t
        0.001
        >>> cfg.window_s
        10.0
        >>> cfg.min_rate
        0.0001
    """

    tolerance_t: float = 0.001
    window_s: float = 10.0
    min_rate: float = 0.0001
    unstable_holdoff_s: float = 2.0
