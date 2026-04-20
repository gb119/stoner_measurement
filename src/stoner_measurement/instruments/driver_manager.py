"""Instrument driver discovery and filtering utilities.

Provides :class:`InstrumentDriverManager` for discovering concrete instrument
driver classes from the local package and third-party entry-points.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import logging
import pkgutil

from stoner_measurement.instruments.base_instrument import BaseInstrument

logger = logging.getLogger(__name__)


class InstrumentDriverManager:
    """Discover and provide access to concrete instrument driver classes.

    Discovery combines:

    * Built-in drivers found by scanning ``stoner_measurement.instruments``
      modules.
    * Third-party drivers exposed via the
      ``stoner_measurement.instruments`` entry-point group.
    """

    def __init__(self) -> None:
        self._drivers: dict[str, type[BaseInstrument]] = {}

    def discover(self) -> None:
        """Discover built-in and entry-point instrument drivers."""
        self._drivers.clear()
        self._discover_builtin_drivers()
        self._discover_entry_point_drivers()
        logger.info("Discovered %d instrument driver(s)", len(self._drivers))

    def register(self, name: str, driver_cls: type[BaseInstrument]) -> None:
        """Manually register a driver class.

        Args:
            name (str):
                Unique identifier for the driver.
            driver_cls (type[BaseInstrument]):
                Driver class to register.

        Raises:
            TypeError:
                If *driver_cls* is not a :class:`BaseInstrument` subclass.
        """
        if not inspect.isclass(driver_cls) or not issubclass(driver_cls, BaseInstrument):
            raise TypeError("driver_cls must be a subclass of BaseInstrument.")
        self._drivers[name] = driver_cls

    def unregister(self, name: str) -> None:
        """Remove a driver class from the registry.

        Args:
            name (str):
                Driver identifier to remove.
        """
        self._drivers.pop(name, None)

    @property
    def driver_classes(self) -> dict[str, type[BaseInstrument]]:
        """Return a copy of discovered driver classes."""
        return dict(self._drivers)

    @property
    def driver_names(self) -> list[str]:
        """Return sorted discovered driver names."""
        return sorted(self._drivers)

    def get(self, name: str) -> type[BaseInstrument] | None:
        """Return a discovered driver class by *name*, or ``None``."""
        return self._drivers.get(name)

    def drivers_by_type(
        self,
        instrument_type: type[BaseInstrument],
        *,
        include_abstract: bool = False,
    ) -> dict[str, type[BaseInstrument]]:
        """Return discovered drivers that subclass a specific instrument type.

        Args:
            instrument_type (type[BaseInstrument]):
                Base class/interface to filter by, for example
                :class:`MagnetController` or :class:`TemperatureController`.

        Keyword Parameters:
            include_abstract (bool):
                If ``True``, include abstract classes in results.
                Defaults to ``False``.

        Returns:
            (dict[str, type[BaseInstrument]]):
                Mapping of driver name to driver class.

        Raises:
            TypeError:
                If *instrument_type* is not a :class:`BaseInstrument` subclass.
        """
        if not inspect.isclass(instrument_type) or not issubclass(instrument_type, BaseInstrument):
            raise TypeError("instrument_type must be a subclass of BaseInstrument.")
        filtered: dict[str, type[BaseInstrument]] = {}
        for name, driver_cls in self._drivers.items():
            if not issubclass(driver_cls, instrument_type):
                continue
            if not include_abstract and inspect.isabstract(driver_cls):
                continue
            filtered[name] = driver_cls
        return filtered

    def _discover_builtin_drivers(self) -> None:
        """Discover concrete built-in drivers from package modules."""
        instruments_pkg = importlib.import_module("stoner_measurement.instruments")
        package_paths = getattr(instruments_pkg, "__path__", None)
        if package_paths is None:
            return
        for module_info in pkgutil.walk_packages(
            package_paths, prefix=f"{instruments_pkg.__name__}."
        ):
            module_name = module_info.name
            if ".protocol." in module_name or ".transport." in module_name:
                continue
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # pragma: no cover  # pylint: disable=broad-exception-caught
                logger.warning("Failed to import instrument module %r: %s", module_name, exc)
                continue
            self._register_concrete_classes_from_module(module)

    def _discover_entry_point_drivers(self) -> None:
        """Discover concrete third-party drivers from entry-points."""
        for entry_point in _iter_entry_points("stoner_measurement.instruments"):
            try:
                driver_cls = entry_point.load()
            except Exception as exc:  # pragma: no cover  # pylint: disable=broad-exception-caught
                logger.warning("Failed to load instrument driver %r: %s", entry_point.name, exc)
                continue
            if not inspect.isclass(driver_cls) or not issubclass(driver_cls, BaseInstrument):
                logger.warning(
                    "Ignoring entry-point %r: target is not a BaseInstrument subclass.",
                    entry_point.name,
                )
                continue
            if inspect.isabstract(driver_cls):
                logger.warning(
                    "Ignoring entry-point %r: target class %s is abstract.",
                    entry_point.name,
                    driver_cls.__name__,
                )
                continue
            self._drivers[entry_point.name] = driver_cls

    def _register_concrete_classes_from_module(self, module: object) -> None:
        """Register concrete :class:`BaseInstrument` subclasses from *module*."""
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if not issubclass(cls, BaseInstrument):
                continue
            if cls.__module__ != getattr(module, "__name__", ""):
                continue
            if inspect.isabstract(cls):
                continue
            self._drivers.setdefault(cls.__name__, cls)


def _iter_entry_points(group: str) -> list[importlib.metadata.EntryPoint]:
    """Return entry-points for *group* with compatibility across Python versions."""
    try:
        selected = importlib.metadata.entry_points(group=group)
    except TypeError:  # pragma: no cover
        selected = importlib.metadata.entry_points().select(group=group)
    except Exception as exc:  # pragma: no cover  # pylint: disable=broad-exception-caught
        logger.warning("Could not load entry-points for %r: %s", group, exc)
        return []
    return list(selected)
