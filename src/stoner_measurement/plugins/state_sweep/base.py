"""Base class for state-sweep plugins."""

from __future__ import annotations

import math
import time
from abc import abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar

import pyqtgraph as pg
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.plugins.state.base import StatePlugin
from stoner_measurement.sweep import (
    BaseSweepGenerator,
    MonitorAndFilterSweepGenerator,
    MultiSegmentRampSweepGenerator,
)

_TIMEOUT_FACTOR_DEFAULT = 2.0
_SPINBOX_MAX_ABS = 1e9


class _StateSweepTabContainer(QWidget):
    """Container for the active sweep generator widget."""

    def __init__(self, plugin: StateSweepPlugin, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._content: QWidget | None = None
        self._refresh()
        plugin.sweep_generator_changed.connect(self._refresh)

    def _refresh(self) -> None:
        if self._content is not None:
            self.layout().removeWidget(self._content)
            self._content.hide()
            self._content.deleteLater()
            self._content = None
        self._content = self._plugin.sweep_generator.config_widget(parent=self)
        self.layout().addWidget(self._content)
        self._content.show()


class _StateSweepPage(QWidget):
    """Combined configuration page for state-sweep plugins."""

    def __init__(self, plugin: StateSweepPlugin, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._build_header_section(plugin, layout)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)
        sweep_container = _StateSweepTabContainer(plugin, parent=self)
        layout.addWidget(sweep_container)
        self._build_data_collection_section(plugin, layout)

    def _build_header_section(self, plugin: StateSweepPlugin, layout: QVBoxLayout) -> None:
        """Build name edit, plugin type, optional generator combo, and timeout factor."""
        header_form = QFormLayout()

        name_edit = QLineEdit(plugin.instance_name)
        name_edit.setToolTip("Python variable name used to access this plugin in the sequence engine")

        def _apply_name() -> None:
            new_name = name_edit.text().strip()
            if new_name and new_name.isidentifier():
                name_edit.setStyleSheet("")
                plugin.instance_name = new_name
            elif not new_name:
                name_edit.setStyleSheet("border: 1px solid red;")
                name_edit.setToolTip("Instance name cannot be empty.")
                name_edit.setText(plugin.instance_name)
            else:
                name_edit.setStyleSheet("border: 1px solid red;")
                name_edit.setToolTip(
                    f"{new_name!r} is not a valid Python identifier. "
                    "Use only letters, digits and underscores, and do not start with a digit."
                )
                name_edit.setText(plugin.instance_name)

        name_edit.editingFinished.connect(_apply_name)
        header_form.addRow("Instance name:", name_edit)
        header_form.addRow("Plugin type:", QLabel(plugin.plugin_type))

        if len(type(plugin)._sweep_generator_classes) > 1:
            self._add_generator_combo(plugin, header_form)

        timeout_factor_spin = pg.SpinBox()
        timeout_factor_spin.setOpts(bounds=(0.1, _SPINBOX_MAX_ABS), decimals=2, step=0.1)
        timeout_factor_spin.setValue(plugin.sweep_timeout_factor)
        timeout_factor_spin.setToolTip(
            "Multiplier applied to the estimated sweep duration to compute the "
            "sweep timeout.  A value of 2.0 means the sweep is allowed twice "
            "its estimated duration before a state_error is emitted.  Has no "
            "effect when the sweep generator cannot estimate its duration."
        )
        timeout_factor_spin.sigValueChanged.connect(
            lambda sb: setattr(plugin, "sweep_timeout_factor", max(0.1, float(sb.value())))
        )
        header_form.addRow("Timeout factor:", timeout_factor_spin)

        header_widget = QWidget()
        header_widget.setLayout(header_form)
        layout.addWidget(header_widget)

    def _add_generator_combo(self, plugin: StateSweepPlugin, header_form: QFormLayout) -> None:
        """Add combo box for selecting sweep generator type when multiple classes exist."""
        combo = QComboBox()
        for cls in type(plugin)._sweep_generator_classes:
            combo.addItem(cls.__name__, cls)
        current_idx = combo.findData(type(plugin.sweep_generator))
        if current_idx >= 0:
            combo.setCurrentIndex(current_idx)

        def _on_type_changed(index: int) -> None:
            cls = combo.itemData(index)
            if cls is not None and not isinstance(plugin.sweep_generator, cls):
                plugin.set_sweep_generator_class(cls)

        def _sync_type_combo() -> None:
            current_cls = type(plugin.sweep_generator)
            idx = combo.findData(current_cls)
            if idx >= 0 and combo.currentIndex() != idx:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

        combo.currentIndexChanged.connect(_on_type_changed)
        plugin.sweep_generator_changed.connect(_sync_type_combo)
        header_form.addRow("Generator type:", combo)

    def _build_data_collection_section(self, plugin: StateSweepPlugin, layout: QVBoxLayout) -> None:
        """Build data collection checkboxes, filter edits, and preceding separator."""
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        data_form = QFormLayout()

        collect_check = QCheckBox()
        collect_check.setChecked(plugin.collect_data)
        clear_check = QCheckBox()
        clear_check.setChecked(plugin.clear_on_start)

        collect_filter_edit = QLineEdit(plugin.collect_filter)
        clear_filter_edit = QLineEdit(plugin.clear_filter)

        data_form.addRow("Collect data:", collect_check)
        data_form.addRow("Clear on start:", clear_check)
        data_form.addRow("Collect filter:", collect_filter_edit)
        data_form.addRow("Clear filter:", clear_filter_edit)

        collect_check.stateChanged.connect(lambda state: setattr(plugin, "collect_data", bool(state)))
        clear_check.stateChanged.connect(lambda state: setattr(plugin, "clear_on_start", bool(state)))

        def _apply_collect_filter() -> None:
            plugin.collect_filter = collect_filter_edit.text().strip() or f"{plugin.instance_name}.meas_flag"

        def _apply_clear_filter() -> None:
            plugin.clear_filter = clear_filter_edit.text().strip() or "True"

        collect_filter_edit.editingFinished.connect(_apply_collect_filter)
        clear_filter_edit.editingFinished.connect(_apply_clear_filter)

        data_widget = QWidget()
        data_widget.setLayout(data_form)
        layout.addWidget(data_widget)


class StateSweepPlugin(StatePlugin):
    """Base class for plugins that run a sub-sequence inside a continuous sweep loop.

    A :class:`StateSweepPlugin` drives a hardware sweep (e.g. a continuously
    ramping magnet, a time-based monitor) by iterating a
    :class:`~stoner_measurement.sweep.BaseSweepGenerator` and executing
    nested sub-steps at each sampled point.

    In addition to the shared state and data-collection infrastructure
    inherited from :class:`~stoner_measurement.plugins.state.base.StatePlugin`,
    this class adds:

    * **Sweep generator** — :attr:`sweep_generator` provides an infinite (or
      finite) stream of ``(index, value, stage, meas_flag)`` tuples.
    * **Sweep timeout** — if the sweep generator can estimate its duration
      (via :meth:`~stoner_measurement.sweep.BaseSweepGenerator.estimated_duration`),
      the allowed wall-clock time is ``estimated_duration × sweep_timeout_factor``.
      When the deadline is exceeded :attr:`state_error` is emitted and the loop
      stops.
    * **Safety limits** — if a sampled value falls outside :attr:`limits`
      :attr:`state_error` is emitted and the loop stops.
    * **Progress signals** — :attr:`state_changed` is emitted at each sampled
      point; :attr:`state_reached` on normal completion.

    Attributes:
        sweep_generator (BaseSweepGenerator):
            Active sweep generator instance.
        sweep_timeout_factor (float):
            Multiplier applied to the sweep generator's estimated duration to
            compute the sweep deadline.  Defaults to ``2.0``.  Has no effect
            when the generator returns ``inf`` for its estimated duration.
        sweep_generator_changed (pyqtSignal):
            Emitted after :attr:`sweep_generator` is replaced.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.state_sweep import SweepTimePlugin
        >>> p = SweepTimePlugin()
        >>> p.plugin_type
        'state_sweep'
        >>> p.sweep_timeout_factor
        2.0
        >>> import math
        >>> math.isinf(p.sweep_timeout)
        True
    """

    _sweep_generator_class: ClassVar[type[BaseSweepGenerator]] = MonitorAndFilterSweepGenerator
    _sweep_generator_classes: ClassVar[list[type[BaseSweepGenerator]]] = [
        MonitorAndFilterSweepGenerator,
        MultiSegmentRampSweepGenerator,
    ]

    sweep_generator_changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.sweep_generator: BaseSweepGenerator = self._sweep_generator_class(state_sweep=self, parent=self)
        self.sweep_timeout_factor: float = _TIMEOUT_FACTOR_DEFAULT
        self._sweep_start_time: float = 0.0
        self._sweep_deadline: float = float("inf")
        self.ix = -1

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a state-sweep plugin.

        Returns:
            (str):
                Always ``"state_sweep"``.
        """
        return "state_sweep"

    @property
    def sweep_timeout(self) -> float:
        """Maximum allowed wall-clock sweep time in seconds.

        Computed as ``sweep_generator.estimated_duration() * sweep_timeout_factor``.
        Returns ``float("inf")`` when the generator cannot estimate its
        duration, effectively disabling the timeout.

        Returns:
            (float):
                Timeout in seconds, or ``inf`` if not calculable.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.sweep import MultiSegmentRampSweepGenerator
            >>> from stoner_measurement.plugins.state_sweep import SweepTimePlugin
            >>> p = SweepTimePlugin()
            >>> p.sweep_generator = MultiSegmentRampSweepGenerator(
            ...     start=0.0, segments=[(2.0, 1.0, True)], state_sweep=p, parent=p
            ... )
            >>> p.sweep_timeout_factor = 3.0
            >>> p.sweep_timeout
            6.0
        """
        return self.sweep_generator.estimated_duration() * self.sweep_timeout_factor

    # ------------------------------------------------------------------
    # JSON serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Serialise this plugin's configuration, including the sweep generator.

        Extends :meth:`~stoner_measurement.plugins.state.base.StatePlugin.to_json`
        with ``"sweep_generator"`` and ``"sweep_timeout_factor"`` keys.

        Returns:
            (dict[str, Any]):
                JSON-serialisable dictionary with all plugin keys.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_sweep import SweepTimePlugin
            >>> d = SweepTimePlugin().to_json()
            >>> d["type"]
            'state_sweep'
            >>> "sweep_generator" in d
            True
            >>> d["sweep_timeout_factor"]
            2.0
        """
        data = super().to_json()
        data["sweep_generator"] = self.sweep_generator.to_json()
        data["sweep_timeout_factor"] = self.sweep_timeout_factor
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore the sweep generator and related settings from *data*.

        Args:
            data (dict[str, Any]):
                Serialised plugin dict as produced by :meth:`to_json`.
        """
        super()._restore_from_json(data)
        if "sweep_generator" in data:
            self.sweep_generator = BaseSweepGenerator.from_json(data["sweep_generator"], state_sweep=self, parent=self)
            self.sweep_generator_changed.emit()
        if "sweep_timeout_factor" in data:
            self.sweep_timeout_factor = max(0.1, float(data["sweep_timeout_factor"]))

    # ------------------------------------------------------------------
    # Sweep generator management
    # ------------------------------------------------------------------

    def set_sweep_generator_class(self, cls: type[BaseSweepGenerator]) -> None:
        """Replace the active sweep generator with a new instance of *cls*.

        Args:
            cls (type[BaseSweepGenerator]):
                The sweep generator class to instantiate.
        """
        if isinstance(self.sweep_generator, cls):
            return
        self.sweep_generator = cls(state_sweep=self, parent=self)
        self.sweep_generator_changed.emit()

    # ------------------------------------------------------------------
    # Configuration tabs
    # ------------------------------------------------------------------

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return a fixed set of configuration tabs for this plugin.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs.
        """
        if self._cached_config_tabs is not None:
            return self._cached_config_tabs

        tabs: list[tuple[str, QWidget]] = [
            (f"{self.name} \u2013 Sweep", _StateSweepPage(self)),
        ]

        settings_widget: QWidget = self._plugin_config_tabs() or QWidget()
        tabs.append((f"{self.name} \u2013 Settings", settings_widget))

        about_tab = self._make_about_tab()
        if about_tab is not None:
            tabs.append(about_tab)

        self._cached_config_tabs = tabs
        return self._cached_config_tabs

    def _plugin_config_tabs(self) -> QWidget | None:
        """Return the settings widget for the *Settings* tab, or ``None``."""
        return None

    # ------------------------------------------------------------------
    # Sweep iteration
    # ------------------------------------------------------------------

    def _begin_sweep(self) -> None:
        """Reset the generator and record the sweep start time and deadline."""
        timeout = self.sweep_timeout
        self._sweep_start_time = time.monotonic()
        self._sweep_deadline = self._sweep_start_time + timeout
        self.sweep_generator.reset()

    def __iter__(self) -> StateSweepPlugin:
        self._begin_sweep()
        return self

    def __next__(self) -> bool:
        """Advance by one point, checking timeout and limits.

        Returns:
            (bool):
                ``True`` if a new point was obtained; ``False`` when the
                generator is exhausted, a timeout is exceeded, or a value
                falls outside :attr:`limits`.  When ``False`` the loop should
                stop.  :attr:`state_error` is emitted on timeout or
                out-of-limits; :attr:`state_reached` is emitted on normal
                exhaustion.
        """
        now = time.monotonic()
        if now > self._sweep_deadline:
            elapsed = now - self._sweep_start_time
            self.state_error.emit(
                f"Sweep timeout exceeded after {elapsed:.1f}s "
                f"(expected ≤{self._sweep_deadline - self._sweep_start_time:.1f}s)"
            )
            self.meas_flag = False
            return False

        try:
            self.ix, self.value, self.stage, self.meas_flag = next(self.sweep_generator)
        except StopIteration:
            self.state_reached.emit(float(self.value))
            self.meas_flag = False
            return False

        lo, hi = self.limits
        if (math.isfinite(lo) and self.value < lo) or (math.isfinite(hi) and self.value > hi):
            self.state_error.emit(
                f"{self.state_name} value {self.value:.4g} {self.units} "
                f"is outside limits [{lo}, {hi}]"
            )
            self.meas_flag = False
            return False

        self.state_changed.emit(float(self.value))
        return True

    # ------------------------------------------------------------------
    # Sub-sequence execution
    # ------------------------------------------------------------------

    def execute_sequence(self, sub_steps: list) -> None:
        """Connect, configure, run the sweep loop with *sub_steps*, then disconnect.

        Args:
            sub_steps (list):
                Ordered list of zero-argument callables.
        """
        self.ix = -1
        self.value = 0.0
        self.stage = 0
        self.meas_flag = False
        self.connect()
        self.configure()
        try:
            if self.clear_on_start:
                self.clear_data()
            self._begin_sweep()
            while next(self):
                for sub_step in sub_steps:
                    sub_step()
                if self.collect_data:
                    self.collect()
        finally:
            self.disconnect()

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def state_name(self) -> str:
        """Human-readable name for the swept state."""

    @property
    @abstractmethod
    def units(self) -> str:
        """Physical units for the swept state."""

    # ------------------------------------------------------------------
    # Instrument hooks (NOP defaults)
    # ------------------------------------------------------------------

    def set_state(self, value: float) -> None:
        """Set the current state value (NOP default)."""

    def get_state(self) -> float:
        """Read the current state value.

        Returns:
            (float):
                Defaults to the most recently sampled :attr:`value`.
        """
        return float(self.value)

    def set_target(self, value: float) -> None:
        """Set the active target value (NOP default)."""

    def set_rate(self, value: float) -> None:
        """Set the active sweep rate (NOP default)."""

    def is_at_target(self) -> bool:
        """Return whether the target is reached (always ``True`` by default)."""
        return True

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return action code lines for a ``while next(...)`` sweep loop.

        Args:
            indent (int):
                Number of four-space indentation levels.
            sub_steps (list):
                Raw sub-step descriptors from the sequence tree.
            render_sub_step (Callable):
                Callback ``(step, indent) -> list[str]`` provided by the engine.

        Returns:
            (list[str]):
                Lines implementing the sweep loop with nested sub-step bodies.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_sweep import SweepTimePlugin
            >>> p = SweepTimePlugin()
            >>> lines = p.generate_action_code(1, [], lambda s, i: [])
            >>> any("while next(" in line for line in lines)
            True
            >>> p.clear_on_start = True
            >>> lines2 = p.generate_action_code(1, [], lambda s, i: [])
            >>> any(".clear_data()" in line for line in lines2)
            True
            >>> p.collect_data = True
            >>> lines3 = p.generate_action_code(1, [], lambda s, i: [])
            >>> any(".collect()" in line for line in lines3)
            True
        """
        prefix = "    " * indent
        loop_prefix = "    " * (indent + 1)
        var_name = self.instance_name
        lines: list[str] = []
        if self.clear_on_start:
            lines.append(f"{prefix}{var_name}.clear_data()")
        lines += [
            f"{prefix}{var_name}._begin_sweep()",
            f"{prefix}while next({var_name}):",
            f"{loop_prefix}wait_for_plot_ready()",
            f'{loop_prefix}print(f"{self.state_name}: {{{var_name}.value:.4g}} {self.units}")',
        ]
        for sub_step in sub_steps:
            lines.extend(render_sub_step(sub_step, indent + 1))
        if self.collect_data:
            lines.append(f"{loop_prefix}{var_name}.collect()")
        lines.append("")
        return lines
