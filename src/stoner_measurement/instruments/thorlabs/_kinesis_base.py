"""Shared Kinesis motor base class for Thorlabs pylablib drivers.

Provides the common connection lifecycle, motion-command, position-query, and
tolerant pylablib API-probing logic used by all Thorlabs Kinesis-backed drivers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from stoner_measurement.instruments.motor_controller import (
    MotorController,
    MotorMoveDirection,
    MotorStatus,
)
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.null_transport import NullTransport

_MotorFactory = Callable[[str], Any]
_MISSING = object()


class _KinesisMotorBase(MotorController):
    """Shared base for Thorlabs pylablib/Kinesis motor drivers.

    Handles all common Kinesis motor operations: connection lifecycle, motion
    commands, position queries, and tolerant API probing via
    :meth:`_call_first_available`.

    Subclasses must set the following class attributes:

    - ``_EXPECTED_IDENTITY_TOKENS`` – tokens used by :meth:`confirm_identity`.
    - ``_DEFAULT_MODEL`` – fallback model name used in :meth:`identify`.
    - ``_DEVICE_NAME`` – human-readable device name for error messages.

    Args:
        serial_number (str):
            Kinesis serial number of the motor controller.

    Keyword Parameters:
        motor_factory (_MotorFactory | None):
            Optional factory used to create the pylablib motor object.
            Primarily intended for tests.
    """

    _DEFAULT_MODEL: str = "UnknownKinesis"
    _DEVICE_NAME: str = "Thorlabs Kinesis"

    def __init__(
        self,
        serial_number: str,
        *,
        motor_factory: _MotorFactory | None = None,
    ) -> None:
        """Initialise the Kinesis motor driver.

        Args:
            serial_number (str):
                Kinesis serial number of the motor controller.

        Keyword Parameters:
            motor_factory (_MotorFactory | None):
                Optional factory used to create the pylablib motor object.
                Primarily intended for tests.
        """
        super().__init__(transport=NullTransport(), protocol=ScpiProtocol())
        self.auto_check_errors = False
        self._serial_number = serial_number
        self._motor_factory = motor_factory
        self._motor: Any | None = None
        self._target_angle: float | None = None

    @property
    def is_connected(self) -> bool:
        """Return ``True`` when the underlying pylablib motor is connected."""
        return self._motor is not None

    def connect(self) -> None:
        """Open a pylablib/Kinesis connection."""
        if self._motor is not None:
            return
        self._motor = self._build_motor()
        try:
            self.confirm_identity()
        except Exception:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        """Close the pylablib/Kinesis connection."""
        if self._motor is None:
            return
        close = getattr(self._motor, "close", None)
        if callable(close):
            close()  # pylint: disable=not-callable
        self._motor = None

    def identify(self) -> str:
        """Return a Kinesis device identity string.

        Returns:
            (str):
                Identity string in the form ``"Thorlabs,<model>,<serial>"``.
        """
        if self._motor is None:
            return f"Thorlabs,{self._DEFAULT_MODEL},{self._serial_number}"
        model = self._call_first_available(("get_model",), default=None)
        if model is None:
            model = self._query_kinesis_description() or self._DEFAULT_MODEL
        serial = self._call_first_available(("get_serial", "get_serial_number"), default=self._serial_number)
        return f"Thorlabs,{model},{serial}"

    def set_velocity(self, velocity: float) -> None:
        """Set motion velocity in degrees per second."""
        if velocity <= 0:
            raise ValueError(f"velocity must be positive, got {velocity}.")
        self._ensure_connected()
        if self._call_first_available(
            ("setup_velocity",),
            max_velocity=velocity,
            acceleration=None,
        ) is not _MISSING:
            return
        if self._call_first_available(("set_velocity",), velocity) is not _MISSING:
            return
        raise NotImplementedError("Motor object does not expose a supported velocity API.")

    def set_acceleration(self, acceleration: float) -> None:
        """Set motion acceleration in degrees per second squared."""
        if acceleration <= 0:
            raise ValueError(f"acceleration must be positive, got {acceleration}.")
        self._ensure_connected()
        if self._call_first_available(
            ("setup_velocity",),
            max_velocity=None,
            acceleration=acceleration,
        ) is not _MISSING:
            return
        if self._call_first_available(("set_acceleration",), acceleration) is not _MISSING:
            return
        raise NotImplementedError("Motor object does not expose a supported acceleration API.")

    def move_to_angle(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        """Move to an absolute angular position in degrees."""
        del direction
        self._ensure_connected()
        self._target_angle = angle
        if self._call_first_available(("move_to",), angle) is not _MISSING:
            return
        raise NotImplementedError("Motor object does not expose move_to().")

    def move_relative(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        """Move by *angle* degrees in *direction*."""
        self._ensure_connected()
        signed_angle = abs(float(angle))
        if direction is MotorMoveDirection.COUNTERCLOCKWISE:
            signed_angle = -signed_angle
        self._target_angle = self.get_position() + signed_angle
        if self._call_first_available(("move_by", "move_relative"), signed_angle) is not _MISSING:
            return
        if self._call_first_available(("move_to",), self._target_angle) is not _MISSING:
            return
        raise NotImplementedError("Motor object does not expose a supported relative or absolute move API.")

    def move_home(self) -> None:
        """Move to the configured home position."""
        self._ensure_connected()
        self._target_angle = None
        if self._call_first_available(("home", "move_home")) is not _MISSING:
            return
        raise NotImplementedError("Motor object does not expose home() or move_home().")

    def set_home(self, angle: float = 0.0) -> None:
        """Set current position reference to a home angle."""
        self._ensure_connected()
        if self._call_first_available(("set_position_reference",), angle) is not _MISSING:
            self._target_angle = angle
            return
        if self._call_first_available(("set_position",), angle) is not _MISSING:
            self._target_angle = angle
            return
        raise NotImplementedError("Motor object does not expose a supported set-home API.")

    def get_position(self) -> float:
        """Return the current angular position in degrees."""
        self._ensure_connected()
        value = self._call_first_available(("get_position",), default=_MISSING)
        if value is _MISSING:
            raise NotImplementedError("Motor object does not expose get_position().")
        return float(value)

    def get_target_position(self) -> float | None:
        """Return the current target angle, if known."""
        return self._target_angle

    def is_moving(self) -> bool:
        """Return ``True`` when movement is currently active."""
        self._ensure_connected()
        moving = self._call_first_available(("is_moving", "is_in_motion"), default=_MISSING)
        if moving is _MISSING:
            raise NotImplementedError("Motor object does not expose a supported motion-state API.")
        return bool(moving)

    def has_reached_target_position(self, tolerance: float = 0.01) -> bool:
        """Return ``True`` when not moving and current angle matches target."""
        if tolerance < 0:
            raise ValueError(f"tolerance must be non-negative, got {tolerance}.")
        target = self.get_target_position()
        if target is None:
            return not self.is_moving()
        return (not self.is_moving()) and abs(self.get_position() - target) <= tolerance

    @property
    def status(self) -> MotorStatus:
        """Return a consolidated Kinesis motor status snapshot."""
        return MotorStatus(
            current_angle=self.get_position(),
            target_angle=self.get_target_position(),
            moving=self.is_moving(),
            homed=self._read_homed_state(),
        )

    def _ensure_connected(self) -> None:
        if self._motor is None:
            raise ConnectionError(f"Thorlabs {self._DEVICE_NAME} is not connected.")

    def _build_motor(self) -> Any:
        factory = self._motor_factory
        if factory is None:
            from pylablib.devices import (
                Thorlabs,  # pylint: disable=import-outside-toplevel
            )

            factory = Thorlabs.KinesisMotor
        return factory(self._serial_number)

    def _call_first_available(
        self,
        names: tuple[str, ...],
        *args: Any,
        default: Any = _MISSING,
        **kwargs: Any,
    ) -> Any:
        self._ensure_connected()
        for name in names:
            func = getattr(self._motor, name, None)
            if not callable(func):
                continue
            if kwargs:
                cleaned_kwargs = {key: value for key, value in kwargs.items() if value is not None}
                return func(*args, **cleaned_kwargs)
            return func(*args)
        return default

    def _query_kinesis_description(self) -> str | None:
        """Look up this serial number in pylablib's Kinesis device list.

        Returns the device description string if found, or ``None`` when the
        device is not listed or pylablib is unavailable.
        """
        try:
            from pylablib.devices import (
                Thorlabs,  # pylint: disable=import-outside-toplevel
            )

            devices = dict(Thorlabs.list_kinesis_devices())
            return devices.get(self._serial_number)
        except Exception:
            return None

    def _read_homed_state(self) -> bool | None:
        if self._motor is None:
            return None
        for name in ("is_homed", "get_homed"):
            func = getattr(self._motor, name, None)
            if callable(func):
                return bool(func())  # pylint: disable=not-callable
        return None
