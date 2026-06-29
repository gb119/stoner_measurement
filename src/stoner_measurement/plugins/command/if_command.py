"""IfCommand - conditional sub-sequence command."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qtpy.QtWidgets import QFormLayout, QLineEdit, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.plugins.sequence.base import SequencePlugin


class IfCommand(CommandPlugin, SequencePlugin):
    """Run nested sequence steps only when a Python expression is truthy.

    Use this command as a branch in the sequence tree when only some nested
    actions should run for a point, segment, or step. The expression is
    evaluated against the live sequence namespace, so conditions can reference
    any plugin instance or variable already available to the generated script.
    """

    def __init__(self, parent=None, condition: str = "True") -> None:
        """Initialise the condition command."""
        super().__init__(parent)
        self.condition = condition

    @property
    def name(self) -> str:
        """Human-readable name for the command."""
        return "If"

    def execute(self) -> None:
        """No-op leaf execution.

        ``IfCommand`` is intended to be used as a sequence container. If it is
        accidentally run as a leaf command it has no side effects.
        """

    def execute_sequence(self, sub_steps: list) -> None:
        """Run *sub_steps* when :attr:`condition` evaluates truthy."""
        if bool(self.eval(self.condition)):
            for sub_step in sub_steps:
                sub_step()

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return an ``if`` block containing the rendered sub-steps.

        An empty ``If`` container is treated as a no-op to avoid emitting a
        branch with no executable body into generated scripts.
        """
        prefix = "    " * indent
        condition = self.condition.strip() or "True"
        if not sub_steps:
            self.log.warning(
                "IfCommand %r has no sub-steps; skipping generated code emission.",
                self.instance_name,
            )
            return []
        lines = [f"{prefix}if {condition}:"]
        for sub_step in sub_steps:
            lines.extend(render_sub_step(sub_step, indent + 1))
        lines.append("")
        return lines

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return the condition editor widget."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        condition_edit = QLineEdit(self.condition)
        condition_edit.setToolTip("Python expression evaluated for truthiness before running nested steps.")

        def _apply_condition() -> None:
            self.condition = condition_edit.text().strip() or "True"

        condition_edit.editingFinished.connect(_apply_condition)
        layout.addRow("Condition:", condition_edit)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise the condition command."""
        data = super().to_json()
        data["condition"] = self.condition
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore condition text from serialised state."""
        self.condition = str(data.get("condition", self.condition)).strip() or "True"
