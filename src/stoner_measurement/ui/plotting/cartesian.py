"""Bundled Cartesian factory preserving the standalone PlotWidget API."""

from stoner_measurement.core.plotting.contracts import (
    CoordinateSystem,
    PlotCapabilities,
    PlotOperation,
    Presentation,
)
from stoner_measurement.ui.plotting.interfaces import DISPLAY_CONTRACT_VERSION

CARTESIAN_CAPABILITIES = PlotCapabilities(
    frozenset({(CoordinateSystem.CARTESIAN, 2)}),
    frozenset({Presentation.LINE, Presentation.POINTS}),
    frozenset(PlotOperation),
    uncertainties=True,
    named_axes=True,
)


class CartesianDisplayFactory:
    """Create the bundled Cartesian display without eager graphics imports."""

    factory_id = "cartesian"
    name = "Cartesian traces"
    contract_version = DISPLAY_CONTRACT_VERSION
    capabilities = CARTESIAN_CAPABILITIES

    def create(self, parent):
        """Construct the existing widget and an owning adapter only on selection."""
        from stoner_measurement.ui.plot_widget import PlotWidget
        from stoner_measurement.ui.plotting_bridge import CartesianPlotBridge

        return CartesianPlotBridge(PlotWidget(parent), owns_widget=True)
