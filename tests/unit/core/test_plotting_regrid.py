"""Surface trace gridding, duplicate reduction and bounded interpolation."""

import numpy as np
import pytest

from stoner_measurement.core.plotting.contracts import PlotData
from stoner_measurement.core.plotting.regrid import regrid_trace


@pytest.mark.parametrize("policy, expected", [("mean", 3), ("first", 2), ("last", 4)])
def test_repeated_x_reduces_channels_in_acquisition_order(policy, expected):
    xs = np.array([1, 0, 1, np.nextafter(1.0, 2.0)])
    data = PlotData({"x": xs, "z": [2, 9, 3, 4], "value": [12, 19, 13, 14]})
    result = regrid_trace(data, policy=policy)
    np.testing.assert_array_equal(result.channels["x"], [0, 1])
    np.testing.assert_array_equal(result.channels["z"], [9, expected])
    np.testing.assert_array_equal(result.channels["value"], [19, expected + 10])
    np.testing.assert_array_equal(data.channels["x"], xs)
    assert result.metadata == data.metadata


def test_different_sampling_interpolates_onto_exact_existing_grid():
    data = PlotData({"x": [2, 0, 0.5], "z": [4, 0, 1], "value": [14, 10, 11]})
    result = regrid_trace(data, [0, 1, 2])
    np.testing.assert_array_equal(result.channels["x"], [0, 1, 2])
    np.testing.assert_array_equal(result.channels["z"], [0, 2, 4])
    np.testing.assert_array_equal(result.channels["value"], [10, 12, 14])


@pytest.mark.parametrize("bounds", ["nearest", "missing"])
def test_outside_range_uses_selected_bounds_policy(bounds):
    data = PlotData({"x": [0.1, 0.9], "z": [1, 9]})
    result = regrid_trace(data, [0, 0.5, 1], bounds=bounds)
    expected = [1, 5, 9] if bounds == "nearest" else [np.nan, 5, np.nan]
    np.testing.assert_allclose(result.channels["z"], expected)


def test_boundary_fill_uses_nearest_valid_signal_and_its_error():
    data = PlotData(
        {"x": [0, 1, 2], "z": [np.nan, 5, np.nan]},
        uncertainties={"z": [7, 0.2, 9]},
    )
    result = regrid_trace(data, [-1, 0, 1, 2, 3])
    np.testing.assert_allclose(result.channels["z"], [5, np.nan, 5, np.nan, 5])
    np.testing.assert_allclose(result.uncertainties["z"], [0.2, np.nan, 0.2, np.nan, 0.2])


def test_internal_nan_gaps_are_not_bridged_and_all_missing_stays_missing():
    data = PlotData({"x": [0, 1, 2], "z": [0, np.nan, 2], "value": [np.nan] * 3})
    result = regrid_trace(data, [-1, 0, 0.5, 1, 1.5, 2, 3])
    np.testing.assert_allclose(result.channels["z"], [0, 0, np.nan, np.nan, np.nan, 2, 2])
    assert np.all(np.isnan(result.channels["value"]))


def test_mean_and_interpolation_propagate_independent_errors():
    data = PlotData(
        {"x": [0, 0, 2], "z": [1, 3, 6]},
        uncertainties={"z": [3, 4, 2], "x": [0.3, 0.4, 0.2]},
    )
    result = regrid_trace(data, [-1, 0, 1, 2, 3])
    np.testing.assert_allclose(result.channels["z"], [2, 2, 4, 6, 6])
    expected = [2.5, 2.5, np.hypot(1.25, 1), 2, 2]
    np.testing.assert_allclose(result.uncertainties["z"], expected)
    np.testing.assert_allclose(result.uncertainties["x"], np.array(expected) / 10)


def test_single_coordinate_can_fill_bounds_or_leave_gaps():
    data = PlotData({"x": [1, 1], "z": [2, 4]})
    np.testing.assert_array_equal(regrid_trace(data, [0, 1, 2]).channels["z"], [3, 3, 3])
    np.testing.assert_allclose(
        regrid_trace(data, [0, 1, 2], bounds="missing").channels["z"], [np.nan, 3, np.nan]
    )


@pytest.mark.parametrize("xs", [[], [0, np.nan], [0, np.inf]])
def test_invalid_source_coordinates_are_rejected(xs):
    with pytest.raises(ValueError, match="nonempty, finite"):
        regrid_trace(PlotData({"x": xs, "z": xs}))


def test_strict_mode_preserves_samples_and_unknown_policies_fail():
    data = PlotData({"x": [1, 0, 1], "z": [2, 3, 4]})
    assert regrid_trace(data, [0, 2], policy="strict") is data
    with pytest.raises(ValueError, match="policy"):
        regrid_trace(data, policy="unsupported")
    with pytest.raises(ValueError, match="bounds"):
        regrid_trace(data, bounds="unsupported")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
