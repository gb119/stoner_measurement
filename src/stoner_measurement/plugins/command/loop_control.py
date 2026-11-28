"""Conditional ``break`` and ``continue`` commands for scan and sweep loops."""

from __future__ import annotations

from typing import Any

from qtpy.QtWidgets import QFormLayout, QLineEdit, QWidget

from stoner_measurement.core.sequence_hooks import active_iteration_scopes
from stoner_measurement.plugins.command.base import CommandPlugin


def _has_valid_loop_position(command, sequence_steps: list, *, python_control: bool) -> bool:
    """Check every position, respecting Python helper scopes for break and continue."""
    positions = []

    def walk(steps: list, inside_loop: bool = False) -> None:
        for step in steps:
            plugin, children = step if isinstance(step, tuple) else (step, [])
            if plugin is command:
                positions.append(inside_loop)
            inherits_loop = inside_loop and not (
                python_control and getattr(plugin, "isolates_loop_control", False)
            )
            if children:
                walk(children, inherits_loop or bool(getattr(plugin, "is_loop_container", False)))

    walk(sequence_steps)
    return bool(positions) and all(positions)


class _ConditionalLoopControlCommand(CommandPlugin):
    """Base class for guarded loop-control statements in generated scripts."""

    statement: str

    def __init__(self, parent=None, condition: str = "True") -> None:
        """Initialise the command with its Python condition expression."""
        super().__init__(parent)
        self.condition = condition

    def execute(self) -> None:
        """Do nothing when invoked outside generated sequence code."""

    def generate_action_code(self, indent: int, sub_steps: list, render_sub_step) -> list[str]:
        """Generate a guarded ``break`` or ``continue`` statement."""
        prefix = "    " * indent
        condition = self.condition.strip() or "True"
        return [
            f"{prefix}if {condition}:",
            f"{prefix}    {self.statement}",
            "",
        ]

    def validate_sequence_position(self, sequence_steps: list) -> None:
        """Raise when any occurrence of this command is outside a loop container."""
        if not _has_valid_loop_position(self, sequence_steps, python_control=True):
            raise ValueError(f"{self.name} must be placed inside a scan or sweep loop.")

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return an editor for the Python condition expression."""
        widget = QWidget(parent)
        layout = QFormLayout(widget)
        condition_edit = QLineEdit(self.condition)
        condition_edit.setToolTip(
            f"Python expression evaluated before executing {self.statement}."
        )

        def _apply_condition() -> None:
            self.condition = condition_edit.text().strip() or "True"

        condition_edit.editingFinished.connect(_apply_condition)
        layout.addRow("Condition:", condition_edit)
        return widget

    def to_json(self) -> dict[str, Any]:
        """Serialise the condition expression."""
        data = super().to_json()
        data["condition"] = self.condition
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore the condition expression."""
        self.condition = str(data.get("condition", self.condition)).strip() or "True"


class BreakIfCommand(_ConditionalLoopControlCommand):
    """End the containing scan or sweep when a condition becomes true.

    Use this command inside a scan or sweep when the remaining points should
    be abandoned after a runtime condition is met. The condition is evaluated
    in the live sequence namespace at the command's position in each loop
    iteration. A true result executes Python's ``break`` statement, ending the
    nearest containing scan or sweep; a false result lets the sequence
    continue normally.

    The configuration tab contains the standard instance-name field and a
    **Condition** editor. Enter a Python expression that uses values already
    available in the sequence namespace, such as a measured output or a
    controller state. A blank condition is stored as ``True``. This command
    must remain inside a scan or sweep in the sequence tree because ``break``
    is not valid at the top level.

    The command emits its conditional loop-control statement when the
    sequence script is generated. Calling :meth:`execute` directly does
    nothing because loop control can only be applied by the generated code.

    Attributes:
        condition (str):
            Python expression evaluated before deciding whether to end the
            current scan or sweep. Defaults to ``"True"``.
        statement (str):
            Loop-control statement emitted into generated code. Always
            ``"break"`` for this plugin.
        instance_name (str):
            Inherited sequence-instance name. Defaults to ``"break_if"``.
        sequence_engine (SequenceEngine | None):
            Inherited reference to the sequence engine and its live
            namespace.
        comment (str):
            Inherited optional note displayed beside this step.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.
        condition (str):
            Initial Python condition expression. Defaults to ``"True"``.

    Examples:
        With an instance named ``break_if`` in the sequence, use the
        QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            break_if.condition = "counter.value > maximum_value"
    """

    _DEFAULT_INSTANCE = "break_if"
    statement = "break"

    @property
    def name(self) -> str:
        """Return the command's human-readable name."""
        return "Break If"


class ContinueIfCommand(_ConditionalLoopControlCommand):
    """Skip the rest of a scan or sweep iteration when a condition is true.

    Use this command inside a scan or sweep when later steps in selected loop
    iterations should be skipped without ending the whole scan. The condition
    is evaluated in the live sequence namespace at the command's position in
    each iteration. A true result executes Python's ``continue`` statement,
    moving directly to the next point of the nearest containing scan or sweep;
    a false result lets the remaining steps run normally.

    The configuration tab contains the standard instance-name field and a
    **Condition** editor. Enter a Python expression that uses values already
    available in the sequence namespace, such as a measured output or a
    controller state. A blank condition is stored as ``True``. This command
    must remain inside a scan or sweep in the sequence tree because
    ``continue`` is not valid at the top level.

    The command emits its conditional loop-control statement when the
    sequence script is generated. Calling :meth:`execute` directly does
    nothing because loop control can only be applied by the generated code.

    Attributes:
        condition (str):
            Python expression evaluated before deciding whether to skip the
            rest of the current iteration. Defaults to ``"True"``.
        statement (str):
            Loop-control statement emitted into generated code. Always
            ``"continue"`` for this plugin.
        instance_name (str):
            Inherited sequence-instance name. Defaults to ``"continue_if"``.
        sequence_engine (SequenceEngine | None):
            Inherited reference to the sequence engine and its live
            namespace.
        comment (str):
            Inherited optional note displayed beside this step.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.
        condition (str):
            Initial Python condition expression. Defaults to ``"True"``.

    Examples:
        With an instance named ``continue_if`` in the sequence, use the
        QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            continue_if.condition = "counter.value < minimum_value"
    """

    _DEFAULT_INSTANCE = "continue_if"
    statement = "continue"

    @property
    def name(self) -> str:
        """Return the command's human-readable name."""
        return "Continue If"


class SkipCollectionCommand(CommandPlugin):
    """Clear the measurement flag for the current scan or sweep point.

    Place **Skip Collection** inside the scan or sweep. Wrap it in an **If**
    step to reject a point based on a measurement or another runtime condition.
    Subsequent steps see the cleared flag immediately. The next point receives
    its own flag from the scan or sweep generator.

    The **General** tab sets the instance name and comment.

    Attributes:
        instance_name (str): Inherited script and QtConsole identifier.
        comment (str): Inherited note displayed beside the step.

    Examples:
        In the Script tab, an instance named ``skip_collection`` can be called
        after evaluating a point inside the loop::

            if measured_signal < minimum_signal:
                skip_collection()
    """

    @property
    def name(self) -> str:
        """Return the command's human-readable name."""
        return "Skip Collection"

    def validate_sequence_position(self, sequence_steps: list) -> None:
        """Require an enclosing scan or sweep, including through helper containers."""
        if not _has_valid_loop_position(self, sequence_steps, python_control=False):
            raise ValueError(f"{self.name} must be placed inside a scan or sweep loop.")

    def execute(self) -> None:
        """Clear the live flag of the innermost active point."""
        from stoner_measurement.plugins.state.base import StatePlugin

        scopes = active_iteration_scopes()
        if not scopes or not isinstance(scopes[0].owner, StatePlugin):
            raise RuntimeError(f"{self.name} requires an active scan or sweep point.")
        scopes[0].owner.meas_flag = False
