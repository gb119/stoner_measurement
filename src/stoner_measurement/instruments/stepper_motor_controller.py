"""Abstract interfaces for stepper motor controller instruments."""

from __future__ import annotations

import time
from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from stoner_measurement.instruments.base_instrument import BaseInstrument

if TYPE_CHECKING:
    from stoner_measurement.instruments.protocol.base import BaseProtocol
    from stoner_measurement.instruments.transport.base import BaseTransport


@dataclass
class StepperMotorStatus:
    """Consolidated status snapshot of a stepper motor controller.

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
    """

    current_angle: float
    target_angle: float | None
    moving: bool
    homed: bool | None = None


class StepperMotor(Protocol):
    """Protocol describing the expected stepper motor interface."""

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

    def move_to_angle(self, angle: float) -> None:
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


class StepperMotorController(BaseInstrument):
    """Abstract base class for stepper motor controller drivers."""

    def __init__(self, transport: BaseTransport, protocol: BaseProtocol) -> None:
        """Initialise the stepper motor controller base class.

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
    def move_to_angle(self, angle: float) -> None:
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
    def status(self) -> StepperMotorStatus:
        """Return a consolidated stepper-motor status snapshot."""
        return StepperMotorStatus(
            current_angle=self.get_position(),
            target_angle=self.get_target_position(),
            moving=self.is_moving(),
            homed=None,
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
        raise TimeoutError("Timed out waiting for stepper motor to reach target position.")
