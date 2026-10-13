"""Source-coordinate plotting contracts and safe queued data snapshots."""

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from stoner_measurement.core.plotting.contracts import (
    AddMarker,
    AngularUnit,
    AxisDescription,
    ChannelMetadata,
    ClearPlot,
    ConfigureAxes,
    CoordinateBinding,
    CoordinateDescriptor,
    CoordinateSystem,
    ModifySeries,
    PlotCapabilities,
    PlotData,
    PlotOperation,
    PlotRequest,
    PlotResult,
    Presentation,
    RemoveAxes,
    RemoveMarkers,
    RemoveSeries,
    ResultStatus,
    SeriesDescription,
    SeriesUpdate,
    SphericalConvention,
    UpdateMode,
)


def test_snapshot_survives_producer_mutation_and_cannot_be_made_writable():
    values = np.array([1.0, 2.0])
    errors = np.array([0.1, 0.2])
    channels = {"field": values}
    metadata = {"field": ChannelMetadata("Field", "T")}
    uncertainties = {"field": errors}
    data = PlotData(channels, metadata, uncertainties)
    values[:] = 99
    errors[:] = 99
    channels.clear()
    metadata.clear()
    uncertainties.clear()

    np.testing.assert_array_equal(data.channels["field"], [1, 2])
    np.testing.assert_array_equal(data.uncertainties["field"], [0.1, 0.2])
    assert data.metadata["field"].unit == "T"
    for column in (data.channels["field"], data.uncertainties["field"]):
        with pytest.raises(ValueError):
            column[0] = 4
        with pytest.raises(ValueError):
            column.setflags(write=True)
    with pytest.raises(TypeError):
        data.channels["new"] = values
    with pytest.raises(FrozenInstanceError):
        data.metadata["field"].unit = "V"


@pytest.mark.parametrize(
    "channels,metadata,errors",
    [
        ({}, {}, {}),
        ({"x": [1], "y": [1, 2]}, {}, {}),
        ({"x": [[1, 2]]}, {}, {}),
        ({"": [1]}, {}, {}),
        ({"x": [1]}, {"missing": ChannelMetadata()}, {}),
        ({"x": [1]}, {"x": {"unit": "T"}}, {}),
        ({"x": [1]}, {}, {"missing": [1]}),
        ({"x": [1]}, {}, {"x": [1, 2]}),
        ({"x": [1]}, {}, {"x": [-0.1]}),
    ],
)
def test_invalid_sample_tables_are_rejected(channels, metadata, errors):
    with pytest.raises(ValueError):
        PlotData(channels, metadata, errors)


def test_empty_and_missing_samples_remain_representable():
    assert len(PlotData({"x": [], "y": []}).channels["x"]) == 0
    data = PlotData({"x": [1, np.nan], "y": [np.nan, 3]}, uncertainties={"y": [0, np.nan]})
    assert np.isnan(data.channels["x"][1])
    assert np.isnan(data.uncertainties["y"][1])


def test_complete_trace_request_captures_axes_style_and_errors():
    axes = {"x": "bottom", "y": "right"}
    style = {"colour": "red", "line_width": 3.0}
    update = SeriesUpdate(
        "sample:voltage",
        PlotData({"field": [1, 2], "voltage": [3, 4]}, uncertainties={"voltage": [0.1, 0.2]}),
        CoordinateBinding("field", "voltage"),
        title="Voltage",
        axes=axes,
        style=style,
    )
    axes["y"] = "left"
    style["colour"] = "blue"
    assert update.axes["y"] == "right"
    assert update.style["colour"] == "red"
    assert update.series_id != update.title
    assert PlotRequest(update).request_id != PlotRequest(update).request_id


def test_point_append_uses_same_complete_sample_contract():
    update = SeriesUpdate(
        "voltage",
        PlotData({"x": [1], "y": [2]}),
        CoordinateBinding("x", "y"),
        mode=UpdateMode.APPEND,
        presentation=Presentation.POINTS,
    )
    assert update.mode == UpdateMode.APPEND
    assert len(update.data.channels["x"]) == 1


@pytest.mark.parametrize(
    "system,binding,convention",
    [
        (CoordinateSystem.POLAR, CoordinateBinding("theta", "radius"), None),
        (CoordinateSystem.CYLINDRICAL, CoordinateBinding("radius", "theta", "height"), None),
        (
            CoordinateSystem.SPHERICAL,
            CoordinateBinding("radius", "theta", "phi"),
            SphericalConvention.THETA_INCLINATION,
        ),
        (
            CoordinateSystem.SPHERICAL,
            CoordinateBinding("radius", "theta", "phi"),
            SphericalConvention.THETA_AZIMUTH,
        ),
    ],
)
def test_generalised_coordinates_preserve_source_values(system, binding, convention):
    data = PlotData(
        {"radius": [2], "theta": [90], "phi": [180], "height": [4]},
        {"theta": ChannelMetadata("theta", "deg"), "phi": ChannelMetadata("phi", "deg")},
    )
    update = SeriesUpdate(
        "angular",
        data,
        binding,
        CoordinateDescriptor(system, AngularUnit.DEGREES, spherical_convention=convention),
    )
    assert update.binding.x == ("theta" if system == CoordinateSystem.POLAR else "radius")
    assert update.data.channels["theta"][0] == 90
    assert update.coordinates.spherical_convention == convention


@pytest.mark.parametrize(
    "descriptor,binding",
    [
        (CoordinateDescriptor(), CoordinateBinding("missing", "y")),
        (CoordinateDescriptor(CoordinateSystem.POLAR), CoordinateBinding("x", "y", "z")),
        (CoordinateDescriptor(CoordinateSystem.CYLINDRICAL), CoordinateBinding("x", "y")),
        (
            CoordinateDescriptor(CoordinateSystem.POLAR, AngularUnit.DEGREES),
            CoordinateBinding("x", "y"),
        ),
    ],
)
def test_invalid_bindings_and_angular_units_fail_before_dispatch(descriptor, binding):
    data = PlotData({"x": [1], "y": [2], "z": [3]}, {"x": ChannelMetadata("phase", "rad")})
    with pytest.raises(ValueError):
        SeriesUpdate("bad", data, binding, descriptor)


def test_spherical_convention_is_required_and_system_specific():
    with pytest.raises(ValueError, match="explicit"):
        CoordinateDescriptor(CoordinateSystem.SPHERICAL)
    with pytest.raises(ValueError, match="only"):
        CoordinateDescriptor(spherical_convention=SphericalConvention.THETA_INCLINATION)


def test_intensity_is_independent_of_third_coordinate():
    data = PlotData({"x": [1], "y": [2], "height": [3], "signal": [4]})
    update = SeriesUpdate(
        "map",
        data,
        CoordinateBinding("x", "y", value="signal"),
        presentation=Presentation.INTENSITY,
    )
    assert update.binding.dimensions == 2
    assert update.binding.value == "signal"
    with pytest.raises(ValueError, match="value channel"):
        SeriesUpdate(
            "map", data, CoordinateBinding("x", "y", "height"), presentation=Presentation.INTENSITY
        )


def test_capabilities_return_explicit_rejections_instead_of_dropping_features():
    capabilities = PlotCapabilities(
        {(CoordinateSystem.CARTESIAN, 2)},
        {Presentation.LINE},
        {PlotOperation.UPDATE_SERIES},
    )
    supported = SeriesUpdate("a", PlotData({"x": [1], "y": [2]}), CoordinateBinding("x", "y"))
    assert capabilities.unsupported_reasons(PlotRequest(supported)) == ()
    request = PlotRequest(
        SeriesUpdate(
            "b",
            PlotData({"x": [1], "y": [2], "z": [3], "value": [4]}, uncertainties={"z": [0.1]}),
            CoordinateBinding("x", "y", "z", "value"),
            presentation=Presentation.POINTS,
            axes={"y": "right"},
        )
    )
    reasons = " ".join(capabilities.unsupported_reasons(request))
    for feature in ("coordinates", "presentation", "Named axes", "uncertainties", "value channels"):
        assert feature in reasons
    assert capabilities.unsupported_reasons(PlotRequest(ClearPlot()))
    assert capabilities.unsupported_reasons(
        PlotRequest(ConfigureAxes((AxisDescription("right", "y"),)))
    )


def test_capability_collections_are_immutable_and_layouts_validated():
    operations = {PlotOperation.CLEAR}
    capabilities = PlotCapabilities(
        {(CoordinateSystem.CARTESIAN, 2)}, {Presentation.LINE}, operations
    )
    operations.clear()
    assert capabilities.operations == {PlotOperation.CLEAR}
    with pytest.raises(ValueError):
        PlotCapabilities({(CoordinateSystem.POLAR, 3)}, {Presentation.LINE}, operations)


def test_marker_coordinates_and_axis_anchors_are_captured():
    position = {"x": 1.0, "y": 2.0}
    axes = {"x": "top", "y": "right"}
    marker = AddMarker(position, axes=axes)
    position["x"] = 99
    axes["y"] = "left"
    assert marker.position["x"] == 1
    assert marker.axes["y"] == "right"
    assert marker.label is None
    assert RemoveMarkers().marker_ids is None
    with pytest.raises(ValueError):
        AddMarker({"x": 1})


@pytest.mark.parametrize("limits", [(2, 1), (1, 1), (np.inf, None), (1,)])
def test_invalid_axis_ranges_rejected(limits):
    with pytest.raises(ValueError):
        AxisDescription("bottom", "x", limits=limits)


def test_partial_axis_range_and_all_operations_have_portable_records():
    axis = AxisDescription("bottom", "x", limits=(0, None), mouse_active=True)
    configure = ConfigureAxes([axis])
    assert configure.axes == (axis,)
    with pytest.raises(ValueError, match="unique"):
        ConfigureAxes((axis, axis))
    payloads = (
        SeriesUpdate("a", PlotData({"x": [], "y": []}), CoordinateBinding("x", "y")),
        ModifySeries("a", title="New", visible=False),
        RemoveSeries("a"),
        configure,
        RemoveAxes(["bottom"]),
        AddMarker({"x": 1, "y": 2}),
        RemoveMarkers(),
        ClearPlot(),
    )
    assert {payload.operation for payload in payloads} == set(PlotOperation)
    assert SeriesDescription("a", "New", CoordinateBinding("x", "y")).series_id == "a"


@pytest.mark.parametrize("status", list(ResultStatus))
def test_terminal_results_keep_identity_and_generation(status):
    result = PlotResult("request", "main", 3, status, message="detail")
    assert result.request_id == "request"
    assert result.generation == 3
    with pytest.raises(ValueError):
        PlotResult("request", "main", -1, status, message="detail")


@pytest.mark.parametrize(
    "status", [ResultStatus.UNSUPPORTED, ResultStatus.FAILED, ResultStatus.CANCELLED]
)
def test_failure_results_require_diagnostics(status):
    with pytest.raises(ValueError):
        PlotResult("request", "main", 1, status)


def test_mutable_metadata_and_untyped_payloads_are_rejected():
    with pytest.raises(ValueError):
        ChannelMetadata(name=["Field"])
    with pytest.raises(ValueError):
        CoordinateBinding(None, "y")
    with pytest.raises(ValueError):
        AxisDescription("bottom", "x", label={"unit": "T"})
    with pytest.raises(ValueError):
        PlotRequest({"operation": "clear"})


def test_error_results_cannot_return_successful_marker_identifiers():
    with pytest.raises(ValueError):
        PlotResult("request", "main", 1, ResultStatus.FAILED, "error", marker_id=1)
    assert PlotResult("request", "main", 1, ResultStatus.APPLIED, marker_id=1).marker_id == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
