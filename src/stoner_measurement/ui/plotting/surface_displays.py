"""Lightweight factories for Cartesian height plots and XY intensity maps.

Renderer imports are deliberately deferred until the host selects a factory.
"""

from stoner_measurement.core.plotting.contracts import (
    CoordinateSystem,
    PlotCapabilities,
    PlotOperation,
    Presentation,
)
from stoner_measurement.ui.plotting.interfaces import DISPLAY_CONTRACT_VERSION

_OPERATIONS = frozenset(
    {
        PlotOperation.UPDATE_SERIES,
        PlotOperation.MODIFY_SERIES,
        PlotOperation.REMOVE_SERIES,
        PlotOperation.CONFIGURE_AXES,
        PlotOperation.CLEAR,
    }
)


class Cartesian3DDisplayFactory:
    """Render Cartesian XYZ points, lines and rectilinear surfaces."""

    factory_id = "cartesian_3d"
    name = "Cartesian XYZ"
    contract_version = DISPLAY_CONTRACT_VERSION
    capabilities = PlotCapabilities(
        layouts=frozenset({(CoordinateSystem.CARTESIAN, 3)}),
        presentations=frozenset({Presentation.LINE, Presentation.POINTS, Presentation.SURFACE}),
        operations=_OPERATIONS,
        named_axes=True,
        value_channel=True,
        surface_versions=frozenset({1}),
    )

    def create(self, parent):
        """Construct one owned Qt canvas on demand."""
        from stoner_measurement.ui.plotting.surface_canvas import SurfaceCanvasDisplay

        return SurfaceCanvasDisplay(parent, self.capabilities, three_dimensional=True)


class IntensityDisplayFactory:
    """Render rectilinear XY cells with an independent Z colour scale."""

    factory_id = "intensity"
    name = "XY intensity"
    contract_version = DISPLAY_CONTRACT_VERSION
    capabilities = PlotCapabilities(
        layouts=frozenset({(CoordinateSystem.CARTESIAN, 2)}),
        presentations=frozenset({Presentation.INTENSITY}),
        operations=_OPERATIONS,
        named_axes=True,
        value_channel=True,
        surface_versions=frozenset({1}),
    )

    def create(self, parent):
        """Construct one owned Qt canvas on demand."""
        from stoner_measurement.ui.plotting.surface_canvas import SurfaceCanvasDisplay

        return SurfaceCanvasDisplay(parent, self.capabilities, three_dimensional=False)
