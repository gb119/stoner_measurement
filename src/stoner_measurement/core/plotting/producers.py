"""Build complete Cartesian requests from existing point/trace producers."""

from stoner_measurement.core.plotting.contracts import (
    AxisDescription,
    ChannelMetadata,
    ConfigureAxes,
    CoordinateBinding,
    CoordinateDescriptor,
    PlotData,
    PlotOperation,
    Presentation,
    SeriesUpdate,
    SurfaceBinding,
    UpdateMode,
)


def generalised_update(
    surface_id,
    xs,
    ys,
    zs,
    *,
    form,
    acquisition_id="default",
    slice_id=None,
    duplicates="reject",
    reset_on_change=False,
    coordinates=None,
    labels=None,
    errors=None,
    values=None,
    title=None,
    style=None,
    append=False,
) -> SeriesUpdate:
    """Capture an explicitly bound XYZ/intensity slice or point transaction.

    Args:
        surface_id (str): Stable identity independent of the displayed title.
        xs, ys, zs (array-like): Equal-length captured source columns.

    Keyword Parameters:
        form (str): xyz, xy_intensity, or xyz_value; never inferred from roles.
        acquisition_id (str): Explicit run identity.
        slice_id (str | None): Whole-slice identity; None denotes cell updates.
        duplicates (str): reject or replace repeated cells/slices.
        reset_on_change (bool): Permit a new run to reset this surface.
        coordinates (CoordinateDescriptor | None): Source coordinate meaning.
        labels (dict | None): ChannelMetadata or structured physical labels.
        errors (dict | None): Uncertainties keyed by captured source slots.
        values (array-like | None): Explicit independent colour for xyz_value.
        title (str | None): User-facing title, independent of identity.
        style (dict | None): Applicable renderer style overrides.
        append (bool): Append cells rather than replace a complete slice.

    Returns:
        (SeriesUpdate): Immutable, complete surface transaction.

    Raises:
        ValueError: For unknown forms, missing independent values or bad shapes.
    """
    if form not in ("xyz", "xy_intensity", "xyz_value"):
        raise ValueError(f"Unknown plotting form: {form!r}.")
    channels = {"x": xs, "y": ys, "z": zs}
    if form == "xyz_value":
        if values is None:
            raise ValueError("Coloured XYZ requires an explicit independent value source.")
        channels["value"] = values
    metadata = {
        key: label
        if isinstance(label, ChannelMetadata)
        else ChannelMetadata(getattr(label, "label", str(label)), getattr(label, "unit", ""))
        for key, label in (labels or {}).items()
    }
    binding = CoordinateBinding(
        "x",
        "y",
        z=None if form == "xy_intensity" else "z",
        value="z" if form == "xy_intensity" else "value" if form == "xyz_value" else None,
    )
    return SeriesUpdate(
        surface_id,
        PlotData(channels, metadata, errors),
        binding,
        coordinates=coordinates or CoordinateDescriptor(),
        presentation=Presentation.INTENSITY
        if form == "xy_intensity"
        else (Presentation.POINTS if append else Presentation.SURFACE),
        mode=UpdateMode.APPEND if append else UpdateMode.REPLACE,
        title=title,
        style=style or {},
        surface=SurfaceBinding(
            surface_id,
            acquisition_id,
            "cells" if append else "slice",
            slice_id,
            duplicates,
            reset_on_change,
        ),
    )


def ensure_plugin_axes(plugin, axes) -> bool:
    """Ensure missing configured axes through a capable portable endpoint.

    Return False for the standalone legacy path. Displays without explicit axis
    configuration defer axis handling to their complete series updates.
    """
    client = getattr(plugin.sequence_engine, "plot_client", None)
    if client is None:
        return False
    capabilities = client.capabilities()
    if capabilities is None or PlotOperation.CONFIGURE_AXES not in capabilities.operations:
        return True
    existing = {axis.name for axis in client.axes()}
    missing = tuple(
        AxisDescription(name, slot, ChannelMetadata(name))
        for slot, name in dict.fromkeys(axes)
        if name not in existing
    )
    if missing:
        from stoner_measurement.core.plotting.service import submit_from_plugin

        submit_from_plugin(plugin, ConfigureAxes(missing))
    return True


def xy_update(
    name,
    xs,
    ys,
    *,
    x_error=None,
    y_error=None,
    x_label="",
    y_label="",
    x_axis="bottom",
    y_axis="left",
    style=None,
    append=False,
) -> SeriesUpdate:
    """Capture data, errors, physical labels, axes and styles in one operation.

    Labels may be strings or existing structured labels with label/unit fields.
    Their conversion does not import the rendering library or any QWidget.
    """
    metadata = {
        key: ChannelMetadata(getattr(label, "label", str(label)), getattr(label, "unit", ""))
        for key, label in (("x", x_label), ("y", y_label))
    }
    errors = {key: value for key, value in (("x", x_error), ("y", y_error)) if value is not None}
    return SeriesUpdate(
        name,
        PlotData({"x": xs, "y": ys}, metadata, errors),
        CoordinateBinding("x", "y"),
        mode=UpdateMode.APPEND if append else UpdateMode.REPLACE,
        axes={"x": x_axis, "y": y_axis},
        style=style or {},
    )
