"""SequencePlugin — abstract base class for plugins that contain sub-sequences.

Any plugin that should be able to act as a container in the sequence tree —
i.e. accept other steps nested beneath it — must inherit from
:class:`SequencePlugin`.  :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
uses this base class so that multi-dimensional scans can be expressed as
arbitrarily deep trees.

The module also provides :class:`TopLevelSequence`, a concrete non-Qt
implementation that acts as the root container for the whole measurement
sequence.  It shares the engine namespace with all nested plugins because the
:class:`~stoner_measurement.core.sequence_engine.SequenceEngine` uses a single
flat ``dict`` as the execution namespace throughout a run.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable

from stoner_measurement.plugins.base_plugin import BasePlugin


class SequencePlugin(BasePlugin):
    """Abstract base class for plugins that act as containers in the sequence tree.

    A :class:`SequencePlugin` can hold nested sub-steps.  The sequence engine
    and the UI tree widget both recognise :class:`SequencePlugin` instances as
    branch nodes that may accept child steps dropped onto them.

    Concrete implementations must supply :attr:`name` (from
    :class:`~stoner_measurement.plugins.base_plugin.BasePlugin`) and
    :meth:`execute_sequence`.

    :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
    inherits from this class to gain sub-sequence container behaviour, whilst
    retaining its full instrument-lifecycle API.

    Attributes:
        sub_steps (list):
            The sub-step descriptors assigned by the sequence engine when
            building an execution plan from the sequence tree.  Each element is
            either a plain entry-point name string (for a leaf sub-step) or a
            ``(ep_name, [sub-steps…])`` tuple (for a nested
            :class:`SequencePlugin` sub-step).  Defaults to an empty list.

    Examples:
        >>> from stoner_measurement.plugins.sequence import SequencePlugin
        >>> issubclass(SequencePlugin, SequencePlugin)
        True
    """

    #: Sub-step descriptors set by the engine before calling execute_sequence.
    _sub_steps: list

    @property
    def sub_steps(self) -> list:
        """Sub-step descriptors assigned by the engine for this node.

        Returns:
            (list):
                List of step descriptors (strings or tuples).

        Examples:
            >>> from stoner_measurement.plugins.sequence import TopLevelSequence
            >>> seq = TopLevelSequence()
            >>> seq.sub_steps
            []
        """
        try:
            return self._sub_steps
        except AttributeError:
            return []

    @sub_steps.setter
    def sub_steps(self, value: list) -> None:
        """Set the sub-step descriptors for this node.

        Args:
            value (list):
                New list of step descriptors.
        """
        self._sub_steps = list(value)

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a sequence container.

        Returns:
            (str):
                Always ``"sequence"``.
        """
        return "sequence"

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return action code lines by transparently rendering all sub-steps.

        A generic :class:`SequencePlugin` container has no action of its own;
        it simply delegates to each nested step at the same indentation level.
        :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`
        overrides this method to wrap sub-steps inside a scan loop.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Raw sub-step descriptors from the sequence tree.
            render_sub_step (Callable):
                Callback ``(step, indent) -> list[str]`` provided by the engine.

        Returns:
            (list[str]):
                Lines for all nested sub-steps at the same indentation level.

        Examples:
            >>> from stoner_measurement.plugins.sequence import TopLevelSequence
            >>> seq = TopLevelSequence()
            >>> lines = seq.generate_action_code(0, [], lambda s, i: [])
            >>> lines
            []
        """
        lines: list[str] = []
        for sub_step in sub_steps:
            lines.extend(render_sub_step(sub_step, indent))
        return lines

    @abstractmethod
    def execute_sequence(self, sub_steps: list) -> None:
        """Execute *sub_steps* at the appropriate point in this plugin's lifecycle.

        The sequence engine calls this method when running a sequence tree.
        Each element of *sub_steps* is a zero-argument callable that, when
        invoked, runs the corresponding nested step (including its own lifecycle
        and any further sub-steps).

        Concrete implementations should call :meth:`connect` and
        :meth:`configure` before running sub-steps, and :meth:`disconnect` in a
        ``finally`` block afterwards.  :class:`StateControlPlugin` subclasses
        will typically also call :meth:`~stoner_measurement.plugins.state_control.StateControlPlugin.ramp_to`
        for each setpoint before invoking the sub-step callables.

        Args:
            sub_steps (list):
                Ordered list of zero-argument callables, one per nested step.

        Examples:
            >>> from stoner_measurement.plugins.sequence import TopLevelSequence
            >>> seq = TopLevelSequence()
            >>> called = []
            >>> seq.execute_sequence([lambda: called.append(1), lambda: called.append(2)])
            >>> called
            [1, 2]
        """


class TopLevelSequence(SequencePlugin):
    """Concrete root container for the entire measurement sequence.

    :class:`TopLevelSequence` represents the invisible top-level node in the
    sequence tree.  Its :meth:`execute_sequence` implementation simply calls
    each sub-step callable in order, making it a transparent pass-through.

    Unlike :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`,
    this class is *pure Python* — it does not inherit from
    :class:`~PyQt6.QtCore.QObject` and therefore has no Qt signals or event-loop
    dependencies.

    The engine namespace is shared automatically because the
    :class:`~stoner_measurement.core.sequence_engine.SequenceEngine` maintains
    a single flat ``dict`` for the duration of a run.

    Attributes:
        name (str):
            Always ``"Sequence"``.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.sequence import TopLevelSequence
        >>> seq = TopLevelSequence()
        >>> seq.plugin_type
        'sequence'
        >>> seq.name
        'Sequence'
        >>> called = []
        >>> seq.execute_sequence([lambda: called.append("a"), lambda: called.append("b")])
        >>> called
        ['a', 'b']
    """

    @property
    def name(self) -> str:
        """Human-readable name for the root sequence container.

        Returns:
            (str):
                Always ``"Sequence"``.
        """
        return "Sequence"

    def execute_sequence(self, sub_steps: list) -> None:
        """Call each sub-step callable in order.

        Args:
            sub_steps (list):
                Ordered list of zero-argument callables.

        Examples:
            >>> from stoner_measurement.plugins.sequence import TopLevelSequence
            >>> seq = TopLevelSequence()
            >>> results = []
            >>> seq.execute_sequence([lambda: results.append(1)])
            >>> results
            [1]
        """
        for sub_step in sub_steps:
            sub_step()
