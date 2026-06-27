"""Abstract interfaces for motor controller instruments."""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


class MotorMoveDirection(Enum):
    """Direction policy for wrapped angular moves."""

    CLOCKWISE = "clockwise"
    COUNTERCLOCKWISE = "counterclockwise"
    SHORTEST = "shortest"
    # Backwards-compatible alias for older saved configurations/tests.
    TOWARDS_ZERO = "towards_zero"


def wrap_angle_360(angle: float) -> float:
    """Normalise *angle* into the half-open interval ``[0, 360)``."""
    wrapped = float(angle) % 360.0
    if wrapped < 0.0:
        wrapped += 360.0
    return wrapped


@dataclass(frozen=True)
class MotorMovePlan:
    """Resolved relative motor move."""

    current_angle: float
    target_angle: float
    relative_angle: float
    direction: MotorMoveDirection


def resolve_wrapped_target_angle(
    current_angle: float,
    target_angle: float,
    direction: MotorMoveDirection,
    clockwise_limit: float = 190.0,
    counterclockwise_limit: float = 170.0,
) -> float:
    """Resolve a target angle for legacy callers using the larger configured soft limit."""
    soft_limit = max(abs(float(clockwise_limit)), abs(float(counterclockwise_limit)))
    return resolve_relative_motor_move(current_angle, target_angle, direction, soft_limit=soft_limit).target_angle


def resolve_relative_motor_move(
    current_angle: float,
    target_angle: float,
    direction: MotorMoveDirection,
    *,
    soft_limit: float,
    force: bool = False,
) -> MotorMovePlan:
    """Resolve a requested angle into a relative move inside ``±soft_limit``."""
    limit = abs(float(soft_limit))
    current = _normalise_angle_to_soft_limit(current_angle, limit)
    target = _normalise_angle_to_soft_limit(target_angle, limit)
    requested_direction = _normalise_move_direction(direction)
    resolved_direction = requested_direction

    if requested_direction is MotorMoveDirection.CLOCKWISE:
        while target < current:
            target += 360.0
    elif requested_direction is MotorMoveDirection.COUNTERCLOCKWISE:
        while target > current:
            target -= 360.0
    else:
        resolved_direction = (
            MotorMoveDirection.COUNTERCLOCKWISE
            if target < current
            else MotorMoveDirection.CLOCKWISE
        )

    if not force and not -limit <= target <= limit:
        raise ValueError(
            f"Motor target {target:.3f}° exceeds the configured soft-limit range "
            f"-{limit:.3f}° to +{limit:.3f}°."
        )

    return MotorMovePlan(
        current_angle=current,
        target_angle=target,
        relative_angle=abs(target - current),
        direction=resolved_direction,
    )


def _normalise_move_direction(direction: MotorMoveDirection) -> MotorMoveDirection:
    """Return the canonical direction mode."""
    if direction is MotorMoveDirection.TOWARDS_ZERO:
        return MotorMoveDirection.SHORTEST
    return direction


def _normalise_angle_to_soft_limit(angle: float, soft_limit: float) -> float:
    """Normalise *angle* into the ``[-soft_limit, +soft_limit]`` range."""
    if soft_limit < 180.0:
        raise ValueError(f"soft_limit must be at least 180 degrees, got {soft_limit}.")
    value = float(angle)
    while value > soft_limit:
        value -= 360.0
    while value < -soft_limit:
        value += 360.0
    return value


@dataclass
class MotorStatus:
    """Consolidated status snapshot of a motor controller.

    Attributes:
        current_angle (float):
            Current angular position in degrees.
        target_angle (float | None):
            Current commanded target angle in degrees, if known.
        moving (bool):
            ``True`` when motion is currently in progress.
        homed (bool | None):
            ``True`` when the stage reports a homed state, ``False`` when not
            homed, or ``None`` when unavailable.
        revolutions (int):
            Number of complete revolutions represented by the current absolute
            angle, rounded down in units of 360 degrees.
    """

    current_angle: float
    target_angle: float | None
    moving: bool
    homed: bool | None = None
    revolutions: int = 0


class Motor(Protocol):
    """Protocol describing the expected motor interface."""

    def connect(self) -> None:
        """Open the controller connection."""
        ...

    def disconnect(self) -> None:
        """Close the controller connection."""
        ...

    @property
    def is_connected(self) -> bool:
        """Return ``True`` when the controller is connected."""
        ...

    def identify(self) -> str:
        """Return an identity string for the controller."""
        ...

    def set_velocity(self, velocity: float) -> None:
        """Set travel velocity in degrees per second."""
        ...

    def set_acceleration(self, acceleration: float) -> None:
        """Set travel acceleration in degrees per second squared."""
        ...

    def move_to_angle(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        """Move to an absolute angle in degrees."""
        ...

    def move_relative(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        """Move by *angle* degrees in *direction*."""
        ...

    def move_home(self) -> None:
        """Move to the configured home position."""
        ...

    def set_home(self, angle: float = 0.0) -> None:
        """Set the current position reference to a home angle."""
        ...

    def get_position(self) -> float:
        """Return current angular position in degrees."""
        ...

    def get_target_position(self) -> float | None:
        """Return the current target angle in degrees, if known."""
        ...

    def is_moving(self) -> bool:
        """Return ``True`` when the motor is moving."""
        ...

    def has_reached_target_position(self, tolerance: float = 0.01) -> bool:
        """Return ``True`` when current and target positions are within tolerance."""
        ...


class MotorController(BaseInstrument):
    """Abstract base class for motor controller drivers."""

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol) -> None:
        """Initialise the motor controller base class.

        Args:
            transport (BaseTransport):
                Transport layer used for physical I/O.
            protocol (BaseProtocol):
                Protocol layer used for command formatting/parsing.
        """
        super().__init__(transport=transport, protocol=protocol)

    def connect(self) -> None:
        """Open the controller connection and verify identity."""
        super().connect()
        try:
            self.confirm_identity()
        except Exception:
            self.disconnect()
            raise

    @abstractmethod
    def set_velocity(self, velocity: float) -> None:
        """Set travel velocity in degrees per second."""

    @abstractmethod
    def set_acceleration(self, acceleration: float) -> None:
        """Set travel acceleration in degrees per second squared."""

    @abstractmethod
    def move_to_angle(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        """Move to an absolute angle in degrees."""

    def move_relative(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        """Move by *angle* degrees in *direction* using the absolute move API."""
        signed_angle = abs(float(angle))
        canonical_direction = _normalise_move_direction(direction)
        if canonical_direction is MotorMoveDirection.COUNTERCLOCKWISE:
            signed_angle = -signed_angle
        self.move_to_angle(self.get_position() + signed_angle, direction=canonical_direction)

    @abstractmethod
    def move_home(self) -> None:
        """Move to the configured home position."""

    @abstractmethod
    def set_home(self, angle: float = 0.0) -> None:
        """Set the current position reference to a home angle."""

    @abstractmethod
    def get_position(self) -> float:
        """Return current angular position in degrees."""

    @abstractmethod
    def get_target_position(self) -> float | None:
        """Return the current target angle in degrees, if known."""

    @abstractmethod
    def is_moving(self) -> bool:
        """Return ``True`` when the motor is moving."""

    @abstractmethod
    def has_reached_target_position(self, tolerance: float = 0.01) -> bool:
        """Return ``True`` when current and target positions are within tolerance."""

    @property
    def status(self) -> MotorStatus:
        """Return a consolidated motor status snapshot."""
        return MotorStatus(
            current_angle=self.get_position(),
            target_angle=self.get_target_position(),
            moving=self.is_moving(),
            homed=None,
            revolutions=int(self.get_position() // 360.0),
        )

    def wait_for_target_position(
        self,
        *,
        timeout: float = 120.0,
        poll_period: float = 0.05,
        tolerance: float = 0.01,
    ) -> None:
        """Wait until target position is reached or timeout expires."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.has_reached_target_position(tolerance=tolerance):
                return
            time.sleep(poll_period)
        raise TimeoutError("Timed out waiting for motor to reach target position.")

    def return_to_local(self) -> None:
        """Return the controller front panel to local/manual operation."""
        # Optional for many motor drivers; default to a no-op.
        return
