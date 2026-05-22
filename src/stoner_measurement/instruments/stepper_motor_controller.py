"""Backward-compatible aliases for renamed motor controller abstractions."""

from stoner_measurement.instruments.motor_controller import Motor as StepperMotor
from stoner_measurement.instruments.motor_controller import (
    MotorController as StepperMotorController,
)
from stoner_measurement.instruments.motor_controller import MotorStatus as StepperMotorStatus

__all__ = ["StepperMotor", "StepperMotorController", "StepperMotorStatus"]
