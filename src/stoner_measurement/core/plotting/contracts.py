"""Version-one plotting messages and producer interfaces.

These records describe source coordinates, never projected graphics positions.
They contain no widget or rendering-library references. The service module
implements dispatch and acknowledgements; display factories remain a later stage.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import ClassVar, Literal, Protocol
from uuid import uuid4

import numpy as np
from numpy.typing import ArrayLike, NDArray

CONTRACT_VERSION = 1
CoordinateSlot = Literal["x", "y", "z"]


class CoordinateSystem(StrEnum):
    """Meaning of the generalised x, y and z coordinate slots."""

    CARTESIAN = "cartesian"
    POLAR = "polar"
    CYLINDRICAL = "cylindrical"
    SPHERICAL = "spherical"


class AngularUnit(StrEnum):
    """Units shared by angular slots in a coordinate descriptor."""

    RADIANS = "radians"
    DEGREES = "degrees"


class AngleWrapping(StrEnum):
    """Azimuth display convention; inclination is never wrapped."""

    NONE = "none"
    POSITIVE = "positive"
    SIGNED = "signed"


class SphericalConvention(StrEnum):
    """Explicit meanings for spherical theta (y) and phi (z)."""

    THETA_INCLINATION = "theta_inclination_phi_azimuth"
    THETA_AZIMUTH = "theta_azimuth_phi_inclination"


@dataclass(frozen=True)
class CoordinateDescriptor:
    """Define source coordinates and their angular display conventions.

    Args:
        system (CoordinateSystem): Cartesian, polar, cylindrical or spherical.
        angular_unit (AngularUnit): Units of all angular coordinate slots.
        wrapping (AngleWrapping): Azimuth wrapping about angular_origin.
        angular_origin (float): Azimuth reference direction in angular_unit.
        clockwise (bool): Whether increasing azimuth is displayed clockwise.
        spherical_convention (SphericalConvention | None): Required explicitly
            for spherical coordinates; forbidden for other systems. Inclination
            is measured from the positive polar axis, not the equatorial plane.

    Notes:
        Cylindrical slots are r, theta, axial z; spherical slots are r, theta,
        phi. Descriptors do not convert or wrap acquisition arrays.
    """

    system: CoordinateSystem = CoordinateSystem.CARTESIAN
    angular_unit: AngularUnit = AngularUnit.RADIANS
    wrapping: AngleWrapping = AngleWrapping.NONE
    angular_origin: float = 0.0
    clockwise: bool = False
    spherical_convention: SphericalConvention | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "system", CoordinateSystem(self.system))
        object.__setattr__(self, "angular_unit", AngularUnit(self.angular_unit))
        object.__setattr__(self, "wrapping", AngleWrapping(self.wrapping))
        if not isfinite(self.angular_origin):
            raise ValueError("Angular origin must be finite.")
        if self.system == CoordinateSystem.SPHERICAL:
            if self.spherical_convention is None:
                raise ValueError("Spherical coordinates require an explicit angle convention.")
            object.__setattr__(
                self, "spherical_convention", SphericalConvention(self.spherical_convention)
            )
        elif self.spherical_convention is not None:
            raise ValueError("A spherical convention applies only to spherical coordinates.")

    def validate_dimensions(self, dimensions: int) -> None:
        """Reject coordinate counts that do not match this system.

        Args:
            dimensions (int): Number of bound coordinates, either two or three.

        Raises:
            ValueError: If the coordinate count is incompatible.
        """
        allowed = {
            CoordinateSystem.CARTESIAN: (2, 3),
            CoordinateSystem.POLAR: (2,),
            CoordinateSystem.CYLINDRICAL: (3,),
            CoordinateSystem.SPHERICAL: (3,),
        }
        if dimensions not in allowed[self.system]:
            raise ValueError(f"{self.system} does not support {dimensions} coordinates.")


@dataclass(frozen=True)
class ChannelMetadata:
    """Describe one source channel without coupling to an axis widget.

    Args:
        name (str): Human-readable physical quantity.
        unit (str): Source unit; angular metadata must agree with the descriptor.
        source_key (str | None): Optional catalogue reference for provenance.
        column_key (str | None): Optional column reference within that source.
    """

    name: str = ""
    unit: str = ""
    source_key: str | None = None
    column_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not isinstance(self.unit, str):
            raise ValueError("Channel names and units must be strings.")
        for reference in (self.source_key, self.column_key):
            if reference is not None:
                _nonempty(reference, "Source reference")


def _nonempty(value: object, name: str) -> None:
    """Require a nonblank identifier without silently rewriting it."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string.")


@dataclass(frozen=True, init=False)
class PlotData:
    """Capture an owned, immutable snapshot of equally sized source channels.

    Args:
        channels (Mapping[str, ArrayLike]): One-dimensional numeric columns.
            Empty columns are valid; at least one named channel is required.
        metadata (Mapping[str, ChannelMetadata]): Optional descriptions of
            existing channels. Missing descriptions are completed from keys.
        uncertainties (Mapping[str, ArrayLike]): Optional symmetric absolute
            uncertainties keyed by their source channel, in the same units.

    Raises:
        ValueError: For missing channels, inconsistent shapes, invalid metadata
            or negative uncertainties. NaNs remain valid missing samples.

    Notes:
        Arrays are backed by owned immutable bytes, so a recipient cannot
        re-enable write access. Mutating a producer's arrays or mappings after
        construction does not change the snapshot. Topology/interpolation for
        maps and surfaces is deliberately outside this version's sample table.
    """

    channels: Mapping[str, NDArray[np.float64]]
    metadata: Mapping[str, ChannelMetadata]
    uncertainties: Mapping[str, NDArray[np.float64]]

    def __init__(
        self,
        channels: Mapping[str, ArrayLike],
        metadata: Mapping[str, ChannelMetadata] | None = None,
        uncertainties: Mapping[str, ArrayLike] | None = None,
    ) -> None:
        """Normalise array-like input into immutable numeric column mappings."""
        if not channels:
            raise ValueError("Plot data requires at least one channel.")
        captured_channels = {key: self._snapshot(value) for key, value in channels.items()}
        for key in captured_channels:
            _nonempty(key, "Channel key")
        lengths = {len(value) for value in captured_channels.values()}
        if len(lengths) != 1:
            raise ValueError("Plot channels must have equal lengths.")
        metadata = dict(metadata or {})
        uncertainties = dict(uncertainties or {})
        if set(metadata).difference(captured_channels) or set(uncertainties).difference(
            captured_channels
        ):
            raise ValueError("Metadata and uncertainties must refer to existing channels.")
        metadata = {key: metadata.get(key, ChannelMetadata(key)) for key in captured_channels}
        if any(not isinstance(value, ChannelMetadata) for value in metadata.values()):
            raise ValueError("Channel metadata must use ChannelMetadata records.")
        captured_errors = {key: self._snapshot(value) for key, value in uncertainties.items()}
        if any(
            len(value) not in lengths or np.any(value < 0) for value in captured_errors.values()
        ):
            raise ValueError("Uncertainties must match channel lengths and be nonnegative.")
        object.__setattr__(self, "channels", MappingProxyType(captured_channels))
        object.__setattr__(self, "metadata", MappingProxyType(metadata))
        object.__setattr__(self, "uncertainties", MappingProxyType(captured_errors))

    @staticmethod
    def _snapshot(values: ArrayLike) -> NDArray[np.float64]:
        """Capture a numeric column in a permanently read-only buffer."""
        array = np.asarray(values, dtype=np.float64)
        if array.ndim != 1:
            raise ValueError("Plot channels must be one-dimensional.")
        if isinstance(array.base, bytes) and not array.flags.writeable and array.flags.c_contiguous:
            return array
        return np.frombuffer(array.tobytes(), dtype=np.float64)


@dataclass(frozen=True)
class CoordinateBinding:
    """Bind named source channels to generalised coordinates and optional value.

    Args:
        x (str): First coordinate channel (r for polar/cylindrical/spherical).
        y (str): Second coordinate channel (theta for angular systems).
        z (str | None): Optional third coordinate (axial z or spherical phi).
        value (str | None): Independent intensity/colour channel, never inferred
            from the third coordinate or TraceData's auxiliary z role.
    """

    x: str
    y: str
    z: str | None = None
    value: str | None = None

    def __post_init__(self) -> None:
        for channel in (self.x, self.y):
            _nonempty(channel, "Coordinate channel")
        for optional_channel in (self.z, self.value):
            if optional_channel is not None:
                _nonempty(optional_channel, "Bound channel")

    @property
    def dimensions(self) -> int:
        """Return the number of coordinate slots, excluding intensity."""
        return 2 if self.z is None else 3

    def validate(self, data: PlotData, coordinates: CoordinateDescriptor) -> None:
        """Validate source references and coordinate count without projection.

        Args:
            data (PlotData): Source snapshot.
            coordinates (CoordinateDescriptor): Declared coordinate semantics.

        Raises:
            ValueError: If a bound channel is absent or dimensions are invalid.
        """
        for channel in (self.x, self.y, self.z, self.value):
            if channel is not None and channel not in data.channels:
                raise ValueError(f"Unknown bound channel: {channel!r}.")
        coordinates.validate_dimensions(self.dimensions)
        angular_slots = {
            CoordinateSystem.CARTESIAN: (),
            CoordinateSystem.POLAR: (self.y,),
            CoordinateSystem.CYLINDRICAL: (self.y,),
            CoordinateSystem.SPHERICAL: (self.y, self.z),
        }
        units = {
            AngularUnit.RADIANS: {"", "rad", "radian", "radians"},
            AngularUnit.DEGREES: {"", "deg", "degree", "degrees", "°"},
        }
        for channel in angular_slots[coordinates.system]:
            if (
                channel is not None
                and data.metadata[channel].unit not in units[coordinates.angular_unit]
            ):
                raise ValueError(f"Angular channel {channel!r} disagrees with descriptor units.")


class Presentation(StrEnum):
    """Rendering intent independent of coordinate system."""

    LINE = "line"
    POINTS = "points"
    INTENSITY = "intensity"
    SURFACE = "surface"


class UpdateMode(StrEnum):
    """Whether a sample table replaces or extends the existing series."""

    REPLACE = "replace"
    APPEND = "append"


class PlotOperation(StrEnum):
    """Portable operations that displays can accept or reject explicitly."""

    UPDATE_SERIES = "update_series"
    MODIFY_SERIES = "modify_series"
    REMOVE_SERIES = "remove_series"
    CONFIGURE_AXES = "configure_axes"
    REMOVE_AXES = "remove_axes"
    ADD_MARKER = "add_marker"
    REMOVE_MARKERS = "remove_markers"
    CLEAR = "clear"


@dataclass(frozen=True)
class SurfaceBinding:
    """Versioned, explicitly negotiated rectilinear surface assembly.

    Args:
        surface_id (str): Stable surface identity, equal to the series ID.
        acquisition_id (str): Run identity; clear or explicitly change to reset.
        kind (str): Fixed-Y slice, individual cells, or replay snapshot.
        slice_id (str | None): Stable identity of a complete trace slice.
        duplicates (str): Reject repeats, or explicitly replace slices/cells.
        reset_on_change (bool): Discard the old grid on acquisition-ID change.
        slices (tuple): Snapshot-only slice ID/Y pairs for later reacquisition.
        version (int): Extension version, negotiated through surface_versions.

    Notes:
        X/Y keys are exact and finite. Missing cells stay absent; measured NaNs
        remain missing values. Visibility and removal address the whole surface.
        Titles never determine grouping. Slice visibility is outside version one.
    """

    surface_id: str
    acquisition_id: str = "default"
    kind: Literal["slice", "cells", "snapshot"] = "cells"
    slice_id: str | None = None
    duplicates: Literal["reject", "replace"] = "reject"
    reset_on_change: bool = False
    slices: tuple[tuple[str, float], ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        _nonempty(self.surface_id, "Surface ID")
        _nonempty(self.acquisition_id, "Acquisition ID")
        if self.version != 1 or self.kind not in ("slice", "cells", "snapshot"):
            raise ValueError("Unsupported surface binding version or kind.")
        if self.duplicates not in ("reject", "replace"):
            raise ValueError("Unknown surface duplicate policy.")
        if self.kind == "slice":
            _nonempty(self.slice_id, "Slice ID")
        elif self.slice_id is not None:
            raise ValueError("Only trace slices have a slice ID.")
        slices = tuple((name, float(y)) for name, y in self.slices)
        if slices and self.kind != "snapshot":
            raise ValueError("Slice catalogue belongs only to replay snapshots.")
        if len({name for name, _ in slices}) != len(slices) or len({y for _, y in slices}) != len(
            slices
        ):
            raise ValueError("Duplicate replay slice identities or coordinates.")
        for name, y in slices:
            _nonempty(name, "Slice ID")
            if not isfinite(y):
                raise ValueError("Slice coordinates must be finite.")
        object.__setattr__(self, "slices", slices)


@dataclass(frozen=True)
class SeriesUpdate:
    """Submit data and presentation settings as one acknowledged operation.

    Args:
        series_id (str): Stable display identity; legacy titles supply this ID.
        data (PlotData): Owned snapshot, including metadata and uncertainties.
        binding (CoordinateBinding): Explicit source-channel assignments.
        coordinates (CoordinateDescriptor): Source coordinate system.
        mode (UpdateMode): Replace the table or append rows with the same schema.
        presentation (Presentation): Line, points, intensity or surface intent.
        title (str | None): Display title; None preserves the existing title.
        axes (Mapping[CoordinateSlot, str]): Named axis assignments.
        style (Mapping[str, str | float]): Portable Cartesian style keys:
            colour, line_style, point_style, line_width and point_size. Values
            are validated by the supporting adapter, not a rendering library.
        surface (SurfaceBinding | None): Optional negotiated rectilinear assembly.

    Notes:
        An append must preserve channel schema, binding and coordinate semantics;
        the service checks that against existing state in Stage 2. Complete the
        data, axes, labels and style operation before reporting application.
    """

    series_id: str
    data: PlotData
    binding: CoordinateBinding
    coordinates: CoordinateDescriptor = field(default_factory=CoordinateDescriptor)
    mode: UpdateMode = UpdateMode.REPLACE
    presentation: Presentation = Presentation.LINE
    title: str | None = None
    axes: Mapping[CoordinateSlot, str] = field(default_factory=dict)
    style: Mapping[str, str | float] = field(default_factory=dict)
    surface: SurfaceBinding | None = None
    operation: ClassVar[PlotOperation] = PlotOperation.UPDATE_SERIES

    def __post_init__(self) -> None:
        _nonempty(self.series_id, "Series ID")
        self.binding.validate(self.data, self.coordinates)
        if self.surface is not None:
            if self.surface.surface_id != self.series_id:
                raise ValueError("Surface and series identities must match.")
            if self.binding.z is None and self.binding.value is None:
                raise ValueError("Surfaces require an explicit height or value channel.")
            if self.mode != UpdateMode.REPLACE and self.surface.kind == "snapshot":
                raise ValueError("A surface replay snapshot must replace its series.")
        object.__setattr__(self, "mode", UpdateMode(self.mode))
        object.__setattr__(self, "presentation", Presentation(self.presentation))
        if self.presentation == Presentation.INTENSITY and self.binding.value is None:
            raise ValueError("Intensity presentation requires a value channel.")
        allowed_slots = {"x", "y"} if self.binding.z is None else {"x", "y", "z"}
        if set(self.axes).difference(allowed_slots):
            raise ValueError("Axis assignments must refer to bound coordinate slots.")
        for name in self.axes.values():
            _nonempty(name, "Axis name")
        object.__setattr__(self, "axes", MappingProxyType(dict(self.axes)))
        object.__setattr__(self, "style", _style_snapshot(self.style))


def _style_snapshot(style: Mapping[str, str | float]) -> Mapping[str, str | float]:
    """Copy the version-one portable style vocabulary."""
    if set(style).difference({"colour", "line_style", "point_style", "line_width", "point_size"}):
        raise ValueError("Unknown portable style key.")
    if any(not isinstance(value, (str, int, float)) for value in style.values()):
        raise ValueError("Style values must be scalar strings or numbers.")
    return MappingProxyType(dict(style))


@dataclass(frozen=True)
class ModifySeries:
    """Change title, visibility or style without changing series identity.

    Args:
        series_id (str): Existing series identity.
        title (str | None): Replacement title, or None to preserve it.
        visible (bool | None): Visibility, or None to preserve it.
        style (Mapping[str, str | float]): Partial style update.
    """

    series_id: str
    title: str | None = None
    visible: bool | None = None
    style: Mapping[str, str | float] = field(default_factory=dict)
    operation: ClassVar[PlotOperation] = PlotOperation.MODIFY_SERIES

    def __post_init__(self) -> None:
        _nonempty(self.series_id, "Series ID")
        object.__setattr__(self, "style", _style_snapshot(self.style))


@dataclass(frozen=True)
class RemoveSeries:
    """Remove a series identified by series_id, including its error bars."""

    series_id: str
    operation: ClassVar[PlotOperation] = PlotOperation.REMOVE_SERIES

    def __post_init__(self) -> None:
        _nonempty(self.series_id, "Series ID")


@dataclass(frozen=True)
class AxisDescription:
    """Describe an axis without exposing a ViewBox or a private axis map.

    Args:
        name (str): Stable axis name, e.g. bottom or left for legacy plots.
        slot (CoordinateSlot): Generalised coordinate orientation.
        label (ChannelMetadata): Physical quantity and source units.
        scale (str): linear, log, symlog, logit or asinh.
        parameter (float): Scale parameter; positive for symlog/asinh.
        limits (tuple[float | None, float | None]): Source-coordinate bounds.
            None means autoscale that bound.
        visible (bool): Whether the axis is displayed.
        mouse_active (bool): Whether mouse gestures control this axis.
        grid (bool): Whether to display its grid.
        side (str | None): Optional renderer-specific axis placement.
    """

    name: str
    slot: CoordinateSlot
    label: ChannelMetadata = field(default_factory=ChannelMetadata)
    scale: str = "linear"
    parameter: float = 1.0
    limits: tuple[float | None, float | None] = (None, None)
    visible: bool = True
    mouse_active: bool = False
    grid: bool = False
    side: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.name, "Axis name")
        if not isinstance(self.label, ChannelMetadata):
            raise ValueError("Axis labels must use ChannelMetadata records.")
        if self.slot not in ("x", "y", "z"):
            raise ValueError("Unknown coordinate slot.")
        if self.scale not in ("linear", "log", "symlog", "logit", "asinh"):
            raise ValueError("Unknown axis scale.")
        if not isfinite(self.parameter) or (
            self.scale in ("symlog", "asinh") and self.parameter <= 0
        ):
            raise ValueError("Invalid axis scale parameter.")
        limits = tuple(self.limits)
        if len(limits) != 2 or any(value is not None and not isfinite(value) for value in limits):
            raise ValueError("Axis limits must be two finite values or None.")
        lower, upper = limits
        if lower is not None and upper is not None and lower >= upper:
            raise ValueError("Axis lower limit must be less than its upper limit.")
        object.__setattr__(self, "limits", limits)


@dataclass(frozen=True)
class ConfigureAxes:
    """Create/update the axes described in axes as one operation."""

    axes: tuple[AxisDescription, ...]
    operation: ClassVar[PlotOperation] = PlotOperation.CONFIGURE_AXES

    def __post_init__(self) -> None:
        object.__setattr__(self, "axes", tuple(self.axes))
        if len({axis.name for axis in self.axes}) != len(self.axes):
            raise ValueError("Axis descriptions must have unique names.")


@dataclass(frozen=True)
class RemoveAxes:
    """Remove named axes and their anchored markers using existing semantics."""

    names: tuple[str, ...]
    operation: ClassVar[PlotOperation] = PlotOperation.REMOVE_AXES

    def __post_init__(self) -> None:
        object.__setattr__(self, "names", tuple(self.names))
        for name in self.names:
            _nonempty(name, "Axis name")


@dataclass(frozen=True)
class AddMarker:
    """Place a marker in declared source coordinates, retaining its axis anchor.

    Args:
        position (Mapping[CoordinateSlot, float]): x/y and optional z values.
        coordinates (CoordinateDescriptor): Coordinate meaning and angular units.
        axes (Mapping[CoordinateSlot, str]): Explicit anchors; omitted anchors
            resolve to the first active axis for each slot at application time.
        label (str | None): Explicit text, or None for coordinate-derived text.
    """

    position: Mapping[CoordinateSlot, float]
    coordinates: CoordinateDescriptor = field(default_factory=CoordinateDescriptor)
    axes: Mapping[CoordinateSlot, str] = field(default_factory=dict)
    label: str | None = None
    operation: ClassVar[PlotOperation] = PlotOperation.ADD_MARKER

    def __post_init__(self) -> None:
        position = dict(self.position)
        if set(position) not in ({"x", "y"}, {"x", "y", "z"}):
            raise ValueError("Markers require x/y coordinates and optional z.")
        self.coordinates.validate_dimensions(len(position))
        if any(not isfinite(value) for value in position.values()):
            raise ValueError("Marker coordinates must be finite.")
        if set(self.axes).difference(position):
            raise ValueError("Marker axes must refer to its coordinate slots.")
        for name in self.axes.values():
            _nonempty(name, "Axis name")
        object.__setattr__(self, "position", MappingProxyType(position))
        object.__setattr__(self, "axes", MappingProxyType(dict(self.axes)))


@dataclass(frozen=True)
class RemoveMarkers:
    """Remove the marker_ids supplied, or all markers when marker_ids is None."""

    marker_ids: tuple[int, ...] | None = None
    operation: ClassVar[PlotOperation] = PlotOperation.REMOVE_MARKERS

    def __post_init__(self) -> None:
        if self.marker_ids is not None:
            object.__setattr__(self, "marker_ids", tuple(self.marker_ids))


@dataclass(frozen=True)
class ClearPlot:
    """Clear data, styles, markers and collected labels, retaining configured axes."""

    operation: ClassVar[PlotOperation] = PlotOperation.CLEAR


type PlotPayload = (
    SeriesUpdate
    | ModifySeries
    | RemoveSeries
    | ConfigureAxes
    | RemoveAxes
    | AddMarker
    | RemoveMarkers
    | ClearPlot
)


@dataclass(frozen=True)
class PlotRequest:
    """Address one immutable payload to a display with a unique request_id.

    Args:
        payload (PlotPayload): Complete logical operation.
        target (str): Display identity, initially main.
        request_id (str): Producer-generated ID, unique for each submission.

    Notes:
        Submission transfers this snapshot. Reusing an ID must be rejected by
        the service. A display generation is assigned at dispatch time.
    """

    payload: PlotPayload
    target: str = "main"
    request_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        _nonempty(self.target, "Display target")
        _nonempty(self.request_id, "Request ID")
        if not isinstance(
            self.payload,
            (
                SeriesUpdate,
                ModifySeries,
                RemoveSeries,
                ConfigureAxes,
                RemoveAxes,
                AddMarker,
                RemoveMarkers,
                ClearPlot,
            ),
        ):
            raise ValueError("Unknown plotting payload.")


class ResultStatus(StrEnum):
    """Terminal outcomes; applied acknowledges state application, not painting."""

    APPLIED = "applied"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NO_DISPLAY = "no_display"


@dataclass(frozen=True)
class PlotResult:
    """Report exactly one terminal result for an accepted request.

    Args:
        request_id (str): Submission identity.
        target (str): Display identity.
        generation (int): Display lifetime at dispatch; zero for no display.
        status (ResultStatus): Applied, unsupported, failed, cancelled or no display.
        message (str): Human-readable diagnostic, required for errors/cancellation.
        marker_id (int | None): Assigned marker identity for an applied add.
    """

    request_id: str
    target: str
    generation: int
    status: ResultStatus
    message: str = ""
    marker_id: int | None = None

    def __post_init__(self) -> None:
        _nonempty(self.request_id, "Request ID")
        _nonempty(self.target, "Display target")
        object.__setattr__(self, "status", ResultStatus(self.status))
        if self.generation < 0:
            raise ValueError("Display generation cannot be negative.")
        if self.marker_id is not None and (
            self.status != ResultStatus.APPLIED or self.marker_id < 1
        ):
            raise ValueError("Only applied results can return a positive marker ID.")
        if self.status in (ResultStatus.UNSUPPORTED, ResultStatus.FAILED, ResultStatus.CANCELLED):
            _nonempty(self.message, "Result diagnostic")


@dataclass(frozen=True)
class PlotCapabilities:
    """Declare portable operations and supported coordinate/presentation layouts.

    Args:
        layouts (frozenset[tuple[CoordinateSystem, int]]): System/dimension pairs.
        presentations (frozenset[Presentation]): Accepted rendering intents.
        operations (frozenset[PlotOperation]): Accepted operation types.
        uncertainties (bool): Whether bound-coordinate error bars are supported.
        named_axes (bool): Whether requests may name axes beyond bottom/left.
        value_channel (bool): Whether independent intensity/colour is supported.
        surface_versions (frozenset[int]): Opt-in rectilinear assembly versions.
            Empty by default; accepting XYZ alone does not imply grid assembly.
        value_uncertainties (bool): Support independent intensity/colour errors.

    Notes:
        Acceptance here establishes structural support, not adapter-specific
        validation of styles, scales or current series/axis state.
    """

    layouts: frozenset[tuple[CoordinateSystem, int]]
    presentations: frozenset[Presentation]
    operations: frozenset[PlotOperation]
    uncertainties: bool = False
    named_axes: bool = False
    value_channel: bool = False
    surface_versions: frozenset[int] = frozenset()
    value_uncertainties: bool = False

    def __post_init__(self) -> None:
        versions = frozenset(self.surface_versions)
        if versions.difference({1}):
            raise ValueError("Unknown surface assembly version.")
        object.__setattr__(self, "surface_versions", versions)
        layouts = frozenset(
            (CoordinateSystem(system), dimensions) for system, dimensions in self.layouts
        )
        for system, dimensions in layouts:
            convention = (
                SphericalConvention.THETA_INCLINATION
                if system == CoordinateSystem.SPHERICAL
                else None
            )
            CoordinateDescriptor(system, spherical_convention=convention).validate_dimensions(
                dimensions
            )
        object.__setattr__(self, "layouts", layouts)
        object.__setattr__(
            self, "presentations", frozenset(Presentation(value) for value in self.presentations)
        )
        object.__setattr__(
            self, "operations", frozenset(PlotOperation(value) for value in self.operations)
        )

    def unsupported_reasons(self, request: PlotRequest) -> tuple[str, ...]:
        """Return explicit structural rejection reasons, or an empty tuple.

        Args:
            request (PlotRequest): Request to check before dispatch.

        Returns:
            (tuple[str, ...]): Reasons for an unsupported terminal result.
        """
        payload = request.payload
        reasons = []
        if payload.operation not in self.operations:
            reasons.append(f"Unsupported operation: {payload.operation}.")
        if isinstance(payload, (SeriesUpdate, AddMarker)):
            dimensions = (
                payload.binding.dimensions
                if isinstance(payload, SeriesUpdate)
                else len(payload.position)
            )
            if (payload.coordinates.system, dimensions) not in self.layouts:
                reasons.append(
                    f"Unsupported coordinates: {payload.coordinates.system}/{dimensions}."
                )
            if not self.named_axes and any(
                name != {"x": "bottom", "y": "left"}.get(slot)
                for slot, name in payload.axes.items()
            ):
                reasons.append("Named axes are unsupported.")
        if isinstance(payload, SeriesUpdate):
            if payload.surface is not None and payload.surface.version not in self.surface_versions:
                reasons.append("Rectilinear surface assembly is unsupported.")
            if payload.binding.value is not None and not self.value_channel:
                reasons.append("Independent value channels are unsupported.")
            if payload.presentation not in self.presentations:
                reasons.append(f"Unsupported presentation: {payload.presentation}.")
            bound = (payload.binding.x, payload.binding.y, payload.binding.z)
            if not self.uncertainties and any(key in payload.data.uncertainties for key in bound):
                reasons.append("Coordinate uncertainties are unsupported.")
            if payload.binding.value in payload.data.uncertainties and not self.value_uncertainties:
                reasons.append("Independent value uncertainties are unsupported.")
        if isinstance(payload, (ConfigureAxes, RemoveAxes)) and not self.named_axes:
            reasons.append("Axis configuration is unsupported.")
        return tuple(reasons)


@dataclass(frozen=True)
class SeriesDescription:
    """Public series state for selectors, without exposing graphics objects.

    Args:
        series_id (str): Stable display identity.
        title (str): Current display name.
        binding (CoordinateBinding): Source channel assignments.
        coordinates (CoordinateDescriptor): Source coordinate meaning.
        visible (bool): Current visibility.
    """

    series_id: str
    title: str
    binding: CoordinateBinding
    coordinates: CoordinateDescriptor = field(default_factory=CoordinateDescriptor)
    visible: bool = True

    def __post_init__(self) -> None:
        _nonempty(self.series_id, "Series ID")
        self.coordinates.validate_dimensions(self.binding.dimensions)


class PlotTicket(Protocol):
    """Thread-safe completion interface implemented by the plotting service."""

    @property
    def request_id(self) -> str:
        """Return the request identity."""
        ...

    def wait(self, timeout: float | None = None) -> PlotResult | None:
        """Wait in a worker for a result; return None on wait timeout.

        Args:
            timeout (float | None): Seconds to wait, zero to poll, None to wait
                until completion or service cancellation. A timed-out wait does
                not cancel the request. GUI callers must use notifications.

        Returns:
            (PlotResult | None): Terminal result, or None while still pending.
        """
        ...


class PlotClient(Protocol):
    """Stable producer endpoint implemented by PlotService."""

    def submit(self, request: PlotRequest) -> PlotTicket:
        """Submit a snapshot without accessing GUI objects or blocking on drawing.

        Args:
            request (PlotRequest): Operation with a unique request ID.

        Returns:
            (PlotTicket): Exactly-once terminal completion handle.
        """
        ...

    def axes(self, target: str = "main") -> tuple[AxisDescription, ...]:
        """Return a public thread-safe axis snapshot for target."""
        ...

    def capabilities(self, target: str = "main") -> PlotCapabilities | None:
        """Return target capabilities, or None when no display is attached."""
        ...

    def series(self, target: str = "main") -> tuple[SeriesDescription, ...]:
        """Return public thread-safe series descriptions for target."""
        ...
