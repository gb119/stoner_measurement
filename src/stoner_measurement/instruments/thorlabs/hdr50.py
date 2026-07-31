"""Thorlabs HDR50 rotation-stage driver using the legacy APT ActiveX control."""

from __future__ import annotations

from collections.abc import Callable
import logging
import time
from typing import Any

import numpy as np

from stoner_measurement.instruments.motor_controller import (
    MotorController,
    MotorMoveDirection,
    MotorStatus,
)
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.transport.null_transport import NullTransport

logger = logging.getLogger(__name__)

_MotorFactory = Callable[[str], Any]
_APT_MOTOR_PROG_ID = "MGMOTOR.MGMotorCtrl.1"
_CHANNEL = 0
_MOVING_STATUS_MASK = 0x10 | 0x20
_HOMED_STATUS_MASK = 0x400
_COMMAND_RETRIES = 3
_COMMAND_SETTLE_S = 0.05
_POSITION_TOLERANCE_DEG = 0.01


class _AptActiveXMotor:
    """Small Python wrapper around Thorlabs' registered APT motor control."""

    def __init__(
        self,
        serial_number: str,
        *,
        dispatch: Callable[[str], Any] | None = None,
        settle_time: float = _COMMAND_SETTLE_S,
    ) -> None:
        self.serial_number = str(serial_number)
        self._settle_time = settle_time
        self._control: Any | None = None
        if dispatch is None:
            try:
                from win32com.client import Dispatch  # pylint: disable=import-outside-toplevel
            except ImportError as exc:
                logger.error(f"Failed at import of pywin32 for ThorLabs APT ActiveX control:{exc}")
                raise RuntimeError(
                    "Thorlabs HDR50 ActiveX support requires pywin32 and the Thorlabs APT software."
                ) from exc
            dispatch = Dispatch

        try:
            self._control = dispatch(_APT_MOTOR_PROG_ID)
            self._control.StartCtrl()
            self._control.HWSerialNum = int(self.serial_number)
            self._control.EnableHWChannel(_CHANNEL)
        except Exception as exc:
            logger.error(f"Failed at initialising Thorlab APT ActiveX control: {exc}")
            self.close()
            raise RuntimeError(
                "Could not start the Thorlabs APT motor ActiveX control. "
                "Install the Thorlabs APT software with matching Python bitness "
                f"and check controller serial number {self.serial_number}."
            ) from exc

    def close(self) -> None:
        control = self._control
        if control is not None:
            try:
                control.StopCtrl()
            finally:
                self._control = None

    def get_model(self) -> str:
        return "HDR50"

    def get_serial_number(self) -> str:
        return self.serial_number

    def get_position(self) -> float:
        return float(self._control.GetPosition_Position(_CHANNEL))

    def setup_velocity(
        self,
        *,
        max_velocity: float | None = None,
        acceleration: float | None = None,
    ) -> None:
        min_velocity, old_acceleration, old_max_velocity = self._velocity_parameters()
        requested_acceleration = old_acceleration if acceleration is None else float(acceleration)
        requested_max_velocity = old_max_velocity if max_velocity is None else float(max_velocity)

        for _attempt in range(_COMMAND_RETRIES):
            self._control.SetVelParams(_CHANNEL, min_velocity, requested_acceleration, requested_max_velocity)
            actual_min, actual_acceleration, actual_max_velocity = self._velocity_parameters()
            if (
                np.isclose(actual_min, min_velocity, rel_tol=1e-6, abs_tol=1e-6)
                and np.isclose(actual_acceleration, requested_acceleration, rel_tol=1e-6, abs_tol=1e-6)
                and np.isclose(actual_max_velocity, requested_max_velocity, rel_tol=1e-6, abs_tol=1e-6)
            ):
                return
            time.sleep(self._settle_time)
        raise RuntimeError("APT controller did not apply the requested velocity parameters.")

    def move_to(self, angle: float) -> None:
        target = float(angle)
        if np.isclose(self.get_position(), target, abs_tol=_POSITION_TOLERANCE_DEG):
            return

        for _attempt in range(_COMMAND_RETRIES):
            self._control.SetAbsMovePos(_CHANNEL, target)
            self._control.MoveAbsolute(_CHANNEL, False)
            time.sleep(self._settle_time)
            if self.is_moving() or np.isclose(
                self.get_position(),
                target,
                abs_tol=_POSITION_TOLERANCE_DEG,
            ):
                return
        raise RuntimeError(f"APT controller did not start the move to {target:g} degrees.")

    def move_relative(self, angle: float) -> None:
        self.move_to(self.get_position() + float(angle))

    def home(self) -> None:
        self._control.MoveHome(_CHANNEL, False)

    def set_position_reference(self, angle: float) -> None:
        self._control.SetPosition(_CHANNEL, float(angle))

    def is_moving(self) -> bool:
        return bool(abs(int(self._control.GetStatusBits_Bits(_CHANNEL))) & _MOVING_STATUS_MASK)

    def is_homed(self) -> bool:
        return bool(abs(int(self._control.GetStatusBits_Bits(_CHANNEL))) & _HOMED_STATUS_MASK)

    def _velocity_parameters(self) -> tuple[float, float, float]:
        return (
            float(self._control.GetVelParams_MinVel(_CHANNEL)),
            float(self._control.GetVelParams_Accn(_CHANNEL)),
            float(self._control.GetVelParams_MaxVel(_CHANNEL)),
        )


class ThorlabsHDR50(MotorController):
    """Control an HDR50/BSC201 through the Thorlabs APT ActiveX interface."""

    _EXPECTED_IDENTITY_TOKENS = ("Thorlabs", "HDR50")
    preferred_connection_transport = "Kinesis USB"

    def __init__(self, serial_number: str, *, motor_factory: _MotorFactory | None = None) -> None:
        super().__init__(transport=NullTransport(), protocol=ScpiProtocol())
        logger.debug(f"Creating APT motor for {serial_number}")
        self.auto_check_errors = False
        self._serial_number = str(serial_number)
        self._motor_factory = motor_factory
        self._motor: Any | None = None
        self._target_angle: float | None = None

    @property
    def is_connected(self) -> bool:
        return self._motor is not None
    
    @property
    def serial_number(self):
        """Read only property for the serial number."""
        return self._serial_number

    def connect(self) -> None:
        if self._motor is not None:
            return
        logger.debug(f"Connecting to motor at {self.serial_number}")
        factory = self._motor_factory or _AptActiveXMotor
        logger.debug(f"Created factor {self._motor_factory or _AptActiveXMotor}")
        self._motor = factory(self._serial_number)
        try:
            self.confirm_identity()
            logger.debug("Confirmed APT identity")
        except Exception as exc:
            logger.error(f"Failed to confirm APT identity {exc}")
            self.disconnect()
            raise

    def disconnect(self) -> None:
        if self._motor is None:
            return
        try:
            self._motor.close()
        finally:
            self._motor = None

    def identify(self) -> str:
        if self._motor is None:
            return f"Thorlabs,HDR50,{self._serial_number}"
        return f"Thorlabs,{self._motor.get_model()},{self._motor.get_serial_number()}"

    def set_velocity(self, velocity: float) -> None:
        if velocity <= 0:
            raise ValueError(f"velocity must be positive, got {velocity}.")
        self._connected_motor().setup_velocity(max_velocity=float(velocity))

    def set_acceleration(self, acceleration: float) -> None:
        if acceleration <= 0:
            raise ValueError(f"acceleration must be positive, got {acceleration}.")
        self._connected_motor().setup_velocity(acceleration=float(acceleration))

    def move_to_angle(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        del direction
        self._target_angle = float(angle)
        self._connected_motor().move_to(self._target_angle)

    def move_relative(
        self,
        angle: float,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        signed_angle = abs(float(angle))
        if direction is MotorMoveDirection.COUNTERCLOCKWISE:
            signed_angle = -signed_angle
        self._target_angle = self.get_position() + signed_angle
        motor = self._connected_motor()
        move_relative = getattr(motor, "move_relative", None)
        if callable(move_relative):
            move_relative(signed_angle)
        else:
            motor.move_to(self._target_angle)

    def move_home(self) -> None:
        self._target_angle = None
        self._connected_motor().home()

    def set_home(self, angle: float = 0.0) -> None:
        self._connected_motor().set_position_reference(float(angle))
        self._target_angle = float(angle)

    def get_position(self) -> float:
        return float(self._connected_motor().get_position())

    def get_target_position(self) -> float | None:
        return self._target_angle

    def is_moving(self) -> bool:
        return bool(self._connected_motor().is_moving())

    def has_reached_target_position(self, tolerance: float = 0.01) -> bool:
        if tolerance < 0:
            raise ValueError(f"tolerance must be non-negative, got {tolerance}.")
        if self._target_angle is None:
            return not self.is_moving()
        return not self.is_moving() and abs(self.get_position() - self._target_angle) <= tolerance

    @property
    def status(self) -> MotorStatus:
        motor = self._connected_motor()
        homed = getattr(motor, "is_homed", None)
        state = MotorStatus(
            current_angle=self.get_position(),
            target_angle=self._target_angle,
            moving=self.is_moving(),
            homed=bool(homed()) if callable(homed) else None,
        )
        logger.debug("APT Motor {state=}")
        return state

    def _connected_motor(self) -> Any:
        if self._motor is None:
            raise ConnectionError("Thorlabs HDR50 is not connected.")
        return self._motor
