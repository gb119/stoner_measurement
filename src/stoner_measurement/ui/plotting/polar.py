"""Lightweight factory for two-dimensional radius/angle plots."""

from stoner_measurement.core.plotting.contracts import (
    CoordinateSystem,
    PlotCapabilities,
    PlotOperation,
    Presentation,
)
from stoner_measurement.ui.plotting.interfaces import DISPLAY_CONTRACT_VERSION


class PolarDisplayFactory:
    """Create a polar display lazily, alongside the Cartesian XY factory."""

    factory_id = "polar"
    name = "Polar traces"
    contract_version = DISPLAY_CONTRACT_VERSION
    capabilities = PlotCapabilities(
        layouts=frozenset({(CoordinateSystem.POLAR, 2)}),
        presentations=frozenset({Presentation.LINE, Presentation.POINTS}),
        operations=frozenset(
            {
                PlotOperation.UPDATE_SERIES,
                PlotOperation.MODIFY_SERIES,
                PlotOperation.REMOVE_SERIES,
                PlotOperation.CONFIGURE_AXES,
                PlotOperation.CLEAR,
            }
        ),
        uncertainties=True,
        named_axes=True,
    )

    def create(self, parent):
        """Construct one GUI-owned polar canvas only when selected."""
        from stoner_measurement.ui.plotting.polar_canvas import PolarCanvasDisplay

        return PolarCanvasDisplay(parent, self.capabilities)
