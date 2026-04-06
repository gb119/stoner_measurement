"""Tests for the SequenceEngine."""

from __future__ import annotations

import time

from stoner_measurement.core.sequence_engine import SequenceEngine, _to_var_name
from stoner_measurement.plugins.dummy import DummyPlugin

# ---------------------------------------------------------------------------
# _to_var_name helper
# ---------------------------------------------------------------------------


class TestToVarName:
    def test_lowercase(self):
        assert _to_var_name("Dummy") == "dummy"

    def test_spaces_to_underscores(self):
        assert _to_var_name("My Plugin") == "my_plugin"

    def test_hyphens_to_underscores(self):
        assert _to_var_name("Hall-Effect") == "hall_effect"

    def test_already_lower(self):
        assert _to_var_name("already_lower") == "already_lower"


# ---------------------------------------------------------------------------
# SequenceEngine basic lifecycle
# ---------------------------------------------------------------------------


class TestSequenceEngineLifecycle:
    def test_creates_engine(self, engine):
        assert engine is not None

    def test_not_running_initially(self, engine):
        assert not engine.is_running

    def test_not_paused_initially(self, engine):
        assert not engine.is_paused

    def test_namespace_has_builtins(self, engine):
        ns = engine.namespace
        assert "__builtins__" in ns

    def test_shutdown_is_idempotent(self, qapp):
        eng = SequenceEngine()
        eng.shutdown()
        eng.shutdown()  # second call should not raise


# ---------------------------------------------------------------------------
# Plugin namespace management
# ---------------------------------------------------------------------------


class TestPluginNamespace:
    def test_add_plugin_appears_in_namespace(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        assert "dummy" in engine.namespace
        assert engine.namespace["dummy"] is plugin

    def test_add_plugin_uses_plugin_name(self, engine):
        plugin = DummyPlugin()  # plugin.name == "Dummy"
        engine.add_plugin("my_ep", plugin)
        # var_name derived from plugin.name ("Dummy" → "dummy")
        assert "dummy" in engine.namespace
        # ep alias also added when different
        assert "my_ep" in engine.namespace

    def test_add_plugin_sets_sequence_engine_reference(self, engine):
        plugin = DummyPlugin()
        assert plugin.sequence_engine is None
        engine.add_plugin("dummy", plugin)
        assert plugin.sequence_engine is engine

    def test_remove_plugin_clears_namespace(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        engine.remove_plugin("dummy")
        assert "dummy" not in engine.namespace

    def test_remove_plugin_clears_sequence_engine_reference(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        engine.remove_plugin("dummy")
        assert plugin.sequence_engine is None

    def test_remove_nonexistent_plugin_noop(self, engine):
        engine.remove_plugin("nonexistent")  # should not raise

    def test_engine_namespace_returns_live_dict(self, engine, qapp):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        # Write a value into the engine namespace directly
        engine._namespace["_test_var"] = 99
        assert plugin.engine_namespace.get("_test_var") == 99

    def test_engine_namespace_detached_returns_empty(self):
        from stoner_measurement.plugins.dummy import DummyPlugin as _DP
        plugin = _DP()
        assert plugin.engine_namespace == {}


# ---------------------------------------------------------------------------
# REPL command execution
# ---------------------------------------------------------------------------


class TestReplExecution:
    def test_execute_command_assigns_variable(self, engine, qapp):
        engine.execute_command("_x = 42")
        _wait_for_idle(engine, qapp)
        assert engine.namespace.get("_x") == 42

    def test_execute_command_emits_output(self, engine, qapp):
        received: list[str] = []
        engine.output.connect(lambda s: received.append(s))
        engine.execute_command("print('hello')")
        _wait_for_idle(engine, qapp)
        assert any("hello" in s for s in received)

    def test_execute_command_emits_expression_result(self, engine, qapp):
        received: list[str] = []
        engine.output.connect(lambda s: received.append(s))
        engine.execute_command("1 + 1")
        _wait_for_idle(engine, qapp)
        assert any("2" in s for s in received)

    def test_execute_command_error_emits_error_output(self, engine, qapp):
        errors: list[str] = []
        engine.error_output.connect(lambda s: errors.append(s))
        engine.execute_command("1 / 0")
        _wait_for_idle(engine, qapp)
        assert errors

    def test_execute_command_shares_namespace_with_script(self, engine, qapp):
        engine.execute_command("_seq_var = 99")
        _wait_for_idle(engine, qapp)
        engine.run_script("_seq_result = _seq_var + 1")
        _wait_for_script_finished(engine, qapp)
        assert engine.namespace.get("_seq_result") == 100


# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------


class TestScriptExecution:
    def test_run_script_executes_code(self, engine, qapp):
        engine.run_script("_result = 7 * 6")
        _wait_for_script_finished(engine, qapp)
        assert engine.namespace.get("_result") == 42

    def test_run_script_emits_status_running(self, engine, qapp):
        statuses: list[str] = []
        engine.status_changed.connect(lambda s: statuses.append(s))
        engine.run_script("import time; time.sleep(0.01)")
        _wait_for_script_finished(engine, qapp)
        assert "Running" in statuses

    def test_run_script_emits_status_idle_on_completion(self, engine, qapp):
        statuses: list[str] = []
        engine.status_changed.connect(lambda s: statuses.append(s))
        engine.run_script("pass")
        _wait_for_script_finished(engine, qapp)
        assert "Idle" in statuses

    def test_run_script_emits_script_finished(self, engine, qapp):
        finished: list[bool] = []
        engine.script_finished.connect(lambda: finished.append(True))
        engine.run_script("pass")
        _wait_for_script_finished(engine, qapp)
        assert finished

    def test_run_script_captures_stdout(self, engine, qapp):
        received: list[str] = []
        engine.output.connect(lambda s: received.append(s))
        engine.run_script("print('from script')")
        _wait_for_script_finished(engine, qapp)
        assert any("from script" in s for s in received)

    def test_run_script_syntax_error_emits_error(self, engine, qapp):
        errors: list[str] = []
        statuses: list[str] = []
        engine.error_output.connect(lambda s: errors.append(s))
        engine.status_changed.connect(lambda s: statuses.append(s))
        engine.run_script("def (broken:")
        _wait_for_status(engine, qapp, {"Error", "Idle"})
        assert errors or "Error" in statuses

    def test_run_script_runtime_error_emits_error(self, engine, qapp):
        errors: list[str] = []
        engine.error_output.connect(lambda s: errors.append(s))
        engine.run_script("raise ValueError('oops')")
        _wait_for_status(engine, qapp, {"Error"})
        assert errors

    def test_stop_interrupts_long_script(self, engine, qapp):
        statuses: list[str] = []
        engine.status_changed.connect(lambda s: statuses.append(s))
        engine.run_script("import time\nfor _ in range(1000):\n    time.sleep(0.001)\n")
        time.sleep(0.02)  # let it start
        engine.stop()
        _wait_for_status(engine, qapp, {"Stopped", "Error", "Idle"})
        assert any(s in statuses for s in ("Stopped",))

    def test_empty_script_runs_without_error(self, engine, qapp):
        finished: list[bool] = []
        engine.script_finished.connect(lambda: finished.append(True))
        engine.run_script("")
        _wait_for_script_finished(engine, qapp)
        assert finished


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


class TestCodeGeneration:
    def test_empty_steps_returns_comment(self, engine):
        code = engine.generate_sequence_code([], {})
        assert "No sequence steps" in code

    def test_trace_plugin_generates_lifecycle_api(self, engine):
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code = engine.generate_sequence_code(["dummy"], plugins)
        assert "dummy.connect()" in code
        assert "dummy.configure()" in code
        assert "data = dummy.measure({})" in code
        assert "for channel, x, y in data:" in code
        assert "dummy.disconnect()" in code

    def test_variable_name_in_generated_code(self, engine):
        plugin = DummyPlugin()  # name == "Dummy"
        plugins = {"dummy": plugin}
        code = engine.generate_sequence_code(["dummy"], plugins)
        assert "dummy" in code

    def test_unknown_ep_name_generates_not_found_comment(self, engine):
        code = engine.generate_sequence_code(["nonexistent"], {})
        assert "No sequence steps" in code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIMEOUT = 5.0  # seconds
_POLL = 0.02


def _wait_for_idle(engine: SequenceEngine, qapp, timeout: float = _TIMEOUT) -> None:
    """Wait until the engine has finished processing the most-recently submitted command.

    Uses the ``_completed`` counter on the worker thread so we know the item
    has been fully processed (not just dequeued).
    """
    initial = engine._thread._completed
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if engine._thread._completed > initial:
            # Give Qt a moment to deliver any pending cross-thread signals.
            time.sleep(0.01)
            qapp.processEvents()
            return
        time.sleep(_POLL)


def _wait_for_script_finished(
    engine: SequenceEngine, qapp, timeout: float = _TIMEOUT
) -> None:
    """Wait until the currently running script has finished."""
    initial = engine._thread._completed
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if engine._thread._completed > initial and not engine.is_running:
            # Give Qt a moment to deliver the script_finished signal.
            time.sleep(0.01)
            qapp.processEvents()
            return
        time.sleep(_POLL)


def _wait_for_status(
    engine: SequenceEngine,
    qapp,
    target_statuses: set[str],
    timeout: float = _TIMEOUT,
) -> None:
    """Wait until the engine emits one of the *target_statuses*."""
    received: list[str] = []
    engine.status_changed.connect(lambda s: received.append(s))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if any(s in target_statuses for s in received):
            return
        time.sleep(_POLL)
