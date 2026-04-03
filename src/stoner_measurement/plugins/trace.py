"""TracePlugin — abstract base class for plugins that collect (x, y) traces.

Trace plugins acquire a complete sequence of (x, y) data points from one or
more instrument channels.  Examples include current-voltage characteristics,
frequency sweeps, and time-series captures.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, ClassVar

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QFormLayout, QVBoxLayout, QWidget

from stoner_measurement.plugins.base_plugin import BasePlugin, _ABCQObjectMeta
from stoner_measurement.scan import BaseScanGenerator, FunctionScanGenerator, SteppedScanGenerator

if TYPE_CHECKING:
    pass


class _ScanTabContainer(QWidget):
    """Container that hosts the active scan generator's config widget.

    The content is replaced automatically whenever the owning
    :class:`TracePlugin` emits :attr:`~TracePlugin.scan_generator_changed`.
    """

    def __init__(self, plugin: TracePlugin, parent: QWidget | None = None) -> None:
        """Initialise the container and bind it to *plugin*."""
        super().__init__(parent)
        self._plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._content: QWidget | None = None
        self._refresh()
        plugin.scan_generator_changed.connect(self._refresh)

    def _refresh(self) -> None:
        """Replace the content widget with the current generator's config widget."""
        if self._content is not None:
            self.layout().removeWidget(self._content)
            self._content.hide()
            self._content.deleteLater()
            self._content = None
        self._content = self._plugin.scan_generator.config_widget(parent=self)
        self.layout().addWidget(self._content)
        self._content.show()


class _ScanTypeSelector(QWidget):
    """Widget for selecting the scan generator class used by a :class:`TracePlugin`.

    Presents a labelled combo box populated from the plugin's
    :attr:`~TracePlugin._scan_generator_classes` list.  Changing the selection
    calls :meth:`~TracePlugin.set_scan_generator_class` on the plugin and the
    combo box stays in sync if the generator is changed programmatically.
    """

    def __init__(self, plugin: TracePlugin, parent: QWidget | None = None) -> None:
        """Initialise the selector widget and bind it to *plugin*."""
        super().__init__(parent)
        self._plugin = plugin
        layout = QFormLayout(self)
        self._combo = QComboBox()
        for cls in plugin._scan_generator_classes:
            self._combo.addItem(cls.__name__, cls)
        current_cls = type(plugin.scan_generator)
        idx = self._combo.findData(current_cls)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        layout.addRow("Generator type:", self._combo)
        self._combo.currentIndexChanged.connect(self._on_changed)
        plugin.scan_generator_changed.connect(self._sync_combo)

    def _on_changed(self, index: int) -> None:
        """Forward the selected class to the plugin."""
        cls = self._combo.itemData(index)
        if cls is not None and not isinstance(self._plugin.scan_generator, cls):
            self._plugin.set_scan_generator_class(cls)

    def _sync_combo(self) -> None:
        """Keep the combo box in sync with the plugin's current generator type."""
        current_cls = type(self._plugin.scan_generator)
        idx = self._combo.findData(current_cls)
        if idx >= 0 and self._combo.currentIndex() != idx:
            self._combo.blockSignals(True)
            self._combo.setCurrentIndex(idx)
            self._combo.blockSignals(False)


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
    * **Scan generator** — :attr:`scan_generator` holds the active
      :class:`~stoner_measurement.scan.BaseScanGenerator` instance.  The
      default class used is given by :attr:`_scan_generator_class` and can be
      changed at runtime via :meth:`set_scan_generator_class`.

    Attributes:
        _scan_generator_class (type[BaseScanGenerator]):
            Default scan generator class instantiated in :meth:`__init__`.
            Override at class level in a subclass to change the default for
            that plugin type.
        _scan_generator_classes (list[type[BaseScanGenerator]]):
            Ordered list of scan generator classes offered to the user in the
            *Scan Type* configuration tab.  The tab is only shown when this
            list contains more than one entry.  Override at class level to
            restrict or extend the available choices.
        scan_generator (BaseScanGenerator):
            Active scan generator instance.  Replaced (and
            :attr:`scan_generator_changed` emitted) when
            :meth:`set_scan_generator_class` is called.
        scan_generator_changed (pyqtSignal):
            Emitted after :attr:`scan_generator` is replaced with a new
            instance.  The first configuration tab and the *Scan Type*
            selector both connect to this signal to update their content.
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

    _scan_generator_class: ClassVar[type[BaseScanGenerator]] = SteppedScanGenerator
    _scan_generator_classes: ClassVar[list[type[BaseScanGenerator]]] = [
        SteppedScanGenerator,
        FunctionScanGenerator,
    ]

    trace_started = pyqtSignal(str)
    trace_point = pyqtSignal(str, float, float)
    trace_complete = pyqtSignal(str)
    scan_generator_changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy and create the built-in scan generator."""
        super().__init__(parent)
        self.scan_generator: BaseScanGenerator = self._scan_generator_class(parent=self)

    # ------------------------------------------------------------------
    # Scan generator management
    # ------------------------------------------------------------------

    def set_scan_generator_class(self, cls: type[BaseScanGenerator]) -> None:
        """Replace the active scan generator with a new instance of *cls*.

        If the current generator is already an instance of *cls* this method
        does nothing.  Otherwise a new instance is created (with this plugin
        as Qt parent), assigned to :attr:`scan_generator`, and
        :attr:`scan_generator_changed` is emitted so that connected widgets
        can refresh their content.

        Args:
            cls (type[BaseScanGenerator]):
                The scan generator class to instantiate.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> from stoner_measurement.scan import FunctionScanGenerator
            >>> plugin = DummyPlugin()
            >>> plugin.set_scan_generator_class(FunctionScanGenerator)
            >>> isinstance(plugin.scan_generator, FunctionScanGenerator)
            True
        """
        if isinstance(self.scan_generator, cls):
            return
        self.scan_generator = cls(parent=self)
        self.scan_generator_changed.emit()

    # ------------------------------------------------------------------
    # Plugin type tag
    # ------------------------------------------------------------------

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a trace collector.

        Returns:
            (str):
                Always ``"trace"``.
        """
        return "trace"

    # ------------------------------------------------------------------
    # Configuration tabs
    # ------------------------------------------------------------------

    def config_tabs(
        self, parent: QWidget | None = None
    ) -> list[tuple[str, QWidget]]:
        """Return configuration tabs with the scan generator widget as the first tab.

        The returned list always begins with a *Scan* tab containing a
        :class:`_ScanTabContainer` whose content updates whenever the active
        generator changes.  When :attr:`_scan_generator_classes` lists more
        than one class, a *Scan Type* tab with a :class:`_ScanTypeSelector`
        combo box is appended next.  Plugin-specific tabs from
        :meth:`_plugin_config_tabs` follow.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs; the scan generator tab
                is always first.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> tabs = plugin.config_tabs()
            >>> "Scan" in tabs[0][0]
            True
        """
        tabs: list[tuple[str, QWidget]] = [
            (f"{self.name} \u2013 Scan", _ScanTabContainer(self, parent=parent)),
        ]
        if len(self._scan_generator_classes) > 1:
            tabs.append(
                (f"{self.name} \u2013 Scan Type", _ScanTypeSelector(self, parent=parent))
            )
        tabs.extend(self._plugin_config_tabs(parent=parent))
        return tabs

    def _plugin_config_tabs(
        self, parent: QWidget | None = None
    ) -> list[tuple[str, QWidget]]:
        """Return plugin-specific configuration tabs (excluding scan tabs).

        The default implementation delegates to
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.config_tabs`,
        which wraps :meth:`config_widget` in a single tab titled with
        :attr:`name`.

        Override this method in a subclass to contribute additional plugin-
        specific tabs.  Do **not** override :meth:`config_tabs` directly; that
        would bypass the scan-related tabs injected by this class.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs for plugin-specific tabs.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> tabs = plugin._plugin_config_tabs()
            >>> len(tabs)
            2
        """
        return BasePlugin.config_tabs(self, parent=parent)

    # ------------------------------------------------------------------
    # Abstract acquisition interface
    # ------------------------------------------------------------------

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
