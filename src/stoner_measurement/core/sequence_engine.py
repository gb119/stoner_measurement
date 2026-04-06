"""Sequence engine — runs Python scripts in an isolated namespace with plugin instances.

The engine maintains a persistent background :class:`QThread` that processes
both REPL commands (from the console widget) and full Python scripts (from the
sequence editor).  Plugin instances registered with the
:class:`~stoner_measurement.core.plugin_manager.PluginManager` are injected
into the namespace automatically, so scripts can reference them directly by a
sanitised variable name derived from each plugin's ``name`` property.

Namespace access
----------------
The shared interpreter namespace is a plain Python ``dict`` that persists for
the lifetime of the engine.  It is the ``globals()`` environment in which all
scripts and REPL commands execute.

* **Scripts** read and write namespace variables in the normal Python way —
  any assignment (``x = 1``) or import creates a new key; subsequent scripts
  or REPL commands see the same variable.
* **Plugin lifecycle methods** (``connect``, ``configure``, ``measure``, etc.)
  can access the same namespace via
  :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.engine_namespace`.
  When a plugin is registered with the engine its
  :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.sequence_engine`
  attribute is set to the owning :class:`SequenceEngine` instance, which gives
  the plugin a direct reference to the live ``_namespace`` dict.  For example::

      class MyPlugin(TracePlugin):
          def connect(self) -> None:
              # Read a parameter set by an earlier script step
              sweep_start = self.engine_namespace.get("sweep_start", 0.0)
              self._instrument.set_start(sweep_start)

  The :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.namespace`
  property on :class:`SequenceEngine` (see below) returns a *snapshot copy*
  and is intended for external inspection (e.g. by the UI); plugin code should
  use ``engine_namespace`` instead so that mutations are immediately visible
  to running scripts.
"""

from __future__ import annotations

import builtins
import queue
import sys
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from io import TextIOBase
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, pyqtSignal

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin


class _SignalStream(TextIOBase):
    """A :class:`io.TextIOBase` that forwards :meth:`write` calls to a Qt signal.

    Used to redirect ``sys.stdout`` and ``sys.stderr`` in the worker thread so
    that output from running scripts and REPL commands appears in the console.

    Args:
        signal (pyqtSignal):
            Signal to emit each time text is written; must accept a single
            ``str`` argument.
    """

    def __init__(self, signal: pyqtSignal) -> None:
        super().__init__()
        self._signal = signal

    def write(self, s: str) -> int:
        """Emit *s* via the signal and return its length.

        Args:
            s (str):
                Text to emit.

        Returns:
            (int):
                Number of characters written (always ``len(s)``).
        """
        if s:
            self._signal.emit(s)
        return len(s)

    def flush(self) -> None:
        """No-op flush (required by :class:`io.IOBase` interface)."""


class _EngineThread(QThread):
    """Persistent worker thread that processes queued commands and scripts.

    The thread runs a blocking loop, reading items from an internal
    :class:`queue.Queue`.  Each item is a ``(kind, content)`` tuple where
    *kind* is one of ``"command"``, ``"script"``, or ``"quit"``.

    Signals
    -------
    output(str):
        Emitted for every chunk of text written to ``sys.stdout`` during
        execution.
    error_output(str):
        Emitted for every chunk of text written to ``sys.stderr`` or when
        an unhandled exception occurs.
    status_changed(str):
        Emitted when execution status changes, e.g. ``"Running"``,
        ``"Paused"``, ``"Stopped"``, ``"Idle"``, ``"Error"``.
    script_finished():
        Emitted when a script runs to completion without error.

    Args:
        namespace (dict):
            The shared Python namespace (``globals`` dict) used for all
            ``exec`` / ``eval`` calls.
        parent (QObject | None):
            Optional Qt parent.
    """

    output = pyqtSignal(str)
    error_output = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    script_finished = pyqtSignal()

    def __init__(
        self,
        namespace: dict,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._namespace = namespace
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # starts un-paused (event set = running)
        self._running_script = False
        self._completed: int = 0  # incremented after each command or script finishes

    # ------------------------------------------------------------------
    # Queue submission
    # ------------------------------------------------------------------

    def submit_command(self, source: str) -> None:
        """Queue a single REPL *source* line for execution.

        Args:
            source (str):
                A Python expression or statement to evaluate.
        """
        self._queue.put(("command", source))

    def submit_script(self, code_str: str) -> None:
        """Queue a complete Python *code_str* script for execution.

        Args:
            code_str (str):
                A full Python script to compile and execute.
        """
        self._queue.put(("script", code_str))

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def request_stop(self) -> None:
        """Signal the currently executing script to stop."""
        self._stop_event.set()
        self._pause_event.set()  # unblock if paused

    def pause(self) -> None:
        """Pause script execution at the next Python line boundary."""
        if self._running_script:
            self._pause_event.clear()
            self.status_changed.emit("Paused")

    def resume(self) -> None:
        """Resume a paused script."""
        self._pause_event.set()
        if self._running_script:
            self.status_changed.emit("Running")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Process items from the command queue until a *quit* sentinel arrives."""
        out_stream = _SignalStream(self.output)
        err_stream = _SignalStream(self.error_output)

        while True:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            kind, content = item
            if kind == "quit":
                break
            elif kind == "command":
                self._exec_command(content, out_stream, err_stream)
            elif kind == "script":
                self._exec_script(content, out_stream, err_stream)
            self._completed += 1

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    def _make_tracer(self):
        """Return a ``sys.settrace``-compatible function for pause/stop support.

        The tracer is called by the Python interpreter at every line of code
        executed in the worker thread.  It checks the stop and pause events
        and raises :class:`KeyboardInterrupt` when a stop is requested or
        blocks via :meth:`threading.Event.wait` when paused.

        Returns:
            (callable):
                A trace function suitable for :func:`sys.settrace`.
        """
        stop_event = self._stop_event
        pause_event = self._pause_event

        def _tracer(frame, event, arg):  # noqa: ANN001, ANN202
            """Trace function called by CPython at every line/call/return boundary.

            Called by the Python interpreter for each ``"call"``, ``"line"``,
            ``"return"`` and ``"exception"`` event.  The ``frame`` argument is
            the current stack frame, ``event`` is the event type string, and
            ``arg`` is event-dependent (e.g. the return value for ``"return"``
            events).  Returning the tracer itself re-installs it for subsequent
            events; returning ``None`` would stop tracing.
            """
            if stop_event.is_set():
                raise KeyboardInterrupt("Sequence stopped by user")
            if not pause_event.is_set():
                pause_event.wait()
            if stop_event.is_set():
                raise KeyboardInterrupt("Sequence stopped by user")
            return _tracer

        return _tracer

    def _exec_script(
        self,
        code_str: str,
        out_stream: _SignalStream,
        err_stream: _SignalStream,
    ) -> None:
        """Compile and execute *code_str* in the shared namespace.

        Args:
            code_str (str):
                Python source code to execute.
            out_stream (_SignalStream):
                Stream forwarding stdout to the output signal.
            err_stream (_SignalStream):
                Stream forwarding stderr to the error_output signal.
        """
        self._running_script = True
        self._stop_event.clear()
        self._pause_event.set()
        self.status_changed.emit("Running")

        try:
            compiled = compile(code_str, "<sequence>", "exec")
            old_tracer = sys.gettrace()
            sys.settrace(self._make_tracer())
            try:
                with redirect_stdout(out_stream), redirect_stderr(err_stream):
                    exec(compiled, self._namespace)  # noqa: S102
            finally:
                sys.settrace(old_tracer)
            self.status_changed.emit("Idle")
            self.script_finished.emit()
        except KeyboardInterrupt:
            self.status_changed.emit("Stopped")
        except SyntaxError as exc:
            self.error_output.emit(f"Syntax error: {exc}")
            self.status_changed.emit("Error")
        except Exception:
            self.error_output.emit(traceback.format_exc().rstrip())
            self.status_changed.emit("Error")
        finally:
            self._running_script = False

    def _exec_command(
        self,
        source: str,
        out_stream: _SignalStream,
        err_stream: _SignalStream,
    ) -> None:
        """Execute a single REPL *source* command.

        Tries ``eval`` first (for expressions whose value should be displayed),
        falls back to ``exec`` for statements.

        Args:
            source (str):
                Python expression or statement.
            out_stream (_SignalStream):
                Stream forwarding stdout to the output signal.
            err_stream (_SignalStream):
                Stream forwarding stderr to the error_output signal.
        """
        try:
            with redirect_stdout(out_stream), redirect_stderr(err_stream):
                try:
                    result = eval(source, self._namespace)  # noqa: S307
                    if result is not None:
                        out_stream.write(repr(result) + "\n")
                except SyntaxError:
                    exec(source, self._namespace)  # noqa: S102
        except Exception:
            self.error_output.emit(traceback.format_exc().rstrip())


def _to_var_name(name: str) -> str:
    """Convert a plugin *name* to a valid Python identifier.

    Converts to lowercase and replaces spaces and hyphens with underscores.

    Args:
        name (str):
            Plugin name (e.g. ``"My Plugin"``).

    Returns:
        (str):
            Sanitised identifier (e.g. ``"my_plugin"``).

    Examples:
        >>> _to_var_name("My Plugin")
        'my_plugin'
        >>> _to_var_name("Hall-Effect Sensor")
        'hall_effect_sensor'
    """
    return name.lower().replace(" ", "_").replace("-", "_")


class SequenceEngine(QObject):
    """Python interpreter for sequence execution and interactive REPL.

    The engine maintains a persistent :class:`~PyQt6.QtCore.QThread` that
    processes commands from an internal queue.  Plugin instances are injected
    into the interpreter namespace so that sequence scripts can reference them
    directly by a sanitised variable name.

    Two execution modes are supported:

    * **REPL mode** — single Python expressions or statements submitted via
      :meth:`execute_command`.  Results and errors are emitted as signals.
    * **Script mode** — a complete Python script submitted via
      :meth:`run_script`.  The script is compiled and executed with
      ``sys.settrace`` installed so that :meth:`pause` and :meth:`stop` work
      at Python line boundaries.

    All scripts and REPL commands share the same persistent namespace (a plain
    Python ``dict`` used as ``globals()``).  Variables assigned in one script
    are visible in all subsequent scripts and REPL commands.

    Plugin code can read and write the same namespace via
    :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.engine_namespace`
    — see the module-level documentation for details and an example.

    Signals
    -------
    output(str):
        Text written to ``sys.stdout`` during execution.
    error_output(str):
        Text written to ``sys.stderr`` or unhandled exception tracebacks.
    status_changed(str):
        Execution status: ``"Idle"``, ``"Running"``, ``"Paused"``,
        ``"Stopped"``, or ``"Error"``.
    script_finished():
        Emitted when a script runs to completion without raising an exception.

    Args:
        parent (QObject | None):
            Optional Qt parent.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> engine = SequenceEngine()
        >>> engine.is_running
        False
        >>> engine.shutdown()
    """

    output = pyqtSignal(str)
    error_output = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    script_finished = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._namespace = self._make_namespace()
        self._plugin_var_names: dict[str, str] = {}  # ep_name → var_name in namespace

        self._thread = _EngineThread(namespace=self._namespace, parent=self)
        self._thread.output.connect(self.output)
        self._thread.error_output.connect(self.error_output)
        self._thread.status_changed.connect(self.status_changed)
        self._thread.script_finished.connect(self.script_finished)
        self._thread.start()

    # ------------------------------------------------------------------
    # Namespace management
    # ------------------------------------------------------------------

    def _make_namespace(self) -> dict:
        """Create a fresh Python namespace seeded with standard builtins.

        Returns:
            (dict):
                Initial ``globals`` dict for the interpreter.
        """
        return {
            "__builtins__": builtins,
            "__name__": "__sequence__",
        }

    def add_plugin(self, ep_name: str, plugin: BasePlugin) -> None:
        """Add *plugin* to the interpreter namespace.

        The variable name is taken from ``plugin.instance_name`` (a valid
        Python identifier, defaulting to a sanitised form of ``plugin.name``).
        If the entry-point name *ep_name* produces a different identifier it
        is also added as an alias.

        The plugin's
        :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.sequence_engine`
        attribute is set to this engine so that lifecycle methods
        (``connect``, ``configure``, ``measure``, etc.) can access the shared
        namespace via
        :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.engine_namespace`.

        Args:
            ep_name (str):
                Entry-point name used to register the plugin.
            plugin (BasePlugin):
                Plugin instance to expose in the namespace.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> engine = SequenceEngine()
            >>> plugin = DummyPlugin()
            >>> engine.add_plugin("dummy", plugin)
            >>> "dummy" in engine.namespace
            True
            >>> plugin.sequence_engine is engine
            True
            >>> engine.shutdown()
        """
        var_name = plugin.instance_name
        self._namespace[var_name] = plugin
        self._plugin_var_names[ep_name] = var_name
        ep_var = _to_var_name(ep_name)
        if ep_var != var_name:
            self._namespace[ep_var] = plugin
        plugin.sequence_engine = self

    def remove_plugin(self, ep_name: str) -> None:
        """Remove the plugin registered under *ep_name* from the namespace.

        The plugin's :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.sequence_engine`
        reference is also cleared so that the plugin no longer holds a reference
        to this engine.

        Args:
            ep_name (str):
                Entry-point name passed to :meth:`add_plugin`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> engine = SequenceEngine()
            >>> engine.add_plugin("dummy", DummyPlugin())
            >>> engine.remove_plugin("dummy")
            >>> "dummy" in engine.namespace
            False
            >>> engine.shutdown()
        """
        var_name = self._plugin_var_names.pop(ep_name, None)
        plugin = self._namespace.pop(var_name, None) if var_name is not None else None
        ep_var = _to_var_name(ep_name)
        if plugin is None:
            plugin = self._namespace.pop(ep_var, None)
        else:
            self._namespace.pop(ep_var, None)
        if plugin is not None:
            plugin.sequence_engine = None

    def rename_plugin(self, ep_name: str, new_var_name: str) -> None:
        """Rename the namespace variable for the plugin registered under *ep_name*.

        Removes the old variable name and inserts the plugin under *new_var_name*.
        Does nothing if *ep_name* is not currently registered.

        Args:
            ep_name (str):
                Entry-point name passed to :meth:`add_plugin`.
            new_var_name (str):
                New Python identifier to use in the namespace.

        Raises:
            ValueError:
                If *new_var_name* is already used by a different plugin
                in the namespace.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> engine = SequenceEngine()
            >>> plugin = DummyPlugin()
            >>> engine.add_plugin("dummy", plugin)
            >>> engine.rename_plugin("dummy", "my_dummy")
            >>> "my_dummy" in engine.namespace
            True
            >>> "dummy" in engine.namespace
            False
            >>> engine.shutdown()
        """
        old_var = self._plugin_var_names.get(ep_name)
        if old_var is None:
            return
        # Guard against overwriting a variable belonging to a different plugin.
        if new_var_name != old_var and new_var_name in self._namespace:
            existing = self._namespace[new_var_name]
            current_plugin = self._namespace.get(old_var)
            if existing is not current_plugin:
                raise ValueError(
                    f"Cannot rename plugin {ep_name!r}: "
                    f"{new_var_name!r} is already in use in the namespace."
                )
        plugin = self._namespace.pop(old_var, None)
        if plugin is not None:
            self._namespace[new_var_name] = plugin
            self._plugin_var_names[ep_name] = new_var_name

    @property
    def namespace(self) -> dict:
        """Read-only snapshot of the current interpreter namespace.

        Returns a *copy* of the interpreter ``globals`` dict so that callers
        cannot accidentally mutate the live namespace.  This property is
        intended for external inspection (e.g. the UI displaying available
        variables) and for testing.

        .. note::
            Plugin lifecycle methods should **not** use this property to read
            back values from the namespace, because the copy they receive would
            immediately become stale.  Use
            :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.engine_namespace`
            instead, which returns the *live* dict directly.

        Returns:
            (dict):
                A shallow copy of the interpreter globals.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = SequenceEngine()
            >>> isinstance(engine.namespace, dict)
            True
            >>> engine.shutdown()
        """
        return dict(self._namespace)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_script(self, code_str: str) -> None:
        """Submit *code_str* for execution in the background thread.

        If a script is already running it is allowed to complete (or be stopped
        via :meth:`stop`) before the new script is executed.  To cancel the
        current script call :meth:`stop` before submitting a new one.

        Args:
            code_str (str):
                Python source code to execute.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = SequenceEngine()
            >>> engine.run_script("x = 1 + 1")
            >>> engine.shutdown()
        """
        self._thread.submit_script(code_str)

    def execute_command(self, source: str) -> None:
        """Submit a single REPL *source* line for execution.

        The command is placed on the internal queue and processed in order
        after any currently pending scripts or commands.

        Args:
            source (str):
                Python expression or statement.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = SequenceEngine()
            >>> engine.execute_command("1 + 1")
            >>> engine.shutdown()
        """
        self._thread.submit_command(source)

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def pause(self) -> None:
        """Pause script execution at the next line boundary.

        Has no effect if no script is currently running.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = SequenceEngine()
            >>> engine.pause()  # no-op when idle
            >>> engine.shutdown()
        """
        self._thread.pause()

    def resume(self) -> None:
        """Resume a paused script.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = SequenceEngine()
            >>> engine.resume()  # no-op when not paused
            >>> engine.shutdown()
        """
        self._thread.resume()

    def stop(self) -> None:
        """Request the currently running script to stop.

        The stop is honoured at the next Python line boundary (via
        ``sys.settrace``).  Has no effect if no script is running.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = SequenceEngine()
            >>> engine.stop()  # no-op when idle
            >>> engine.shutdown()
        """
        self._thread.request_stop()

    def shutdown(self) -> None:
        """Cleanly stop the background thread and wait for it to finish.

        Should be called when the application closes.  Sends a quit sentinel
        to the queue, then waits up to 2 seconds for the thread to exit.
        If it does not exit within the timeout, the thread is forcibly
        terminated.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = SequenceEngine()
            >>> engine.shutdown()
        """
        self._thread.request_stop()
        self._thread._queue.put(("quit", None))
        self._thread.wait(2000)
        if self._thread.isRunning():
            self._thread.terminate()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """``True`` while a script is executing.

        Returns:
            (bool):
                ``True`` if the worker thread is currently executing a script.
        """
        return self._thread._running_script

    @property
    def is_paused(self) -> bool:
        """``True`` while execution is paused.

        Returns:
            (bool):
                ``True`` if the pause event is cleared (i.e., execution is
                suspended).
        """
        return not self._thread._pause_event.is_set()

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------

    def generate_code(self, plugins: dict[str, BasePlugin]) -> str:
        """Generate a Python script stub from the registered *plugins*.

        Produces a script that imports nothing extra (plugins are already in
        the namespace) and demonstrates how to call each plugin according to
        its type.

        Args:
            plugins (dict[str, BasePlugin]):
                Mapping of entry-point name → plugin instance.

        Returns:
            (str):
                A Python script with usage stubs for each plugin.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> engine = SequenceEngine()
            >>> engine.add_plugin("dummy", DummyPlugin())
            >>> code = engine.generate_code({"dummy": DummyPlugin()})
            >>> "measure" in code
            True
            >>> "connect" in code and "disconnect" in code
            True
            >>> engine.shutdown()
        """
        # Import here to avoid circular imports at module level.
        from stoner_measurement.plugins.monitor import MonitorPlugin
        from stoner_measurement.plugins.state_control import StateControlPlugin
        from stoner_measurement.plugins.trace import TracePlugin
        from stoner_measurement.plugins.transform import TransformPlugin

        lines = [
            "# Sequence script — auto-generated from loaded plugins.",
            "# Edit as needed, then click Run.",
            "#",
        ]

        if not plugins:
            lines.append("# No plugins loaded yet.")
            return "\n".join(lines) + "\n"

        lines.append("# Available plugin instances:")
        for ep_name, plugin in plugins.items():
            var_name = plugin.instance_name
            lines.append(
                f"#   {var_name:<20} — {type(plugin).__name__} ({plugin.plugin_type})"
            )

        lines.append("")

        for ep_name, plugin in plugins.items():
            var_name = plugin.instance_name
            sep = f"# {'─' * 60}"
            lines.append(sep)
            lines.append(f"# {type(plugin).__name__}: {var_name}")
            lines.append("")

            if isinstance(plugin, TracePlugin):
                lines += [
                    f"{var_name}.connect()",
                    f"{var_name}.configure()",
                    "try:",
                    f"    data = {var_name}.measure({{}})",
                    "    for channel, x, y in data:",
                    '        print(f"{channel}: x={x:.4g}, y={y:.4g}")',
                    "finally:",
                    f"    {var_name}.disconnect()",
                ]
            elif isinstance(plugin, StateControlPlugin):
                state_name = plugin.state_name
                units = plugin.units
                lines += [
                    f"{var_name}.connect()",
                    f"{var_name}.configure()",
                    "try:",
                    f"    # Ramp {state_name} to a target value",
                    f"    {var_name}.ramp_to(0.0)",
                    f'    print(f"{state_name}: {{{var_name}.get_state():.4g}} {units}")',
                    "finally:",
                    f"    {var_name}.disconnect()",
                ]
            elif isinstance(plugin, MonitorPlugin):
                lines += [
                    f"data = {var_name}.read()",
                    "print(data)",
                ]
            elif isinstance(plugin, TransformPlugin):
                lines += [
                    f"# result = {var_name}.run(data)",
                ]

            lines.append("")

        return "\n".join(lines)

    def generate_sequence_code(
        self,
        steps: list,
        plugins: dict[str, BasePlugin],
    ) -> str:
        """Generate executable Python code from the sequence tree.

        Walks *steps* (the nested list returned by
        :attr:`~stoner_measurement.ui.dock_panel.DockPanel.sequence_steps`)
        and emits real Python code that reflects the tree structure — nested
        ``try/finally`` blocks for
        :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`
        container steps with sub-steps indented inside them.

        The generated script is ready to paste into the sequence editor and
        run; it is not a commented stub.

        Args:
            steps (list):
                Nested sequence step list from
                :attr:`~stoner_measurement.ui.dock_panel.DockPanel.sequence_steps`.
                Each element is either a plain entry-point name string or a
                ``(ep_name, [sub-steps…])`` tuple.
            plugins (dict[str, BasePlugin]):
                Mapping of entry-point name → plugin instance.

        Returns:
            (str):
                Executable Python script representing the sequence tree.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> engine = SequenceEngine()
            >>> plugin = DummyPlugin()
            >>> engine.add_plugin("dummy", plugin)
            >>> code = engine.generate_sequence_code(["dummy"], {"dummy": plugin})
            >>> "measure" in code
            True
            >>> engine.shutdown()
        """
        # Import here to avoid circular imports at module level.
        from stoner_measurement.plugins.monitor import MonitorPlugin
        from stoner_measurement.plugins.sequence_plugin import SequencePlugin
        from stoner_measurement.plugins.state_control import StateControlPlugin
        from stoner_measurement.plugins.trace import TracePlugin
        from stoner_measurement.plugins.transform import TransformPlugin

        header = [
            "# Sequence script — auto-generated from sequence tree.",
            "# Edit as needed, then click Run.",
            "",
        ]

        if not steps:
            return "\n".join(header) + "# No sequence steps defined yet.\n"

        body_lines: list[str] = []

        def _render_step(step: str | tuple, indent: int) -> None:
            """Recursively render one step (leaf or branch) at *indent* depth."""
            prefix = "    " * indent

            if isinstance(step, tuple):
                ep_name, sub_steps = step
            else:
                ep_name = step
                sub_steps = []

            plugin = plugins.get(ep_name)
            if plugin is None:
                body_lines.append(f"{prefix}# {ep_name}: plugin not found")
                return

            var_name = plugin.instance_name

            if isinstance(plugin, TracePlugin):
                body_lines += [
                    f"{prefix}{var_name}.connect()",
                    f"{prefix}{var_name}.configure()",
                    f"{prefix}try:",
                    f"{prefix}    data = {var_name}.measure({{}})",
                    f"{prefix}    for channel, x, y in data:",
                    f'{prefix}        print(f"{{channel}}: x={{x:.4g}}, y={{y:.4g}}")',
                    f"{prefix}finally:",
                    f"{prefix}    {var_name}.disconnect()",
                ]

            elif isinstance(plugin, StateControlPlugin):
                state_name = plugin.state_name
                units = plugin.units
                inner_prefix = prefix + "    "
                body_lines += [
                    f"{prefix}{var_name}.connect()",
                    f"{prefix}{var_name}.configure()",
                    f"{prefix}try:",
                    f"{inner_prefix}# Ramp {state_name} to a target value",
                    f"{inner_prefix}{var_name}.ramp_to(0.0)",
                    f'{inner_prefix}print(f"{state_name}: {{{var_name}.get_state():.4g}} {units}")',
                ]
                for sub_step in sub_steps:
                    _render_step(sub_step, indent + 1)
                body_lines += [
                    f"{prefix}finally:",
                    f"{prefix}    {var_name}.disconnect()",
                ]

            elif isinstance(plugin, SequencePlugin):
                # Generic SequencePlugin (not a StateControlPlugin).
                body_lines += [
                    f"{prefix}{var_name}.connect()",
                    f"{prefix}{var_name}.configure()",
                    f"{prefix}try:",
                ]
                for sub_step in sub_steps:
                    _render_step(sub_step, indent + 1)
                body_lines += [
                    f"{prefix}finally:",
                    f"{prefix}    {var_name}.disconnect()",
                ]

            elif isinstance(plugin, MonitorPlugin):
                body_lines += [
                    f"{prefix}data = {var_name}.read()",
                    f"{prefix}print(data)",
                ]

            elif isinstance(plugin, TransformPlugin):
                body_lines.append(f"{prefix}# result = {var_name}.run(data)")

            else:
                body_lines.append(f"{prefix}# {var_name}: unknown plugin type")

            body_lines.append("")

        for step in steps:
            _render_step(step, 0)

        return "\n".join(header + body_lines)
