"""Shared nanovoltmeter driver registry for trace plugins."""

from __future__ import annotations

from stoner_measurement.instruments.keithley.k182 import Keithley182
from stoner_measurement.instruments.keithley.k2182 import Keithley2182A
from stoner_measurement.instruments.nanovoltmeter import Nanovoltmeter

NANOVOLTMETER_DRIVERS: dict[str, type[Nanovoltmeter]] = {
    "keithley_182": Keithley182,
    "keithley_2182a": Keithley2182A,
}

NANOVOLTMETER_DRIVER_LABELS = {
    key: driver.display_name() for key, driver in NANOVOLTMETER_DRIVERS.items()
}

__all__ = ["NANOVOLTMETER_DRIVERS", "NANOVOLTMETER_DRIVER_LABELS"]
