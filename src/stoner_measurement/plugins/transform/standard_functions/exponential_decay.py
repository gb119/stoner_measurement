"""Exponential-decay fitting function with a constant background."""

import numpy as np


def fit(x, amplitude, decay_time, offset):
    """Return an exponential decay plus a constant offset."""
    return offset + amplitude * np.exp(-(x - np.nanmin(x)) / decay_time)


def p0(x, y):
    """Estimate amplitude, decay time, and background from the endpoints."""
    offset = float(y[-1])
    amplitude = float(y[0] - offset)
    decay_time = max(float(np.nanmax(x) - np.nanmin(x)) / 3.0, float(np.spacing(1.0)))
    return amplitude, decay_time, offset
