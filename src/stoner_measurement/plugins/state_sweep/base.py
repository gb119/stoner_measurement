"""Base class for state-sweep plugins."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar

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

        header_widget = QWidget()
        header_widget.setLayout(header_form)
        layout.addWidget(header_widget)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        sweep_container = _StateSweepTabContainer(plugin, parent=self)
        layout.addWidget(sweep_container)

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
    """Base class for plugins that run a sub-sequence inside a sweep loop."""

    _sweep_generator_class: ClassVar[type[BaseSweepGenerator]] = MonitorAndFilterSweepGenerator
    _sweep_generator_classes: ClassVar[list[type[BaseSweepGenerator]]] = [
        MonitorAndFilterSweepGenerator,
        MultiSegmentRampSweepGenerator,
    ]

    sweep_generator_changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.sweep_generator: BaseSweepGenerator = self._sweep_generator_class(state_sweep=self, parent=self)
        self.ix = -1

    @property
    def plugin_type(self) -> str:
        return "state_sweep"

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data["sweep_generator"] = self.sweep_generator.to_json()
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        super()._restore_from_json(data)
        if "sweep_generator" in data:
            self.sweep_generator = BaseSweepGenerator.from_json(data["sweep_generator"], state_sweep=self, parent=self)
            self.sweep_generator_changed.emit()

    def set_sweep_generator_class(self, cls: type[BaseSweepGenerator]) -> None:
        if isinstance(self.sweep_generator, cls):
            return
        self.sweep_generator = cls(state_sweep=self, parent=self)
        self.sweep_generator_changed.emit()

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
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
        return None

    def _begin_sweep(self) -> None:
        self.sweep_generator.reset()

    def __iter__(self) -> StateSweepPlugin:
        self._begin_sweep()
        return self

    def __next__(self) -> bool:
        try:
            self.ix, self.value, self.stage, self.meas_flag = next(self.sweep_generator)
            return True
        except StopIteration:
            self.meas_flag = False
            return False

    def execute_sequence(self, sub_steps: list) -> None:
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

    @property
    @abstractmethod
    def state_name(self) -> str:
        """Human-readable name for the swept state."""

    @property
    @abstractmethod
    def units(self) -> str:
        """Physical units for the swept state."""

    def set_state(self, value: float) -> None:
        """Set the current state value (NOP default)."""

    def get_state(self) -> float:
        """Read the current state value."""
        return float(self.value)

    def set_target(self, value: float) -> None:
        """Set the active target value (NOP default)."""

    def set_rate(self, value: float) -> None:
        """Set the active sweep rate (NOP default)."""

    def is_at_target(self) -> bool:
        """Return whether the target is reached (always ``True`` by default)."""
        return True

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
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
