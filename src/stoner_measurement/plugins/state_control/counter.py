"""Backward-compatibility shim — re-exports CounterPlugin from state_scan.

New code should use :mod:`stoner_measurement.plugins.state_scan` directly.
"""

from stoner_measurement.plugins.state_scan.counter import CounterPlugin

__all__ = ["CounterPlugin"]
