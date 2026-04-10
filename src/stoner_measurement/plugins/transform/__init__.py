"""Transform sub-package — plugins that perform data transforms or reductions.

Exports :class:`TransformPlugin` (abstract base) from
:mod:`stoner_measurement.plugins.transform.base`.
"""

from stoner_measurement.plugins.transform.base import TransformPlugin

__all__ = [
    "TransformPlugin",
]
