"""Built-in containers for serial and concurrent sub-sequence execution."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor  # pylint: disable=no-name-in-module

from qtpy.QtCore import QObject
from qtpy.QtWidgets import QWidget

from stoner_measurement.plugins.base_plugin import _ABCQObjectMeta
from stoner_measurement.plugins.sequence.base import SequencePlugin
from stoner_measurement.qt_compat import pyqtSignal


class _FunctionSequencePlugin(QObject, SequencePlugin, metaclass=_ABCQObjectMeta):
    """Base for containers whose generated children run in helper functions."""

    instance_name_changed = pyqtSignal(str, str)
    comment_changed = pyqtSignal(str, str)

    #: A helper function is a new Python scope, so loop control cannot target an
    #: enclosing scan or sweep across this container boundary.
    isolates_loop_control = True

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the container's Qt object hierarchy."""
        super().__init__(parent)

    def _on_instance_name_changed(self, old_name: str, new_name: str) -> None:
        """Notify the sequence tree when this instance is renamed."""
        self.instance_name_changed.emit(old_name, new_name)

    def _on_comment_changed(self, old_comment: str, new_comment: str) -> None:
        """Notify the sequence tree when this instance's comment changes."""
        self.comment_changed.emit(old_comment, new_comment)

    @property
    def has_lifecycle(self) -> bool:
        """Sequence-only containers do not own hardware lifecycle operations."""
        return False

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return the General tab followed by the standard optional About tab."""

        def _build_tabs() -> list[tuple[str, QWidget]]:
            tabs = [("General", self._general_config_widget(parent=parent))]
            about_tab = self._make_about_tab()
            if about_tab is not None:
                tabs.append(about_tab)
            return tabs

        return self._get_cached_config_tabs(_build_tabs)

    def _render_function(
        self,
        function_name: str,
        steps: list,
        indent: int,
        render_sub_step: Callable,
    ) -> list[str]:
        """Render *steps* as a zero-argument helper function."""
        body: list[str] = []
        for step in steps:
            body.extend(render_sub_step(step, indent + 1))

        if not any(line.strip() for line in body):
            return []

        prefix = "    " * indent
        return [f"{prefix}def {function_name}():", *body]


class RunSequentiallyPlugin(_FunctionSequencePlugin):
    """Run every nested step in order as one callable sub-sequence.

    Use this sequence container to group several steps into one explicitly
    ordered operation. Its main purpose is to build a multi-step branch beneath
    :class:`RunParallelPlugin`: the parallel container treats the whole
    ``Run Sequentially`` container as one branch, while this plugin runs its
    own children one after another in their displayed sequence order.

    The configuration panel contains a *General* tab for the instance name and
    optional sequence-list comment. There are no plugin-specific settings.
    The *About* tab contains this documentation.

    When sequence code is generated, the nested steps are placed in a helper
    function named from :attr:`instance_name`, for example
    ``_fit_branch_sequence``. :meth:`execute` calls that helper and any other
    supplied child callables in order. It returns only after the final child
    completes. If a child raises an exception, that exception propagates to the
    sequence engine and later children in this container are not run.

    This plugin has no hardware lifecycle, configuration values, or reported
    data outputs of its own. Its children retain their normal plugin behaviour
    and share the sequence engine namespace.

    Attributes:
        instance_name (str):
            Python identifier used for this container in generated sequence
            code. It also provides the template for the helper-function name.
        comment (str):
            Optional note displayed beside this step in the sequence tree.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Group two fitting steps beneath a ``Run Sequentially`` container, then
        place that container directly beneath ``Run Parallel`` to make the two
        fits one ordered parallel branch.

        From the QtConsole, inspect the generated-code identifier::

            run_sequentially.instance_name
            run_sequentially.comment = "Fit both channels in order"

        The callable execution contract can also be inspected directly::

            completed = []
            run_sequentially.execute([
                lambda: completed.append("first"),
                lambda: completed.append("second"),
            ])
    """

    @property
    def name(self) -> str:
        """Return the human-readable plugin name."""
        return "Run Sequentially"

    def execute(self, sub_steps: list[Callable[[], None]]) -> None:
        """Invoke each child callable in list order."""
        for sub_step in sub_steps:
            sub_step()

    def execute_sequence(self, sub_steps: list[Callable[[], None]]) -> None:
        """Implement the standard sequence-container execution contract."""
        self.execute(sub_steps)

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Emit one helper function containing all nested steps, then call it."""
        function_name = f"_{self.instance_name}_sequence"
        lines = self._render_function(
            function_name,
            sub_steps,
            indent,
            render_sub_step,
        )
        if not lines:
            return []

        prefix = "    " * indent
        lines.extend(
            [
                f"{prefix}{self.instance_name}.execute([{function_name}])",
                "",
            ]
        )
        return lines


class RunParallelPlugin(_FunctionSequencePlugin):
    """Run each immediate nested step concurrently and wait for all to finish.

    Use this sequence container when independent operations can run at the same
    time, such as measurements on different instruments or plotting and saving
    the same completed data. Each immediate child is one parallel branch. To
    run several ordered steps within a branch, place them inside a
    :class:`RunSequentiallyPlugin` child.

    The configuration panel contains a *General* tab for the instance name and
    optional sequence-list comment. There are no plugin-specific settings.
    The *About* tab contains this documentation.

    Generated sequence code defines one helper function for each active child.
    Each name combines this container's :attr:`instance_name` with the child
    instance name, for example ``_run_parallel_fit_branch``. Repeated child
    names receive a numeric suffix. :meth:`execute` starts one worker thread
    per helper and blocks until every submitted branch has completed. If a
    branch fails, all other submitted branches are still allowed to finish;
    the exception is then propagated to the sequence engine so the run is
    reported as failed.

    Parallel branches share the sequence engine namespace. Use independent
    instruments or read-only inputs unless the child plugins explicitly
    provide synchronization. Do not place operations with a data dependency
    in separate branches, and do not access the same hardware driver from
    multiple branches unless that driver is documented as thread-safe.

    This plugin has no hardware lifecycle, configuration values, or reported
    data outputs of its own. The contained plugins retain their normal
    lifecycles and outputs.

    Attributes:
        instance_name (str):
            Python identifier used for this container and as the prefix for
            generated parallel-branch helper functions.
        comment (str):
            Optional note displayed beside this step in the sequence tree.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Add two independent measurement plugins directly beneath this
        container to run them concurrently. For two independent fitting
        pipelines, add two ``Run Sequentially`` children and place each
        pipeline's fitting steps beneath its corresponding child.

        From the QtConsole, inspect or clarify the container identity::

            run_parallel.instance_name
            run_parallel.comment = "Fit and save concurrently"

        The blocking execution contract can also be exercised directly::

            run_parallel.execute([first_operation, second_operation])
    """

    @property
    def name(self) -> str:
        """Return the human-readable plugin name."""
        return "Run Parallel"

    def execute(self, sub_steps: list[Callable[[], None]]) -> None:
        """Execute child callables concurrently and block until all complete."""
        if not sub_steps:
            return

        with ThreadPoolExecutor(
            max_workers=len(sub_steps),
            thread_name_prefix=self.instance_name,
        ) as executor:
            futures = [executor.submit(sub_step) for sub_step in sub_steps]
            for future in futures:
                future.result()

    def execute_sequence(self, sub_steps: list[Callable[[], None]]) -> None:
        """Implement the standard sequence-container execution contract."""
        self.execute(sub_steps)

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Emit one helper per child and execute those helpers concurrently."""
        lines: list[str] = []
        function_names: list[str] = []
        used_names: set[str] = set()
        for sub_step in sub_steps:
            plugin_or_name = sub_step[0] if isinstance(sub_step, tuple) else sub_step
            child_name = getattr(plugin_or_name, "instance_name", str(plugin_or_name))
            base_name = f"_{self.instance_name}_{child_name}"
            function_name = base_name
            suffix = 2
            while function_name in used_names:
                function_name = f"{base_name}_{suffix}"
                suffix += 1
            branch_lines = self._render_function(
                function_name,
                [sub_step],
                indent,
                render_sub_step,
            )
            if not branch_lines:
                continue
            used_names.add(function_name)
            lines.extend(branch_lines)
            function_names.append(function_name)

        if not function_names:
            return []

        prefix = "    " * indent
        callables = ", ".join(function_names)
        lines.extend(
            [
                f"{prefix}{self.instance_name}.execute([{callables}])",
                "",
            ]
        )
        return lines
