"""Thorlabs HDR50 rotation stage driver via pylablib/Kinesis."""

from __future__ import annotations

from stoner_measurement.instruments.thorlabs._kinesis_base import KinesisMotorBase


class ThorlabsHDR50(KinesisMotorBase):
    """Driver for Thorlabs HDR50 driven through pylablib's Kinesis API.

    This driver is intentionally tolerant of small pylablib API naming
    differences and tries common method names for velocity, acceleration, and
    homing operations.
    """

    _EXPECTED_IDENTITY_TOKENS = ("HDR50", "THORLABS")
    _DEFAULT_MODEL = "HDR50"
    _DEVICE_NAME = "HDR50"
