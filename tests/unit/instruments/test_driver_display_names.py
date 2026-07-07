"""Tests for human-friendly instrument driver labels."""

from __future__ import annotations

from stoner_measurement.instruments.eurotherm import Eurotherm2000Series, Eurotherm3200Series
from stoner_measurement.instruments.oxford import OxfordIPS120
from stoner_measurement.instruments.simulated import SimulatedTemperatureController
from stoner_measurement.instruments.thorlabs import ThorlabsKDC101KPRMTE


def test_display_name_splits_camel_case_and_numbers():
    assert OxfordIPS120.display_name() == "Oxford IPS 120"
    assert ThorlabsKDC101KPRMTE.display_name() == "Thorlabs KDC 101 KPRMTE"


def test_display_name_keeps_controller_families_readable():
    assert Eurotherm2000Series.display_name() == "Eurotherm 2000 Series"
    assert Eurotherm3200Series.display_name() == "Eurotherm 3200 Series"
    assert SimulatedTemperatureController.display_name() == "Simulated Temperature Controller"
