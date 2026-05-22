"""Thorlabs KDC101 + KPRMTE motor stage driver via pylablib/Kinesis."""

from __future__ import annotations

from stoner_measurement.instruments.thorlabs._kinesis_base import KinesisMotorBase


class ThorlabsKDC101KPRMTE(KinesisMotorBase):
    """Driver for a Thorlabs KDC101 controller with a KPRMTE servo stage."""

    _EXPECTED_IDENTITY_TOKENS = ("KDC101", "KPRMTE", "THORLABS")
    _DEFAULT_MODEL = "KDC101-KPRMTE"
    _DEVICE_NAME = "KDC101 + KPRMTE"

