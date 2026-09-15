"""Sequence command that repeats another step's generated action code."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QWidget

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.command.base import CommandPlugin


class RunAgainCommand(CommandPlugin):
    """Run an existing sequence step again at the command's current position.

    The selected step keeps its original configuration and instance identity.
    Its normal action code is emitted again, so plugin-type-specific behaviour
    such as scans, measurements, transforms, and commands is preserved.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.target_step = ""
        self.reconnect_and_configure = False
        self._sequence_steps: list = []
        self._rendering = False

    @property
    def name(self) -> str:
        return "Run Again"

    def eligible_steps(self) -> list[BasePlugin]:
        """Return existing sequence steps other than this command instance."""
        if self.sequence_engine is None:
            return []
        return [plugin for plugin in self.sequence_engine.step_plugins() if plugin is not self]

    def _target_plugin(self) -> BasePlugin:
        for plugin in self.eligible_steps():
            if plugin.instance_name == self.target_step:
                return plugin
        if not self.target_step:
            raise RuntimeError("No sequence step is selected to run again.")
        raise RuntimeError(f"Sequence step {self.target_step!r} is not present in the sequence.")

    def bind_sequence_steps(self, steps: list) -> None:
        """Bind the nested sequence tree used during code generation."""
        self._sequence_steps = list(steps)

    def _target_descriptor(self) -> tuple[BasePlugin, list]:
        """Return the selected plugin and its original nested sub-steps."""
        def find(steps: list) -> tuple[BasePlugin, list] | None:
            for step in steps:
                plugin, children = step if isinstance(step, tuple) else (step, [])
                if isinstance(plugin, BasePlugin) and plugin.instance_name == self.target_step:
                    return plugin, children
                if found := find(children):
                    return found
            return None

        found = find(self._sequence_steps)
        if found is None:
            target = self._target_plugin()
            found = (target, [])
        if found[0].disabled:
            raise RuntimeError(f"Sequence step {self.target_step!r} is disabled and cannot run again.")
        return found

    def execute(self) -> None:
        """Reject direct calls; generated code executes the target action directly."""
        raise RuntimeError("Run Again must be executed as part of a generated sequence.")

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return the target-step selector and lifecycle option."""
        return _RunAgainWidget(self, parent)

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Emit the selected step's normal action code at this position."""
        del sub_steps
        if self._rendering:
            raise RuntimeError("Run Again selections form a recursive cycle.")
        target, target_sub_steps = self._target_descriptor()
        prefix = "    " * indent
        lines: list[str] = []
        if self.reconnect_and_configure and target.has_lifecycle:
            lines.extend(
                [
                    f"{prefix}{target.instance_name}.connect()",
                    f"{prefix}{target.instance_name}.configure()",
                ]
            )
        elif target.has_lifecycle:
            lines.append(f"{prefix}{target.instance_name}.require_ready()")
        self._rendering = True
        try:
            lines.extend(target.generate_action_code(indent, target_sub_steps, render_sub_step))
        finally:
            self._rendering = False
        return lines

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data.update(
            {
                "target_step": self.target_step,
                "reconnect_and_configure": self.reconnect_and_configure,
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        self.target_step = str(data.get("target_step", ""))
        self.reconnect_and_configure = bool(data.get("reconnect_and_configure", False))


class _RunAgainWidget(QWidget):
    """Configuration widget bound to a :class:`RunAgainCommand`."""

    def __init__(self, command: RunAgainCommand, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._command = command
        layout = QFormLayout(self)

        self._target_combo = QComboBox(self)
        self._target_combo.setObjectName("run_again_target")
        self._target_combo.currentIndexChanged.connect(self._on_target_changed)
        layout.addRow("Sequence step:", self._target_combo)

        self._reconnect_check = QCheckBox(self)
        self._reconnect_check.setObjectName("reconnect_and_configure")
        self._reconnect_check.setChecked(command.reconnect_and_configure)
        self._reconnect_check.toggled.connect(self._on_reconnect_changed)
        layout.addRow("Reconnect and configure:", self._reconnect_check)

        layout.addRow(
            QLabel(
                "<i>The selected step's current configuration is reused.</i>",
                self,
            )
        )
        self.refresh_step_list()
        if command.sequence_engine is not None:
            command.sequence_engine.namespace_updated.connect(self.refresh_step_list)

    def refresh_step_list(self) -> None:
        """Refresh available steps while preserving the configured target."""
        configured = self._command.target_step
        steps = self._command.eligible_steps()
        self._target_combo.blockSignals(True)
        self._target_combo.clear()
        for plugin in steps:
            self._target_combo.addItem(
                f"{plugin.instance_name} ({plugin.name})",
                plugin.instance_name,
            )
        if not steps:
            self._target_combo.addItem("No other sequence steps available", "")
            self._target_combo.model().item(0).setEnabled(False)
        selected = self._target_combo.findData(configured)
        if selected < 0 and not configured and steps:
            selected = 0
        self._target_combo.setCurrentIndex(selected)
        self._target_combo.blockSignals(False)
        if selected >= 0:
            self._command.target_step = str(self._target_combo.itemData(selected) or "")

    def _on_target_changed(self, index: int) -> None:
        if index >= 0:
            self._command.target_step = str(self._target_combo.itemData(index) or "")

    def _on_reconnect_changed(self, checked: bool) -> None:
        self._command.reconnect_and_configure = checked
