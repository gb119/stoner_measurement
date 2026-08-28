"""Shared acquisition-order branch detection for transform plugins."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_SMOOTHING_WINDOW = 11
DEFAULT_SMOOTHING_POLYORDER = 2
DEFAULT_TURNING_PROMINENCE = 0.01
DEFAULT_MINIMUM_BRANCH_LENGTH = 10


@dataclass(frozen=True)
class Branch:
    """One monotonic acquisition-order branch."""

    indices: np.ndarray
    direction: int


class BranchSplittingMixin:
    """Provide configurable rising/falling branch detection and diagnostics."""

    smoothing_window: int
    smoothing_polyorder: int
    turning_point_prominence: float
    minimum_branch_length: int
    turning_points: list[int]
    branch_directions: list[int]

    def _init_branch_splitting(self) -> None:
        self.smoothing_window = DEFAULT_SMOOTHING_WINDOW
        self.smoothing_polyorder = DEFAULT_SMOOTHING_POLYORDER
        self.turning_point_prominence = DEFAULT_TURNING_PROMINENCE
        self.minimum_branch_length = DEFAULT_MINIMUM_BRANCH_LENGTH
        self.turning_points = []
        self.branch_directions = []

    def _split_branches(self, x: np.ndarray) -> list[Branch]:
        """Detect branches and update the public diagnostic attributes."""
        branches, self.turning_points = detect_branches(
            x,
            smoothing_window=self.smoothing_window,
            smoothing_polyorder=self.smoothing_polyorder,
            prominence_fraction=self.turning_point_prominence,
            minimum_length=self.minimum_branch_length,
        )
        self.branch_directions = [branch.direction for branch in branches]
        return branches


def detect_branches(
    x: np.ndarray,
    *,
    smoothing_window: int,
    smoothing_polyorder: int,
    prominence_fraction: float,
    minimum_length: int,
) -> tuple[list[Branch], list[int]]:
    """Smooth x and split it at prominent acquisition-order extrema."""
    from scipy.signal import find_peaks, savgol_filter  # type: ignore[import-untyped]  # noqa: PLC0415, I001

    n_points = len(x)
    if n_points < 3:
        return [], []
    window = _valid_savgol_window(smoothing_window, n_points)
    polyorder = min(max(0, int(smoothing_polyorder)), window - 1)
    smoothed = savgol_filter(x, window, polyorder, mode="interp")
    robust_span = float(np.percentile(smoothed, 95) - np.percentile(smoothed, 5))
    span = robust_span if robust_span > 0.0 else float(np.ptp(smoothed))
    prominence = max(0.0, float(prominence_fraction)) * span
    distance = max(2, int(minimum_length))
    peaks, peak_info = find_peaks(smoothed, prominence=prominence, distance=distance)
    troughs, trough_info = find_peaks(-smoothed, prominence=prominence, distance=distance)
    candidates = [
        (int(index), 1, float(value))
        for index, value in zip(peaks, peak_info["prominences"], strict=True)
    ]
    candidates.extend(
        (int(index), -1, float(value))
        for index, value in zip(troughs, trough_info["prominences"], strict=True)
    )
    candidates.sort()
    alternating: list[tuple[int, int, float]] = []
    for candidate in candidates:
        if alternating and candidate[1] == alternating[-1][1]:
            if candidate[2] > alternating[-1][2]:
                alternating[-1] = candidate
        else:
            alternating.append(candidate)

    turns = _remove_short_segments([item[0] for item in alternating], n_points, distance)
    boundaries = [0, *(turn + 1 for turn in turns), n_points]
    branches: list[Branch] = []
    for start, stop in zip(boundaries[:-1], boundaries[1:], strict=True):
        indices = np.arange(start, stop, dtype=int)
        if len(indices) < 2:
            continue
        delta = float(smoothed[indices[-1]] - smoothed[indices[0]])
        if delta != 0.0:
            branches.append(Branch(indices=indices, direction=1 if delta > 0.0 else -1))
    return branches, turns


def _valid_savgol_window(requested: int, n_points: int) -> int:
    window = max(3, int(requested))
    if window % 2 == 0:
        window += 1
    if window > n_points:
        window = n_points if n_points % 2 else n_points - 1
    return max(3, window)


def _remove_short_segments(turns: list[int], n_points: int, minimum: int) -> list[int]:
    retained = list(turns)
    while retained:
        boundaries = [0, *(turn + 1 for turn in retained), n_points]
        lengths = np.diff(np.asarray(boundaries, dtype=int))
        short = np.flatnonzero(lengths < minimum)
        if not len(short):
            break
        segment = int(short[0])
        if segment == 0:
            del retained[0]
        elif segment == len(boundaries) - 2:
            retained.pop()
        else:
            left = lengths[segment - 1]
            right = lengths[segment + 1]
            del retained[segment - 1 if left >= right else segment]
    return retained
