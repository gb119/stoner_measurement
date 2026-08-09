"""Thorlabs HDR50 rotation-stage driver using direct APT.dll access."""

from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
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
_DllLoader = Callable[[str], Any]
_COMMAND_RETRIES = 3
_COMMAND_SETTLE_S = 0.05
_POSITION_TOLERANCE_DEG = 0.01
_APT_HOME_CLOCKWISE = 1
_APT_HOME_COUNTERCLOCKWISE = 2
# Values published by the locally installed APTAPI.h.  Including the full
# motion-controller set lets the selector serve both the HDR50 controller and
# the KDC101/KPRMTE route presented by the same motor panel.
_APT_MOTOR_HARDWARE_TYPES = (
    11,
    12,
    13,
    14,
    21,
    22,
    24,
    25,
    26,
    29,
    31,
    40,
    42,
    43,
    44,
    45,
    47,
    50,
    55,
    60,
    61,
    62,
    63,
)


@dataclass(frozen=True)
class AptControllerInfo:
    """Identity information returned for an attached APT motor controller."""

    serial_number: str
    model: str
    software_version: str
    hardware_notes: str
    hardware_type: int


class _AptDllRuntime:
    """Reference-count the process-global APT server lifecycle."""

    _lock = threading.RLock()
    _users = 0
    _dll: Any | None = None

    @classmethod
    def acquire(cls, dll: Any) -> None:
        with cls._lock:
            if cls._users == 0:
                result = int(dll.APTInit())
                if result != 0:
                    raise RuntimeError(f"APTInit failed with error code {result}.")
                cls._dll = dll
            elif not cls._same_library(cls._dll, dll):
                raise RuntimeError("APT.dll is already initialised from a different library instance.")
            cls._users += 1

    @classmethod
    def release(cls, dll: Any) -> None:
        with cls._lock:
            if cls._users == 0 or not cls._same_library(cls._dll, dll):
                return
            cls._users -= 1
            if cls._users == 0:
                try:
                    result = int(dll.APTCleanUp())
                    if result != 0:
                        logger.error(f"APTCleanUp returned error code {result}")
                except Exception as exc:
                    logger.error(f"Failed while cleaning up APT.dll: {exc}")
                finally:
                    cls._dll = None

    @staticmethod
    def _same_library(first: Any, second: Any) -> bool:
        if first is second:
            return True
        first_handle = getattr(first, "_handle", None)
        second_handle = getattr(second, "_handle", None)
        return first_handle is not None and first_handle == second_handle


class _AptDllMotor:
    """Small typed wrapper around the motion functions exported by APT.dll."""

    def __init__(
        self,
        serial_number: str,
        *,
        dll: Any | None = None,
        dll_path: str | os.PathLike[str] | None = None,
        dll_loader: _DllLoader | None = None,
        settle_time: float = _COMMAND_SETTLE_S,
    ) -> None:
        self.serial_number = str(serial_number)
        self._serial = ctypes.c_long(int(self.serial_number))
        self._settle_time = settle_time
        self._position_offset = 0.0
        self._dll: Any | None = None
        self._runtime_acquired = False

        try:
            self._dll = dll or self._load_dll(dll_path=dll_path, dll_loader=dll_loader)
            _AptDllRuntime.acquire(self._dll)
            self._runtime_acquired = True
            self._check_result("InitHWDevice", self._dll.InitHWDevice(self._serial))
            logger.debug(f"Initialised APT.dll motor at serial number {self.serial_number}")
        except Exception as exc:
            logger.error(f"Failed to initialise APT.dll motor {self.serial_number}: {exc}")
            self.close()
            raise RuntimeError(
                "Could not initialise the Thorlabs HDR50 through APT.dll. "
                "Install the Thorlabs APT software with matching Python bitness "
                f"and check controller serial number {self.serial_number}."
            ) from exc

    def close(self) -> None:
        dll = self._dll
        if dll is not None and self._runtime_acquired:
            _AptDllRuntime.release(dll)
        self._runtime_acquired = False
        self._dll = None

    @classmethod
    def discover(
        cls,
        *,
        dll: Any | None = None,
        dll_path: str | os.PathLike[str] | None = None,
        dll_loader: _DllLoader | None = None,
    ) -> list[AptControllerInfo]:
        """Enumerate attached APT motor controllers and their identities."""
        apt_dll = dll or cls._load_dll(dll_path=dll_path, dll_loader=dll_loader)
        _AptDllRuntime.acquire(apt_dll)
        discovered: dict[str, AptControllerInfo] = {}
        try:
            for hardware_type in _APT_MOTOR_HARDWARE_TYPES:
                count = ctypes.c_long()
                result = int(apt_dll.GetNumHWUnitsEx(ctypes.c_long(hardware_type), ctypes.byref(count)))
                if result != 0:
                    logger.debug(f"APT discovery skipped hardware type {hardware_type}: error code {result}")
                    continue
                for index in range(count.value):
                    serial = ctypes.c_long()
                    cls._check_result(
                        "GetHWSerialNumEx",
                        apt_dll.GetHWSerialNumEx(
                            ctypes.c_long(hardware_type),
                            ctypes.c_long(index),
                            ctypes.byref(serial),
                        ),
                    )
                    info = cls._hardware_information(apt_dll, serial.value, hardware_type)
                    discovered[info.serial_number] = info
        except Exception as exc:
            logger.error(f"Failed while enumerating attached APT controllers: {exc}")
            raise
        finally:
            _AptDllRuntime.release(apt_dll)
        controllers = sorted(discovered.values(), key=lambda item: int(item.serial_number))
        logger.debug(f"Discovered {len(controllers)} attached APT motor controller(s)")
        return controllers

    def get_model(self) -> str:
        return "HDR50"

    def get_serial_number(self) -> str:
        return self.serial_number

    def get_position(self) -> float:
        position = ctypes.c_float()
        self._check_result("MOT_GetPosition", self._dll.MOT_GetPosition(self._serial, ctypes.byref(position)))
        return float(position.value) - self._position_offset

    def setup_velocity(
        self,
        *,
        max_velocity: float | None = None,
        acceleration: float | None = None,
    ) -> None:
        min_velocity, old_acceleration, old_max_velocity = self._velocity_parameters()
        requested_acceleration = old_acceleration if acceleration is None else float(acceleration)
        requested_max_velocity = old_max_velocity if max_velocity is None else float(max_velocity)

        for attempt in range(1, _COMMAND_RETRIES + 1):
            self._check_result(
                "MOT_SetVelParams",
                self._dll.MOT_SetVelParams(
                    self._serial,
                    ctypes.c_float(min_velocity),
                    ctypes.c_float(requested_acceleration),
                    ctypes.c_float(requested_max_velocity),
                ),
            )
            actual_min, actual_acceleration, actual_max_velocity = self._velocity_parameters()
            if (
                np.isclose(actual_min, min_velocity, rtol=1e-6, atol=1e-6)
                and np.isclose(actual_acceleration, requested_acceleration, rtol=1e-6, atol=1e-6)
                and np.isclose(actual_max_velocity, requested_max_velocity, rtol=1e-6, atol=1e-6)
            ):
                logger.debug(
                    f"Applied APT velocity parameters after attempt {attempt}: "
                    f"acceleration={requested_acceleration}, max_velocity={requested_max_velocity}"
                )
                return
            logger.error(
                f"APT velocity readback did not match on attempt {attempt}: "
                f"requested=({min_velocity}, {requested_acceleration}, {requested_max_velocity}), "
                f"actual=({actual_min}, {actual_acceleration}, {actual_max_velocity})"
            )
            time.sleep(self._settle_time)
        raise RuntimeError("APT controller did not apply the requested velocity parameters.")

    def move_to(self, angle: float) -> None:
        target = float(angle)
        if np.isclose(self.get_position(), target, atol=_POSITION_TOLERANCE_DEG):
            return

        hardware_target = target + self._position_offset
        for attempt in range(1, _COMMAND_RETRIES + 1):
            self._check_result(
                "MOT_MoveAbsoluteEx",
                self._dll.MOT_MoveAbsoluteEx(self._serial, ctypes.c_float(hardware_target), ctypes.c_int(False)),
            )
            time.sleep(self._settle_time)
            if self.is_moving() or np.isclose(self.get_position(), target, atol=_POSITION_TOLERANCE_DEG):
                logger.debug(f"APT move to {target} started after attempt {attempt}")
                return
            logger.error(f"APT move to {target} did not start on attempt {attempt}")
        raise RuntimeError(f"APT controller did not start the move to {target:g} degrees.")

    def move_relative(self, angle: float) -> None:
        distance = float(angle)
        initial_position = self.get_position()
        target = initial_position + distance
        for attempt in range(1, _COMMAND_RETRIES + 1):
            self._check_result(
                "MOT_MoveRelativeEx",
                self._dll.MOT_MoveRelativeEx(self._serial, ctypes.c_float(distance), ctypes.c_int(False)),
            )
            time.sleep(self._settle_time)
            if self.is_moving() or np.isclose(self.get_position(), target, atol=_POSITION_TOLERANCE_DEG):
                logger.debug(f"APT relative move by {distance} started after attempt {attempt}")
                return
            logger.error(f"APT relative move by {distance} did not start on attempt {attempt}")
        raise RuntimeError(f"APT controller did not start the relative move by {distance:g} degrees.")

    def home(
        self,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        home_direction, limit_switch, velocity, zero_offset = self._home_parameters()
        requested_direction = (
            _APT_HOME_COUNTERCLOCKWISE
            if direction is MotorMoveDirection.COUNTERCLOCKWISE
            else _APT_HOME_CLOCKWISE
        )
        if home_direction != requested_direction:
            self._check_result(
                "MOT_SetHomeParams",
                self._dll.MOT_SetHomeParams(
                    self._serial,
                    ctypes.c_long(requested_direction),
                    ctypes.c_long(limit_switch),
                    ctypes.c_float(velocity),
                    ctypes.c_float(zero_offset),
                ),
            )
        self._check_result("MOT_MoveHome", self._dll.MOT_MoveHome(self._serial, ctypes.c_int(False)))

    def _home_parameters(self) -> tuple[int, int, float, float]:
        direction = ctypes.c_long()
        limit_switch = ctypes.c_long()
        velocity = ctypes.c_float()
        zero_offset = ctypes.c_float()
        self._check_result(
            "MOT_GetHomeParams",
            self._dll.MOT_GetHomeParams(
                self._serial,
                ctypes.byref(direction),
                ctypes.byref(limit_switch),
                ctypes.byref(velocity),
                ctypes.byref(zero_offset),
            ),
        )
        return direction.value, limit_switch.value, float(velocity.value), float(zero_offset.value)

    def set_position_reference(self, angle: float) -> None:
        """Implement an arbitrary position reference as a driver-side offset."""
        physical_position = self.get_position() + self._position_offset
        self._position_offset = physical_position - float(angle)

    def is_moving(self) -> bool:
        status_bits = ctypes.c_long()
        self._check_result(
            "MOT_GetStatusBits",
            self._dll.MOT_GetStatusBits(self._serial, ctypes.byref(status_bits)),
        )
        return bool(abs(int(status_bits.value)) & (0x10 | 0x20))

    def is_homed(self) -> bool:
        status_bits = ctypes.c_long()
        self._check_result(
            "MOT_GetStatusBits",
            self._dll.MOT_GetStatusBits(self._serial, ctypes.byref(status_bits)),
        )
        return bool(abs(int(status_bits.value)) & 0x400)

    def _velocity_parameters(self) -> tuple[float, float, float]:
        minimum = ctypes.c_float()
        acceleration = ctypes.c_float()
        maximum = ctypes.c_float()
        self._check_result(
            "MOT_GetVelParams",
            self._dll.MOT_GetVelParams(
                self._serial,
                ctypes.byref(minimum),
                ctypes.byref(acceleration),
                ctypes.byref(maximum),
            ),
        )
        return float(minimum.value), float(acceleration.value), float(maximum.value)

    @classmethod
    def _hardware_information(cls, dll: Any, serial: int, hardware_type: int) -> AptControllerInfo:
        model = ctypes.create_string_buffer(256)
        software_version = ctypes.create_string_buffer(256)
        hardware_notes = ctypes.create_string_buffer(256)
        cls._check_result(
            "GetHWInfo",
            dll.GetHWInfo(
                ctypes.c_long(serial),
                model,
                ctypes.c_long(len(model)),
                software_version,
                ctypes.c_long(len(software_version)),
                hardware_notes,
                ctypes.c_long(len(hardware_notes)),
            ),
        )
        return AptControllerInfo(
            serial_number=str(serial),
            model=model.value.decode(errors="replace"),
            software_version=software_version.value.decode(errors="replace"),
            hardware_notes=hardware_notes.value.decode(errors="replace"),
            hardware_type=hardware_type,
        )

    @staticmethod
    def _check_result(operation: str, result: Any) -> None:
        error_code = int(result)
        if error_code != 0:
            raise RuntimeError(f"{operation} failed with APT error code {error_code}.")

    @staticmethod
    def _load_dll(
        *,
        dll_path: str | os.PathLike[str] | None,
        dll_loader: _DllLoader | None,
    ) -> Any:
        loader = dll_loader
        if loader is None:
            if os.name != "nt":
                raise OSError("Thorlabs APT.dll is only available on Windows.")
            loader = ctypes.WinDLL

        candidates = _apt_dll_candidates(dll_path)
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                logger.debug(f"Loading Thorlabs APT library from {candidate}")
                return loader(str(candidate))
            except Exception as exc:
                logger.error(f"Failed to load APT.dll from {candidate}: {exc}")
        searched = ", ".join(str(path) for path in candidates)
        raise FileNotFoundError(f"Could not find a loadable APT.dll. Searched: {searched}")


def _apt_dll_candidates(explicit_path: str | os.PathLike[str] | None = None) -> list[Path]:
    """Return explicit, configured, and standard APT.dll locations."""
    candidates: list[Path] = []
    configured = explicit_path or os.environ.get("THORLABS_APT_DLL")
    if configured:
        path = Path(configured).expanduser()
        candidates.append(path / "APT.dll" if path.is_dir() else path)
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "Thorlabs" / "APT" / "APT Server" / "APT.dll")
    candidates.append(Path(r"C:\Program Files\Thorlabs\APT\APT Server\APT.dll"))
    candidates.append(Path(r"C:\Program Files (x86)\Thorlabs\APT\APT Server\APT.dll"))
    return list(dict.fromkeys(candidates))


class ThorlabsHDR50(MotorController):
    """Control an HDR50/BSC201 through direct Thorlabs APT.dll calls."""

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
    def serial_number(self) -> str:
        """Return the configured controller serial number."""
        return self._serial_number

    def connect(self) -> None:
        if self._motor is not None:
            return
        logger.debug(f"Connecting to motor at {self.serial_number}")
        factory = self._motor_factory or _AptDllMotor
        logger.debug(f"Using APT motor factory {factory}")
        try:
            self._motor = factory(self._serial_number)
            self.confirm_identity()
            logger.debug("Confirmed APT identity")
        except Exception as exc:
            logger.error(f"Failed to connect or confirm APT identity: {exc}")
            self.disconnect()
            raise

    @classmethod
    def discover_controllers(cls) -> list[AptControllerInfo]:
        """Return attached controllers visible through APT.dll."""
        try:
            return _AptDllMotor.discover()
        except Exception as exc:
            logger.error(f"Failed to discover Thorlabs APT controllers: {exc}")
            raise

    def disconnect(self) -> None:
        if self._motor is None:
            return
        try:
            self._motor.close()
        except Exception as exc:
            logger.error(f"Failed while disconnecting APT motor: {exc}")
            raise
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
        self._connected_motor().move_relative(signed_angle)

    def move_home(
        self,
        direction: MotorMoveDirection = MotorMoveDirection.CLOCKWISE,
    ) -> None:
        if direction is MotorMoveDirection.SHORTEST:
            direction = (
                MotorMoveDirection.COUNTERCLOCKWISE
                if self.get_position() > 0.0
                else MotorMoveDirection.CLOCKWISE
            )
        self._target_angle = None
        motor = self._connected_motor()
        if isinstance(motor, _AptDllMotor):
            motor.home(direction)
        else:
            # Retain compatibility with injected/legacy motor objects whose
            # native home method predates direction-aware APT homing.
            motor.home()

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
            homed=bool(homed()) if callable(homed) else None,  # pylint: disable=not-callable
        )
        logger.debug(f"APT Motor {state=}")
        return state

    def _connected_motor(self) -> Any:
        if self._motor is None:
            raise ConnectionError("Thorlabs HDR50 is not connected.")
        return self._motor
