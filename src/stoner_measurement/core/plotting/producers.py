"""Build complete Cartesian requests from existing point/trace producers."""

from stoner_measurement.core.plotting.contracts import (
    AxisDescription,
    ChannelMetadata,
    ConfigureAxes,
    CoordinateBinding,
    PlotData,
    PlotOperation,
    SeriesUpdate,
    UpdateMode,
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
