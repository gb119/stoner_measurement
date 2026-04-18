"""State plugin package — shared abstract base for state-scan and state-sweep plugins.

Exports :class:`StatePlugin`, the common ancestor for both
:class:`~stoner_measurement.plugins.state_scan.base.StateScanPlugin` and
:class:`~stoner_measurement.plugins.state_sweep.base.StateSweepPlugin`.
"""

from stoner_measurement.plugins.state.base import StatePlugin

__all__ = [
    "StatePlugin",
]
