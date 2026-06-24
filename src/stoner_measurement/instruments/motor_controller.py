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
    TOWARDS_ZERO = "towards_zero"


def _display_signed_angle(angle: float) -> float:
    """Return angle displayed in the conventional signed wrapped range [-180, 180]."""
    wrapped = wrap_angle_360(angle)
    if wrapped > 180.0:
        return wrapped - 360.0
    if _is_effectively_equal(wrapped, 180.0):
        return 180.0
    return wrapped


def wrap_angle_360(angle: float) -> float:
    """Normalise *angle* into the half-open interval ``[0, 360)``."""
    wrapped = float(angle) % 360.0
    if wrapped < 0.0:
        wrapped += 360.0
    return wrapped


def _is_effectively_equal(angle_a: float, angle_b: float, tolerance: float = 1e-9) -> bool:
    """Return ``True`` when two angles are numerically equal within tolerance."""
    return abs(float(angle_a) - float(angle_b)) <= tolerance


def _is_signed_180_pair(current_angle: float, target_angle: float) -> bool:
    """Return ``True`` for the special case of ``+180`` to ``-180`` or vice versa."""
    return (
        _is_effectively_equal(abs(float(current_angle)), 180.0)
        and _is_effectively_equal(abs(float(target_angle)), 180.0)
        and float(current_angle) * float(target_angle) < 0.0
    )


def _path_crosses_threshold(
    start_wrapped: float,
    delta: float,
    threshold_wrapped: float,
) -> bool:
    """Return ``True`` when the wrapped move path passes through a threshold angle."""
    if abs(delta) <= 0.0:
        return False

    end_unwrapped = start_wrapped + delta
    low = min(start_wrapped, end_unwrapped)
    high = max(start_wrapped, end_unwrapped)
    threshold = wrap_angle_360(threshold_wrapped)

    start_cycle = int((low - threshold) // 360.0)
    end_cycle = int((high - threshold) // 360.0)
    for cycle in range(start_cycle, end_cycle + 1):
        crossing = threshold + 360.0 * cycle
        if low < crossing <= high:
            return True
    return False


def _path_stays_within_safe_window(
    start_wrapped: float,
    delta: float,
    clockwise_limit: float,
    counterclockwise_limit: float,
) -> bool:
    """Return ``True`` when the move stays within the configured safe window."""
    if abs(delta) <= 0.0:
        return True
    if delta > 0.0:
        return not _path_crosses_threshold(start_wrapped, delta, clockwise_limit)
    return not _path_crosses_threshold(start_wrapped, delta, counterclockwise_limit)


def _distance_from_safe_window_boundary(
    start_wrapped: float, delta: float, clockwise_limit: float, counterclockwise_limit: float
) -> float:
    """Return the distance between the path and the relevant configured safe boundary."""
    end_wrapped = wrap_angle_360(start_wrapped + delta)
    if abs(delta) <= 0.0:
        clockwise_margin = min(abs(start_wrapped - clockwise_limit), abs(end_wrapped - clockwise_limit))
        counterclockwise_margin = min(
            abs(start_wrapped - counterclockwise_limit),
            abs(end_wrapped - counterclockwise_limit),
        )
        return min(clockwise_margin, counterclockwise_margin)
    if delta > 0.0:
        if _path_crosses_threshold(start_wrapped, delta, clockwise_limit):
            return 0.0
        return min(abs(start_wrapped - clockwise_limit), abs(end_wrapped - clockwise_limit))
    if _path_crosses_threshold(start_wrapped, delta, counterclockwise_limit):
        return 0.0
    return min(abs(start_wrapped - counterclockwise_limit), abs(end_wrapped - counterclockwise_limit))


def resolve_wrapped_target_angle(
    current_angle: float,
    target_angle: float,
    direction: MotorMoveDirection,
    clockwise_limit: float = 190.0,
    counterclockwise_limit: float = 170.0,
) -> float:
    """Resolve a wrapped target angle into an absolute target angle."""
    current = float(current_angle)
    target = float(target_angle)
    current_wrapped = wrap_angle_360(current)
    target_wrapped = wrap_angle_360(target)
    if direction is MotorMoveDirection.CLOCKWISE:
        delta = (target_wrapped - current_wrapped) % 360.0
        return current + delta
    if direction is MotorMoveDirection.COUNTERCLOCKWISE:
        delta = -((current_wrapped - target_wrapped) % 360.0)
        return current + delta
    if _is_signed_180_pair(current, target):
        if current > 0.0 and target < 0.0:
            counterclockwise_delta = -360.0
            return current + counterclockwise_delta
        if current < 0.0 and target > 0.0:
            clockwise_delta = 360.0
            return current + clockwise_delta
    clockwise_delta = (target_wrapped - current_wrapped) % 360.0
    counterclockwise_delta = -((current_wrapped - target_wrapped) % 360.0)
    clockwise_is_safe = _path_stays_within_safe_window(
        current_wrapped, clockwise_delta, clockwise_limit, counterclockwise_limit
    )
    counterclockwise_is_safe = _path_stays_within_safe_window(
        current_wrapped, counterclockwise_delta, clockwise_limit, counterclockwise_limit
    )

    if clockwise_is_safe and not counterclockwise_is_safe:
        return current + clockwise_delta
    if counterclockwise_is_safe and not clockwise_is_safe:
        return current + counterclockwise_delta
    if clockwise_is_safe and counterclockwise_is_safe:
        if abs(clockwise_delta) < abs(counterclockwise_delta):
            return current + clockwise_delta
        if abs(counterclockwise_delta) < abs(clockwise_delta):
            return current + counterclockwise_delta

    clockwise_distance = _distance_from_safe_window_boundary(
        current_wrapped, clockwise_delta, clockwise_limit, counterclockwise_limit
    )
    counterclockwise_distance = _distance_from_safe_window_boundary(
        current_wrapped, counterclockwise_delta, clockwise_limit, counterclockwise_limit
    )
    if clockwise_distance > counterclockwise_distance:
        return current + clockwise_delta
    if counterclockwise_distance > clockwise_distance:
        return current + counterclockwise_delta
    clockwise_target = current + clockwise_delta
    counterclockwise_target = current + counterclockwise_delta
    if abs(_display_signed_angle(counterclockwise_target)) < abs(_display_signed_angle(clockwise_target)):
        return counterclockwise_target
    if abs(_display_signed_angle(clockwise_target)) < abs(_display_signed_angle(counterclockwise_target)):
        return clockwise_target
    if abs(counterclockwise_target) < abs(clockwise_target):
        return counterclockwise_target
    if abs(clockwise_target) < abs(counterclockwise_target):
        return clockwise_target
    if _display_signed_angle(counterclockwise_target) < _display_signed_angle(clockwise_target):
        return counterclockwise_target
    if clockwise_delta <= abs(counterclockwise_delta):
        return current + clockwise_delta
    return current + counterclockwise_delta


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
