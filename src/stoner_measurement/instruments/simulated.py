"""Simulated instrument drivers for development and testing.

Provides concrete temperature-controller and magnet-controller drivers that
simulate realistic behaviour without requiring physical hardware.  The drivers
are ordinary instrument drivers and are therefore discovered automatically by
:class:`stoner_measurement.instruments.driver_manager.InstrumentDriverManager`.
"""

from __future__ import annotations

import time
from math import copysign

from stoner_measurement.instruments.magnet_controller import (
    HeaterState,
    MagnetController,
    MagnetLimits,
    MagnetState,
    MagnetStatus,
)
from stoner_measurement.instruments.motor_controller import (
    MotorController,
    MotorMoveDirection,
    MotorStatus,
)
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.temperature_controller import (
    ControllerCapabilities,
    ControlMode,
    PIDParameters,
    RampState,
    SensorStatus,
    TemperatureController,
)
from stoner_measurement.instruments.transport.null_transport import NullTransport


class SimulatedTemperatureController(TemperatureController):
    """Simple simulated temperature controller."""

    _EXPECTED_IDENTITY_TOKENS = ("SIMULATED TEMPERATURE CONTROLLER",)

    _CAPABILITIES = ControllerCapabilities(
        num_inputs=4,
        num_loops=2,
        input_channels=("A", "B", "C", "D"),
        loop_numbers=(1, 2),
        has_ramp=True,
        has_pid=True,
        heater_range_labels={1: ("Off", "Low", "Medium", "High"), 2: ("Off", "Low", "Medium", "High")},
    )

    def __init__(self, transport=None, protocol=None) -> None:
        super().__init__(
            transport=transport if transport is not None else NullTransport(),
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )
        self._temperature = 300.0
        self._last_update = time.monotonic()
        self._setpoints = {1: 300.0, 2: 300.0}
        self._active_setpoints = {1: 300.0, 2: 300.0}
        self._modes = {1: ControlMode.CLOSED_LOOP, 2: ControlMode.CLOSED_LOOP}
        self._inputs = {1: "A", 2: "B"}
        self._pid = {1: PIDParameters(20.0, 5.0, 0.0), 2: PIDParameters(20.0, 5.0, 0.0)}
        self._ramp_rates = {1: 10.0, 2: 10.0}
        self._ramp_enabled = {1: True, 2: True}
        self._heater_ranges = {1: 3, 2: 3}

    def identify(self) -> str:
        return "OpenAI,Simulated Temperature Controller,SIM001,1.0"

    def _update(self) -> None:
        now = time.monotonic()
        dt = now - self._last_update
        self._last_update = now

        for loop in (1, 2):
            target = self._setpoints[loop]
            active = self._active_setpoints[loop]

            if self._ramp_enabled[loop]:
                ramp_step = self._ramp_rates[loop] * dt / 60.0
                delta = target - active
                if abs(delta) <= ramp_step:
                    active = target
                else:
                    active += ramp_step if delta > 0.0 else -ramp_step
            else:
                active = target

            self._active_setpoints[loop] = active

        control_target = self._active_setpoints[1]
        self._temperature += (
            control_target - self._temperature
        ) * min(dt / 20.0, 1.0)

    def get_temperature(self, channel: str) -> float:
        self._update()
        offsets = {"A": 0.0, "B": 0.2, "C": 1.0, "D": 5.0}
        return self._temperature + offsets.get(channel, 0.0)

    def get_sensor_status(self, channel: str) -> SensorStatus:
        return SensorStatus.OK

    def get_input_channel(self, loop: int) -> str:
        return self._inputs[loop]

    def set_input_channel(self, loop: int, channel: str) -> None:
        self._inputs[loop] = channel

    def get_setpoint(self, loop: int) -> float:
        return self._setpoints[loop]

    def set_setpoint(self, loop: int, value: float) -> None:
        self._setpoints[loop] = value

    def get_loop_mode(self, loop: int) -> ControlMode:
        return self._modes[loop]

    def set_loop_mode(self, loop: int, mode: ControlMode) -> None:
        self._modes[loop] = mode

    def get_heater_output(self, loop: int) -> float:
        self._update()
        error = abs(
            self._active_setpoints[loop]
            - self.get_temperature(self._inputs[loop])
        )
        return min(error * 2.0, 100.0)

    def set_heater_range(self, loop: int, range_: int) -> None:
        self._heater_ranges[loop] = range_

    def get_heater_range(self, loop: int) -> int:
        return self._heater_ranges[loop]

    def get_pid(self, loop: int) -> PIDParameters:
        return self._pid[loop]

    def set_pid(self, loop: int, p: float, i: float, d: float) -> None:
        self._pid[loop] = PIDParameters(p, i, d)

    def get_ramp_rate(self, loop: int) -> float:
        return self._ramp_rates[loop]

    def set_ramp_rate(self, loop: int, rate: float) -> None:
        self._ramp_rates[loop] = rate

    def get_ramp_enabled(self, loop: int) -> bool:
        return self._ramp_enabled[loop]

    def set_ramp_enabled(self, loop: int, enabled: bool) -> None:
        self._ramp_enabled[loop] = enabled

    def get_ramp_state(self, loop: int) -> RampState:
        self._update()
        if abs(self._active_setpoints[loop] - self._setpoints[loop]) > 1e-9:
            return RampState.RAMPING
        return RampState.IDLE

    def get_capabilities(self) -> ControllerCapabilities:
        return self._CAPABILITIES


class SimulatedMagnetController(MagnetController):
    """Simple simulated superconducting magnet controller."""

    _EXPECTED_IDENTITY_TOKENS = ("SIMULATED MAGNET CONTROLLER",)

    def __init__(self, transport=None, protocol=None) -> None:
        super().__init__(
            transport=transport if transport is not None else NullTransport(),
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )
        self._last_update = time.monotonic()
        self._current = 0.0
        self._io_delay_s = 0.05
        self._target_current = 0.0
        self._ramp_rate_aps = 1.0
        self._heater = True
        self._magnet_constant = 0.1
        self._heater_state = HeaterState.ON
        self._persistent_field: float | None = None
        self._supply_current_at_persistent_entry: float | None = None
        self._limits = MagnetLimits(max_current=100.0, max_field=10.0, max_ramp_rate=5.0)
        self._coil_resistance = 0.1
        self._coil_inductance = 3.0
        self._paused = False
        self._ramping = False

    def _simulate_io_delay(self) -> None:
        """Simulate finite hardware communication latency."""
        time.sleep(self._io_delay_s)

    def identify(self) -> str:
        return "OpenAI,Simulated Magnet Controller,SIMMAG001,1.0"

    def _update(self) -> None:
        now = time.monotonic()
        dt = now - self._last_update
        self._last_update = now
        if self._paused:
            self._ramping = False
            return
        step = self._ramp_rate_aps * dt
        delta = self._target_current - self._current
        if abs(delta) <= step:
            self._current = self._target_current
            self._ramping = False
        else:
            self._current += step if delta > 0 else -step
            self._ramping = True

    def get_model(self) -> str:
        return "Simulated Magnet Controller"

    def get_firmware_version(self) -> str:
        return "1.0"

    @property
    def current(self) -> float:
        self._simulate_io_delay()
        self._update()
        return self._current

    @property
    def field(self) -> float:
        self._simulate_io_delay()
        return self.current * self._magnet_constant

    @property
    def voltage(self) -> float:
        self._simulate_io_delay()
        current = self.current
        didt = 0.0
        if self._ramping:
            delta = self._target_current - current
            if abs(delta) > 1e-12:
                didt = self._ramp_rate_aps if delta > 0 else -self._ramp_rate_aps
        return self._coil_inductance * didt

    @property
    def status(self) -> MagnetStatus:
        self._simulate_io_delay()
        current = self.current
        at_target = abs(self._target_current - current) < 1e-6

        if self._heater_state is HeaterState.WARMING:
            self._heater_state = HeaterState.ON

        if at_target:
            state = MagnetState.AT_TARGET
        elif self._ramping:
            state = MagnetState.RAMPING
        else:
            state = MagnetState.STANDBY

        return MagnetStatus(
            state=state,
            current=current,
            field=current * self._magnet_constant,
            voltage=self.voltage,
            persistent=self._heater_state is HeaterState.OFF,
            heater_on=self._heater_state is HeaterState.ON,
            heater_state=self._heater_state,
            persistent_field=self._persistent_field,
            at_target=at_target,
        )

    @property
    def magnet_constant(self) -> float:
        return self._magnet_constant

    @property
    def limits(self) -> MagnetLimits:
        return self._limits

    @property
    def heater(self) -> bool:
        return self._heater_state is HeaterState.ON

    def set_target_current(self, current: float) -> None:
        self._simulate_io_delay()
        self._target_current = current

    def set_target_field(self, field: float) -> None:
        self._simulate_io_delay()
        self._target_current = field / self._magnet_constant

    def set_ramp_rate_current(self, rate: float) -> None:
        self._simulate_io_delay()
        self._ramp_rate_aps = rate / 60.0

    def set_ramp_rate_field(self, rate: float) -> None:
        self._simulate_io_delay()
        self._ramp_rate_aps = rate / 60.0 / self._magnet_constant

    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        self._simulate_io_delay()
        self._magnet_constant = tesla_per_amp

    def set_limits(self, limits: MagnetLimits) -> None:
        self._simulate_io_delay()
        self._limits = limits

    def ramp_to_target(self) -> None:
        self._simulate_io_delay()
        if self._heater_state in {HeaterState.WARMING, HeaterState.COOLING}:
            raise RuntimeError("Cannot ramp while the switch heater is in transition.")
        self._paused = False
        self._ramping = abs(self._target_current - self._current) > 1e-6

    def ramp_to_current(self, current: float, *, wait: bool = False) -> None:
        self._simulate_io_delay()
        self.set_target_current(current)
        if self._heater_state in {HeaterState.WARMING, HeaterState.COOLING}:
            raise RuntimeError("Cannot ramp while the switch heater is in transition.")
        self._paused = False
        self._ramping = True

    def ramp_to_field(self, field: float, *, wait: bool = False) -> None:
        self._simulate_io_delay()
        self.set_target_field(field)
        if self._heater_state in {HeaterState.WARMING, HeaterState.COOLING}:
            raise RuntimeError("Cannot ramp while the switch heater is in transition.")
        self._paused = False
        self._ramping = True

    def pause_ramp(self) -> None:
        self._simulate_io_delay()
        self._paused = True
        self._ramping = False

    def hold(self) -> None:
        """Hold the present output without changing field."""
        self._simulate_io_delay()
        self.pause_ramp()

    def go_to_zero(self) -> None:
        """Ramp the simulated supply output to zero."""
        self._simulate_io_delay()
        self._target_current = 0.0
        self._paused = False
        self._ramping = abs(self._current) > 1e-6

    def abort_ramp(self) -> None:
        self._simulate_io_delay()
        self._target_current = self.current
        self._paused = True
        self._ramping = False

    def heater_on(self) -> None:
        self._simulate_io_delay()
        persistent_entry_current = self._supply_current_at_persistent_entry or 0.0
        if self._persistent_field is not None and abs(self._current - persistent_entry_current) > 1e-6:
            raise RuntimeError(
                "Cannot turn heater on in persistent mode until the supply "
                "current matches the trapped persistent current."
            )
        self._heater_state = HeaterState.WARMING
        self._heater = True

    def heater_off(self) -> None:
        self._simulate_io_delay()
        self._persistent_field = self.field
        self._supply_current_at_persistent_entry = self.current
        self._heater_state = HeaterState.COOLING
        self._heater = False
        self._heater_state = HeaterState.OFF

    def return_to_local(self) -> None:
        """No-op for the simulated controller, which has no front panel."""
        self._simulate_io_delay()
        return


class SimulatedMotorController(MotorController):
    """Simple simulated motor controller."""

    _EXPECTED_IDENTITY_TOKENS = ("SIMULATED MOTOR CONTROLLER",)

    def __init__(self, transport=None, protocol=None) -> None:
        super().__init__(
            transport=transport if transport is not None else NullTransport(),
            protocol=protocol if protocol is not None else ScpiProtocol(),
        )
        self._last_update = time.monotonic()
        self._position = 0.0
        self._target_position = 0.0
        self._velocity = 10.0
        self._acceleration = 30.0
        self._current_velocity = 0.0
        self._home_position = 0.0
        self._homed = True
        self._moving = False

    def identify(self) -> str:
        return "OpenAI,Simulated Motor Controller,SIMMOTOR001,1.0"

    def _update(self) -> None:
        now = time.monotonic()
        dt = now - self._last_update
        self._last_update = now

        if not self._moving:
            self._current_velocity = 0.0
            return

        delta = self._target_position - self._position
        distance = abs(delta)
        direction = copysign(1.0, delta) if distance > 0.0 else 0.0

        if distance <= 1e-9:
            self._position = self._target_position
            self._moving = False
            self._current_velocity = 0.0
            return

        max_velocity = max(self._velocity, 1e-9)
        accel = max(self._acceleration, 1e-9)
        stopping_distance = (self._current_velocity ** 2) / (2.0 * accel)

        if stopping_distance >= distance:
            self._current_velocity = max(0.0, self._current_velocity - accel * dt)
        else:
            self._current_velocity = min(max_velocity, self._current_velocity + accel * dt)

        step = self._current_velocity * dt
        if step >= distance:
            self._position = self._target_position
            self._moving = False
            self._current_velocity = 0.0
        else:
            self._position += direction * step

    def set_velocity(self, velocity: float) -> None:
        self._velocity = max(float(velocity), 0.0)

    def set_acceleration(self, acceleration: float) -> None:
        self._acceleration = max(float(acceleration), 0.0)

    def move_to_angle(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        self._update()
        del direction
        self._target_position = float(angle)
        self._moving = abs(self._target_position - self._position) > 1e-9

    def move_relative(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        self._update()
        signed_angle = abs(float(angle))
        if direction is MotorMoveDirection.COUNTERCLOCKWISE:
            signed_angle = -signed_angle
        self._target_position = self._position + signed_angle
        self._moving = abs(self._target_position - self._position) > 1e-9

    def move_home(self) -> None:
        self.move_to_angle(self._home_position)

    def set_home(self, angle: float = 0.0) -> None:
        self._update()
        offset = self._position - float(angle)
        self._position -= offset
        self._target_position -= offset
        self._home_position = float(angle)
        self._homed = True

    def get_position(self) -> float:
        self._update()
        return self._position

    def get_target_position(self) -> float | None:
        self._update()
        return self._target_position

    def is_moving(self) -> bool:
        self._update()
        return self._moving

    def has_reached_target_position(self, tolerance: float = 0.01) -> bool:
        self._update()
        return abs(self._target_position - self._position) <= tolerance

    @property
    def status(self) -> MotorStatus:
        """Return a consolidated motor status snapshot."""
        return MotorStatus(
            current_angle=self.get_position(),
            target_angle=self.get_target_position(),
            moving=self.is_moving(),
            homed=self._homed,
            revolutions=int(self.get_position() // 360.0),
        )
