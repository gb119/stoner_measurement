"""Shared differential-conductance sweep transformations."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DifferentialResult:
    """Reduced values from an alternating delta-current sweep."""

    current: np.ndarray
    voltage: np.ndarray
    change_voltage: np.ndarray
    response: np.ndarray
    power: np.ndarray


def modulate_current_sweep(values: np.ndarray, delta_current: float) -> np.ndarray:
    """Return *values* with alternating ``+dI`` and ``-dI`` offsets."""
    nominal = np.asarray(values, dtype=float)
    if nominal.ndim != 1:
        raise ValueError("Differential-mode scan values must be one-dimensional.")
    if len(nominal) < 3:
        raise ValueError("Differential mode requires at least three scan points.")
    if not np.isfinite(delta_current) or delta_current <= 0.0:
        raise ValueError("Delta current must be a positive finite value.")
    signs = np.where(np.arange(len(nominal)) % 2 == 0, 1.0, -1.0)
    return nominal + signs * delta_current


def reduce_differential_readings(
    nominal_current: np.ndarray,
    voltage: np.ndarray,
    delta_current: float,
    *,
    conductance: bool,
) -> DifferentialResult:
    """Reduce alternating readings to average voltage and differential response.

    For consecutive readings ``X, Y, Z`` the requested definitions are
    ``V = (X + 2Y + Z) / 4`` and
    ``dV = (X - 2Y + Z) / 4 * (-1)**n``.  The first reduced point uses
    ``n = 0``.  Differential resistance is ``dV / dI`` and differential
    conductance is its reciprocal ``dI / dV``.
    """
    nominal = np.asarray(nominal_current, dtype=float)
    readings = np.asarray(voltage, dtype=float)
    if nominal.ndim != 1 or readings.ndim != 1 or len(nominal) != len(readings):
        raise ValueError("Nominal currents and voltage readings must be equal-length vectors.")
    # Reuse the validation and keep the modulation/reduction contracts aligned.
    modulate_current_sweep(nominal, delta_current)

    x = readings[:-2]
    y = readings[1:-1]
    z = readings[2:]
    interior_voltage = (x + 2.0 * y + z) / 4.0
    polarity = np.where(np.arange(len(interior_voltage)) % 2 == 0, 1.0, -1.0)
    interior_change_voltage = (x - 2.0 * y + z) * polarity / 4.0
    change_voltage = np.empty_like(readings)
    change_voltage[1:-1] = interior_change_voltage
    change_voltage[0] = interior_change_voltage[0]
    change_voltage[-1] = interior_change_voltage[-1]
    average_voltage = np.empty_like(readings)
    average_voltage[1:-1] = interior_voltage
    average_voltage[0] = readings[0] - change_voltage[0]
    final_modulation_sign = 1.0 if (len(readings) - 1) % 2 == 0 else -1.0
    average_voltage[-1] = readings[-1] - final_modulation_sign * change_voltage[-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        if conductance:
            response = np.where(
                np.abs(change_voltage) > 1e-30,
                delta_current / change_voltage,
                float("nan"),
            )
        else:
            response = change_voltage / delta_current
    return DifferentialResult(
        current=nominal.copy(),
        voltage=average_voltage,
        change_voltage=change_voltage,
        response=response,
        power=delta_current * change_voltage,
    )
