"""Linear fitting function that calculates a carrier density."""

import numpy as np
from scipy.constants import e

def fit(x, n_q, offset):
    """Return a straight line."""
    slope=1/(n_q*e)
    return slope * x + offset


def p0(x, y):
    """Estimate slope and offset with a first-order polynomial fit."""
    slope, offset = np.polyfit(x, y, 1)
    n_q=1/(slope*e)
    return float(n_q), float(offset)
