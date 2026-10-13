"""GUI display and factory interfaces, independent of sequence plugins."""

from collections.abc import Mapping
from typing import Any, Protocol

from qtpy.QtWidgets import QWidget

from stoner_measurement.core.plotting.contracts import (
    AxisDescription,
    PlotCapabilities,
    PlotPayload,
    SeriesDescription,
)
from stoner_measurement.core.plotting.state import DisplayState

DISPLAY_CONTRACT_VERSION = 1


class PlotDisplay(Protocol):
    """GUI-owned adapter created on demand and closed by its host.

    ``changed`` is a no-argument Qt signal emitted when public descriptions
    change. validate must reject malformed operations before mutation. apply
    finishes the complete logical operation before returning a marker ID or None.
    Legacy Cartesian methods are optional and are outside this protocol.
    """

    widget: QWidget
    capabilities: PlotCapabilities
    changed: Any

    def validate(self, payload: PlotPayload) -> None:
        """Validate an operation against the current display state."""
        ...

    def apply(self, payload: PlotPayload) -> int | None:
        """Apply on the GUI thread without asynchronous renderer callbacks."""
        ...

    def descriptions(self) -> tuple[tuple[AxisDescription, ...], tuple[SeriesDescription, ...]]:
        """Return portable public descriptions without graphics objects."""
        ...

    def close(self) -> None:
        """Release this display's owned resources; safe to call repeatedly."""
        ...

    def export_state(self) -> DisplayState:
        """Export explicit DisplayState for idle replacement; no graphics objects."""
        ...

    def import_state(self, state: DisplayState) -> None:
        """Hydrate a hidden candidate completely before committing replacement."""
        ...

    def export_settings(self) -> dict[str, Any]:
        """Export versioned JSON renderer preferences without measurement arrays."""
        ...

    def import_settings(self, settings: Mapping[str, Any]) -> None:
        """Restore versioned renderer preferences at startup."""
        ...


class PlotDisplayFactory(Protocol):
    """Lightweight metadata plus on-demand widget construction.

    Entry points expose a no-argument factory class. Its ID must equal the
    entry-point name. Loading metadata must not create a widget or connection.
    create owns any partial resources until it returns a complete adapter;
    widget children must belong to the supplied parent so failed creation can
    be cleaned up. Factories are separate from BasePlugin and instrument sessions.
    """

    factory_id: str
    name: str
    contract_version: int
    capabilities: PlotCapabilities

    def create(self, parent: QWidget) -> PlotDisplay:
        """Create one display and its widget on the GUI thread."""
        ...
