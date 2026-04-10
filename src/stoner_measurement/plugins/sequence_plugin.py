"""Backward-compatibility shim for ``stoner_measurement.plugins.sequence_plugin``.

The :class:`SequencePlugin` and :class:`TopLevelSequence` classes have been
moved to :mod:`stoner_measurement.plugins.sequence.base`.  This module
re-exports them so that existing code that imports from
``stoner_measurement.plugins.sequence_plugin`` continues to work.

New code should import directly from :mod:`stoner_measurement.plugins.sequence`::

    from stoner_measurement.plugins.sequence import SequencePlugin, TopLevelSequence
"""

from stoner_measurement.plugins.sequence.base import SequencePlugin, TopLevelSequence

__all__ = [
    "SequencePlugin",
    "TopLevelSequence",
]
