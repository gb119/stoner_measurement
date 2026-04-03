"""Abstract base class for all measurement plugins.

A plugin must:

1. Inherit from :class:`BasePlugin`.
2. Override :attr:`name` to provide a unique string identifier.
3. Optionally override :meth:`config_widget` to supply a configuration
   :class:`~PyQt6.QtWidgets.QWidget` that will appear as a tab in the
   right-hand panel.
4. Optionally override :meth:`config_tabs` to contribute multiple labelled
   tabs to the configuration panel.
5. Optionally override :meth:`monitor_widget` to contribute a live-status
   widget to the left dock panel.

Concrete plugin behaviour is added by subclassing one of the four specialised
sub-types: :class:`~stoner_measurement.plugins.trace.TracePlugin`,
:class:`~stoner_measurement.plugins.state_control.StateControlPlugin`,
:class:`~stoner_measurement.plugins.monitor.MonitorPlugin`, or
:class:`~stoner_measurement.plugins.transform.TransformPlugin`.
"""

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QLabel, QWidget


class _ABCQObjectMeta(type(QObject), ABCMeta):
    """Combined metaclass that resolves the conflict between QObject and ABCMeta."""


class BasePlugin(ABC):
    """Abstract root class shared by all measurement plugins.

    Subclasses must implement :attr:`name`.  Subclasses may optionally
    override :meth:`config_widget`, :meth:`config_tabs`, and
    :meth:`monitor_widget` to provide richer UI integration.

    Rather than subclassing :class:`BasePlugin` directly, prefer one of the
    four specialised sub-types:

    * :class:`~stoner_measurement.plugins.trace.TracePlugin` — collects (x, y)
      traces from instruments.
    * :class:`~stoner_measurement.plugins.state_control.StateControlPlugin` —
      controls experimental state (field, temperature, etc.).
    * :class:`~stoner_measurement.plugins.monitor.MonitorPlugin` — passively
      records auxiliary quantities.
    * :class:`~stoner_measurement.plugins.transform.TransformPlugin` — performs
      pure-computation transforms on collected data.

    Attributes:
        plugin_type (str):
            Short tag identifying the sub-type.  Overridden by each
            specialised base class.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique human-readable name for this plugin."""

    @property
    def plugin_type(self) -> str:
        """Short tag identifying the plugin sub-type.

        Returns:
            (str):
                ``"base"`` for direct :class:`BasePlugin` subclasses.
                Overridden to ``"trace"``, ``"state"``, ``"monitor"``, or
                ``"transform"`` by the respective specialised sub-types.
        """
        return "base"

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
            >>> from stoner_measurement.plugins.base_plugin import BasePlugin
            >>> class _Minimal(BasePlugin):
            ...     @property
            ...     def name(self): return "Minimal"
            >>> plugin = _Minimal()
            >>> tabs = plugin.config_tabs()
            >>> len(tabs)
            1
            >>> tabs[0][0]
            'Minimal'
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
