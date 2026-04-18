"""Backward-compatibility shim — re-exports StateScanPlugin as StateControlPlugin.

New code should use :mod:`stoner_measurement.plugins.state_scan` directly.
"""

from stoner_measurement.plugins.state_scan.base import StateScanPlugin as StateControlPlugin

__all__ = ["StateControlPlugin"]
