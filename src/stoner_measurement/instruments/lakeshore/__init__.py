"""Lakeshore instrument drivers."""

from stoner_measurement.instruments.lakeshore.current_sources import (
    LakeshoreM81CurrentSource,
)
from stoner_measurement.instruments.lakeshore.lia import LakeshoreM81LockIn
from stoner_measurement.instruments.lakeshore.ls625 import Lakeshore625
from stoner_measurement.instruments.lakeshore.temperature_controllers import (
    Lakeshore335,
    Lakeshore336,
    Lakeshore340,
)

# Backward-compatibility alias — Lakeshore625 is the correct model number.
Lakeshore525 = Lakeshore625

__all__ = [
    "Lakeshore335",
    "Lakeshore336",
    "Lakeshore340",
    "Lakeshore525",
    "Lakeshore625",
    "LakeshoreM81CurrentSource",
    "LakeshoreM81LockIn",
]
