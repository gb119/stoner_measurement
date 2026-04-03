"""Plugin manager — discovers and loads plugin classes.

Plugins are discovered via Python package entry-points under the group
``stoner_measurement.plugins``.  Each entry-point value must be a subclass
of :class:`~stoner_measurement.plugins.base_plugin.BasePlugin`.
"""

from __future__ import annotations

import importlib.metadata
import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class PluginManager(QObject):
    """Discovers, loads, and provides access to measurement plugins.

    Signals
    -------
    plugins_changed:
        Emitted after the plugin registry is (re-)built.
    """

    plugins_changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._plugins: dict[str, BasePlugin] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Scan entry-points and instantiate all registered plugins."""
        self._plugins.clear()
        group = "stoner_measurement.plugins"
        try:
            eps = importlib.metadata.entry_points(group=group)
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not load entry-points: %s", exc)
            eps = []

        for ep in eps:
            try:
                plugin_cls = ep.load()
                instance = plugin_cls()
                self._plugins[ep.name] = instance
                logger.debug("Loaded plugin %r from %s", ep.name, ep.value)
            except Exception as exc:  # pragma: no cover
                logger.warning("Failed to load plugin %r: %s", ep.name, exc)

        logger.info("Discovered %d plugin(s)", len(self._plugins))
        self.plugins_changed.emit()

    def register(self, name: str, plugin: BasePlugin) -> None:  # type: ignore[name-defined]
        """Manually register a plugin instance (useful for testing).

        Parameters
        ----------
        name:
            Unique identifier for the plugin.
        plugin:
            Plugin instance to register.
        """
        self._plugins[name] = plugin
        self.plugins_changed.emit()

    def unregister(self, name: str) -> None:
        """Remove a plugin from the registry.

        Parameters
        ----------
        name:
            Identifier of the plugin to remove.
        """
        self._plugins.pop(name, None)
        self.plugins_changed.emit()

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    @property
    def plugins(self) -> dict[str, BasePlugin]:  # type: ignore[name-defined]
        """Mapping of plugin name → plugin instance."""
        return dict(self._plugins)

    @property
    def plugin_names(self) -> list[str]:
        """Sorted list of registered plugin names."""
        return sorted(self._plugins)

    def get(self, name: str) -> BasePlugin | None:  # type: ignore[name-defined]
        """Return the plugin with *name*, or ``None`` if not found."""
        return self._plugins.get(name)

    def plugins_by_type(self, plugin_type: str) -> dict[str, BasePlugin]:  # type: ignore[name-defined]
        """Return a filtered mapping of plugins matching *plugin_type*.

        Args:
            plugin_type (str):
                The :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.plugin_type`
                tag to filter by (e.g. ``"trace"``, ``"state"``, ``"monitor"``,
                ``"transform"``).

        Returns:
            (dict[str, BasePlugin]):
                Mapping of plugin name → plugin instance for all registered
                plugins whose :attr:`plugin_type` equals *plugin_type*.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.plugin_manager import PluginManager
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> pm = PluginManager()
            >>> pm.register("dummy", DummyPlugin())
            >>> pm.plugins_by_type("trace")
            {'dummy': <...DummyPlugin...>}
            >>> pm.plugins_by_type("state")
            {}
        """
        return {name: p for name, p in self._plugins.items() if p.plugin_type == plugin_type}
