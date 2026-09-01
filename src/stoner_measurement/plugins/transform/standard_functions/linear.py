"""Linear fitting function."""

import numpy as np


def fit(x, slope, offset):
    """Return a straight line."""
    return slope * x + offset


def p0(x, y):
    """Estimate slope and offset with a first-order polynomial fit."""
    slope, offset = np.polyfit(x, y, 1)
    return float(slope), float(offset)
