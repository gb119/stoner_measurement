"""Tests for motor controller abstractions and Thorlabs motor drivers."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from stoner_measurement.instruments.errors import InstrumentError
from stoner_measurement.instruments.motor_controller import MotorController
from stoner_measurement.instruments.protocol.scpi import ScpiProtocol
from stoner_measurement.instruments.thorlabs import ThorlabsHDR50, ThorlabsKDC101KPRMTE
from stoner_measurement.instruments.transport import NullTransport


def test_motor_controller_is_abstract():
    with pytest.raises(TypeError):
        MotorController(NullTransport(), ScpiProtocol())  # type: ignore[abstract]


@dataclass
class _FakeMotor:
    serial: str
    model: str = "HDR50"
    position: float = 0.0
    moving: bool = False
    homed: bool = False
    velocity: float | None = None
    acceleration: float | None = None
    closed: bool = False

    def setup_velocity(
        self,
        *,
        max_velocity: float | None = None,
        acceleration: float | None = None,
    ) -> None:
        if max_velocity is not None:
            self.velocity = max_velocity
        if acceleration is not None:
            self.acceleration = acceleration

    def move_to(self, angle: float) -> None:
        self.moving = True
        self.position = angle

    def home(self) -> None:
        self.moving = True
        self.position = 0.0

    def set_position_reference(self, angle: float) -> None:
        self.position = angle
        self.homed = True

    def get_position(self) -> float:
        return self.position

    def is_moving(self) -> bool:
        return self.moving

    def is_homed(self) -> bool:
        return self.homed

    def get_model(self) -> str:
        return self.model

    def get_serial_number(self) -> str:
        return self.serial

    def close(self) -> None:
        self.closed = True


class TestThorlabsHDR50:
    def test_connect_set_motion_move_and_status(self):
        created: list[_FakeMotor] = []

        def _factory(serial: str) -> _FakeMotor:
            motor = _FakeMotor(serial=serial)
            created.append(motor)
            return motor

        driver = ThorlabsHDR50(serial_number="12345678", motor_factory=_factory)
        driver.connect()

        motor = created[0]
        driver.set_velocity(12.5)
        driver.set_acceleration(7.5)
        driver.move_to_angle(45.0)

        assert motor.velocity == pytest.approx(12.5)
        assert motor.acceleration == pytest.approx(7.5)
        assert driver.get_target_position() == pytest.approx(45.0)
        assert driver.has_reached_target_position() is False

        motor.moving = False
        assert driver.has_reached_target_position() is True

        status = driver.status
        assert status.current_angle == pytest.approx(45.0)
        assert status.target_angle == pytest.approx(45.0)
        assert status.homed is False

    def test_set_home_move_home_identify_disconnect(self):
        motor = _FakeMotor(serial="00001111")
        driver = ThorlabsHDR50(serial_number="00001111", motor_factory=lambda _serial: motor)

        driver.connect()
        driver.set_home(5.0)
        assert motor.position == pytest.approx(5.0)
        assert driver.get_target_position() == pytest.approx(5.0)

        driver.move_home()
        assert driver.get_target_position() is None

        motor.moving = False
        assert driver.identify() == "Thorlabs,HDR50,00001111"

        driver.disconnect()
        assert motor.closed is True

    def test_input_validation(self):
        driver = ThorlabsHDR50(serial_number="1234", motor_factory=lambda serial: _FakeMotor(serial=serial))
        driver.connect()
        with pytest.raises(ValueError, match="velocity"):
            driver.set_velocity(0)
        with pytest.raises(ValueError, match="acceleration"):
            driver.set_acceleration(-1)
        with pytest.raises(ValueError, match="tolerance"):
            driver.has_reached_target_position(tolerance=-0.1)

    def test_wait_for_target_position(self):
        motor = _FakeMotor(serial="1234", moving=True)
        driver = ThorlabsHDR50(serial_number="1234", motor_factory=lambda serial: motor)
        driver.connect()
        driver.move_to_angle(20.0)

        with pytest.raises(TimeoutError):
            driver.wait_for_target_position(timeout=0.01, poll_period=0.0)

        motor.moving = False
        driver.wait_for_target_position(timeout=0.1, poll_period=0.0)

    def test_connect_fails_on_identity_mismatch(self):
        """connect() must close the motor and raise when identity check fails."""

        @dataclass
        class _WrongMotor:
            serial: str
            closed: bool = False

            def get_model(self) -> str:
                return "K-CUBE"

            def get_serial_number(self) -> str:
                return self.serial

            def close(self) -> None:
                self.closed = True

        wrong_motor = _WrongMotor(serial="9999")
        driver = ThorlabsHDR50(serial_number="9999", motor_factory=lambda _s: wrong_motor)
        with pytest.raises(InstrumentError, match="identity"):
            driver.connect()
        assert wrong_motor.closed is True
        assert driver.is_connected is False


class TestThorlabsKDC101KPRMTE:
    def test_connect_set_motion_move_and_status(self):
        created: list[_FakeMotor] = []

        def _factory(serial: str) -> _FakeMotor:
            motor = _FakeMotor(serial=serial, model="KDC101-KPRMTE")
            created.append(motor)
            return motor

        driver = ThorlabsKDC101KPRMTE(serial_number="12345678", motor_factory=_factory)
        driver.connect()

        motor = created[0]
        driver.set_velocity(12.5)
        driver.set_acceleration(7.5)
        driver.move_to_angle(45.0)

        assert motor.velocity == pytest.approx(12.5)
        assert motor.acceleration == pytest.approx(7.5)
        assert driver.get_target_position() == pytest.approx(45.0)
        assert driver.has_reached_target_position() is False

        motor.moving = False
        assert driver.has_reached_target_position() is True

        status = driver.status
        assert status.current_angle == pytest.approx(45.0)
        assert status.target_angle == pytest.approx(45.0)
        assert status.homed is False

    def test_set_home_move_home_identify_disconnect(self):
        motor = _FakeMotor(serial="00001111", model="KDC101-KPRMTE")
        driver = ThorlabsKDC101KPRMTE(serial_number="00001111", motor_factory=lambda _serial: motor)

        driver.connect()
        driver.set_home(5.0)
        assert motor.position == pytest.approx(5.0)
        assert driver.get_target_position() == pytest.approx(5.0)

        driver.move_home()
        assert driver.get_target_position() is None

        motor.moving = False
        assert driver.identify() == "Thorlabs,KDC101-KPRMTE,00001111"

        driver.disconnect()
        assert motor.closed is True

    def test_input_validation(self):
        driver = ThorlabsKDC101KPRMTE(
            serial_number="1234",
            motor_factory=lambda serial: _FakeMotor(serial=serial, model="KDC101-KPRMTE"),
        )
        driver.connect()
        with pytest.raises(ValueError, match="velocity"):
            driver.set_velocity(0)
        with pytest.raises(ValueError, match="acceleration"):
            driver.set_acceleration(-1)
        with pytest.raises(ValueError, match="tolerance"):
            driver.has_reached_target_position(tolerance=-0.1)

    def test_wait_for_target_position(self):
        motor = _FakeMotor(serial="1234", model="KDC101-KPRMTE", moving=True)
        driver = ThorlabsKDC101KPRMTE(serial_number="1234", motor_factory=lambda serial: motor)
        driver.connect()
        driver.move_to_angle(20.0)

        with pytest.raises(TimeoutError):
            driver.wait_for_target_position(timeout=0.01, poll_period=0.0)

        motor.moving = False
        driver.wait_for_target_position(timeout=0.1, poll_period=0.0)

    def test_connect_fails_on_identity_mismatch(self):
        """connect() must close the motor and raise when identity check fails."""

        @dataclass
        class _WrongMotor:
            serial: str
            closed: bool = False

            def get_model(self) -> str:
                return "K-CUBE"

            def get_serial_number(self) -> str:
                return self.serial

            def close(self) -> None:
                self.closed = True

        wrong_motor = _WrongMotor(serial="9999")
        driver = ThorlabsKDC101KPRMTE(serial_number="9999", motor_factory=lambda _s: wrong_motor)
        with pytest.raises(InstrumentError, match="identity"):
            driver.connect()
        assert wrong_motor.closed is True
        assert driver.is_connected is False
