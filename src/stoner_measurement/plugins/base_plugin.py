"""Abstract base class for all measurement plugins.

A plugin must:

1. Inherit from :class:`BasePlugin`.
2. Override :attr:`name` to provide a unique string identifier.
3. Implement :meth:`execute` to yield ``(x, y)`` data pairs.
4. Optionally override :meth:`config_widget` to supply a configuration
   :class:`~PyQt6.QtWidgets.QWidget` that will appear as a tab in the
   right-hand panel.
5. Optionally override :meth:`config_tabs` to contribute multiple labelled
   tabs to the configuration panel.
6. Optionally override :meth:`monitor_widget` to contribute a live-status
   widget to the left dock panel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generator

from PyQt6.QtWidgets import QLabel, QWidget


class BasePlugin(ABC):
    """Abstract base class for measurement plugins.

    Subclasses must implement :attr:`name` and :meth:`execute`.
    Subclasses may optionally override :meth:`config_widget`,
    :meth:`config_tabs`, and :meth:`monitor_widget` to provide richer
    UI integration.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique human-readable name for this plugin."""

    @abstractmethod
    def execute(
        self, parameters: dict[str, Any]
    ) -> Generator[tuple[float, float], None, None]:
        """Execute the measurement step described by *parameters*.

        Yields
        ------
        tuple[float, float]
            ``(x, y)`` data points produced by the step.

        Parameters
        ----------
        parameters:
            Step-specific configuration provided by the user.
        """

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a :class:`QWidget` for configuring this plugin.

        The default implementation returns a simple label.  Override this
        method to provide a richer configuration interface.  This method is
        called by the default :meth:`config_tabs` implementation to supply the
        single tab widget.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The configuration widget for this plugin.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> widget = plugin.config_widget()
            >>> widget is not None
            True
        """
        label = QLabel(f"<i>No configuration available for <b>{self.name}</b></i>")
        label.setParent(parent)
        return label

    def config_tabs(
        self, parent: QWidget | None = None
    ) -> list[tuple[str, QWidget]]:
        """Return a list of ``(tab_title, widget)`` pairs for the config panel.

        Each pair contributes one tab to the right-hand configuration panel.
        The default implementation wraps :meth:`config_widget` in a
        single-element list using :attr:`name` as the tab title.

        Override this method when a plugin needs to contribute more than one
        tab, or when a custom tab title is desired.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget passed to each tab widget.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> tabs = plugin.config_tabs()
            >>> len(tabs)
            1
            >>> tabs[0][0]
            'Dummy'
        """
        return [(self.name, self.config_widget(parent=parent))]

    def monitor_widget(self, parent: QWidget | None = None) -> QWidget | None:
        """Return an optional live-status widget for the left dock panel.

        The widget will be displayed in the monitoring section of the
        :class:`~stoner_measurement.ui.dock_panel.DockPanel` while the plugin
        is registered.  The default implementation returns ``None``, meaning
        the plugin contributes no monitoring widget.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget | None):
                A monitoring widget, or ``None`` if the plugin provides none.

        Examples:
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> plugin.monitor_widget() is None
            True
        """
        return None
