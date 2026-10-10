"""Prepare single-valued trace rows without changing acquired trace tables."""

import numpy as np

from stoner_measurement.core.plotting.contracts import PlotData


def _tolerance(xs):
    """Only merge coordinate differences at floating-point round-off scale."""
    return 64 * np.finfo(float).eps * np.max(np.abs(xs))


def _interpolate(xs, values, target, *, uncertainty=False, bounds="nearest", valid=None):
    """Interpolate adjacent samples, retaining NaN gaps and handling the bounds."""
    result = np.full(target.shape, np.nan)
    right = np.searchsorted(xs, target)
    nearest = np.clip(right, 0, len(xs) - 1)
    left = np.clip(right - 1, 0, len(xs) - 1)
    nearest = np.where(np.abs(xs[left] - target) < np.abs(xs[nearest] - target), left, nearest)
    exact = np.abs(xs[nearest] - target) <= _tolerance(xs)
    result[exact] = values[nearest[exact]]
    between = (right > 0) & (right < len(xs)) & ~exact
    upper = right[between]
    lower = upper - 1
    weight = (target[between] - xs[lower]) / (xs[upper] - xs[lower])
    if uncertainty:
        result[between] = np.hypot((1 - weight) * values[lower], weight * values[upper])
    else:
        result[between] = (1 - weight) * values[lower] + weight * values[upper]
    if bounds == "nearest":
        indices = np.flatnonzero(np.isfinite(values) if valid is None else valid)
        if len(indices):
            result[(target < xs[0]) & ~exact] = values[indices[0]]
            result[(target > xs[-1]) & ~exact] = values[indices[-1]]
    return result


def regrid_trace(data: PlotData, target=None, *, policy="mean", bounds="nearest") -> PlotData:
    """Sort/merge a trace and interpolate it onto an established surface X grid.

    Args:
        data (PlotData): Captured X, Z and optional value channels and errors.
        target (array-like | None): Existing sorted X grid; None establishes one.

    Keyword Parameters:
        policy (str): mean, first or last for repeated X; strict leaves data intact.
        bounds (str): nearest holds the closest valid boundary sample outside
            the measured range; missing leaves these coordinates as NaN.

    Returns:
        (PlotData): Immutable plotting samples with original channel metadata.

    Raises:
        ValueError: For unknown policies or empty/non-finite coordinates.

    Notes:
        Round-off-equivalent X values merge within 64 eps times the source scale.
        Mean ignores non-finite signals, leaving all-missing groups as NaN.
        First/last use acquisition order. Interpolation never bridges a missing
        source sample. Errors use independent-error propagation
        for means and interpolation; no errors are inferred from branch spread.
    """
    if policy not in ("mean", "first", "last", "strict"):
        raise ValueError(f"Unknown surface re-gridding policy: {policy!r}.")
    if bounds not in ("nearest", "missing"):
        raise ValueError(f"Unknown surface re-gridding bounds policy: {bounds!r}.")
    if policy == "strict":
        return data
    xs = data.channels["x"]
    if not len(xs) or not np.all(np.isfinite(xs)):
        raise ValueError("Surface re-gridding requires nonempty, finite X coordinates.")
    order = np.argsort(xs, kind="stable")
    sorted_x = xs[order]
    starts = np.r_[0, np.flatnonzero(np.diff(sorted_x) > _tolerance(xs)) + 1]
    groups = np.split(order, starts[1:])
    grid = sorted_x[starts]
    channels = {"x": grid}
    errors = {}
    for name, source in data.channels.items():
        reduced, reduced_errors = [], []
        for group in groups:
            if policy == "mean":
                valid = group[np.isfinite(source[group])]
                reduced.append(np.mean(source[valid]) if len(valid) else np.nan)
                if name in data.uncertainties:
                    reduced_errors.append(
                        np.linalg.norm(data.uncertainties[name][valid]) / len(valid)
                        if len(valid)
                        else np.nan
                    )
            else:
                index = np.min(group) if policy == "first" else np.max(group)
                reduced.append(source[index])
                if name in data.uncertainties:
                    reduced_errors.append(data.uncertainties[name][index])
        if name != "x":
            channels[name] = np.asarray(reduced)
        if name in data.uncertainties:
            errors[name] = np.asarray(reduced_errors)
    if target is not None:
        target = np.asarray(target, dtype=float)
        if (
            target.ndim != 1
            or not len(target)
            or not np.all(np.isfinite(target))
            or np.any(np.diff(target) <= 0)
        ):
            raise ValueError("The surface target X grid must be finite, nonempty and increasing.")
        errors = {
            name: _interpolate(
                grid,
                source,
                target,
                uncertainty=True,
                bounds=bounds,
                valid=np.isfinite(channels[name]),
            )
            for name, source in errors.items()
        }
        channels = {
            name: target if name == "x" else _interpolate(grid, source, target, bounds=bounds)
            for name, source in channels.items()
        }
    return PlotData(channels, data.metadata, errors)
