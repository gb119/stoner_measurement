"""Transform sub-package — plugins that perform data transforms or reductions.

Exports :class:`TransformPlugin` (abstract base) from
:mod:`stoner_measurement.plugins.transform.base` and concrete transform
implementations.
"""

from stoner_measurement.plugins.transform.base import TransformPlugin
from stoner_measurement.plugins.transform.curve_fit import CurveFitPlugin
from stoner_measurement.plugins.transform.fourier_transform import (
    FourierTransformPlugin,
)
from stoner_measurement.plugins.transform.savgol_filter import SavitzkyGolayPlugin
from stoner_measurement.plugins.transform.window_filter import WindowFilterPlugin

__all__ = [
    "CurveFitPlugin",
    "FourierTransformPlugin",
    "SavitzkyGolayPlugin",
    "WindowFilterPlugin",
    "TransformPlugin",
]
