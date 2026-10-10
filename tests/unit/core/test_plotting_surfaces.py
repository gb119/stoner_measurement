"""Rectilinear surface policies, immutable snapshots and incremental ownership."""

from dataclasses import replace

import numpy as np
import pytest

from stoner_measurement.core.plotting.contracts import (
    ChannelMetadata,
    CoordinateDescriptor,
    PlotCapabilities,
    PlotData,
    PlotOperation,
    PlotRequest,
    Presentation,
    SurfaceBinding,
)
from stoner_measurement.core.plotting.producers import generalised_update
from stoner_measurement.core.plotting.surfaces import prepare_surface


def slice_update(y=0, *, xs=(0, 1), zs=(4, 5), **kwargs):
    return generalised_update(
        "grid", xs, [y] * len(xs), zs, form="xyz", slice_id=repr(float(y)), **kwargs
    )


def apply(update, grid=None):
    grid, keys = prepare_surface(update, grid)
    grid.commit(update, keys)
    return grid


def test_slices_accumulate_and_replay_retains_reacquisition_identity():
    grid = apply(slice_update(10, duplicates="replace"))
    apply(slice_update(20, xs=(1, 0), zs=(6, 7), duplicates="replace"), grid)
    snapshot = grid.snapshot()
    assert snapshot.surface.slices == (("10.0", 10.0), ("20.0", 20.0))
    restored = apply(snapshot)
    apply(slice_update(10, zs=(8, 9), duplicates="replace"), restored)
    np.testing.assert_array_equal(restored.snapshot().data.channels["z"], [8, 9, 7, 6])


def test_point_cells_are_sorted_by_coordinates_and_missing_cells_stay_absent():
    grid = None
    for x, y, z in ((0, 0, 1), (1, 0, 2), (1, 1, np.nan)):
        grid = apply(
            generalised_update("grid", [x], [y], [z], form="xy_intensity", append=True), grid
        )
    data = grid.snapshot().data
    assert len(grid.cells) == 3
    np.testing.assert_array_equal(data.channels["x"], [0, 1, 1])
    assert np.isnan(data.channels["z"][-1])
    assert grid.snapshot().binding.value == "z" and grid.snapshot().binding.z is None


@pytest.mark.parametrize(
    "bad, message",
    [
        (slice_update(0), "Duplicate"),
        (slice_update(1, xs=(0, 2)), "X grid"),
        (slice_update(np.nan), "finite"),
        (slice_update(1, xs=(0, np.inf)), "finite"),
        (slice_update(1, xs=(0, 0)), "distinct"),
        (slice_update(1, acquisition_id="next"), "reset"),
        (
            replace(slice_update(1), surface=SurfaceBinding("grid", kind="slice", slice_id="0.0")),
            "retain",
        ),
        (
            replace(slice_update(1), data=PlotData({"x": [0, 1], "y": [1, 2], "z": [4, 5]})),
            "fixed Y",
        ),
        (
            replace(
                slice_update(1),
                data=PlotData(
                    {"x": [0, 1], "y": [1, 1], "z": [4, 5]}, {"z": ChannelMetadata("changed", "K")}
                ),
            ),
            "metadata",
        ),
    ],
)
def test_invalid_slice_is_rejected_without_mutating_existing_cells(bad, message):
    grid = apply(slice_update(0))
    before = dict(grid.cells)
    with pytest.raises(ValueError, match=message):
        prepare_surface(bad, grid)
    assert grid.cells == before


def test_explicit_run_change_resets_without_inheriting_cells():
    first = apply(slice_update(0))
    new = apply(slice_update(5, acquisition_id="next", reset_on_change=True), first)
    assert len(new.cells) == 2 and len(first.cells) == 2
    assert new.snapshot().surface.acquisition_id == "next"
    assert set(new.slices) == {"5.0"}


def test_duplicate_cell_replace_and_exact_float_keys():
    point = generalised_update("grid", [1], [2], [3], form="xyz", append=True, duplicates="replace")
    grid = apply(point)
    apply(replace(point, data=PlotData({"x": [1], "y": [2], "z": [8]})), grid)
    apply(replace(point, data=PlotData({"x": [np.nextafter(1.0, 2.0)], "y": [2], "z": [9]})), grid)
    assert len(grid.cells) == 2
    np.testing.assert_array_equal(grid.snapshot().data.channels["z"], [8, 9])


def test_xyz_and_independent_value_are_never_interchanged_and_snapshots_are_immutable():
    values = np.array([8.0, 9.0])
    update = generalised_update(
        "grid", [0, 1], [2, 2], [4, 5], form="xyz_value", values=values, slice_id="slice"
    )
    values[:] = 0
    assert update.binding.z == "z" and update.binding.value == "value"
    np.testing.assert_array_equal(update.data.channels["value"], [8, 9])
    with pytest.raises(ValueError):
        update.data.channels["x"].setflags(write=True)


def test_existing_factory_requires_explicit_surface_opt_in():
    capabilities = PlotCapabilities(
        frozenset({("cartesian", 3)}),
        frozenset({Presentation.SURFACE}),
        frozenset({PlotOperation.UPDATE_SERIES}),
    )
    request = PlotRequest(slice_update())
    assert capabilities.unsupported_reasons(request) == (
        "Rectilinear surface assembly is unsupported.",
    )
    assert replace(capabilities, surface_versions=frozenset({1})).unsupported_reasons(request) == ()


def test_cell_updates_do_not_snapshot_or_copy_the_existing_grid(monkeypatch):
    point = generalised_update("grid", [0], [0], [3], form="xyz", append=True)
    grid = apply(point)
    cells = grid.cells

    def no_snapshot():
        pytest.fail("Incremental updates must not assemble canonical snapshots")

    monkeypatch.setattr(grid, "snapshot", no_snapshot)
    for x in range(1, 1001):
        apply(replace(point, data=PlotData({"x": [x], "y": [0], "z": [x]})), grid)
    assert grid.cells is cells and len(cells) == 1001


def test_duplicate_policy_can_be_explicitly_changed_for_reacquisition():
    grid = apply(slice_update(0))
    apply(slice_update(0, zs=(8, 9), duplicates="replace"), grid)
    np.testing.assert_array_equal(grid.snapshot().data.channels["z"], [8, 9])


def test_intensity_uncertainties_require_explicit_independent_value_support():
    update = generalised_update(
        "grid", [1], [2], [3], form="xy_intensity", append=True, errors={"z": [0.1]}
    )
    caps = PlotCapabilities(
        frozenset({("cartesian", 2)}),
        frozenset({Presentation.INTENSITY}),
        frozenset({PlotOperation.UPDATE_SERIES}),
        value_channel=True,
        surface_versions=frozenset({1}),
    )
    request = PlotRequest(update)
    assert caps.unsupported_reasons(request) == (
        "Independent value uncertainties are unsupported.",
    )
    assert replace(caps, value_uncertainties=True).unsupported_reasons(request) == ()


def test_explicit_angular_coordinates_preserve_source_samples():
    update = generalised_update(
        "grid",
        [1],
        [90],
        [4],
        form="xyz",
        append=True,
        coordinates=CoordinateDescriptor("cylindrical", "degrees"),
        labels={"y": ChannelMetadata("Azimuth", "deg")},
    )
    np.testing.assert_array_equal(apply(update).snapshot().data.channels["y"], [90])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
