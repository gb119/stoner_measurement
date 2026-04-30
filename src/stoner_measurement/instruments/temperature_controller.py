"""Abstract base class for temperature controller instruments.

Defines the common interface for all temperature controller drivers, covering
the feature sets of instruments such as the Lakeshore 335, 336, 340 and 350,
the Oxford Instruments ITC503, and the Oxford Instruments Mercury iTC.

The interface is divided into three tiers:

**Core abstract methods** — must be implemented by every concrete driver:
    sensor readings and status, control-loop setpoint and mode, heater output
    and range, PID parameters, ramp control, input-channel assignment, and
    capability reporting.

**Concrete composite methods** — default implementations built from the core
    abstracts: :meth:`get_temperature_reading`, :meth:`get_ramp_state`,
    :meth:`get_loop_status`, :meth:`get_controller_status`, and
    :meth:`wait_for_setpoint`.

**Optional methods** — raise :class:`NotImplementedError` by default; override
    in drivers that support the feature (check via
    :meth:`get_capabilities` before calling): alarms, zone/table control,
    autotuning, sensor excitation and filtering, calibration-curve assignment,
    and cryogen/auxiliary outputs.
"""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ControlMode(Enum):
    """Operating mode of a PID control loop.

    Attributes:
        OFF:
            Loop disabled; no control action.
        CLOSED_LOOP:
            Standard PID feedback to the assigned input sensor.
        ZONE:
            Automatic zone-table (scheduled PID) control.
        OPEN_LOOP:
            Manual heater output; sensor reading is not used for control.
        MONITOR:
            Sensor monitored but no heater driven (monitor-only input).
    """

    OFF = "off"
    CLOSED_LOOP = "closed_loop"
    ZONE = "zone"
    OPEN_LOOP = "open_loop"
    MONITOR = "monitor"


class RampState(Enum):
    """Whether a control loop's setpoint is currently being ramped.

    Attributes:
        IDLE:
            No active ramp; setpoint is at the programmed value.
        RAMPING:
            Setpoint is being ramped towards the target at the programmed rate.
    """

    IDLE = "idle"
    RAMPING = "ramping"


class SensorStatus(Enum):
    """Validity and range status of a temperature sensor reading.

    Attributes:
        OK:
            Reading is within the calibrated range and appears valid.
        INVALID:
            Reading cannot be trusted (e.g. sensor disconnected or failed).
        OVERRANGE:
            Measured signal exceeds the upper calibration limit.
        UNDERRANGE:
            Measured signal is below the lower calibration limit.
        FAULT:
            Hardware fault detected on the sensor channel.
    """

    OK = "ok"
    INVALID = "invalid"
    OVERRANGE = "overrange"
    UNDERRANGE = "underrange"
    FAULT = "fault"


class AlarmState(Enum):
    """Alarm status for a sensor channel.

    Attributes:
        DISABLED:
            Alarm checking is not active for this channel.
        OK:
            Temperature is within the configured alarm limits.
        LOW:
            Temperature has fallen below the low-alarm threshold.
        HIGH:
            Temperature has risen above the high-alarm threshold.
    """

    DISABLED = "disabled"
    OK = "ok"
    LOW = "low"
    HIGH = "high"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PIDParameters:
    """PID gain parameters for one control loop.

    Attributes:
        p (float):
            Proportional gain (dimensionless; instrument-specific range).
        i (float):
            Integral gain, sometimes labelled *reset* or *Ti*
            (units instrument-specific; commonly seconds or repeats/minute).
        d (float):
            Derivative gain, sometimes labelled *rate* or *Td*
            (units instrument-specific; commonly seconds).
    """

    p: float
    i: float
    d: float


@dataclass(frozen=True)
class InputChannelSettings:
    """Configuration settings for a single sensor input channel.

    Captures the sensor type, range, filtering, and calibration curve
    assignment for one input channel.  Fields that are not applicable
    to a particular driver are set to ``None``.

    Attributes:
        sensor_type (int | None):
            Instrument-specific sensor type code (e.g. 0 = Disabled,
            1 = Diode, 2 = PTC RTD, 3 = NTC RTD).  ``None`` if not
            configurable on this driver.
        autorange (bool | None):
            ``True`` when automatic ranging is enabled; ``None`` if not
            supported.
        range_ (int | None):
            Manual range index (instrument-specific).  Meaningful only
            when *autorange* is ``False``; ``None`` if not supported.
        compensation (bool | None):
            ``True`` when current-reversal compensation is active (diode /
            RTD inputs on some controllers); ``None`` if not supported.
        units (int | None):
            Temperature units code (e.g. 1 = K, 2 = °C, 3 = sensor
            units).  ``None`` if not configurable.
        filter_enabled (bool | None):
            ``True`` when the digital averaging filter is active; ``None``
            if not supported.
        filter_points (int | None):
            Number of readings averaged by the filter (1 effectively
            disables averaging); ``None`` if not supported.
        filter_window (float | None):
            Percentage deviation window that resets the filter (0 disables
            windowing); ``None`` if not supported.
        curve_number (int | None):
            Calibration curve number assigned to this channel (0 = none);
            ``None`` if curve assignment is not supported.
    """

    sensor_type: int | None = None
    autorange: bool | None = None
    range_: int | None = None
    compensation: bool | None = None
    units: int | None = None
    filter_enabled: bool | None = None
    filter_points: int | None = None
    filter_window: float | None = None
    curve_number: int | None = None


@dataclass(frozen=True)
class ZoneEntry:
    """One entry in a temperature controller's zone / table control table.

    Zone control divides the operating temperature range into consecutive
    segments.  Each segment has its own PID gains, setpoint ramp rate,
    heater range, and manual heater output power.  When the active setpoint
    crosses *upper_bound* the controller automatically loads the next zone's
    parameters.

    Attributes:
        upper_bound (float):
            Upper setpoint boundary for this zone in Kelvin.  When the
            setpoint is at or below this value the zone's PID and heater
            settings are applied.
        p (float):
            Proportional gain for this zone.
        i (float):
            Integral gain (reset) for this zone.
        d (float):
            Derivative gain (rate) for this zone.
        ramp_rate (float):
            Setpoint ramp rate for this zone in Kelvin per minute.  A value
            of ``0`` means the setpoint changes immediately (no ramp).
        heater_range (int):
            Heater range index for this zone (instrument-specific; ``0``
            conventionally means heater off).
        heater_output (float):
            Manual heater output power percentage for this zone (0–100 %).
            Used when the loop is in open-loop mode or as the initial value
            when entering the zone.
    """

    upper_bound: float
    p: float
    i: float
    d: float
    ramp_rate: float
    heater_range: int
    heater_output: float


@dataclass(frozen=True)
class TemperatureReading:
    """A snapshot of a single sensor channel reading.

    Attributes:
        value (float):
            Numeric sensor reading expressed in the units given by the
            *units* field.  Drivers should convert to Kelvin and set
            ``units="K"`` wherever possible; raw resistance or voltage
            readings should set the appropriate unit string instead.
        status (SensorStatus):
            Validity / range status of the reading.
        units (str):
            Native units reported by the instrument (e.g. ``"K"``, ``"C"``,
            ``"V"``, ``"Ohm"``).  Defaults to ``"K"``.
    """

    value: float
    status: SensorStatus
    units: str = "K"


@dataclass(frozen=True)
class LoopStatus:
    """A snapshot of one PID control loop's complete state.

    Attributes:
        setpoint (float):
            Current setpoint temperature in Kelvin.
        process_value (float):
            Temperature reading at the loop's input sensor in Kelvin.
        mode (ControlMode):
            Active control mode of the loop.
        heater_output (float):
            Heater output as a percentage (0–100 %).
        heater_range (int | None):
            Active heater range index (instrument-specific; ``0`` conventionally
            means heater off), or ``None`` if the controller does not expose a
            heater range setting.
        ramp_enabled (bool):
            ``True`` when automatic setpoint ramping is enabled.
        ramp_rate (float):
            Setpoint ramp rate in Kelvin per minute.
        ramp_state (RampState):
            Whether the loop is currently executing a ramp.
        p (float):
            Proportional gain.
        i (float):
            Integral gain.
        d (float):
            Derivative gain.
        input_channel (str):
            Identifier of the sensor channel driving this loop.
    """

    setpoint: float
    process_value: float
    mode: ControlMode
    heater_output: float
    ramp_enabled: bool
    ramp_rate: float
    ramp_state: RampState
    p: float
    i: float
    d: float
    input_channel: str
    heater_range: int | None = None


@dataclass
class TemperatureStatus:
    """A full controller status snapshot.

    Attributes:
        temperatures (dict[str, TemperatureReading]):
            Mapping of channel identifier to sensor reading.
        loops (dict[int, LoopStatus]):
            Mapping of loop number to loop status snapshot.
        error_state (str | None):
            Human-readable error/fault description, or ``None`` if the
            controller reports no fault.
    """

    temperatures: dict[str, TemperatureReading]
    loops: dict[int, LoopStatus]
    error_state: str | None = None


@dataclass(frozen=True)
class ControllerCapabilities:
    """Static capability descriptor for a temperature controller driver.

    Attributes:
        num_inputs (int):
            Total number of sensor input channels.
        num_loops (int):
            Total number of PID control loops.
        input_channels (tuple[str, ...]):
            Ordered tuple of channel identifiers (e.g. ``("A", "B", "C")``).
        loop_numbers (tuple[int, ...]):
            Ordered tuple of loop numbers (e.g. ``(1, 2)``).
        has_ramp (bool):
            ``True`` if the driver supports setpoint ramping.
        has_pid (bool):
            ``True`` if the driver supports PID parameter read/write.
        has_autotune (bool):
            ``True`` if the driver supports PID autotuning.
        has_alarm (bool):
            ``True`` if the driver supports sensor alarm limits.
        has_zone (bool):
            ``True`` if the driver supports zone/table (scheduled PID) control.
        has_user_curves (bool):
            ``True`` if the driver supports user-defined calibration curves.
        has_sensor_excitation (bool):
            ``True`` if the driver supports configuring sensor excitation.
        has_cryogen_control (bool):
            ``True`` if the driver supports cryogen-flow or needle-valve control
            (e.g. Oxford Instruments ITC503 or Mercury iTC).
        has_gas_auto_mode (bool):
            ``True`` if the driver supports switching the gas/needle-valve control
            between automatic and manual mode.
        has_manual_heater_output (bool):
            ``True`` if the driver supports setting the heater output directly
            (required for :attr:`~ControlMode.OPEN_LOOP` operation).
        has_input_settings (bool):
            ``True`` if the driver supports reading and writing per-channel
            input configuration (sensor type, range, filter, calibration curve
            assignment) via :meth:`~TemperatureController.get_input_channel_settings`
            and :meth:`~TemperatureController.set_input_channel_settings`.
        heater_range_labels (dict[int, tuple[str, ...]]):
            Optional per-loop mapping of heater range index to human-readable
            label.  The tuple index corresponds to the integer range index passed
            to :meth:`~TemperatureController.set_heater_range`.  An empty dict
            (the default) means the UI should fall back to numeric indices.
        min_temperature (float | None):
            Minimum achievable temperature in Kelvin, or ``None`` if unknown.
        max_temperature (float | None):
            Maximum controllable temperature in Kelvin, or ``None`` if unknown.
    """

    num_inputs: int
    num_loops: int
    input_channels: tuple[str, ...]
    loop_numbers: tuple[int, ...]
    has_ramp: bool = True
    has_pid: bool = True
    has_autotune: bool = False
    has_alarm: bool = False
    has_zone: bool = False
    has_user_curves: bool = False
    has_sensor_excitation: bool = False
    has_cryogen_control: bool = False
    has_gas_auto_mode: bool = False
    has_manual_heater_output: bool = False
    has_input_settings: bool = False
    heater_range_labels: dict[int, tuple[str, ...]] = field(default_factory=dict)
    min_temperature: float | None = None
    max_temperature: float | None = None


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class TemperatureController(BaseInstrument):
    """Abstract base class for temperature controller instruments.

    Provides a uniform interface for reading temperatures, managing setpoints,
    and controlling heater output across a range of cryogenic and laboratory
    temperature controllers including the Lakeshore 335, 336, 340 and 350,
    the Oxford Instruments ITC503, and the Oxford Instruments Mercury iTC.
    All temperature values are in Kelvin unless otherwise stated.

    Subclasses must implement the seventeen core abstract methods.  Optional
    capability methods raise :class:`NotImplementedError` by default; drivers
    override only those methods that their hardware supports.  Callers should
    consult :meth:`get_capabilities` to determine which optional features are
    available before invoking them.

    Attributes:
        transport (BaseTransport):
            Transport layer instance.
        protocol (BaseProtocol):
            Protocol instance.

    Examples:
        >>> from stoner_measurement.instruments.transport import NullTransport
        >>> from stoner_measurement.instruments.protocol import LakeshoreProtocol
        >>> from stoner_measurement.instruments.temperature_controller import (
        ...     TemperatureController, ControlMode, SensorStatus,
        ...     ControllerCapabilities, PIDParameters,
        ... )
        >>> class _TC(TemperatureController):
        ...     def get_temperature(self, channel): return 300.0
        ...     def get_sensor_status(self, channel): return SensorStatus.OK
        ...     def get_input_channel(self, loop): return "A"
        ...     def set_input_channel(self, loop, channel): pass
        ...     def get_setpoint(self, loop): return 300.0
        ...     def set_setpoint(self, loop, value): pass
        ...     def get_loop_mode(self, loop): return ControlMode.CLOSED_LOOP
        ...     def set_loop_mode(self, loop, mode): pass
        ...     def get_heater_output(self, loop): return 50.0
        ...     def set_heater_range(self, loop, range_): pass
        ...     def get_pid(self, loop): return PIDParameters(50.0, 1.0, 0.0)
        ...     def set_pid(self, loop, p, i, d): pass
        ...     def get_ramp_rate(self, loop): return 5.0
        ...     def set_ramp_rate(self, loop, rate): pass
        ...     def get_ramp_enabled(self, loop): return False
        ...     def set_ramp_enabled(self, loop, enabled): pass
        ...     def get_capabilities(self):
        ...         return ControllerCapabilities(
        ...             num_inputs=2, num_loops=1,
        ...             input_channels=("A", "B"), loop_numbers=(1,),
        ...         )
        >>> tc = _TC(NullTransport(), LakeshoreProtocol())
        >>> tc.get_temperature("A")
        300.0
        >>> tc.get_capabilities().num_loops
        1
    """

    def __init__(
        self,
        transport: BaseTransport,
        protocol: BaseProtocol,
    ) -> None:
        """Initialise the temperature controller.

        Args:
            transport (BaseTransport):
                Transport layer instance.
            protocol (BaseProtocol):
                Protocol instance.
        """
        super().__init__(transport=transport, protocol=protocol)

    # ------------------------------------------------------------------
    # Core abstract methods — sensor inputs
    # ------------------------------------------------------------------

    @abstractmethod
    def get_temperature(self, channel: str) -> float:
        """Return the current temperature for *channel* in Kelvin.

        Args:
            channel (str):
                Sensor channel identifier (instrument-specific, e.g. ``"A"``).

        Returns:
            (float):
                Current temperature in Kelvin.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_temperature("A")
            300.0
        """

    @abstractmethod
    def get_sensor_status(self, channel: str) -> SensorStatus:
        """Return the validity/range status of the sensor on *channel*.

        Args:
            channel (str):
                Sensor channel identifier (instrument-specific, e.g. ``"A"``).

        Returns:
            (SensorStatus):
                Current validity and range status of the sensor reading.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_sensor_status("A")
            <SensorStatus.OK: 'ok'>
        """

    @abstractmethod
    def get_input_channel(self, loop: int) -> str:
        """Return the sensor channel currently assigned to control *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (str):
                Channel identifier of the sensor driving this loop.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_input_channel(1)
            'A'
        """

    @abstractmethod
    def set_input_channel(self, loop: int, channel: str) -> None:
        """Assign sensor *channel* as the input for control *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            channel (str):
                Sensor channel identifier to assign.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *channel* is not a valid sensor input for this instrument.
        """

    # ------------------------------------------------------------------
    # Core abstract methods — control loops
    # ------------------------------------------------------------------

    @abstractmethod
    def get_setpoint(self, loop: int) -> float:
        """Return the current setpoint for control *loop* in Kelvin.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (float):
                Setpoint temperature in Kelvin.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_setpoint(1)
            300.0
        """

    @abstractmethod
    def set_setpoint(self, loop: int, value: float) -> None:
        """Set the target temperature for control *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            value (float):
                Desired setpoint in Kelvin.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *value* is outside the instrument's valid range.
        """

    @abstractmethod
    def get_loop_mode(self, loop: int) -> ControlMode:
        """Return the active control mode for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (ControlMode):
                Current control mode of the loop.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_loop_mode(1)
            <ControlMode.CLOSED_LOOP: 'closed_loop'>
        """

    @abstractmethod
    def set_loop_mode(self, loop: int, mode: ControlMode) -> None:
        """Set the control mode for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            mode (ControlMode):
                Desired control mode.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *mode* is not supported by this loop on this instrument.
        """

    # ------------------------------------------------------------------
    # Core abstract methods — heater outputs
    # ------------------------------------------------------------------

    @abstractmethod
    def get_heater_output(self, loop: int) -> float:
        """Return the heater output percentage for control *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (float):
                Heater output as a percentage (0–100 %).

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_heater_output(1)
            50.0
        """

    @abstractmethod
    def set_heater_range(self, loop: int, range_: int) -> None:
        """Set the heater range for control *loop*.

        The meaning of *range_* is instrument-specific.  A value of ``0``
        conventionally means "heater off".

        Args:
            loop (int):
                Control loop number (1-based).
            range_ (int):
                Heater range index (instrument-specific).

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    def get_heater_range(self, loop: int) -> int:
        """Return the current heater range index for control *loop*.

        The meaning of the returned index is instrument-specific.  A value of
        ``0`` conventionally means "heater off".

        Drivers that support reading the heater range should override this
        method.  The default implementation raises :class:`NotImplementedError`.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (int):
                Current heater range index.

        Raises:
            NotImplementedError:
                If the driver does not support reading the heater range.
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_heater_range(1)
            0
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support reading the heater range."
        )

    def set_manual_heater_output(self, loop: int, output: float) -> None:
        """Set the manual (open-loop) heater output percentage for *loop*.

        Used when the loop is in :attr:`~ControlMode.OPEN_LOOP` mode to drive
        the heater to a fixed percentage without PID feedback.

        The default implementation raises :class:`NotImplementedError`.
        Drivers that support open-loop heater output should override this method
        and set :attr:`ControllerCapabilities.has_manual_heater_output` to
        ``True`` in their capabilities descriptor.

        Args:
            loop (int):
                Control loop number (1-based).
            output (float):
                Desired heater output as a percentage (0–100 %).

        Raises:
            NotImplementedError:
                If the driver does not support manual heater output control.
                Check :attr:`ControllerCapabilities.has_manual_heater_output`
                before calling.
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *output* is outside 0–100 %.

        Examples:
            >>> tc.set_manual_heater_output(1, 25.0)
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support setting the manual heater output. "
            "Check get_capabilities().has_manual_heater_output before calling this method."
        )

    # ------------------------------------------------------------------
    # Core abstract methods — PID
    # ------------------------------------------------------------------

    @abstractmethod
    def get_pid(self, loop: int) -> PIDParameters:
        """Return the PID parameters for control *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (PIDParameters):
                Current proportional, integral and derivative gain values.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_pid(1)
            PIDParameters(p=50.0, i=1.0, d=0.0)
        """

    @abstractmethod
    def set_pid(self, loop: int, p: float, i: float, d: float) -> None:
        """Set the PID parameters for control *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            p (float):
                Proportional gain.
            i (float):
                Integral gain (reset).
            d (float):
                Derivative gain (rate).

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If any gain value is outside the instrument's valid range.
        """

    # ------------------------------------------------------------------
    # Core abstract methods — ramp control
    # ------------------------------------------------------------------

    @abstractmethod
    def get_ramp_rate(self, loop: int) -> float:
        """Return the setpoint ramp rate for *loop* in Kelvin per minute.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (float):
                Ramp rate in Kelvin per minute.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_ramp_rate(1)
            5.0
        """

    @abstractmethod
    def set_ramp_rate(self, loop: int, rate: float) -> None:
        """Set the setpoint ramp rate for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            rate (float):
                Ramp rate in Kelvin per minute.  A value of ``0`` typically
                disables ramping or sets an unlimited rate (instrument-specific).

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *rate* is negative or exceeds the instrument's maximum.
        """

    @abstractmethod
    def get_ramp_enabled(self, loop: int) -> bool:
        """Return ``True`` if setpoint ramping is enabled for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (bool):
                ``True`` when the ramp function is active.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_ramp_enabled(1)
            False
        """

    @abstractmethod
    def set_ramp_enabled(self, loop: int, enabled: bool) -> None:
        """Enable or disable setpoint ramping for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            enabled (bool):
                ``True`` to activate the ramp function, ``False`` to disable it.

        Raises:
            ConnectionError:
                If the transport is not open.
        """

    # ------------------------------------------------------------------
    # Core abstract method — capabilities
    # ------------------------------------------------------------------

    @abstractmethod
    def get_capabilities(self) -> ControllerCapabilities:
        """Return the static capability descriptor for this controller driver.

        Returns:
            (ControllerCapabilities):
                Descriptor advertising the number of inputs, loops, and
                which optional feature groups are supported.

        Examples:
            >>> caps = tc.get_capabilities()
            >>> caps.num_loops
            1
            >>> caps.has_ramp
            True
        """

    # ------------------------------------------------------------------
    # Concrete composite methods — built from core abstracts
    # ------------------------------------------------------------------

    def get_temperature_reading(self, channel: str) -> TemperatureReading:
        """Return a combined temperature value and sensor status for *channel*.

        Calls :meth:`get_temperature` and :meth:`get_sensor_status` and
        packages the results into a :class:`TemperatureReading`.  Drivers
        that can fetch both in a single query should override this method.

        Args:
            channel (str):
                Sensor channel identifier.

        Returns:
            (TemperatureReading):
                Current temperature in Kelvin with validity status.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> reading = tc.get_temperature_reading("A")
            >>> reading.value
            300.0
            >>> reading.status
            <SensorStatus.OK: 'ok'>
        """
        return TemperatureReading(
            value=self.get_temperature(channel),
            status=self.get_sensor_status(channel),
        )

    def get_ramp_state(self, loop: int) -> RampState:
        """Return the current ramp state for *loop*.

        The default implementation infers the state from
        :meth:`get_ramp_enabled`; override in subclasses that can query the
        actual hardware ramp state directly.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (RampState):
                :attr:`~RampState.RAMPING` when the ramp function is active,
                :attr:`~RampState.IDLE` otherwise.

        Raises:
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_ramp_state(1)
            <RampState.IDLE: 'idle'>
        """
        return RampState.RAMPING if self.get_ramp_enabled(loop) else RampState.IDLE

    def get_loop_status(self, loop: int) -> LoopStatus:
        """Return a comprehensive status snapshot for control *loop*.

        Calls all relevant core abstract methods and assembles a
        :class:`LoopStatus` dataclass.  Drivers that can retrieve all loop
        data in a single instrument query should override this method.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (LoopStatus):
                Complete current state of the control loop.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        pid = self.get_pid(loop)
        ramp_on = self.get_ramp_enabled(loop)
        channel = self.get_input_channel(loop)
        try:
            heater_range = self.get_heater_range(loop)
        except NotImplementedError:
            heater_range = 0
        return LoopStatus(
            setpoint=self.get_setpoint(loop),
            process_value=self.get_temperature(channel),
            mode=self.get_loop_mode(loop),
            heater_output=self.get_heater_output(loop),
            heater_range=heater_range,
            ramp_enabled=ramp_on,
            ramp_rate=self.get_ramp_rate(loop),
            ramp_state=self.get_ramp_state(loop),
            p=pid.p,
            i=pid.i,
            d=pid.d,
            input_channel=channel,
        )

    def get_controller_status(self) -> TemperatureStatus:
        """Return a full snapshot of all channels and loops.

        Uses :meth:`get_capabilities` to discover channels and loops, then
        assembles a :class:`TemperatureStatus` from :meth:`get_temperature_reading`
        and :meth:`get_loop_status`.

        Returns:
            (TemperatureStatus):
                Snapshot of all sensor readings and control-loop states.

        Raises:
            ConnectionError:
                If the transport is not open.
        """
        caps = self.get_capabilities()
        temperatures = {ch: self.get_temperature_reading(ch) for ch in caps.input_channels}
        loops = {lp: self.get_loop_status(lp) for lp in caps.loop_numbers}
        return TemperatureStatus(temperatures=temperatures, loops=loops)

    def wait_for_setpoint(  # pylint: disable=too-many-arguments
        self,
        loop: int,
        channel: str,
        *,
        tolerance: float = 0.5,
        timeout: float = 300.0,
        poll_period: float = 1.0,
    ) -> None:
        """Block until the temperature on *channel* is within *tolerance* of the setpoint.

        Polls :meth:`get_temperature` and :meth:`get_setpoint` at intervals of
        *poll_period* seconds until the absolute deviation falls within
        *tolerance*, or until *timeout* seconds have elapsed.

        Args:
            loop (int):
                Control loop whose setpoint is used as the target.
            channel (str):
                Sensor channel to monitor.

        Keyword Parameters:
            tolerance (float):
                Acceptable deviation from the setpoint in Kelvin.  Defaults to
                ``0.5``.
            timeout (float):
                Maximum time to wait in seconds.  Defaults to ``300.0``.
            poll_period (float):
                Interval between temperature polls in seconds.  Defaults to
                ``1.0``.

        Raises:
            TimeoutError:
                If the temperature does not reach the setpoint within
                *timeout* seconds.
            ConnectionError:
                If the transport is not open.
        """
        deadline = time.monotonic() + timeout
        target = self.get_setpoint(loop)
        current = self.get_temperature(channel)
        while time.monotonic() < deadline:
            if abs(current - target) <= tolerance:
                return
            time.sleep(poll_period)
            current = self.get_temperature(channel)
        raise TimeoutError(
            f"Temperature on channel '{channel}' did not reach setpoint {target} K "
            f"within {timeout} s (last reading: {current:.3f} K, "
            f"tolerance: {tolerance} K)."
        )

    def ramp_to_setpoint(
        self,
        loop: int,
        target: float,
        *,
        rate: float | None = None,
    ) -> None:
        """Set a new target setpoint for *loop*, optionally configuring the ramp rate.

        This convenience method performs the typical "ramp to a new temperature"
        sequence:

        1. If *rate* is given, set the ramp rate via :meth:`set_ramp_rate`.
        2. Enable ramping via :meth:`set_ramp_enabled` (only when the driver
           advertises :attr:`~ControllerCapabilities.has_ramp`).
        3. Write the new setpoint via :meth:`set_setpoint`.

        Callers that need to wait for the temperature to arrive should follow
        this call with :meth:`wait_for_setpoint`.

        Args:
            loop (int):
                Control loop number (1-based).
            target (float):
                Desired setpoint in Kelvin.

        Keyword Parameters:
            rate (float | None):
                Ramp rate in Kelvin per minute.  When provided, the rate is
                written to the instrument before the setpoint is updated.
                When ``None`` the currently programmed ramp rate is unchanged.
                Ignored if the driver does not advertise
                :attr:`~ControllerCapabilities.has_ramp`.

        Raises:
            ConnectionError:
                If the transport is not open.
            ValueError:
                If *target* or *rate* are outside the instrument's valid range.

        Examples:
            >>> tc.ramp_to_setpoint(1, 150.0, rate=5.0)
        """
        caps = self.get_capabilities()
        if caps.has_ramp:
            if rate is not None:
                self.set_ramp_rate(loop, rate)
            self.set_ramp_enabled(loop, True)
        self.set_setpoint(loop, target)

    # ------------------------------------------------------------------
    # Optional methods — alarm limits
    # ------------------------------------------------------------------

    def get_alarm_state(self, channel: str) -> AlarmState:
        """Return the current alarm state for sensor *channel*.

        Args:
            channel (str):
                Sensor channel identifier.

        Returns:
            (AlarmState):
                Current alarm condition.

        Raises:
            NotImplementedError:
                If the driver does not support alarm monitoring.
                Check :attr:`ControllerCapabilities.has_alarm` before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support alarm monitoring. "
            "Check get_capabilities().has_alarm before calling this method."
        )

    def get_alarm_limits(self, channel: str) -> tuple[float, float]:
        """Return the ``(low, high)`` alarm limits for sensor *channel* in Kelvin.

        Args:
            channel (str):
                Sensor channel identifier.

        Returns:
            (tuple[float, float]):
                ``(low_limit, high_limit)`` in Kelvin.

        Raises:
            NotImplementedError:
                If the driver does not support alarm limits.
                Check :attr:`ControllerCapabilities.has_alarm` before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support alarm limits. "
            "Check get_capabilities().has_alarm before calling this method."
        )

    def set_alarm_limits(self, channel: str, low: float, high: float) -> None:
        """Set the low and high alarm thresholds for sensor *channel*.

        Args:
            channel (str):
                Sensor channel identifier.
            low (float):
                Low-alarm temperature threshold in Kelvin.
            high (float):
                High-alarm temperature threshold in Kelvin.

        Raises:
            NotImplementedError:
                If the driver does not support alarm limits.
                Check :attr:`ControllerCapabilities.has_alarm` before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support alarm limits. "
            "Check get_capabilities().has_alarm before calling this method."
        )

    def set_alarm_enabled(self, channel: str, enabled: bool) -> None:
        """Enable or disable the alarm for sensor *channel*.

        Args:
            channel (str):
                Sensor channel identifier.
            enabled (bool):
                ``True`` to activate alarm checking, ``False`` to disable it.

        Raises:
            NotImplementedError:
                If the driver does not support alarms.
                Check :attr:`ControllerCapabilities.has_alarm` before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support alarms. "
            "Check get_capabilities().has_alarm before calling this method."
        )

    # ------------------------------------------------------------------
    # Optional methods — zone / table control
    # ------------------------------------------------------------------

    def get_num_zones(self, loop: int) -> int:
        """Return the number of configured zones for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (int):
                Number of zones configured in the zone table.

        Raises:
            NotImplementedError:
                If the driver does not support zone control.
                Check :attr:`ControllerCapabilities.has_zone` before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support zone control. "
            "Check get_capabilities().has_zone before calling this method."
        )

    def get_zone(self, loop: int, zone_index: int) -> ZoneEntry:
        """Return the parameters of zone entry *zone_index* for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            zone_index (int):
                Zone entry index (1-based).

        Returns:
            (ZoneEntry):
                Zone parameters including PID gains, ramp rate, heater range
                and heater output power for this table entry.

        Raises:
            NotImplementedError:
                If the driver does not support zone control.
                Check :attr:`ControllerCapabilities.has_zone` before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support zone control. "
            "Check get_capabilities().has_zone before calling this method."
        )

    def set_zone(self, loop: int, zone_index: int, entry: ZoneEntry) -> None:
        """Write a zone table entry for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            zone_index (int):
                Zone entry index (1-based).
            entry (ZoneEntry):
                Zone parameters to write, including PID gains, ramp rate,
                heater range and heater output power.

        Raises:
            NotImplementedError:
                If the driver does not support zone control.
                Check :attr:`ControllerCapabilities.has_zone` before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support zone control. "
            "Check get_capabilities().has_zone before calling this method."
        )

    # ------------------------------------------------------------------
    # Optional methods — PID autotuning
    # ------------------------------------------------------------------

    def start_autotune(self, loop: int, mode: int = 0) -> None:
        """Start the PID autotuning sequence for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).

        Keyword Parameters:
            mode (int):
                Autotune mode (instrument-specific; commonly ``0`` = P only,
                ``1`` = P+I, ``2`` = P+I+D).  Defaults to ``0``.

        Raises:
            NotImplementedError:
                If the driver does not support autotuning.
                Check :attr:`ControllerCapabilities.has_autotune` before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support autotuning. "
            "Check get_capabilities().has_autotune before calling this method."
        )

    def get_autotune_status(self, loop: int) -> str:
        """Return the current autotune status for *loop* as a string.

        The returned string is instrument-specific; typical values include
        ``"idle"``, ``"running"``, ``"complete"``, and ``"failed"``.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (str):
                Human-readable autotune status.

        Raises:
            NotImplementedError:
                If the driver does not support autotuning.
                Check :attr:`ControllerCapabilities.has_autotune` before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support autotuning. "
            "Check get_capabilities().has_autotune before calling this method."
        )

    # ------------------------------------------------------------------
    # Optional methods — sensor excitation and filtering
    # ------------------------------------------------------------------

    def get_excitation(self, channel: str) -> float:
        """Return the excitation level applied to sensor *channel*.

        The excitation value and its units (voltage, current, or power) are
        instrument-specific.  Common examples: Lakeshore resistive-excitation
        in μV, or Oxford Mercury excitation in μA.

        Args:
            channel (str):
                Sensor channel identifier.

        Returns:
            (float):
                Excitation level in instrument-native units.

        Raises:
            NotImplementedError:
                If the driver does not support excitation configuration.
                Check :attr:`ControllerCapabilities.has_sensor_excitation`
                before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support excitation configuration. "
            "Check get_capabilities().has_sensor_excitation before calling this method."
        )

    def set_excitation(self, channel: str, value: float) -> None:
        """Set the excitation level for sensor *channel*.

        Args:
            channel (str):
                Sensor channel identifier.
            value (float):
                Excitation level in instrument-native units.

        Raises:
            NotImplementedError:
                If the driver does not support excitation configuration.
                Check :attr:`ControllerCapabilities.has_sensor_excitation`
                before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support excitation configuration. "
            "Check get_capabilities().has_sensor_excitation before calling this method."
        )

    def get_filter(self, channel: str) -> dict[str, object]:
        """Return the digital filter settings for sensor *channel*.

        The returned dictionary contains at minimum the keys ``"enabled"``
        (bool), ``"points"`` (int, number of readings averaged), and
        ``"window"`` (float, percentage window for filter reset).

        Args:
            channel (str):
                Sensor channel identifier.

        Returns:
            (dict[str, object]):
                Filter settings keyed by name.

        Raises:
            NotImplementedError:
                If the driver does not support filter configuration.
                Check :attr:`ControllerCapabilities.has_sensor_excitation`
                before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support filter configuration. "
            "Check get_capabilities().has_sensor_excitation before calling this method."
        )

    def set_filter(
        self,
        channel: str,
        *,
        enabled: bool,
        points: int,
        window: float,
    ) -> None:
        """Configure the digital filter for sensor *channel*.

        Args:
            channel (str):
                Sensor channel identifier.

        Keyword Parameters:
            enabled (bool):
                ``True`` to activate the filter, ``False`` to disable it.
            points (int):
                Number of readings to average (1 effectively disables averaging).
            window (float):
                Percentage deviation window that triggers a filter reset
                (0 disables window filtering).

        Raises:
            NotImplementedError:
                If the driver does not support filter configuration.
                Check :attr:`ControllerCapabilities.has_sensor_excitation`
                before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support filter configuration. "
            "Check get_capabilities().has_sensor_excitation before calling this method."
        )

    # ------------------------------------------------------------------
    # Optional methods — calibration curve assignment
    # ------------------------------------------------------------------

    def get_sensor_curve(self, channel: str) -> int:
        """Return the calibration curve number assigned to sensor *channel*.

        Args:
            channel (str):
                Sensor channel identifier.

        Returns:
            (int):
                Curve number (instrument-specific; ``0`` typically means no
                curve assigned).

        Raises:
            NotImplementedError:
                If the driver does not support user calibration curves.
                Check :attr:`ControllerCapabilities.has_user_curves` before
                calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support user calibration curves. "
            "Check get_capabilities().has_user_curves before calling this method."
        )

    def set_sensor_curve(self, channel: str, curve_num: int) -> None:
        """Assign calibration curve *curve_num* to sensor *channel*.

        Args:
            channel (str):
                Sensor channel identifier.
            curve_num (int):
                Curve number to assign (instrument-specific).

        Raises:
            NotImplementedError:
                If the driver does not support user calibration curves.
                Check :attr:`ControllerCapabilities.has_user_curves` before
                calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support user calibration curves. "
            "Check get_capabilities().has_user_curves before calling this method."
        )

    # ------------------------------------------------------------------
    # Optional methods — input channel settings
    # ------------------------------------------------------------------

    def get_input_channel_settings(self, channel: str) -> InputChannelSettings:
        """Return the configuration settings for sensor input *channel*.

        Reads the sensor type, range, filter, and calibration-curve assignment
        for the specified input channel.  The returned
        :class:`InputChannelSettings` instance may contain ``None`` for fields
        that the driver does not support.

        Args:
            channel (str):
                Sensor channel identifier.

        Returns:
            (InputChannelSettings):
                Current configuration of the input channel.

        Raises:
            NotImplementedError:
                If the driver does not support input channel configuration.
                Check :attr:`ControllerCapabilities.has_input_settings`
                before calling.
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> # ctrl.get_input_channel_settings("A")  # requires live instrument
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support input channel settings. "
            "Check get_capabilities().has_input_settings before calling this method."
        )

    def set_input_channel_settings(self, channel: str, settings: InputChannelSettings) -> None:
        """Apply configuration settings to sensor input *channel*.

        Writes the sensor type, range, filter, and calibration-curve
        assignment from *settings* to the instrument.  Fields that are
        ``None`` in *settings* are not changed on the instrument.

        Args:
            channel (str):
                Sensor channel identifier.
            settings (InputChannelSettings):
                Configuration to apply.  ``None`` fields are ignored.

        Raises:
            NotImplementedError:
                If the driver does not support input channel configuration.
                Check :attr:`ControllerCapabilities.has_input_settings`
                before calling.
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> from stoner_measurement.instruments.temperature_controller import InputChannelSettings
            >>> s = InputChannelSettings(filter_enabled=True, filter_points=10, filter_window=2.0)
            >>> # ctrl.set_input_channel_settings("A", s)  # requires live instrument
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support input channel settings. "
            "Check get_capabilities().has_input_settings before calling this method."
        )

    # ------------------------------------------------------------------
    # Optional methods — cryogen / auxiliary outputs
    # ------------------------------------------------------------------

    def get_gas_flow(self) -> float:
        """Return the cryogen gas-flow valve position as a percentage.

        Returns:
            (float):
                Gas-flow valve opening as a percentage (0–100 %).

        Raises:
            NotImplementedError:
                If the driver does not support cryogen flow control.
                Check :attr:`ControllerCapabilities.has_cryogen_control`
                before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support cryogen flow control. "
            "Check get_capabilities().has_cryogen_control before calling this method."
        )

    def set_gas_flow(self, percent: float) -> None:
        """Set the cryogen gas-flow valve to *percent* open.

        Args:
            percent (float):
                Desired valve opening as a percentage (0–100 %).

        Raises:
            NotImplementedError:
                If the driver does not support cryogen flow control.
                Check :attr:`ControllerCapabilities.has_cryogen_control`
                before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support cryogen flow control. "
            "Check get_capabilities().has_cryogen_control before calling this method."
        )

    def get_needle_valve(self) -> float:
        """Return the needle-valve (gas-flow restrictor) position as a percentage.

        Returns:
            (float):
                Needle-valve position as a percentage (0 = fully closed,
                100 = fully open).

        Raises:
            NotImplementedError:
                If the driver does not support needle-valve control.
                Check :attr:`ControllerCapabilities.has_cryogen_control`
                before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support needle-valve control. "
            "Check get_capabilities().has_cryogen_control before calling this method."
        )

    def set_needle_valve(self, position: float) -> None:
        """Set the needle-valve position.

        Args:
            position (float):
                Desired position as a percentage (0 = fully closed,
                100 = fully open).

        Raises:
            NotImplementedError:
                If the driver does not support needle-valve control.
                Check :attr:`ControllerCapabilities.has_cryogen_control`
                before calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support needle-valve control. "
            "Check get_capabilities().has_cryogen_control before calling this method."
        )

    def get_gas_auto(self) -> bool:
        """Return ``True`` if the gas/needle-valve is in automatic control mode.

        In automatic mode the controller determines the gas-flow position itself;
        in manual mode the operator-set position is used directly.

        Drivers that support querying the gas auto mode should override this
        method.  The default implementation raises :class:`NotImplementedError`.

        Returns:
            (bool):
                ``True`` when the gas flow is under automatic control.

        Raises:
            NotImplementedError:
                If the driver does not support gas auto mode.
                Check :attr:`ControllerCapabilities.has_gas_auto_mode` before
                calling.
            ConnectionError:
                If the transport is not open.

        Examples:
            >>> tc.get_gas_auto()
            False
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support gas auto mode. "
            "Check get_capabilities().has_gas_auto_mode before calling this method."
        )

    def set_gas_auto(self, auto: bool) -> None:
        """Enable or disable automatic gas/needle-valve control.

        Args:
            auto (bool):
                ``True`` to engage automatic gas-flow control; ``False`` to
                switch to manual control.

        Raises:
            NotImplementedError:
                If the driver does not support gas auto mode.
                Check :attr:`ControllerCapabilities.has_gas_auto_mode` before
                calling.
            ConnectionError:
                If the transport is not open.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support gas auto mode. "
            "Check get_capabilities().has_gas_auto_mode before calling this method."
        )
