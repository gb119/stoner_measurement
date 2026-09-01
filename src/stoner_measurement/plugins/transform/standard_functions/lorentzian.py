"""Lorentzian peak fitting function with a constant background."""

import numpy as np


def fit(x, amplitude, centre, half_width, offset):
    """Return a Lorentzian peak plus a constant offset."""
    return offset + amplitude / (1.0 + ((x - centre) / half_width) ** 2)


def p0(x, y):
    """Estimate peak height, centre, half-width, and background."""
    offset = float(np.nanmin(y))
    amplitude = float(np.nanmax(y) - offset)
    centre = float(x[np.nanargmax(y)])
    half_width = max(float(np.nanmax(x) - np.nanmin(x)) / 10.0, float(np.spacing(1.0)))
    return amplitude, centre, half_width, offset
