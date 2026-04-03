"""TracePlugin — abstract base class for plugins that collect (x, y) traces.

Trace plugins acquire a complete sequence of (x, y) data points from one or
more instrument channels.  Examples include current-voltage characteristics,
frequency sweeps, and time-series captures.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Generator
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget

from stoner_measurement.plugins.base_plugin import BasePlugin, _ABCQObjectMeta
from stoner_measurement.scan import SteppedScanGenerator


class TracePlugin(QObject, BasePlugin, metaclass=_ABCQObjectMeta):
    """Abstract base class for plugins that collect (x, y) data traces.

    A :class:`TracePlugin` acquires one or more complete traces of (x, y) data
    from instruments.  Subclasses must implement :attr:`name` (inherited from
    :class:`~stoner_measurement.plugins.base_plugin.BasePlugin`) and
    :meth:`execute`.

    The class provides:

    * **Single-channel acquisition** — :meth:`execute` yields ``(x, y)`` pairs
      for the primary channel.
    * **Multi-channel acquisition** — :meth:`execute_multichannel` yields
      ``(channel, x, y)`` triples; the default implementation wraps
      :meth:`execute` using the first entry of :attr:`channel_names`.
    * **Live-plot signals** — :attr:`trace_started`, :attr:`trace_point`, and
      :attr:`trace_complete` allow connected widgets to update during
      acquisition.

    Attributes:
        scan_generator (SteppedScanGenerator):
            Built-in scan generator that defines the sequence of x-axis values
            for this trace.  The configuration widget for this generator is
            presented as the first tab of :meth:`config_tabs`.
        trace_started (pyqtSignal[str]):
            Emitted with the channel name when acquisition of a trace begins.
        trace_point (pyqtSignal[str, float, float]):
            Emitted for each (channel, x, y) data point during acquisition.
        trace_complete (pyqtSignal[str]):
            Emitted with the channel name when a trace is fully acquired.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.dummy import DummyPlugin
        >>> plugin = DummyPlugin()
        >>> plugin.plugin_type
        'trace'
        >>> plugin.x_label
        'x'
        >>> plugin.y_label
        'y'
        >>> plugin.channel_names == [plugin.name]
        True
    """

    trace_started = pyqtSignal(str)
    trace_point = pyqtSignal(str, float, float)
    trace_complete = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy and create the built-in scan generator."""
        super().__init__(parent)
        self.scan_generator: SteppedScanGenerator = SteppedScanGenerator(parent=self)

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a trace collector.

        Returns:
            (str):
                Always ``"trace"``.
        """
        return "trace"

    def config_tabs(
        self, parent: QWidget | None = None
    ) -> list[tuple[str, QWidget]]:
        """Return configuration tabs with the scan generator widget as the first tab.

        The first tab displays the built-in :attr:`scan_generator` configuration
        widget so that the user can define the x-axis scan sequence.  Subsequent
        tabs are inherited from
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_tabs`.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs; the scan generator tab is
                always first.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> tabs = plugin.config_tabs()
            >>> "Scan" in tabs[0][0]
            True
        """
        scan_widget = self.scan_generator.config_widget(parent=parent)
        scan_tab = (f"{self.name} \u2013 Scan", scan_widget)
        return [scan_tab] + super().config_tabs(parent=parent)

    @abstractmethod
    def execute(
        self, parameters: dict[str, Any]
    ) -> Generator[tuple[float, float]]:
        """Acquire a trace and yield ``(x, y)`` data points.

        This method is the primary acquisition entry point.  Each yielded
        tuple represents a single measured (x, y) pair on the default channel.

        Args:
            parameters (dict[str, Any]):
                Step-specific configuration provided by the caller (e.g.
                sweep range, integration time).

        Yields:
            (tuple[float, float]):
                ``(x, y)`` data point pairs.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> pts = list(plugin.execute({"points": 5}))
            >>> len(pts)
            5
            >>> isinstance(pts[0], tuple) and len(pts[0]) == 2
            True
        """

    @property
    def channel_names(self) -> list[str]:
        """Names of the available measurement channels.

        The default implementation returns a single-element list containing
        :attr:`name`.  Override to expose multiple channels.

        Returns:
            (list[str]):
                Ordered list of channel name strings.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> DummyPlugin().channel_names
            ['Dummy']
        """
        return [self.name]

    @property
    def x_label(self) -> str:
        """Axis label for the independent variable.

        Returns:
            (str):
                Human-readable label string; default ``"x"``.
        """
        return "x"

    @property
    def y_label(self) -> str:
        """Axis label for the dependent variable.

        Returns:
            (str):
                Human-readable label string; default ``"y"``.
        """
        return "y"

    def execute_multichannel(
        self, parameters: dict[str, Any]
    ) -> Generator[tuple[str, float, float]]:
        """Acquire traces from all channels and yield ``(channel, x, y)`` triples.

        The default implementation wraps :meth:`execute` using the first entry
        of :attr:`channel_names`.  Override this method when the plugin
        supports simultaneous multi-channel acquisition.

        Args:
            parameters (dict[str, Any]):
                Step-specific configuration forwarded to :meth:`execute`.

        Yields:
            (tuple[str, float, float]):
                ``(channel_name, x, y)`` triples.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> pts = list(plugin.execute_multichannel({"points": 3}))
            >>> len(pts)
            3
            >>> pts[0][0]
            'Dummy'
        """
        channel = self.channel_names[0]
        for x, y in self.execute(parameters):
            yield channel, x, y
