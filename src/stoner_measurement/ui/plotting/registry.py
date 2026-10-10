"""Isolated display-factory discovery with a guaranteed bundled fallback."""

import importlib.metadata
import logging

from stoner_measurement.core.plotting.contracts import PlotCapabilities
from stoner_measurement.ui.plotting.cartesian import CartesianDisplayFactory
from stoner_measurement.ui.plotting.interfaces import DISPLAY_CONTRACT_VERSION, PlotDisplayFactory
from stoner_measurement.ui.plotting.polar import PolarDisplayFactory
from stoner_measurement.ui.plotting.surface_displays import (
    Cartesian3DDisplayFactory,
    IntensityDisplayFactory,
)

logger = logging.getLogger(__name__)
DISPLAY_ENTRY_POINT_GROUP = "stoner_measurement.plot_displays"


class PlotDisplayRegistry:
    """Load lightweight factories, never all their renderer widgets.

    Invalid imports, incompatible versions and duplicate IDs are recorded in
    diagnostics and logged. The bundled Cartesian ID cannot be overridden.
    """

    def __init__(self) -> None:
        self._factories: dict[str, PlotDisplayFactory] = {}
        self._diagnostics: list[str] = []
        self._install_bundled()

    def _install_bundled(self) -> None:
        self._factories = {
            factory.factory_id: factory
            for factory in (
                CartesianDisplayFactory(),
                PolarDisplayFactory(),
                Cartesian3DDisplayFactory(),
                IntensityDisplayFactory(),
            )
        }

    @property
    def factories(self) -> dict[str, PlotDisplayFactory]:
        """Return a copy of registered factory metadata."""
        return dict(self._factories)

    @property
    def diagnostics(self) -> tuple[str, ...]:
        """Return discovery diagnostics without displaying modal dialogs."""
        return tuple(self._diagnostics)

    def get(self, factory_id: str) -> PlotDisplayFactory | None:
        """Look up a factory without constructing its widget."""
        return self._factories.get(factory_id)

    def register(self, factory: PlotDisplayFactory) -> None:
        """Register validated factory metadata; reject ID collisions."""
        if not isinstance(factory.factory_id, str) or not factory.factory_id.strip():
            raise ValueError("A display factory requires a nonempty ID.")
        if not isinstance(factory.name, str) or not factory.name.strip():
            raise ValueError("A display factory requires a nonempty name.")
        if factory.contract_version != DISPLAY_CONTRACT_VERSION:
            raise ValueError("Unsupported display contract version.")
        if not isinstance(factory.capabilities, PlotCapabilities) or not callable(factory.create):
            raise TypeError("Invalid display factory interface.")
        if factory.factory_id in self._factories:
            raise ValueError(f"Duplicate display factory ID: {factory.factory_id}.")
        self._factories[factory.factory_id] = factory

    def discover(self) -> None:
        """Rebuild from installed entry points, retaining the bundled default."""
        self._install_bundled()
        self._diagnostics.clear()
        try:
            entries = importlib.metadata.entry_points(group=DISPLAY_ENTRY_POINT_GROUP)
        except Exception as exc:
            self._report(f"Could not discover plot displays: {exc}")
            return
        for entry in sorted(entries, key=lambda ep: (ep.name, ep.value)):
            try:
                factory_class = entry.load()
                if (
                    factory_class
                    in (
                        CartesianDisplayFactory,
                        PolarDisplayFactory,
                        Cartesian3DDisplayFactory,
                        IntensityDisplayFactory,
                    )
                    and entry.name == factory_class.factory_id
                ):
                    continue  # Source fallback and installed metadata identify one factory.
                factory = factory_class()
                if factory.factory_id != entry.name:
                    raise ValueError("Factory ID must match its entry-point name.")
                self.register(factory)
            except Exception as exc:
                self._report(f"Could not load plot display {entry.name!r}: {exc}")

    def _report(self, message: str) -> None:
        self._diagnostics.append(message)
        logger.warning(message)
