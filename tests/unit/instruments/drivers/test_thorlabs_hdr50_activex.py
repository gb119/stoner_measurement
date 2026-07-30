"""Tests for the HDR50 APT ActiveX backend."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from stoner_measurement.instruments.thorlabs.hdr50 import (
    _APT_MOTOR_PROG_ID,
    _AptActiveXMotor,
)


@dataclass
class _FakeAptControl:
    position: float = 0.0
    min_velocity: float = 0.0
    acceleration: float = 5.0
    max_velocity: float = 10.0
    status_bits: int = 0
    ignore_velocity_writes: int = 0
    ignore_move_commands: int = 0
    calls: list[tuple] = field(default_factory=list)
    HWSerialNum: int | None = None
    pending_position: float = 0.0

    def StartCtrl(self) -> None:
        self.calls.append(("StartCtrl",))

    def EnableHWChannel(self, channel: int) -> None:
        self.calls.append(("EnableHWChannel", channel))

    def StopCtrl(self) -> None:
        self.calls.append(("StopCtrl",))

    def GetPosition_Position(self, channel: int) -> float:
        self.calls.append(("GetPosition_Position", channel))
        return self.position

    def GetVelParams_MinVel(self, channel: int) -> float:
        return self.min_velocity

    def GetVelParams_Accn(self, channel: int) -> float:
        return self.acceleration

    def GetVelParams_MaxVel(self, channel: int) -> float:
        return self.max_velocity

    def SetVelParams(self, channel: int, minimum: float, acceleration: float, maximum: float) -> None:
        self.calls.append(("SetVelParams", channel, minimum, acceleration, maximum))
        if self.ignore_velocity_writes:
            self.ignore_velocity_writes -= 1
            return
        self.min_velocity = minimum
        self.acceleration = acceleration
        self.max_velocity = maximum

    def SetAbsMovePos(self, channel: int, target: float) -> None:
        self.calls.append(("SetAbsMovePos", channel, target))
        self.pending_position = target

    def MoveAbsolute(self, channel: int, wait: bool) -> None:
        self.calls.append(("MoveAbsolute", channel, wait))
        if self.ignore_move_commands:
            self.ignore_move_commands -= 1
            return
        self.status_bits = 0x10

    def GetStatusBits_Bits(self, channel: int) -> int:
        self.calls.append(("GetStatusBits_Bits", channel))
        return self.status_bits


def _motor(control: _FakeAptControl) -> _AptActiveXMotor:
    seen_prog_ids: list[str] = []

    def dispatch(prog_id: str) -> _FakeAptControl:
        seen_prog_ids.append(prog_id)
        return control

    motor = _AptActiveXMotor("70001234", dispatch=dispatch, settle_time=0.0)
    assert seen_prog_ids == [_APT_MOTOR_PROG_ID]
    return motor


def test_active_x_connection_starts_control_and_enables_channel():
    control = _FakeAptControl()
    motor = _motor(control)

    assert control.HWSerialNum == 70001234
    assert control.calls[:2] == [("StartCtrl",), ("EnableHWChannel", 0)]

    motor.close()
    assert control.calls[-1] == ("StopCtrl",)


def test_velocity_write_is_read_back_and_retried():
    control = _FakeAptControl(ignore_velocity_writes=1)
    motor = _motor(control)

    motor.setup_velocity(max_velocity=25.0)

    writes = [call for call in control.calls if call[0] == "SetVelParams"]
    assert len(writes) == 2
    assert control.max_velocity == pytest.approx(25.0)
    assert control.acceleration == pytest.approx(5.0)


def test_move_is_reissued_when_controller_does_not_start():
    control = _FakeAptControl(ignore_move_commands=1)
    motor = _motor(control)

    motor.move_to(45.0)

    move_calls = [call for call in control.calls if call[0] == "MoveAbsolute"]
    assert move_calls == [("MoveAbsolute", 0, False), ("MoveAbsolute", 0, False)]
    assert motor.is_moving() is True


def test_move_failure_is_reported_after_bounded_retries():
    control = _FakeAptControl(ignore_move_commands=10)
    motor = _motor(control)

    with pytest.raises(RuntimeError, match="did not start"):
        motor.move_to(45.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
