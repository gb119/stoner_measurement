"""StateScanPlugin — abstract base class for discrete-step, ramp-to-target state control.

State-scan plugins command hardware to move to a target value and report when
the hardware has settled.  Examples include magnet power-supplies, temperature
controllers, motorised stages, and programmable voltage sources.

A :class:`StateScanPlugin` is the natural "axis" driven by a
:class:`~stoner_measurement.scan.base.BaseScanGenerator`: the generator yields
successive set-point values that are forwarded to :meth:`ramp_to`.
"""

from __future__ import annotations

import math
import time
from abc import abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.plugins.state.base import StatePlugin
from stoner_measurement.scan import (
    ArbitraryFunctionScanGenerator,
    BaseScanGenerator,
    FunctionScanGenerator,
    ListScanGenerator,
    RampScanGenerator,
    SteppedScanGenerator,
)


class _StateScanTabContainer(QWidget):
    """Container that hosts the active scan generator's config widget for a state-scan plugin.

    The content is replaced automatically whenever the owning
    :class:`StateScanPlugin` emits :attr:`~StateScanPlugin.scan_generator_changed`.
    """

    def __init__(self, plugin: StateScanPlugin, parent: QWidget | None = None) -> None:
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


class _StateScanPage(QWidget):
    """Combined scan configuration page for a state-scan plugin.

    Displays the instance-name editor, a scan-generator type selector, a
    horizontal rule, and the active generator's configuration widget, followed
    by the data-collection settings.
    """

    def __init__(self, plugin: StateScanPlugin, parent: QWidget | None = None) -> None:
        """Initialise the scan page and bind it to *plugin*."""
        super().__init__(parent)
        layout = QVBoxLayout(self)

        from PyQt6.QtWidgets import QCheckBox

        # --- Header form: instance name + optional generator selector ---
        header_form = QFormLayout()

        name_edit = QLineEdit(plugin.instance_name)
        name_edit.setToolTip("Python variable name used to access this plugin in the sequence engine")

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
        scan_container = _StateScanTabContainer(plugin, parent=self)
        layout.addWidget(scan_container)

        # --- Horizontal separator before data-collection settings ---
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        # --- Data-collection settings ---
        data_form = QFormLayout()

        collect_check = QCheckBox()
        collect_check.setChecked(plugin.collect_data)
        collect_check.setToolTip("Enable data collection at each iteration step.")

        clear_check = QCheckBox()
        clear_check.setChecked(plugin.clear_on_start)
        clear_check.setToolTip("Clear the collected data when the scan loop starts.")

        collect_filter_edit = QLineEdit(plugin.collect_filter)
        collect_filter_edit.setToolTip(
            "Python expression evaluated to decide whether to collect a data point. "
            f"Default: {plugin.instance_name}.meas_flag"
        )

        clear_filter_edit = QLineEdit(plugin.clear_filter)
        clear_filter_edit.setToolTip(
            "Python expression evaluated to decide whether to clear the data. Default: True"
        )

        data_form.addRow("Collect data:", collect_check)
        data_form.addRow("Clear on start:", clear_check)
        data_form.addRow("Collect filter:", collect_filter_edit)
        data_form.addRow("Clear filter:", clear_filter_edit)

        def _apply_collect(state: int) -> None:
            plugin.collect_data = bool(state)

        def _apply_clear(state: int) -> None:
            plugin.clear_on_start = bool(state)

        def _apply_collect_filter() -> None:
            plugin.collect_filter = collect_filter_edit.text().strip() or f"{plugin.instance_name}.meas_flag"

        def _apply_clear_filter() -> None:
            plugin.clear_filter = clear_filter_edit.text().strip() or "True"

        collect_check.stateChanged.connect(_apply_collect)
        clear_check.stateChanged.connect(_apply_clear)
        collect_filter_edit.editingFinished.connect(_apply_collect_filter)
        clear_filter_edit.editingFinished.connect(_apply_clear_filter)

        data_widget = QWidget()
        data_widget.setLayout(data_form)
        layout.addWidget(data_widget)


class StateScanPlugin(StatePlugin):
    """Abstract base class for plugins that control experimental state via discrete-step scanning.

    A :class:`StateScanPlugin` commands an instrument to move to a target
    value and monitors progress until the state has stabilised.  Subclasses
    must implement :attr:`name`, :attr:`state_name`, :attr:`units`,
    :meth:`set_state`, :meth:`get_state`, and :meth:`is_at_target`.

    Inheriting from :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
    (via :class:`~stoner_measurement.plugins.state.base.StatePlugin`) means
    that a :class:`StateScanPlugin` item in the sequence tree may act as a
    branch node: other steps can be nested beneath it and executed at each
    set-point.

    The class provides:

    * **Instrument lifecycle** — :meth:`connect`, :meth:`configure`, and
      :meth:`disconnect` form the standard sequence-engine interface.  Default
      implementations are no-ops; override them in concrete plugins.
    * **Direct control** — :meth:`set_state` and :meth:`get_state` offer
      a low-level read/write interface to the underlying hardware.
    * **Blocking ramp helper** — :meth:`ramp_to` calls :meth:`set_state`,
      then polls :meth:`is_at_target` until settled or a timeout is reached,
      emitting :attr:`state_changed` at each poll and :attr:`state_reached`
      on success.
    * **Safety limits** — :attr:`limits` defines the allowed set-point range;
      :meth:`ramp_to` will emit :attr:`state_error` rather than commanding an
      out-of-range value.
    * **Scan generator** — :attr:`scan_generator` holds the active
      :class:`~stoner_measurement.scan.BaseScanGenerator` instance.
    * **Data collection** — inherited from
      :class:`~stoner_measurement.plugins.state.base.StatePlugin`.

    Attributes:
        _scan_generator_class (type[BaseScanGenerator]):
            Default scan generator class instantiated in :meth:`__init__`.
        _scan_generator_classes (list[type[BaseScanGenerator]]):
            Ordered list of scan generator classes offered in the config tab.
        scan_generator (BaseScanGenerator):
            Active scan generator instance.
        scan_generator_changed (pyqtSignal):
            Emitted after :attr:`scan_generator` is replaced.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.state_scan import StateScanPlugin
        >>> class _DummyState(StateScanPlugin):
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
        'state_scan'
        >>> p.limits
        (-inf, inf)
        >>> p.settle_timeout
        60.0
        >>> from stoner_measurement.scan import FunctionScanGenerator
        >>> isinstance(p.scan_generator, FunctionScanGenerator)
        True
    """

    _scan_generator_class: ClassVar[type[BaseScanGenerator]] = FunctionScanGenerator
    _scan_generator_classes: ClassVar[list[type[BaseScanGenerator]]] = [
        FunctionScanGenerator,
        SteppedScanGenerator,
        ListScanGenerator,
        RampScanGenerator,
        ArbitraryFunctionScanGenerator,
    ]

    scan_generator_changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy and create the built-in scan generator."""
        super().__init__(parent)
        self.scan_generator: BaseScanGenerator = self._scan_generator_class(parent=self)

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a state-scan controller.

        Returns:
            (str):
                Always ``"state_scan"``.
        """
        return "state_scan"

    # ------------------------------------------------------------------
    # JSON serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Serialise this plugin's configuration, including the scan generator.

        Extends :meth:`~stoner_measurement.plugins.state.base.StatePlugin.to_json`
        with a ``"scan_generator"`` key.

        Returns:
            (dict[str, Any]):
                JSON-serialisable dictionary with all plugin keys.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> plugin = CounterPlugin()
            >>> d = plugin.to_json()
            >>> d["type"]
            'state_scan'
            >>> "scan_generator" in d
            True
            >>> d["collect_data"]
            False
            >>> d["clear_on_start"]
            True
        """
        data = super().to_json()
        data["scan_generator"] = self.scan_generator.to_json()
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore the scan generator and data-collection settings from *data*.

        Args:
            data (dict[str, Any]):
                Serialised plugin dict as produced by :meth:`to_json`.
        """
        super()._restore_from_json(data)
        if "scan_generator" in data:
            gen = BaseScanGenerator.from_json(data["scan_generator"], parent=self)
            self.scan_generator = gen
            self.scan_generator_changed.emit()

    # ------------------------------------------------------------------
    # Scan generator management
    # ------------------------------------------------------------------

    def set_scan_generator_class(self, cls: type[BaseScanGenerator]) -> None:
        """Replace the active scan generator with a new instance of *cls*.

        If the current generator is already an instance of *cls* this method
        does nothing.  Otherwise a new instance is created, assigned to
        :attr:`scan_generator`, and :attr:`scan_generator_changed` is emitted.

        Args:
            cls (type[BaseScanGenerator]):
                The scan generator class to instantiate.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
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

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return a fixed set of configuration tabs for this plugin.

        Returns a *Scan* tab, a *Settings* tab, and an optional *About* tab.
        Widgets are created once and cached.

        Keyword Parameters:
            parent (QWidget | None):
                Ignored after the first call; widgets are cached.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> plugin = CounterPlugin()
            >>> tabs = plugin.config_tabs()
            >>> tabs[0][0]
            'Counter \u2013 Scan'
            >>> tabs[1][0]
            'Counter \u2013 Settings'
        """
        if self._cached_config_tabs is not None:
            return self._cached_config_tabs

        tabs: list[tuple[str, QWidget]] = [
            (f"{self.name} \u2013 Scan", _StateScanPage(self)),
        ]

        settings_widget: QWidget = self._plugin_config_tabs() or QWidget()
        tabs.append((f"{self.name} \u2013 Settings", settings_widget))

        about_tab = self._make_about_tab()
        if about_tab is not None:
            tabs.append(about_tab)

        self._cached_config_tabs = tabs
        return self._cached_config_tabs

    def _plugin_config_tabs(self) -> QWidget | None:
        """Return the settings widget for the *Settings* tab, or ``None``.

        Override in a subclass to provide plugin-specific settings.

        Returns:
            (QWidget | None):
                The settings widget, or ``None`` for a blank tab.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> CounterPlugin()._plugin_config_tabs() is None
            True
        """
        return None

    # ------------------------------------------------------------------
    # Sub-sequence execution
    # ------------------------------------------------------------------

    def execute_sequence(self, sub_steps: list) -> None:
        """Connect, configure, iterate over the scan, run *sub_steps*, then disconnect.

        Args:
            sub_steps (list):
                Ordered list of zero-argument callables.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import StateScanPlugin
            >>> class _S(StateScanPlugin):
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
        self.stage = 0
        self.connect()
        self.configure()
        try:
            for self.ix, self.value, self.meas_flag, self.stage in self.scan_generator:
                self.ramp_to(float(self.value))
                for sub_step in sub_steps:
                    sub_step()
        finally:
            self.disconnect()

    # ------------------------------------------------------------------
    # Instrument API
    # ------------------------------------------------------------------

    @abstractmethod
    def set_state(self, value: float) -> None:
        """Command the hardware to move towards *value*.

        Args:
            value (float):
                Target set-point in the units of :attr:`units`.
        """

    @abstractmethod
    def get_state(self) -> float:
        """Return the current measured value of the controlled quantity.

        Returns:
            (float):
                Present value in the units of :attr:`units`.
        """

    @abstractmethod
    def is_at_target(self) -> bool:
        """Return ``True`` when the hardware has settled at the commanded target.

        Returns:
            (bool):
                ``True`` if settled; ``False`` while ramping or settling.
        """

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

        Validates *value* against :attr:`limits`, calls :meth:`set_state`, then
        polls :meth:`is_at_target`.  :attr:`state_changed` is emitted at each
        poll; :attr:`state_reached` on success; :attr:`state_error` on timeout
        or an out-of-range target.

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
            >>> from stoner_measurement.plugins.state_scan import StateScanPlugin
            >>> class _InstantState(StateScanPlugin):
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
            >>> _ = p.state_reached.connect(lambda v: reached.append(v))
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
                self.state_error.emit(f"Timeout after {self.settle_timeout}s waiting for state to reach {value}")
                return
            time.sleep(poll_interval)
        self.state_reached.emit(self.get_state())

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return action code lines for a scan loop over :attr:`scan_generator`.

        Args:
            indent (int):
                Number of four-space indentation levels.
            sub_steps (list):
                Raw sub-step descriptors from the sequence tree.
            render_sub_step (Callable):
                Callback ``(step, indent) -> list[str]`` provided by the engine.

        Returns:
            (list[str]):
                Lines implementing the scan loop with nested sub-step bodies.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import StateScanPlugin
            >>> class _S(StateScanPlugin):
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
            >>> any("for s.ix, s.value, s.meas_flag, s.stage in s.scan_generator:" in line for line in lines)
            True
            >>> p.clear_on_start = True
            >>> lines2 = p.generate_action_code(1, [], lambda s, i: [])
            >>> any("s.clear_data()" in line for line in lines2)
            True
            >>> p.collect_data = True
            >>> lines3 = p.generate_action_code(1, [], lambda s, i: [])
            >>> any("s.collect()" in line for line in lines3)
            True
        """
        prefix = "    " * indent
        loop_prefix = "    " * (indent + 1)
        var_name = self.instance_name
        lines: list[str] = []
        if self.clear_on_start:
            lines.append(f"{prefix}{var_name}.clear_data()")
        lines += [
            (
                f"{prefix}for {var_name}.ix, {var_name}.value, {var_name}.meas_flag, "
                f"{var_name}.stage in {var_name}.scan_generator:"
            ),
            f"{loop_prefix}wait_for_plot_ready()",
            f"{loop_prefix}{var_name}.ramp_to(float({var_name}.value))",
            f'{loop_prefix}print(f"{self.state_name}: {{{var_name}.get_state():.4g}} {self.units}")',
        ]
        for sub_step in sub_steps:
            lines.extend(render_sub_step(sub_step, indent + 1))
        if self.collect_data:
            lines.append(f"{loop_prefix}{var_name}.collect()")
        lines.append("")
        return lines
