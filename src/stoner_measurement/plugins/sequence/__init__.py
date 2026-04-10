"""Sequence sub-package — container plugins for the measurement sequence tree.

Exports :class:`SequencePlugin` (abstract base) and :class:`TopLevelSequence`
(concrete root container) from :mod:`stoner_measurement.plugins.sequence.base`.
"""

from stoner_measurement.plugins.sequence.base import SequencePlugin, TopLevelSequence

__all__ = [
    "SequencePlugin",
    "TopLevelSequence",
]
