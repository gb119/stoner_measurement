"""Backward-compatibility shim — the correct model number is 625.

.. deprecated::
    Import :class:`~stoner_measurement.instruments.lakeshore.Lakeshore625` instead.
    This module will be removed in a future release.
"""

from stoner_measurement.instruments.lakeshore.ls625 import Lakeshore625 as Lakeshore525

__all__ = ["Lakeshore525"]
