"""Tests for the SequenceEngine."""

from __future__ import annotations

import time

from stoner_measurement.core.sequence_engine import SequenceEngine, _to_var_name
from stoner_measurement.plugins.trace import DummyPlugin

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

    def test_namespace_has_numpy(self, engine):
        ns = engine.namespace
        assert "np" in ns

    def test_namespace_has_numpy_functions(self, engine):
        ns = engine.namespace
        assert "sin" in ns
        assert "sqrt" in ns
        assert "linspace" in ns

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
        from stoner_measurement.plugins.trace import DummyPlugin as _DP
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

    def test_print_still_captured_after_script_using_plugin_eval(self, engine, qapp):
        """print() output must arrive via engine.output even after running a script
        that calls plugin.eval().

        Regression test for the bug where asteval.Interpreter.__init__ permanently
        injected its own ``_printer`` into the engine namespace, causing all
        subsequent print() calls to write to the terminal instead of the console.
        """
        from stoner_measurement.plugins.trace import DummyPlugin

        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)

        # Generate and run the sequence script (DummyPlugin.measure() calls eval).
        code = engine.generate_sequence_code(["dummy"], {"dummy": plugin})
        engine.run_script(code, customised=False)
        _wait_for_script_finished(engine, qapp)

        # After the generated script, print() via execute_command must still be
        # captured by the engine's output signal.
        received: list[str] = []
        engine.output.connect(lambda s: received.append(s))
        engine.execute_command("print('hello_after_eval')")
        _wait_for_idle(engine, qapp)

        assert any("hello_after_eval" in s for s in received), (
            "print() output was not captured after running a script that used plugin.eval(). "
            "Likely asteval.Interpreter polluted the engine namespace with its own _printer."
        )


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
        assert "dummy.data = dummy.measure({})" in code
        assert "for channel" not in code
        assert "dummy.disconnect()" in code

    def test_variable_name_in_generated_code(self, engine):
        plugin = DummyPlugin()  # name == "Dummy"
        plugins = {"dummy": plugin}
        code = engine.generate_sequence_code(["dummy"], plugins)
        assert "dummy" in code

    def test_unknown_ep_name_produces_no_steps_comment(self, engine):
        code = engine.generate_sequence_code(["nonexistent"], {})
        assert "No sequence steps" in code

    def test_return_line_map_false_returns_string(self, engine):
        plugin = DummyPlugin()
        result = engine.generate_sequence_code(["dummy"], {"dummy": plugin})
        assert isinstance(result, str)

    def test_return_line_map_true_returns_tuple(self, engine):
        plugin = DummyPlugin()
        result = engine.generate_sequence_code(
            ["dummy"], {"dummy": plugin}, return_line_map=True
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        code, line_map = result
        assert isinstance(code, str)
        assert isinstance(line_map, dict)

    def test_line_map_code_matches_plain_code(self, engine):
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code_plain = engine.generate_sequence_code(["dummy"], plugins)
        code_mapped, _ = engine.generate_sequence_code(
            ["dummy"], plugins, return_line_map=True
        )
        assert code_plain == code_mapped

    def test_line_map_covers_action_lines(self, engine):
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code, line_map = engine.generate_sequence_code(
            ["dummy"], plugins, return_line_map=True
        )
        assert line_map, "line_map should not be empty for a non-empty sequence"
        # Every entry in the map should point to the dummy plugin.
        assert all(v is plugin for v in line_map.values())

    def test_line_map_keys_are_valid_line_numbers(self, engine):
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code, line_map = engine.generate_sequence_code(
            ["dummy"], plugins, return_line_map=True
        )
        source_lines = code.splitlines()
        total_lines = len(source_lines)
        for lineno in line_map:
            assert 1 <= lineno <= total_lines, f"Line {lineno} out of range 1..{total_lines}"

    def test_line_map_lines_are_action_code(self, engine):
        """Lines in the map should be inside the try: block (action code)."""
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code, line_map = engine.generate_sequence_code(
            ["dummy"], plugins, return_line_map=True
        )
        source_lines = code.splitlines()
        for lineno in line_map:
            line = source_lines[lineno - 1]
            assert line.startswith("    "), (
                f"Action line {lineno} should be indented: {line!r}"
            )

    def test_line_map_empty_for_empty_steps(self, engine):
        _, line_map = engine.generate_sequence_code([], {}, return_line_map=True)
        assert line_map == {}

    def test_line_map_empty_for_unknown_plugin(self, engine):
        _, line_map = engine.generate_sequence_code(
            ["nonexistent"], {}, return_line_map=True
        )
        assert line_map == {}

    def test_line_map_two_steps_both_attributed(self, engine):
        plugin_a = DummyPlugin()
        plugin_a._instance_name = "alpha"
        plugin_b = DummyPlugin()
        plugin_b._instance_name = "beta"
        plugins = {"alpha": plugin_a, "beta": plugin_b}
        code, line_map = engine.generate_sequence_code(
            ["alpha", "beta"], plugins, return_line_map=True
        )
        attributed_plugins = set(line_map.values())
        assert plugin_a in attributed_plugins
        assert plugin_b in attributed_plugins

    def test_phase0_instantiation_imports_emitted(self, engine):
        """Phase 0 should include the BasePlugin import."""
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code = engine.generate_sequence_code(["dummy"], plugins)
        assert "import json as _json" not in code
        assert "from stoner_measurement.plugins.base_plugin import BasePlugin as _BasePlugin" in code

    def test_phase0_instantiation_conditional_guard(self, engine):
        """Phase 0 should use a globals() guard for each plugin."""
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code = engine.generate_sequence_code(["dummy"], plugins)
        assert 'if "dummy" not in globals():' in code

    def test_phase0_instantiation_uses_from_json(self, engine):
        """Phase 0 should reconstruct the plugin via _BasePlugin.from_json."""
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code = engine.generate_sequence_code(["dummy"], plugins)
        assert "_BasePlugin.from_json" in code
        assert "_json.loads" not in code

    def test_phase0_instantiation_embeds_class_path(self, engine):
        """Phase 0 JSON payload must include the plugin class path."""
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code = engine.generate_sequence_code(["dummy"], plugins)
        # The class path comes from BasePlugin.to_json() "class" key.
        cls = type(plugin)
        expected_class = f"{cls.__module__}:{cls.__qualname__}"
        assert expected_class in code

    def test_phase0_precedes_connect_phase(self, engine):
        """The instantiation block must appear before the connect() calls."""
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code = engine.generate_sequence_code(["dummy"], plugins)
        instantiation_pos = code.index('if "dummy" not in globals():')
        connect_pos = code.index("dummy.connect()")
        assert instantiation_pos < connect_pos

    def test_phase0_multiple_plugins_each_have_guard(self, engine):
        """Every plugin in the sequence should have its own instantiation guard."""
        plugin_a = DummyPlugin()
        plugin_a._instance_name = "alpha"
        plugin_b = DummyPlugin()
        plugin_b._instance_name = "beta"
        plugins = {"alpha": plugin_a, "beta": plugin_b}
        code = engine.generate_sequence_code(["alpha", "beta"], plugins)
        assert 'if "alpha" not in globals():' in code
        assert 'if "beta" not in globals():' in code

    def test_phase0_not_emitted_for_empty_steps(self, engine):
        """The instantiation block should not appear when there are no steps."""
        code = engine.generate_sequence_code([], {})
        assert "_BasePlugin.from_json" not in code


# ---------------------------------------------------------------------------
# Exception reporting
# ---------------------------------------------------------------------------


class TestExceptionReporting:
    def test_customised_script_error_shows_sequence_traceback(self, engine, qapp):
        """Customised-script exceptions should show a filtered traceback header."""
        errors: list[str] = []
        engine.error_output.connect(lambda s: errors.append(s))
        engine.run_script("raise ValueError('test error')", customised=True)
        _wait_for_status(engine, qapp, {"Error"})
        assert errors, "error_output should have been emitted"
        combined = "\n".join(errors)
        assert "Traceback (in sequence script):" in combined
        assert "ValueError" in combined
        assert "test error" in combined

    def test_customised_script_error_contains_source_line(self, engine, qapp):
        """Customised-script traceback should include the errant source line."""
        errors: list[str] = []
        engine.error_output.connect(lambda s: errors.append(s))
        script = "x = 1\nraise RuntimeError('boom')\ny = 2\n"
        engine.run_script(script, customised=True)
        _wait_for_status(engine, qapp, {"Error"})
        combined = "\n".join(errors)
        # The traceback should reference the script filename
        assert "<sequence>" in combined
        assert "boom" in combined

    def test_customised_script_no_internal_engine_frames(self, engine, qapp):
        """Customised-script tracebacks should not include engine module frames."""
        errors: list[str] = []
        engine.error_output.connect(lambda s: errors.append(s))
        engine.run_script("raise ValueError('oops')", customised=True)
        _wait_for_status(engine, qapp, {"Error"})
        combined = "\n".join(errors)
        assert "sequence_engine.py" not in combined

    def test_non_customised_script_reports_plugin_name(self, engine, qapp):
        """Auto-generated script exceptions should name the responsible plugin."""
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        plugins = {"dummy": plugin}
        # Build a script that will raise an error at a known action line.
        code, line_map = engine.generate_sequence_code(
            ["dummy"], plugins, return_line_map=True
        )
        # Replace the action body with a line that raises so we can test attribution.
        # Instead, inject a script with the correct structure but a raising action.
        # We craft a minimal script that mirrors what the engine generates but raises.
        action_lineno = min(line_map)  # first mapped line
        source_lines = code.splitlines()
        # Replace the first action line with a raise statement.
        source_lines[action_lineno - 1] = "    raise RuntimeError('plugin error')"
        bad_script = "\n".join(source_lines)

        errors: list[str] = []
        engine.error_output.connect(lambda s: errors.append(s))
        engine.run_script(bad_script, customised=False, line_map=line_map)
        _wait_for_status(engine, qapp, {"Error"})
        combined = "\n".join(errors)
        assert "Error in sequence step:" in combined
        assert plugin.instance_name in combined
        assert "RuntimeError" in combined

    def test_non_customised_script_no_line_map_falls_back(self, engine, qapp):
        """Without a line_map, auto-generated errors emit a regular traceback."""
        errors: list[str] = []
        engine.error_output.connect(lambda s: errors.append(s))
        engine.run_script("raise ValueError('fallback')", customised=False, line_map=None)
        _wait_for_status(engine, qapp, {"Error"})
        combined = "\n".join(errors)
        assert "ValueError" in combined

    def test_non_customised_infra_error_falls_back_to_traceback(self, engine, qapp):
        """Errors outside action lines (e.g. on line 1) should emit a full traceback."""
        plugin = DummyPlugin()
        plugins = {"dummy": plugin}
        code, line_map = engine.generate_sequence_code(
            ["dummy"], plugins, return_line_map=True
        )
        # Replace line 1 (header comment) with a raise — not in line_map.
        source_lines = code.splitlines()
        source_lines[0] = "raise RuntimeError('infra error')"
        bad_script = "\n".join(source_lines)

        errors: list[str] = []
        engine.error_output.connect(lambda s: errors.append(s))
        engine.run_script(bad_script, customised=False, line_map=line_map)
        _wait_for_status(engine, qapp, {"Error"})
        combined = "\n".join(errors)
        # Falls back to full traceback — line_map has no entry for line 1
        assert "RuntimeError" in combined


# ---------------------------------------------------------------------------
# Data catalogs (_traces / _values)
# ---------------------------------------------------------------------------


class TestDataCatalogs:
    def test_traces_catalog_empty_before_plugins(self, engine):
        assert engine.traces_catalog == {}

    def test_values_catalog_empty_before_plugins(self, engine):
        assert engine.values_catalog == {}

    def test_namespace_has_traces_key(self, engine):
        assert "_traces" in engine.namespace

    def test_namespace_has_values_key(self, engine):
        assert "_values" in engine.namespace

    def test_add_trace_plugin_populates_traces_catalog(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        cat = engine.traces_catalog
        assert len(cat) > 0

    def test_trace_catalog_key_format(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        cat = engine.traces_catalog
        assert "dummy:Dummy" in cat

    def test_trace_catalog_value_is_expression(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        assert engine.traces_catalog["dummy:Dummy"] == "dummy.data['Dummy']"

    def test_remove_plugin_clears_traces_catalog(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        engine.remove_plugin("dummy")
        assert engine.traces_catalog == {}

    def test_rename_plugin_updates_traces_catalog(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        plugin._instance_name = "my_dummy"
        engine.rename_plugin("dummy", "my_dummy")
        cat = engine.traces_catalog
        assert "my_dummy:Dummy" in cat
        assert "dummy:Dummy" not in cat

    def test_traces_catalog_in_namespace_is_live(self, engine):
        plugin = DummyPlugin()
        engine.add_plugin("dummy", plugin)
        assert engine._namespace["_traces"] == engine.traces_catalog

    def test_values_catalog_populated_by_state_plugin(self, engine):
        from stoner_measurement.plugins.state_control import CounterPlugin
        plugin = CounterPlugin()
        engine.add_plugin("counter", plugin)
        cat = engine.values_catalog
        assert len(cat) > 0
        assert any("counter" in k for k in cat)

    def test_multiple_plugins_merged_in_catalogs(self, engine):
        from stoner_measurement.plugins.state_control import CounterPlugin
        trace_plugin = DummyPlugin()
        state_plugin = CounterPlugin()
        engine.add_plugin("dummy", trace_plugin)
        engine.add_plugin("counter", state_plugin)
        assert len(engine.traces_catalog) > 0
        assert len(engine.values_catalog) > 0

    def test_plot_widget_initially_none(self, engine):
        """plot_widget is None before being set by the application."""
        assert engine.plot_widget is None

    def test_plot_widget_can_be_set_and_read(self, engine):
        """plot_widget stores the reference assigned to it."""
        from unittest.mock import MagicMock

        mock_pw = MagicMock()
        engine.plot_widget = mock_pw
        assert engine.plot_widget is mock_pw

    def test_plot_widget_can_be_cleared(self, engine):
        """plot_widget can be reset to None."""
        from unittest.mock import MagicMock

        engine.plot_widget = MagicMock()
        engine.plot_widget = None
        assert engine.plot_widget is None




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
