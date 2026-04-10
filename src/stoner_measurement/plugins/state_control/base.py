"""StateControlPlugin — abstract base class for experimental-state controllers.

State-control plugins command hardware to move to a target value and report
when the hardware has settled.  Examples include magnet power-supplies,
temperature controllers, motorised stages, and programmable voltage sources.

A :class:`StateControlPlugin` is the natural "axis" driven by a
:class:`~stoner_measurement.scan.base.BaseScanGenerator`: the generator yields
successive set-point values that are forwarded to :meth:`ramp_to`.
"""

from __future__ import annotations

import math
import time
from abc import abstractmethod
from collections.abc import Callable
from typing import ClassVar

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.plugins.base_plugin import _ABCQObjectMeta
from stoner_measurement.plugins.sequence.base import SequencePlugin
from stoner_measurement.scan import BaseScanGenerator, FunctionScanGenerator, SteppedScanGenerator


class _StateControlScanTabContainer(QWidget):
    """Container that hosts the active scan generator's config widget for a state control plugin.

    The content is replaced automatically whenever the owning
    :class:`StateControlPlugin` emits :attr:`~StateControlPlugin.scan_generator_changed`.
    """

    def __init__(self, plugin: StateControlPlugin, parent: QWidget | None = None) -> None:
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


class _StateControlScanPage(QWidget):
    """Combined scan configuration page for a state control plugin.

    Displays the instance-name editor, a scan-generator type selector, a
    horizontal rule, and the active generator's configuration widget.
    """

    def __init__(self, plugin: StateControlPlugin, parent: QWidget | None = None) -> None:
        """Initialise the scan page and bind it to *plugin*."""
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # --- Header form: instance name + optional generator selector ---
        header_form = QFormLayout()

        name_edit = QLineEdit(plugin.instance_name)
        name_edit.setToolTip(
            "Python variable name used to access this plugin in the sequence engine"
        )

        def _apply_name() -> None:
            new_name = name_edit.text().strip()
            if new_name and new_name.isidentifier():
                name_edit.setStyleSheet("")
                plugin.instance_name = new_name
            else:
                name_edit.setStyleSheet("border: 1px solid red;")
                name_edit.setToolTip(
                    f"{new_name!r} is not a valid Python identifier. "
                    "Use only letters, digits and underscores, "
                    "and do not start with a digit."
                )
                name_edit.setText(plugin.instance_name)

        name_edit.editingFinished.connect(_apply_name)
        header_form.addRow("Instance name:", name_edit)
        header_form.addRow("Plugin type:", QLabel(plugin.plugin_type))

        if len(type(plugin)._scan_generator_classes) > 1:
            combo = QComboBox()
            for cls in type(plugin)._scan_generator_classes:
                combo.addItem(cls.__name__, cls)
            current_idx = combo.findData(type(plugin.scan_generator))
            if current_idx >= 0:
                combo.setCurrentIndex(current_idx)

            def _on_type_changed(index: int) -> None:
                cls = combo.itemData(index)
                if cls is not None and not isinstance(plugin.scan_generator, cls):
                    plugin.set_scan_generator_class(cls)

            def _sync_type_combo() -> None:
                current_cls = type(plugin.scan_generator)
                idx = combo.findData(current_cls)
                if idx >= 0 and combo.currentIndex() != idx:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)

            combo.currentIndexChanged.connect(_on_type_changed)
            plugin.scan_generator_changed.connect(_sync_type_combo)
            header_form.addRow("Generator type:", combo)

        header_widget = QWidget()
        header_widget.setLayout(header_form)
        layout.addWidget(header_widget)

        # --- Horizontal separator ---
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # --- Scan generator config widget (auto-refreshes on generator change) ---
        scan_container = _StateControlScanTabContainer(plugin, parent=self)
        layout.addWidget(scan_container)


class StateControlPlugin(QObject, SequencePlugin, metaclass=_ABCQObjectMeta):
    """Abstract base class for plugins that control experimental state.

    A :class:`StateControlPlugin` commands an instrument to move to a target
    value and monitors progress until the state has stabilised.  Subclasses
    must implement :attr:`name`, :attr:`state_name`, :attr:`units`,
    :meth:`set_state`, :meth:`get_state`, and :meth:`is_at_target`.

    Inheriting from :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
    means that a :class:`StateControlPlugin` item in the sequence tree may act
    as a branch node: other steps can be nested beneath it and will be executed
    via :meth:`execute_sequence` at the appropriate point in the ramp lifecycle.

    The class provides:

    * **Instrument lifecycle** — :meth:`connect`, :meth:`configure`, and
      :meth:`disconnect` form the standard sequence-engine interface for
      opening, configuring, and releasing hardware resources.  Default
      implementations are no-ops; override them in concrete plugins.
    * **Direct control** — :meth:`set_state` and :meth:`get_state` offer
      a low-level read/write interface to the underlying hardware.
    * **Blocking ramp helper** — :meth:`ramp_to` calls :meth:`set_state`,
      then polls :meth:`is_at_target` until settled or a timeout is reached,
      emitting :attr:`state_changed` at each poll and :attr:`state_reached`
      on success.
    * **Safety limits** — :attr:`limits` defines the allowed set-point range;
      :meth:`ramp_to` will emit :attr:`state_error` rather than commanding
      an out-of-range value.
    * **Scan generator** — :attr:`scan_generator` holds the active
      :class:`~stoner_measurement.scan.BaseScanGenerator` instance that
      determines the set-point sequence.  The default generator class is
      given by :attr:`_scan_generator_class` and can be changed at runtime
      via :meth:`set_scan_generator_class`.
    * **Sub-sequence execution** —
      :meth:`execute_sequence` iterates over the scan generator set-points,
      calling :meth:`ramp_to` for each and invoking all sub-step callables
      at every set-point, then disconnects in a ``finally`` block.

    Attributes:
        _scan_generator_class (type[BaseScanGenerator]):
            Default scan generator class instantiated in :meth:`__init__`.
            Override at class level in a subclass to change the default for
            that plugin type.
        _scan_generator_classes (list[type[BaseScanGenerator]]):
            Ordered list of scan generator classes offered to the user in the
            *Scan* configuration tab.  The tab shows a type selector only when
            this list contains more than one entry.
        scan_generator (BaseScanGenerator):
            Active scan generator instance.  Replaced (and
            :attr:`scan_generator_changed` emitted) when
            :meth:`set_scan_generator_class` is called.
        ix (int):
            Zero-based index of the current set-point within the active scan.
            Updated on each iteration step so that nested loops can each
            expose their own independent position via their plugin instance.
        value (float):
            Current set-point value set on the last iteration step.  Updated
            before :meth:`ramp_to` is called; accessible in generated code as
            ``plugin.value``.
        meas_flag (bool):
            Whether the current set-point should be recorded as a measurement.
            Updated on each iteration step alongside :attr:`ix` and
            :attr:`value`.
        state_changed (pyqtSignal[float]):
            Emitted continuously with the current measured value while the
            hardware ramps towards its target.
        state_reached (pyqtSignal[float]):
            Emitted once when the hardware has settled at the target value.
        state_error (pyqtSignal[str]):
            Emitted with a descriptive message if the hardware faults or the
            settle timeout is exceeded.
        scan_generator_changed (pyqtSignal):
            Emitted after :attr:`scan_generator` is replaced with a new
            instance.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.state_control import StateControlPlugin
        >>> class _DummyState(StateControlPlugin):
        ...     @property
        ...     def name(self): return "DummyState"
        ...     @property
        ...     def state_name(self): return "Voltage"
        ...     @property
        ...     def units(self): return "V"
        ...     def set_state(self, value): self._v = value
        ...     def get_state(self): return getattr(self, "_v", 0.0)
        ...     def is_at_target(self): return True
        >>> p = _DummyState()
        >>> p.plugin_type
        'state'
        >>> p.limits
        (-inf, inf)
        >>> p.settle_timeout
        60.0
        >>> from stoner_measurement.scan import SteppedScanGenerator
        >>> isinstance(p.scan_generator, SteppedScanGenerator)
        True
    """

    _scan_generator_class: ClassVar[type[BaseScanGenerator]] = SteppedScanGenerator
    _scan_generator_classes: ClassVar[list[type[BaseScanGenerator]]] = [
        SteppedScanGenerator,
        FunctionScanGenerator,
    ]

    state_changed = pyqtSignal(float)
    state_reached = pyqtSignal(float)
    state_error = pyqtSignal(str)
    instance_name_changed = pyqtSignal(str, str)
    scan_generator_changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy and create the built-in scan generator."""
        super().__init__(parent)
        self.scan_generator: BaseScanGenerator = self._scan_generator_class(parent=self)
        self.ix: int = 0
        self.value: float = 0.0
        self.meas_flag: bool = False

    def _on_instance_name_changed(self, old_name: str, new_name: str) -> None:
        """Emit :attr:`instance_name_changed` when the instance name changes."""
        self.instance_name_changed.emit(old_name, new_name)

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a state controller.

        Returns:
            (str):
                Always ``"state"``.
        """
        return "state"

    # ------------------------------------------------------------------
    # JSON serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> dict:
        """Serialise this plugin's configuration, including the scan generator.

        Extends the base :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
        dict with a ``"scan_generator"`` key containing the serialised
        :attr:`scan_generator` state.

        Returns:
            (dict):
                A JSON-serialisable dictionary with at least the keys produced
                by :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
                plus ``"scan_generator"``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import CounterPlugin
            >>> plugin = CounterPlugin()
            >>> d = plugin.to_json()
            >>> d["type"]
            'state'
            >>> "scan_generator" in d
            True
            >>> d["scan_generator"]["type"]
            'SteppedScanGenerator'
        """
        data = super().to_json()
        data["scan_generator"] = self.scan_generator.to_json()
        return data

    def _restore_from_json(self, data: dict) -> None:
        """Restore the scan generator from *data*.

        Called by :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.from_json`
        after construction.  Reconstructs the :attr:`scan_generator` and emits
        :attr:`scan_generator_changed` so that any already-connected widgets
        can update their content.

        Args:
            data (dict):
                Serialised plugin dict as produced by :meth:`to_json`.
        """
        if "scan_generator" in data:
            from stoner_measurement.scan.base import BaseScanGenerator

            gen = BaseScanGenerator.from_json(data["scan_generator"], parent=self)
            self.scan_generator = gen
            self.scan_generator_changed.emit()

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
            >>> from stoner_measurement.plugins.state_control import CounterPlugin
            >>> plugin = CounterPlugin()
            >>> from stoner_measurement.scan import SteppedScanGenerator
            >>> plugin.set_scan_generator_class(SteppedScanGenerator)
            >>> isinstance(plugin.scan_generator, SteppedScanGenerator)
            True
        """
        if isinstance(self.scan_generator, cls):
            return
        self.scan_generator = cls(parent=self)
        self.scan_generator_changed.emit()

    # ------------------------------------------------------------------
    # Configuration tabs
    # ------------------------------------------------------------------

    def config_tabs(
        self, parent: QWidget | None = None
    ) -> list[tuple[str, QWidget]]:
        """Return a fixed set of configuration tabs for this plugin.

        Returns a *Scan* tab (instance name, state info, optional generator
        selector, and the generator's own config widget), a *Settings* tab
        populated by :meth:`_plugin_config_tabs`, and an optional *About* tab
        whose HTML content is provided by :meth:`_about_html`.

        Tab widgets are created once and cached on the plugin instance so that
        user-edited state is preserved when tabs are hidden and re-shown.

        Keyword Parameters:
            parent (QWidget | None):
                Ignored after the first call; widgets are cached without a
                parent and are re-parented automatically by
                :class:`~PyQt6.QtWidgets.QTabWidget` when added.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs; the *Scan* tab is always
                first.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import CounterPlugin
            >>> plugin = CounterPlugin()
            >>> tabs = plugin.config_tabs()
            >>> tabs[0][0]
            'Counter \u2013 Scan'
            >>> tabs[1][0]
            'Counter \u2013 Settings'
        """
        if hasattr(self, "_cached_config_tabs"):
            return self._cached_config_tabs

        tabs: list[tuple[str, QWidget]] = [
            (f"{self.name} \u2013 Scan", _StateControlScanPage(self)),
        ]

        settings_widget = self._plugin_config_tabs()
        if settings_widget is None:
            settings_widget = QWidget()
        tabs.append((f"{self.name} \u2013 Settings", settings_widget))

        about_html = self._about_html()
        if about_html is not None:
            about_widget = QTextBrowser()
            about_widget.setHtml(about_html)
            tabs.append((f"{self.name} \u2013 About", about_widget))

        self._cached_config_tabs = tabs
        return self._cached_config_tabs

    def _plugin_config_tabs(self) -> QWidget | None:
        """Return the settings widget for the *Settings* tab, or ``None`` for a blank tab.

        The default implementation returns ``None``, which causes
        :meth:`config_tabs` to display an empty :class:`~PyQt6.QtWidgets.QWidget`
        as the *Settings* tab.

        Override this method in a subclass to return a configured
        :class:`~PyQt6.QtWidgets.QWidget` for the *Settings* tab.

        Returns:
            (QWidget | None):
                The settings widget, or ``None`` for a blank tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import CounterPlugin
            >>> CounterPlugin()._plugin_config_tabs() is None
            True
        """
        return None

    def _about_html(self) -> str | None:
        """Return an HTML string for the *About* tab, or ``None`` to omit the tab.

        The default implementation returns ``None`` so that no *About* tab is
        shown.  Override in a subclass to provide plugin-specific documentation.

        Returns:
            (str | None):
                HTML-formatted documentation string, or ``None`` to omit the
                *About* tab entirely.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import CounterPlugin
            >>> CounterPlugin()._about_html() is None
            True
        """
        return None

    # ------------------------------------------------------------------
    # Sub-sequence execution
    # ------------------------------------------------------------------

    def execute_sequence(self, sub_steps: list) -> None:
        """Connect, configure, iterate over the scan, run *sub_steps*, then disconnect.

        For each set-point in :attr:`scan_generator`, calls :meth:`ramp_to`
        to move the hardware to that set-point and then invokes every callable
        in *sub_steps* in order.  The connect/disconnect lifecycle is wrapped
        in a ``try/finally`` block to ensure resources are always released.

        When the scan generator has no stages (i.e. it produces only the
        single start point), this reduces to a single ramp followed by the
        sub-steps — equivalent to the original behaviour.

        Args:
            sub_steps (list):
                Ordered list of zero-argument callables, one per nested step.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _S(StateControlPlugin):
            ...     @property
            ...     def name(self): return "S"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): self._v = float(v)
            ...     def get_state(self): return getattr(self, "_v", 0.0)
            ...     def is_at_target(self): return True
            >>> from stoner_measurement.scan import SteppedScanGenerator
            >>> p = _S()
            >>> p.scan_generator = SteppedScanGenerator(start=0.0, stages=[(2.0, 1.0, True)])
            >>> visited = []
            >>> p.execute_sequence([lambda: visited.append(p.get_state())])
            >>> visited
            [0.0, 1.0, 2.0]
        """
        self.ix = 0
        self.value = 0.0
        self.meas_flag = False
        self.connect()
        self.configure()
        try:
            for self.ix, self.value, self.meas_flag in self.scan_generator:
                self.ramp_to(float(self.value))
                for sub_step in sub_steps:
                    sub_step()
        finally:
            self.disconnect()

    # ------------------------------------------------------------------
    # Instrument lifecycle API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open instrument connections and verify the instrument identity.

        Called once at the start of a measurement sequence to reserve hardware
        resources.  Subclasses should override this method to open serial,
        USB, GPIB, or Ethernet connections and to confirm that the connected
        instrument is the expected type.

        The default implementation is a no-op.  Subclass implementations
        should raise :exc:`RuntimeError` if the instrument cannot be reached
        or is not the expected type.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _S(StateControlPlugin):
            ...     @property
            ...     def name(self): return "S"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): pass
            ...     def get_state(self): return 0.0
            ...     def is_at_target(self): return True
            >>> p = _S()
            >>> p.connect()  # no-op by default
        """

    def configure(self) -> None:
        """Apply plugin settings to the instrument.

        Called after :meth:`connect` and before the measurement loop to push
        configuration (output range, ramp rate, etc.) to the hardware.  May
        also be called mid-sequence to reconfigure without reconnecting.

        The default implementation is a no-op.  Override to send the
        appropriate commands to the instrument.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _S(StateControlPlugin):
            ...     @property
            ...     def name(self): return "S"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): pass
            ...     def get_state(self): return 0.0
            ...     def is_at_target(self): return True
            >>> p = _S()
            >>> p.configure()  # no-op by default
        """

    def disconnect(self) -> None:
        """Release all reserved instrument resources.

        Called at the end of a measurement sequence (or after an error) to
        cleanly close connections and free hardware resources.  The default
        implementation is a no-op.  Override to close serial/USB/GPIB/Ethernet
        connections.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _S(StateControlPlugin):
            ...     @property
            ...     def name(self): return "S"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): pass
            ...     def get_state(self): return 0.0
            ...     def is_at_target(self): return True
            >>> p = _S()
            >>> p.disconnect()  # no-op by default
        """

    @property
    @abstractmethod
    def state_name(self) -> str:
        """Human-readable name of the controlled physical quantity.

        Returns:
            (str):
                E.g. ``"Magnetic Field"``, ``"Temperature"``, ``"Voltage"``.
        """

    @property
    @abstractmethod
    def units(self) -> str:
        """Physical unit of the controlled quantity.

        Returns:
            (str):
                E.g. ``"T"``, ``"K"``, ``"V"``.
        """

    @abstractmethod
    def set_state(self, value: float) -> None:
        """Command the hardware to move towards *value*.

        This method should initiate the change but need not block until the
        hardware has settled; settling is handled by :meth:`ramp_to`.

        Args:
            value (float):
                Target set-point in the units reported by :attr:`units`.
        """

    @abstractmethod
    def get_state(self) -> float:
        """Return the current measured value of the controlled quantity.

        Returns:
            (float):
                Present value in the units reported by :attr:`units`.
        """

    @abstractmethod
    def is_at_target(self) -> bool:
        """Return ``True`` when the hardware has settled at the commanded target.

        Returns:
            (bool):
                ``True`` if the state has stabilised; ``False`` while still
                ramping or settling.
        """

    @property
    def limits(self) -> tuple[float, float]:
        """Allowed set-point range ``(minimum, maximum)``.

        :meth:`ramp_to` rejects targets outside this range by emitting
        :attr:`state_error`.  The default is ``(-inf, inf)`` (no limits).

        Returns:
            (tuple[float, float]):
                ``(min_value, max_value)`` in the units of :attr:`units`.
        """
        return (float("-inf"), float("inf"))

    @property
    def settle_timeout(self) -> float:
        """Maximum time in seconds to wait for the state to reach its target.

        Returns:
            (float):
                Timeout in seconds; default ``60.0``.
        """
        return 60.0

    def ramp_to(self, value: float, poll_interval: float = 0.5) -> None:
        """Command hardware to *value* and block until settled or timed out.

        The method validates *value* against :attr:`limits`, calls
        :meth:`set_state`, then polls :meth:`is_at_target` every
        *poll_interval* seconds.  :attr:`state_changed` is emitted at each
        poll with the current measured value.  :attr:`state_reached` is
        emitted on success; :attr:`state_error` is emitted on timeout or an
        out-of-range target.

        .. note::
            This is a **blocking** call.  In a Qt application, call it from a
            worker thread (e.g. via ``QThreadPool``) to avoid freezing the
            event loop.

        Args:
            value (float):
                Target set-point in the units of :attr:`units`.

        Keyword Parameters:
            poll_interval (float):
                Seconds between successive :meth:`is_at_target` polls;
                default ``0.5``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _InstantState(StateControlPlugin):
            ...     @property
            ...     def name(self): return "Instant"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): self._v = v
            ...     def get_state(self): return getattr(self, "_v", 0.0)
            ...     def is_at_target(self): return True
            >>> reached = []
            >>> p = _InstantState()
            >>> p.state_reached.connect(lambda v: reached.append(v))
            >>> p.ramp_to(1.0, poll_interval=0.0)
            >>> reached
            [1.0]
        """
        lo, hi = self.limits
        if (math.isfinite(lo) and value < lo) or (math.isfinite(hi) and value > hi):
            self.state_error.emit(f"Target {value} is outside limits [{lo}, {hi}]")
            return

        self.set_state(value)
        deadline = time.monotonic() + self.settle_timeout
        while not self.is_at_target():
            self.state_changed.emit(self.get_state())
            if time.monotonic() > deadline:
                self.state_error.emit(
                    f"Timeout after {self.settle_timeout}s waiting for state to reach {value}"
                )
                return
            time.sleep(poll_interval)
        self.state_reached.emit(self.get_state())

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return action code lines for a scan loop over :attr:`scan_generator`.

        Emits a ``for`` loop that iterates over the scan generator's set-points,
        calls :meth:`ramp_to` for each, and recursively renders any nested
        sub-steps inside the loop body.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Raw sub-step descriptors from the sequence tree; rendered via
                *render_sub_step* at ``indent + 1``.
            render_sub_step (Callable):
                Callback ``(step, indent) -> list[str]`` provided by the engine.

        Returns:
            (list[str]):
                Lines implementing the scan loop with nested sub-step bodies.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _S(StateControlPlugin):
            ...     @property
            ...     def name(self): return "S"
            ...     @property
            ...     def state_name(self): return "X"
            ...     @property
            ...     def units(self): return "au"
            ...     def set_state(self, v): pass
            ...     def get_state(self): return 0.0
            ...     def is_at_target(self): return True
            >>> p = _S()
            >>> lines = p.generate_action_code(1, [], lambda s, i: [])
            >>> any("for s.ix, s.value, s.meas_flag in s.scan_generator:" in line for line in lines)
            True
        """
        prefix = "    " * indent
        loop_prefix = "    " * (indent + 1)
        var_name = self.instance_name
        lines: list[str] = [
            f"{prefix}for {var_name}.ix, {var_name}.value, {var_name}.meas_flag in {var_name}.scan_generator:",
            f"{loop_prefix}{var_name}.ramp_to(float({var_name}.value))",
            f'{loop_prefix}print(f"{self.state_name}: {{{var_name}.get_state():.4g}} {self.units}")',
        ]
        for sub_step in sub_steps:
            lines.extend(render_sub_step(sub_step, indent + 1))
        lines.append("")
        return lines

    def reported_values(self) -> dict[str, str]:
        """Return a mapping of the controlled state quantity to a Python expression.

        Reports the current scan set-point as a scalar data value, accessible via
        ``"{instance_name}.value"``.  This allows downstream plugins (e.g. plot
        plugins) to reference the current set-point by its human-readable name.

        Returns:
            (dict[str, str]):
                Single-entry dict ``{"{instance_name}:{state_name}": "{instance_name}.value"}``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> class _S(StateControlPlugin):
            ...     @property
            ...     def name(self): return "Field"
            ...     @property
            ...     def state_name(self): return "Magnetic Field"
            ...     @property
            ...     def units(self): return "T"
            ...     def set_state(self, v): pass
            ...     def get_state(self): return 0.0
            ...     def is_at_target(self): return True
            >>> p = _S()
            >>> vals = p.reported_values()
            >>> list(vals.keys())
            ['field:Magnetic Field']
            >>> vals['field:Magnetic Field']
            'field.value'
        """
        var = self.instance_name
        return {f"{var}:{self.state_name}": f"{var}.value"}

