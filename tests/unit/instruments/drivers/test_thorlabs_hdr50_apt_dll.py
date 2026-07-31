"""Tests for the HDR50 direct APT.dll backend."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from stoner_measurement.instruments.thorlabs.hdr50 import _AptDllMotor


def _value(value):
    return value.value if hasattr(value, "value") else value


@dataclass
class _FakeAptDll:
    position: float = 0.0
    min_velocity: float = 0.0
    acceleration: float = 5.0
    max_velocity: float = 10.0
    status_bits: int = 0
    ignore_velocity_writes: int = 0
    ignore_move_commands: int = 0
    calls: list[tuple] = field(default_factory=list)
    controllers: dict[int, list[int]] = field(default_factory=dict)

    def APTInit(self) -> int:
        self.calls.append(("APTInit",))
        return 0

    def APTCleanUp(self) -> int:
        self.calls.append(("APTCleanUp",))
        return 0

    def InitHWDevice(self, serial) -> int:
        self.calls.append(("InitHWDevice", _value(serial)))
        return 0

    def GetNumHWUnitsEx(self, hardware_type, count) -> int:
        count._obj.value = len(self.controllers.get(_value(hardware_type), []))
        return 0

    def GetHWSerialNumEx(self, hardware_type, index, serial) -> int:
        serial._obj.value = self.controllers[_value(hardware_type)][_value(index)]
        return 0

    def GetHWInfo(self, serial, model, model_len, software, software_len, notes, notes_len) -> int:
        model.value = b"BSC201"
        software.value = b"APT 3.21"
        notes.value = b"Benchtop stepper"
        return 0

    def MOT_GetPosition(self, serial, position) -> int:
        self.calls.append(("MOT_GetPosition", _value(serial)))
        position._obj.value = self.position
        return 0

    def MOT_GetVelParams(self, serial, minimum, acceleration, maximum) -> int:
        minimum._obj.value = self.min_velocity
        acceleration._obj.value = self.acceleration
        maximum._obj.value = self.max_velocity
        return 0

    def MOT_SetVelParams(self, serial, minimum, acceleration, maximum) -> int:
        self.calls.append(
            ("MOT_SetVelParams", _value(serial), _value(minimum), _value(acceleration), _value(maximum))
        )
        if self.ignore_velocity_writes:
            self.ignore_velocity_writes -= 1
            return 0
        self.min_velocity = _value(minimum)
        self.acceleration = _value(acceleration)
        self.max_velocity = _value(maximum)
        return 0

    def MOT_MoveAbsoluteEx(self, serial, target, wait) -> int:
        self.calls.append(("MOT_MoveAbsoluteEx", _value(serial), _value(target), _value(wait)))
        if self.ignore_move_commands:
            self.ignore_move_commands -= 1
            return 0
        self.status_bits = 0x10
        return 0

    def MOT_MoveRelativeEx(self, serial, distance, wait) -> int:
        self.calls.append(("MOT_MoveRelativeEx", _value(serial), _value(distance), _value(wait)))
        self.status_bits = 0x10
        return 0

    def MOT_MoveHome(self, serial, wait) -> int:
        self.calls.append(("MOT_MoveHome", _value(serial), _value(wait)))
        return 0

    def MOT_GetStatusBits(self, serial, status) -> int:
        status._obj.value = self.status_bits
        return 0


def test_dll_connection_initialises_device_and_cleans_up():
    dll = _FakeAptDll()
    motor = _AptDllMotor("70001234", dll=dll, settle_time=0.0)

    assert dll.calls[:2] == [("APTInit",), ("InitHWDevice", 70001234)]

    motor.close()
    assert dll.calls[-1] == ("APTCleanUp",)


def test_dll_discovery_enumerates_controller_serials_and_details():
    dll = _FakeAptDll(controllers={11: [70001234], 12: [70005678]})

    controllers = _AptDllMotor.discover(dll=dll)

    assert [item.serial_number for item in controllers] == ["70001234", "70005678"]
    assert controllers[0].model == "BSC201"
    assert controllers[0].software_version == "APT 3.21"
    assert controllers[0].hardware_notes == "Benchtop stepper"
    assert dll.calls[0] == ("APTInit",)
    assert dll.calls[-1] == ("APTCleanUp",)


def test_velocity_write_is_read_back_and_retried():
    dll = _FakeAptDll(ignore_velocity_writes=1)
    motor = _AptDllMotor("70001234", dll=dll, settle_time=0.0)
    try:
        motor.setup_velocity(max_velocity=25.0)
        writes = [call for call in dll.calls if call[0] == "MOT_SetVelParams"]
        assert len(writes) == 2
        assert dll.max_velocity == pytest.approx(25.0)
        assert dll.acceleration == pytest.approx(5.0)
    finally:
        motor.close()


def test_move_is_reissued_when_controller_does_not_start():
    dll = _FakeAptDll(ignore_move_commands=1)
    motor = _AptDllMotor("70001234", dll=dll, settle_time=0.0)
    try:
        motor.move_to(45.0)
        moves = [call for call in dll.calls if call[0] == "MOT_MoveAbsoluteEx"]
        assert len(moves) == 2
        assert moves[-1][2] == pytest.approx(45.0)
        assert motor.is_moving() is True
    finally:
        motor.close()


def test_move_failure_is_reported_after_bounded_retries():
    dll = _FakeAptDll(ignore_move_commands=10)
    motor = _AptDllMotor("70001234", dll=dll, settle_time=0.0)
    try:
        with pytest.raises(RuntimeError, match="did not start"):
            motor.move_to(45.0)
    finally:
        motor.close()


def test_relative_move_uses_dll_and_confirms_motion_started():
    dll = _FakeAptDll(position=10.0)
    motor = _AptDllMotor("70001234", dll=dll, settle_time=0.0)
    try:
        motor.move_relative(-2.5)
        move = [call for call in dll.calls if call[0] == "MOT_MoveRelativeEx"][-1]
        assert move[2] == pytest.approx(-2.5)
        assert move[3] == 0
    finally:
        motor.close()


def test_position_reference_is_applied_as_a_software_offset():
    dll = _FakeAptDll(position=30.0)
    motor = _AptDllMotor("70001234", dll=dll, settle_time=0.0)
    try:
        motor.set_position_reference(5.0)
        assert motor.get_position() == pytest.approx(5.0)
        motor.move_to(15.0)
        move = [call for call in dll.calls if call[0] == "MOT_MoveAbsoluteEx"][-1]
        assert move[2] == pytest.approx(40.0)
    finally:
        motor.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
