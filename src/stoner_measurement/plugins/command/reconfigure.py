"""Defer selected sequence instances' setup until this command executes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QCheckBox, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command.base import CommandPlugin


class ReconfigureCommand(CommandPlugin):
    """Connect and configure the checked sequence instances at runtime.

    By default selected instances skip startup setup; disable suppression to
    retain it. Every execution safely reconnects and reapplies configuration,
    including loop iterations.
    Commands without an instrument lifecycle can be selected but need no setup.

    Use this command after changing settings or before a measurement whose
    setup must be delayed. On **General**, tick the required sequence instances
    and choose **Suppress connect and configure at startup** (enabled by
    default). Checked, active targets are reconnected and configured in
    sequence order. A target must reach this setup step before an action that
    requires it to be ready, including inside conditional branches and loops.

    The target's inherited ``delay_configuration`` flag is derived from these
    selections; do not edit or save it independently. Reconnection releases
    the target's previous resources first. Missing targets and setup failures
    stop execution with an error. The command publishes no measurement data.

    Attributes:
        target_names (list[str]):
            Selected sequence-instance names.
        suppress_startup_setup (bool):
            Skip startup setup for selected targets; defaults to True.
        instance_name (str):
            Inherited Python identifier for this instance in the Script tab and
            QtConsole.
        comment (str):
            Inherited optional note displayed beside this step.
        sequence_engine (SequenceEngine | None):
            Inherited owning engine and its live namespace; None while
            detached.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        With an instance named ``reconfigure`` in the sequence, use the
        QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            reconfigure.target_names = ["k6221_dc_iv"]
            reconfigure.suppress_startup_setup = True
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._target_names: list[str] = []
        self._suppress_startup_setup = True
        self._available_plugins: list[BasePlugin] = []
        self._active_plugins: list[BasePlugin] = []
        self._known_names: set[str] = set()
        self._setup_changed: Callable[[], None] | None = None

    @property
    def name(self) -> str:
        return "reconfigure"

    @property
    def target_names(self) -> list[str]:
        """Return the selected instance names."""
        return list(self._target_names)

    @target_names.setter
    def target_names(self, names: list[str]) -> None:
        self._target_names = list(dict.fromkeys(str(name) for name in names))
        self._notify_setup_changed()

    @property
    def suppress_startup_setup(self) -> bool:
        """Whether checked targets skip their normal startup setup."""
        return self._suppress_startup_setup

    @suppress_startup_setup.setter
    def suppress_startup_setup(self, value: bool) -> None:
        self._suppress_startup_setup = bool(value)
        self._notify_setup_changed()

    def _notify_setup_changed(self) -> None:
        if self._setup_changed is not None:
            self._setup_changed()
        elif self.sequence_engine is not None:
            self.sequence_engine.rebuild_delayed_configuration()

    def bind_sequence_plugins(
        self,
        plugins: list[BasePlugin],
        active_plugins: list[BasePlugin] | None = None,
        known_names: list[str] | None = None,
    ) -> None:
        """Bind actual instances, including in standalone generated scripts."""
        self._available_plugins = list(plugins)
        self._active_plugins = list(plugins if active_plugins is None else active_plugins)
        self._known_names = (
            set(known_names)
            if known_names is not None
            else {plugin.instance_name for plugin in plugins}
        )

    def execute(self) -> None:
        """Resolve selected instances, then apply setup in sequence order."""
        missing = set(self._target_names) - self._known_names
        if missing:
            raise RuntimeError(
                f"Reconfigure {self.instance_name!r}: missing sequence instances {sorted(missing)!r}."
            )
        for plugin in self._active_plugins:
            if plugin.instance_name in self._target_names:
                plugin.reconfigure()

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Show a flat, checkable list of sequence instances."""
        if self.sequence_engine is not None:
            self.sequence_engine.rebuild_delayed_configuration()
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        suppress = QCheckBox("Suppress connect and configure at startup", widget)
        suppress.setChecked(self.suppress_startup_setup)
        suppress.toggled.connect(lambda checked: setattr(self, "suppress_startup_setup", checked))
        layout.addWidget(suppress)
        choices = QListWidget(widget)
        choices.setObjectName("reconfigureTargets")
        for plugin in self._available_plugins:
            item = QListWidgetItem(f"{plugin.instance_name} ({plugin.name})", choices)
            item.setData(Qt.ItemDataRole.UserRole, plugin.instance_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if plugin.instance_name in self._target_names
                else Qt.CheckState.Unchecked
            )
        row_height = max(choices.sizeHintForRow(0), choices.fontMetrics().height() + 8)
        choices.setFixedHeight(
            row_height * max(1, min(choices.count(), 12)) + 2 * choices.frameWidth()
        )
        choices.itemChanged.connect(lambda _item: self._set_checked_targets(choices))
        layout.addWidget(choices)
        layout.addStretch(1)
        return widget

    def _set_checked_targets(self, choices: QListWidget) -> None:
        self.target_names = [
            choices.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(choices.count())
            if choices.item(row).checkState() == Qt.CheckState.Checked
        ]

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data["target_names"] = self.target_names
        data["suppress_startup_setup"] = self.suppress_startup_setup
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        self.target_names = data.get("target_names", [])
        self.suppress_startup_setup = bool(data.get("suppress_startup_setup", True))


def rebuild_delayed_configuration(
    steps: list,
    previous_plugins: Sequence[BasePlugin] = (),
    changed: Callable[[], None] | None = None,
) -> list[BasePlugin]:
    """Rebuild setup flags from enabled commands, including nested containers."""
    all_plugins: list[BasePlugin] = []
    active: list[BasePlugin] = []

    def visit(step, parent_enabled=True):
        plugin, children = step if isinstance(step, tuple) else (step, [])
        if not isinstance(plugin, BasePlugin):
            return
        enabled = parent_enabled and not plugin.disabled
        if plugin not in all_plugins:
            all_plugins.append(plugin)
        if enabled and plugin not in active:
            active.append(plugin)
        for child in children:
            visit(child, enabled)

    for step in steps:
        visit(step)
    for plugin in [*previous_plugins, *all_plugins]:
        plugin.delay_configuration = False
        if isinstance(plugin, ReconfigureCommand):
            plugin._setup_changed = None
    selected = set()
    for plugin in all_plugins:
        if isinstance(plugin, ReconfigureCommand):
            plugin.bind_sequence_plugins(all_plugins, active)
            plugin._setup_changed = changed
            if plugin in active and plugin.suppress_startup_setup:
                selected.update(plugin.target_names)
    for plugin in active:
        plugin.delay_configuration = plugin.instance_name in selected
    return all_plugins
