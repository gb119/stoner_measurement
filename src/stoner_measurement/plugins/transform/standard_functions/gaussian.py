"""Gaussian peak fitting function with a constant background."""

import numpy as np


def fit(x, amplitude, centre, sigma, offset):
    """Return a Gaussian peak plus a constant offset."""
    return offset + amplitude * np.exp(-0.5 * ((x - centre) / sigma) ** 2)


def p0(x, y):
    """Estimate peak height, centre, width, and background."""
    offset = float(np.nanmin(y))
    amplitude = float(np.nanmax(y) - offset)
    centre = float(x[np.nanargmax(y)])
    sigma = max(float(np.nanmax(x) - np.nanmin(x)) / 6.0, float(np.spacing(1.0)))
    return amplitude, centre, sigma, offset
