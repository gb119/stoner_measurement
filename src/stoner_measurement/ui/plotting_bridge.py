"""Fixed Cartesian renderer bridge and explicitly allowlisted legacy access."""

from __future__ import annotations

from copy import deepcopy
from inspect import signature
from math import isfinite
from typing import cast

import numpy as np
from qtpy.QtGui import QColor

from stoner_measurement.core.plotting.contracts import (
    AddMarker,
    ClearPlot,
    ConfigureAxes,
    ModifySeries,
    Presentation,
    RemoveAxes,
    RemoveMarkers,
    RemoveSeries,
    SeriesUpdate,
    UpdateMode,
)
from stoner_measurement.core.plotting.service import LegacyCall
from stoner_measurement.ui.axis_mappings import AxisLabel, AxisScale, transform_values
from stoner_measurement.ui.plotting.cartesian import CARTESIAN_CAPABILITIES

LEGACY_METHODS = frozenset(
    {
        "append_point",
        "set_trace",
        "set_trace_with_errors",
        "set_default_axis_labels",
        "set_axis_label",
        "ensure_x_axis",
        "ensure_y_axis",
        "add_x_axis",
        "add_y_axis",
        "assign_trace_axes",
        "set_trace_style",
        "set_trace_style_from_dict",
        "set_trace_visible",
        "remove_trace",
        "rename_trace",
        "add_data_marker",
        "remove_data_marker",
        "clear_data_markers",
        "clear_all",
        "set_axis_scale",
        "set_axis_log_scale",
        "set_axis_side",
        "set_axis_visible",
        "set_axis_mouse_active",
        "set_axis_grid",
        "set_axis_range",
        "reset_all_view_ranges",
        "set_rolling_time_window",
        "x_data",
        "y_data",
        "trace_style",
    }
)


class CartesianPlotBridge:
    """Borrow the existing Cartesian widget and apply validated portable requests.

    Args:
        widget (PlotWidget): Existing GUI-owned renderer; this bridge does not close it.
        owns_widget (bool): The bundled factory opts into owned, idempotent close.
    """

    capabilities = CARTESIAN_CAPABILITIES

    def __init__(self, widget, *, owns_widget=False) -> None:
        self.widget = widget
        self.changed = widget.plot_state_changed
        self._owns_widget = owns_widget
        self._closed = False

    def close(self) -> None:
        """Close owned graphics once; standalone borrowed bridges retain ownership."""
        if self._owns_widget and not self._closed:
            self._closed = True
            self.widget.close()

    def export_state(self):
        """Use the widget's explicit public state export."""
        return self.widget.export_plot_state()

    def import_state(self, state) -> None:
        """Hydrate a candidate through the public Cartesian state API."""
        self.widget.import_plot_state(state)

    def export_settings(self):
        """Export versioned preferences without measurement arrays."""
        return self.widget.export_plot_settings()

    def import_settings(self, settings) -> None:
        """Restore versioned Cartesian renderer preferences."""
        self.widget.import_plot_settings(settings)

    def descriptions(self) -> tuple:
        """Return GUI-side public descriptions for service snapshots."""
        return self.widget.plot_axis_descriptions(), self.widget.plot_series_descriptions()

    def validate(self, payload) -> None:
        """Reject malformed style, axis and state changes before graphics mutation."""
        if isinstance(payload, (SeriesUpdate, ModifySeries)):
            self._validate_style(payload.style)
        if isinstance(payload, SeriesUpdate):
            axes = {axis.name: axis for axis in self.widget.plot_axis_descriptions()}
            for slot, name in payload.axes.items():
                if name in axes and axes[name].slot != slot:
                    raise ValueError(f"Axis {name!r} has the wrong orientation.")
        elif isinstance(payload, ModifySeries):
            if payload.series_id not in self.widget.trace_names:
                raise KeyError(f"Unknown series: {payload.series_id}.")
        elif isinstance(payload, ConfigureAxes):
            axes = {axis.name: axis for axis in self.widget.plot_axis_descriptions()}
            for axis in payload.axes:
                if axis.slot == "z":
                    raise ValueError("Cartesian trace display has no third axis.")
                if axis.name in axes and axes[axis.name].slot != axis.slot:
                    raise ValueError("An existing axis cannot change orientation.")
                if axis.side is not None and axis.side not in (
                    ("top", "bottom") if axis.slot == "x" else ("left", "right")
                ):
                    raise ValueError("Invalid axis side.")
                bounds = [value for value in axis.limits if value is not None]
                if bounds and not np.all(
                    np.isfinite(
                        transform_values(bounds, cast(AxisScale, axis.scale), axis.parameter)
                    )
                ):
                    raise ValueError("Axis limits are outside the scale domain.")
        elif isinstance(payload, AddMarker):
            axes = {axis.name: axis for axis in self.widget.plot_axis_descriptions()}
            for slot, name in self._marker_axes(payload).items():
                if name not in axes or axes[name].slot != slot:
                    raise ValueError("Marker anchor references an unknown axis.")
                if not np.isfinite(
                    transform_values(
                        [payload.position[slot]], axes[name].scale, axes[name].parameter
                    )[0]
                ):
                    raise ValueError("Marker is outside the axis scale domain.")

    @staticmethod
    def _validate_style(style) -> None:
        """Validate the Cartesian style vocabulary without creating a curve."""
        if "colour" in style and not QColor(style["colour"]).isValid():
            raise ValueError("Invalid colour.")
        if style.get("line_style", "solid") not in {"solid", "dash", "dot", "dash-dot", "none"}:
            raise ValueError("Invalid line style.")
        if style.get("point_style", "none") not in {
            "none",
            "circle",
            "square",
            "triangle",
            "diamond",
            "plus",
            "cross",
        }:
            raise ValueError("Invalid point style.")
        for key in ("line_width", "point_size"):
            if key in style and (not isfinite(float(style[key])) or float(style[key]) <= 0):
                raise ValueError(f"Invalid {key}.")

    def apply(self, payload):
        """Apply one complete logical operation; acknowledgement follows this return."""
        widget = self.widget
        if isinstance(payload, SeriesUpdate):
            self._apply_series(payload)
        elif isinstance(payload, ModifySeries):
            if payload.title is not None:
                widget.set_trace_title(payload.series_id, payload.title)
            if payload.visible is not None:
                widget.set_trace_visible(payload.series_id, payload.visible)
            if payload.style:
                widget.set_trace_style(payload.series_id, **dict(payload.style))
        elif isinstance(payload, RemoveSeries):
            widget.remove_trace(payload.series_id)
        elif isinstance(payload, ClearPlot):
            widget.clear_all()
        elif isinstance(payload, ConfigureAxes):
            for axis in payload.axes:
                ensure = widget.ensure_x_axis if axis.slot == "x" else widget.ensure_y_axis
                ensure(axis.name, AxisLabel(axis.label.name, axis.label.unit))
                widget.set_axis_scale(axis.name, axis.scale, axis.parameter)
                widget.set_axis_range(axis.name, *axis.limits)
                widget.set_axis_visible(axis.name, axis.visible)
                widget.set_axis_mouse_active(axis.name, axis.mouse_active)
                widget.set_axis_grid(axis.name, axis.grid)
                if axis.side is not None:
                    widget.set_axis_side(axis.name, axis.side)
        elif isinstance(payload, RemoveAxes):
            for name in payload.names:
                widget.remove_axis(name)
        elif isinstance(payload, AddMarker):
            axes = self._marker_axes(payload)
            return widget.add_data_marker(
                payload.position["x"],
                payload.position["y"],
                payload.label,
                x_axis=axes["x"],
                y_axis=axes["y"],
            )
        elif isinstance(payload, RemoveMarkers):
            if payload.marker_ids is None:
                widget.clear_data_markers()
            else:
                for marker_id in payload.marker_ids:
                    widget.remove_data_marker(marker_id)
        return None

    def _marker_axes(self, payload) -> dict:
        """Resolve omitted anchors once, using the first active axes."""
        axes = self.widget.plot_axis_descriptions()
        return {
            slot: payload.axes.get(
                slot,
                next(
                    (axis.name for axis in axes if axis.slot == slot and axis.mouse_active), default
                ),
            )
            for slot, default in (("x", "bottom"), ("y", "left"))
        }

    def _apply_series(self, update: SeriesUpdate) -> None:
        widget = self.widget
        name = update.series_id
        x_axis = update.axes.get("x", "bottom")
        y_axis = update.axes.get("y", "left")
        for slot, axis_name, source_key in (
            ("x", x_axis, update.binding.x),
            ("y", y_axis, update.binding.y),
        ):
            metadata = update.data.metadata[source_key]
            ensure = widget.ensure_x_axis if slot == "x" else widget.ensure_y_axis
            ensure(axis_name, AxisLabel(metadata.name, metadata.unit))
        xs = update.data.channels[update.binding.x]
        ys = update.data.channels[update.binding.y]
        # Point append uses the widget's existing list buffers: no whole-series copy.
        if update.mode == UpdateMode.APPEND and not update.data.uncertainties:
            for x, y in zip(xs, ys):
                widget.append_point(name, float(x), float(y))
            if name not in widget.trace_names:  # Empty append creates an empty series.
                widget.set_trace(name, [], [])
        else:
            errors = update.data.uncertainties
            xerr, yerr = errors.get(update.binding.x), errors.get(update.binding.y)
            if update.mode == UpdateMode.APPEND:
                # Error-bar append is less common; preserve prior uncertainties.
                old_x, old_y = widget.x_data(name), widget.y_data(name)
                old_errors = widget.trace_uncertainties(name)
                xs, ys = np.concatenate((old_x, xs)), np.concatenate((old_y, ys))
                xerr = np.concatenate(
                    (
                        old_errors[0] if old_errors[0] is not None else np.zeros(len(old_x)),
                        xerr
                        if xerr is not None
                        else np.zeros(len(update.data.channels[update.binding.x])),
                    )
                )
                yerr = np.concatenate(
                    (
                        old_errors[1] if old_errors[1] is not None else np.zeros(len(old_y)),
                        yerr
                        if yerr is not None
                        else np.zeros(len(update.data.channels[update.binding.y])),
                    )
                )
            widget.set_trace_with_errors(name, xs, ys, xerr, yerr)
        widget.assign_trace_axes(name, x_axis, y_axis)
        if update.title is not None:
            widget.set_trace_title(name, update.title)
        style = dict(update.style)
        if update.presentation == Presentation.POINTS:
            style.setdefault("line_style", "none")
            style.setdefault("point_style", "circle")
        if style:
            widget.set_trace_style(name, **style)

    def call_legacy(self, call: LegacyCall):
        """Call only the documented Cartesian compatibility surface on the GUI."""
        if call.name not in LEGACY_METHODS:
            raise AttributeError(call.name)
        return getattr(self.widget, call.name)(*call.args, **call.kwargs)

    def normalize_legacy(self, call: LegacyCall) -> LegacyCall:
        """Bind keyword arguments on the GUI before translating legacy calls."""
        if call.name not in LEGACY_METHODS:
            raise AttributeError(call.name)
        bound = signature(getattr(self.widget, call.name)).bind(*call.args, **call.kwargs)
        bound.apply_defaults()
        return LegacyCall(call.name, bound.args, bound.kwargs)

    def legacy_update(self, call: LegacyCall, existing):
        """Convert legacy data calls into portable updates before state commit."""
        from stoner_measurement.core.plotting.producers import xy_update

        name, xs, ys = call.args[:3]
        if call.name == "append_point":
            xs, ys = [xs], [ys]
        xerr, yerr = call.args[3:5] if call.name == "set_trace_with_errors" else (None, None)
        x_axis, y_axis = self.widget.trace_axis_names(name)
        metadata = existing.data.metadata if existing is not None else {}
        axes = {axis.name: axis for axis in self.widget.plot_axis_descriptions()}
        labels = [
            AxisLabel(metadata[key].name, metadata[key].unit)
            if key in metadata
            else AxisLabel(axes[axis_name].label.name, axes[axis_name].label.unit)
            for key, axis_name in (("x", x_axis), ("y", y_axis))
        ]
        return xy_update(
            name,
            xs,
            ys,
            x_error=xerr,
            y_error=yerr,
            x_label=labels[0],
            y_label=labels[1],
            x_axis=x_axis,
            y_axis=y_axis,
            append=call.name == "append_point",
        )


class LegacyPlotFacade:
    """Marshal legacy calls through the service; expose no graphics internals."""

    def __init__(self, service) -> None:
        self.service = service

    @property
    def trace_names(self) -> list[str]:
        """Return a snapshot of plotted series identities."""
        return [series.series_id for series in self.service.series()]

    @property
    def axis_names(self) -> list[str]:
        """Return a snapshot of public axis names."""
        return [axis.name for axis in self.service.axes()]

    def plot_axis_descriptions(self) -> tuple:
        """Return the service's axis descriptions, never a private widget map."""
        return self.service.axes()

    def is_busy_for_data(self) -> bool:
        """Report accepted outstanding requests."""
        return self.service.is_busy_for_data()

    def mark_data_update_queued(self) -> None:
        """Retain the legacy spelling; actual submissions own their tickets."""

    def __getattr__(self, name):
        if name not in LEGACY_METHODS:
            raise AttributeError(name)

        def invoke(*args, **kwargs):
            ticket = self.service.invoke_legacy(LegacyCall(name, deepcopy(args), deepcopy(kwargs)))
            result = ticket.wait(0 if self.service.is_gui_thread() else 10.0)
            if result is None:
                raise TimeoutError(f"Legacy plot call {name!r} timed out.")
            if result.status.value not in {"applied", "no_display"}:
                raise RuntimeError(result.message)
            return ticket.value

        return invoke
