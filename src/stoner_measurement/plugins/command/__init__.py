"""Command sub-package — single-action plugins for the sequence engine.

Exports :class:`CommandPlugin` (abstract base) from
:mod:`stoner_measurement.plugins.command.base` and :class:`SaveCommand`
(built-in concrete implementation) from
:mod:`stoner_measurement.plugins.command.save`.
"""

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.plugins.command.save import SaveCommand

__all__ = [
    "CommandPlugin",
    "SaveCommand",
]
