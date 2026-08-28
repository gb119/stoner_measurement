"""Tests for serial and parallel sequence container plugins."""

from __future__ import annotations

import threading

import pytest
from qtpy.QtWidgets import QLineEdit, QTextBrowser

from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.core.serializer import sequence_from_json, sequence_to_json
from stoner_measurement.plugins.command import BreakIfCommand, WaitCommand
from stoner_measurement.plugins.sequence import (
    RunParallelPlugin,
    RunSequentiallyPlugin,
)
from stoner_measurement.plugins.state_scan import CounterPlugin


def _invoke_in_thread(
    callable_,
    errors: list[BaseException],
) -> tuple[threading.Thread, threading.Event]:
    """Invoke *callable_* in a thread and expose completion and exceptions."""
    completed = threading.Event()

    def _target() -> None:
        try:
            callable_()
        except BaseException as exc:  # noqa: BLE001 - preserve worker failure for assertion
            errors.append(exc)
        finally:
            completed.set()

    thread = threading.Thread(target=_target)
    thread.start()
    return thread, completed


@pytest.mark.parametrize(
    ("plugin_type", "documentation_text"),
    [
        (RunSequentiallyPlugin, "multi-step branch"),
        (RunParallelPlugin, "one worker thread"),
    ],
)
def test_configuration_tabs_are_general_then_about(
    plugin_type,
    documentation_text,
    managed_qt_widget,
):
    """Containers omit empty plugin-specific tabs and keep About last."""
    plugin = plugin_type()
    tabs = plugin.config_tabs()
    for _, widget in tabs:
        managed_qt_widget(widget)

    assert [title for title, _ in tabs] == [
        "General",
        f"{plugin.name} – About",
    ]
    general_widget = tabs[0][1]
    assert len(general_widget.findChildren(QLineEdit)) == 2
    about_widget = tabs[1][1]
    assert isinstance(about_widget, QTextBrowser)
    assert documentation_text in about_widget.toPlainText()


class TestRunSequentiallyPlugin:
    """Behaviour of the serial callable container."""

    def test_execute_sequence_preserves_child_order(self):
        plugin = RunSequentiallyPlugin()
        calls: list[str] = []

        plugin.execute([lambda: calls.append("first"), lambda: calls.append("second")])

        assert calls == ["first", "second"]

    def test_generated_code_defines_and_calls_one_function(self):
        plugin = RunSequentiallyPlugin()
        calls: list[str] = []

        def _render(step, indent):
            return [f"{'    ' * indent}calls.append({step!r})", ""]

        source = "\n".join(plugin.generate_action_code(0, ["a", "b"], _render))
        # Executing the generated source is the behaviour under test; the source is local and deterministic.
        exec(  # noqa: S102  # nosec B102  # pylint: disable=exec-used
            source, {"calls": calls, plugin.instance_name: plugin}
        )

        assert calls == ["a", "b"]
        assert source.count("def ") == 1
        assert "def _run_sequentially_sequence():" in source


class TestRunParallelPlugin:
    """Behaviour of the thread-backed container."""

    def test_children_start_concurrently_and_caller_waits(self):
        plugin = RunParallelPlugin()
        release = threading.Event()
        started = [threading.Event(), threading.Event()]

        def _worker(index: int) -> None:
            started[index].set()
            assert release.wait(2.0)

        errors: list[BaseException] = []
        thread, completed = _invoke_in_thread(
            lambda: plugin.execute([lambda: _worker(0), lambda: _worker(1)]),
            errors,
        )

        assert started[0].wait(2.0)
        assert started[1].wait(2.0)
        assert not completed.is_set()
        release.set()
        thread.join(2.0)

        assert completed.is_set()
        assert not errors

    def test_waits_for_other_children_before_propagating_error(self):
        plugin = RunParallelPlugin()
        release = threading.Event()
        waiting_child_started = threading.Event()
        waiting_child_finished = threading.Event()

        def _fail() -> None:
            raise RuntimeError("parallel branch failed")

        def _wait() -> None:
            waiting_child_started.set()
            assert release.wait(2.0)
            waiting_child_finished.set()

        errors: list[BaseException] = []
        thread, completed = _invoke_in_thread(
            lambda: plugin.execute([_fail, _wait]),
            errors,
        )

        assert waiting_child_started.wait(2.0)
        assert not completed.is_set()
        release.set()
        thread.join(2.0)

        assert completed.is_set()
        assert waiting_child_finished.is_set()
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)

    def test_generated_code_defines_one_function_per_child(self):
        plugin = RunParallelPlugin()
        release = threading.Event()
        started = [threading.Event(), threading.Event()]

        def _render(step, indent):
            return [f"{'    ' * indent}workers[{step}]()", ""]

        def _worker(index: int) -> None:
            started[index].set()
            assert release.wait(2.0)

        source = "\n".join(plugin.generate_action_code(0, [0, 1], _render))
        errors: list[BaseException] = []

        def _execute_source() -> None:
            # Executing the generated source is the behaviour under test.
            exec(  # noqa: S102  # nosec B102  # pylint: disable=exec-used
                source,
                {
                    "workers": [lambda: _worker(0), lambda: _worker(1)],
                    plugin.instance_name: plugin,
                },
            )

        thread, completed = _invoke_in_thread(
            _execute_source,
            errors,
        )

        assert started[0].wait(2.0)
        assert started[1].wait(2.0)
        assert not completed.is_set()
        release.set()
        thread.join(2.0)

        assert completed.is_set()
        assert not errors
        assert source.count("def ") == 2
        assert "def _run_parallel_0():" in source
        assert "def _run_parallel_1():" in source

    def test_duplicate_child_names_receive_unique_function_suffixes(self):
        plugin = RunParallelPlugin()

        def _render(step, indent):
            return [f"{'    ' * indent}pass", ""]

        source = "\n".join(plugin.generate_action_code(0, ["child", "child"], _render))

        assert "def _run_parallel_child():" in source
        assert "def _run_parallel_child_2():" in source


def test_nested_containers_round_trip_through_sequence_json():
    """The established serializer preserves both container types and nesting."""
    parallel = RunParallelPlugin()
    sequential = RunSequentiallyPlugin()
    nested_parallel = RunParallelPlugin()
    nested_parallel.instance_name = "nested_parallel"

    restored = sequence_from_json(
        sequence_to_json([(parallel, [(sequential, [nested_parallel])])])
    )

    restored_parallel, parallel_children = restored[0]
    restored_sequential, sequential_children = parallel_children[0]
    assert isinstance(restored_parallel, RunParallelPlugin)
    assert isinstance(restored_sequential, RunSequentiallyPlugin)
    assert isinstance(sequential_children[0], RunParallelPlugin)
    assert sequential_children[0].instance_name == "nested_parallel"


def test_engine_generated_nested_parallel_sequences_compile(qapp):
    """The complete generator emits valid named helpers for serial branches."""
    engine = SequenceEngine()
    parallel = RunParallelPlugin()
    first_sequence = RunSequentiallyPlugin()
    first_sequence.instance_name = "fit_branch"
    second_sequence = RunSequentiallyPlugin()
    second_sequence.instance_name = "save_branch"
    first_wait = WaitCommand()
    first_wait.instance_name = "fit_wait"
    second_wait = WaitCommand()
    second_wait.instance_name = "save_wait"
    steps = [
        (
            parallel,
            [
                (first_sequence, [first_wait]),
                (second_sequence, [second_wait]),
            ],
        )
    ]

    try:
        source, line_map = engine.generate_sequence_code(
            steps,
            {},
            return_line_map=True,
        )
    finally:
        engine.shutdown()

    compile(source, "<parallel-sequence>", "exec")
    assert line_map
    assert "def _run_parallel_fit_branch():" in source
    assert "def _run_parallel_save_branch():" in source
    assert "def _fit_branch_sequence():" in source
    assert "def _save_branch_sequence():" in source


def test_loop_control_cannot_cross_generated_function_boundary(qapp):
    """Break/continue cannot target an enclosing loop through a helper function."""
    scan = CounterPlugin()
    parallel = RunParallelPlugin()
    break_if = BreakIfCommand()
    steps = [(scan, [(parallel, [break_if])])]

    with pytest.raises(ValueError, match="must be placed inside a scan or sweep loop"):
        break_if.validate_sequence_position(steps)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
