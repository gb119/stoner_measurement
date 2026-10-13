"""Immutable shared plot state and versioned renderer preferences."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType

from stoner_measurement.core.plotting.contracts import AddMarker, AxisDescription, SeriesUpdate


def freeze_settings(value):
    """Capture JSON-compatible preferences without measurement arrays or objects."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Setting keys must be strings.")
        return MappingProxyType({key: freeze_settings(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze_settings(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    raise ValueError("Renderer preferences must contain finite JSON values, not arrays.")


def settings_dict(value):
    """Return independent JSON-compatible preferences for persistence/import."""
    if isinstance(value, Mapping):
        return {key: settings_dict(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [settings_dict(item) for item in value]
    return value


@dataclass(frozen=True)
class SeriesState:
    """Complete series content plus current user visibility."""

    update: SeriesUpdate
    visible: bool = True


@dataclass(frozen=True)
class MarkerState:
    """Stable marker identity and resolved source-coordinate anchor."""

    marker_id: int
    marker: AddMarker

    def __post_init__(self):
        if self.marker_id < 1:
            raise ValueError("Marker IDs must be positive.")


@dataclass(frozen=True)
class DisplayState:
    """Portable plotted state; renderer preferences never contain plotted arrays."""

    axes: tuple[AxisDescription, ...] = ()
    series: tuple[SeriesState, ...] = ()
    markers: tuple[MarkerState, ...] = ()
    renderer_settings: Mapping = field(default_factory=dict)
    version: int = 1

    def __post_init__(self):
        if self.version != 1:
            raise ValueError("Unsupported display state version.")
        for name, key in (
            ("axes", lambda item: item.name),
            ("series", lambda item: item.update.series_id),
            ("markers", lambda item: item.marker_id),
        ):
            items = tuple(getattr(self, name))
            if len({key(item) for item in items}) != len(items):
                raise ValueError(f"Duplicate {name} identities.")
            object.__setattr__(self, name, items)
        object.__setattr__(self, "renderer_settings", freeze_settings(self.renderer_settings))
