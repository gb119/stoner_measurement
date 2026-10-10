"""Incremental canonical rectilinear cells and atomic trace-slice replacement."""

from dataclasses import replace

import numpy as np

from stoner_measurement.core.plotting.contracts import PlotData, SeriesUpdate, UpdateMode


class SurfaceGrid:
    """Store exact coordinate cells without assembling a full table per update.

    Args:
        update (SeriesUpdate): First update, supplying the schema and policies.

    Notes:
        Call validate before renderer mutation and commit only after successful
        application. Snapshots sort Y then X, leaving unacquired cells absent.
        Displays accepting this extension must implement the same slice/cell
        policies, including reset, and accept explicit replay snapshots.
    """

    def __init__(self, update: SeriesUpdate) -> None:
        self.template = update
        self.cells: dict[tuple[float, float], tuple[tuple, tuple]] = {}
        self.slices: dict[str, float] = {}
        self.x_grid: frozenset[float] | None = None

    def validate(self, update: SeriesUpdate) -> tuple[tuple[float, float], ...]:
        """Validate schema, grid and duplicates without changing stored cells."""
        surface = update.surface
        previous = self.template.surface
        if surface is None or previous is None:
            raise ValueError("Surface updates require explicit assembly bindings.")
        if (
            update.binding != self.template.binding
            or update.coordinates != self.template.coordinates
            or update.presentation != self.template.presentation
            or update.data.metadata != self.template.data.metadata
            or tuple(update.data.channels) != tuple(self.template.data.channels)
            or tuple(update.data.uncertainties) != tuple(self.template.data.uncertainties)
        ):
            raise ValueError(
                "Surface updates must preserve schema, metadata, binding and presentation."
            )
        if surface.acquisition_id != previous.acquisition_id:
            raise ValueError("A new acquisition requires an explicit surface reset.")
        xs = update.data.channels[update.binding.x]
        ys = update.data.channels[update.binding.y]
        if not np.all(np.isfinite(xs)) or not np.all(np.isfinite(ys)):
            raise ValueError("Surface grid coordinates must be finite.")
        keys = tuple(zip(map(float, xs), map(float, ys), strict=True))
        if not keys or len(set(keys)) != len(keys):
            raise ValueError("A surface update requires distinct, nonempty grid cells.")
        if surface.kind == "slice":
            if len(set(map(float, ys))) != 1:
                raise ValueError("A trace slice requires one fixed Y coordinate.")
            grid = frozenset(map(float, xs))
            if self.x_grid is None and any(x not in grid for x, _ in self.cells):
                raise ValueError("Trace X grid does not include existing surface cells.")
            if self.x_grid is not None and grid != self.x_grid:
                raise ValueError("Trace slices must retain the established X grid.")
            assert surface.slice_id is not None
            old_y = self.slices.get(surface.slice_id)
            if old_y is not None and old_y != keys[0][1]:
                raise ValueError("A slice ID must retain its fixed Y coordinate.")
            if any(y == keys[0][1] and name != surface.slice_id for name, y in self.slices.items()):
                raise ValueError("A fixed Y coordinate already belongs to another slice ID.")
        elif surface.kind == "cells" and self.x_grid is not None:
            if any(x not in self.x_grid for x, _ in keys):
                raise ValueError("Surface cells must use the established trace X grid.")
        elif surface.kind == "snapshot":
            for _name, y in surface.slices:
                grid = frozenset(x for x, row_y in keys if row_y == y)
                if not grid or (self.x_grid is not None and grid != self.x_grid):
                    raise ValueError("Replay slices must share a nonempty X grid.")
                # Compare replay rows without mutating the live accumulator.
                first_grid = frozenset(x for x, row_y in keys if row_y == surface.slices[0][1])
                if grid != first_grid:
                    raise ValueError("Replay slices must share the same X grid.")
        if surface.kind != "snapshot" and surface.duplicates == "reject":
            if any(key in self.cells for key in keys):
                raise ValueError("Duplicate surface cells; select Replace or clear the surface.")
        return keys

    def commit(self, update: SeriesUpdate, keys: tuple) -> None:
        """Apply previously validated cells after renderer acceptance."""
        surface = update.surface
        assert surface is not None
        if surface.kind == "snapshot":
            self.cells.clear()
            self.slices = dict(surface.slices)
            self.x_grid = (
                frozenset(x for x, y in keys if y == surface.slices[0][1])
                if surface.slices
                else None
            )
        elif surface.kind == "slice":
            assert surface.slice_id is not None
            self.x_grid = frozenset(x for x, _ in keys)
            self.slices[surface.slice_id] = keys[0][1]
        channels = tuple(update.data.channels.values())
        errors = tuple(update.data.uncertainties.values())
        for index, key in enumerate(keys):
            self.cells[key] = (
                tuple(column[index] for column in channels),
                tuple(column[index] for column in errors),
            )
        self.template = update

    def snapshot(self) -> SeriesUpdate:
        """Capture ordered cells and slice identities only on explicit export."""
        assert self.template.surface is not None
        rows = [self.cells[key] for key in sorted(self.cells, key=lambda key: (key[1], key[0]))]
        channels = {
            name: [row[0][index] for row in rows]
            for index, name in enumerate(self.template.data.channels)
        }
        errors = {
            name: [row[1][index] for row in rows]
            for index, name in enumerate(self.template.data.uncertainties)
        }
        return replace(
            self.template,
            data=PlotData(channels, self.template.data.metadata, errors),
            mode=UpdateMode.REPLACE,
            surface=replace(
                self.template.surface,
                kind="snapshot",
                slice_id=None,
                slices=tuple(self.slices.items()),
            ),
        )


def prepare_surface(
    update: SeriesUpdate, existing: SurfaceGrid | None
) -> tuple[SurfaceGrid, tuple]:
    """Prepare an incremental transaction, or an explicitly requested new run."""
    surface = update.surface
    if surface is None:
        raise ValueError("Surface updates require explicit assembly bindings.")
    if existing is not None:
        assert existing.template.surface is not None
        if surface.acquisition_id != existing.template.surface.acquisition_id:
            if not surface.reset_on_change:
                raise ValueError("Acquisition ID changed; enable reset or clear the surface first.")
            existing = None
    grid = existing if existing is not None else SurfaceGrid(update)
    return grid, grid.validate(update)
