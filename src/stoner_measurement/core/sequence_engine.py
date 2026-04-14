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
import linecache
import logging
import queue
import re
import sys
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from io import TextIOBase
from typing import TYPE_CHECKING, Any, Literal, overload

import numpy as np
from PyQt6.QtCore import QObject, QThread, pyqtSignal

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin

#: Logger name used for all sequence-engine and plugin log messages.
SEQUENCE_LOGGER_NAME = "stoner_measurement.sequence"

#: Regex that matches (and removes) the ``# __SM_{n}__`` line-map marker comments
#: embedded in generated sequence code before Black formatting.
_SM_MARKER_STRIP_RE = re.compile(r"\s*#\s*__SM_\d+__")

#: Regex that captures the marker index from a ``# __SM_{n}__`` comment.
_SM_MARKER_FIND_RE = re.compile(r"#\s*__SM_(\d+)__")


class _QtLogHandler(logging.Handler, QObject):
    """A :class:`logging.Handler` that forwards log records via a Qt signal.

    Instances of this handler can be attached to a Python :class:`logging.Logger`
    so that log records are delivered to any Qt slot connected to
    :attr:`record_emitted`.  This is used to route sequence-engine log messages
    to the :class:`~stoner_measurement.ui.log_viewer.LogViewerWindow` without
    blocking the engine thread.

    Args:
        parent (QObject | None):
            Optional Qt parent.

    Keyword Parameters:
        level (int):
            Minimum log level to handle.  Defaults to ``logging.DEBUG``.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> handler = _QtLogHandler()
        >>> handler.level == logging.DEBUG
        True
    """

    record_emitted = pyqtSignal(logging.LogRecord)

    def __init__(self, parent: QObject | None = None, level: int = logging.DEBUG) -> None:
        logging.Handler.__init__(self, level)
        QObject.__init__(self, parent)

    def emit(self, record: logging.LogRecord) -> None:
        """Forward *record* to all connected Qt slots.

        Args:
            record (logging.LogRecord):
                The log record to forward.
        """
        try:
            self.record_emitted.emit(record)
        except RuntimeError:
            # The underlying C++ Qt object may have been deleted (e.g. during
            # application shutdown) before the Python logging atexit handler
            # runs.  Silently ignore in that case.
            pass
        except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            self.handleError(record)


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

    def submit_script(
        self,
        code_str: str,
        customised: bool = True,
        line_map: dict[int, BasePlugin] | None = None,
    ) -> None:
        """Queue a complete Python *code_str* script for execution.

        Args:
            code_str (str):
                A full Python script to compile and execute.

        Keyword Parameters:
            customised (bool):
                ``True`` when the user has manually edited the generated script,
                or when the script was loaded from a file rather than generated
                from the sequence tree.  Controls the exception-reporting
                strategy: customised scripts show a filtered traceback; auto-
                generated scripts report the responsible sequence-step plugin.
            line_map (dict[int, BasePlugin] | None):
                Mapping of 1-based line numbers in the script to the plugin
                instance whose generated code occupies that line.  Only
                meaningful (and used) when *customised* is ``False``.  Pass
                ``None`` to skip plugin attribution.
        """
        self._queue.put(("script", code_str, customised, line_map))

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

            kind = item[0]
            if kind == "quit":
                break
            elif kind == "command":
                self._exec_command(item[1], out_stream, err_stream)
            elif kind == "script":
                # item is ("script", code_str, customised, line_map)
                self._exec_script(item[1], out_stream, err_stream, item[2], item[3])
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

        def _tracer(frame, event, arg):  # noqa: ANN001, ANN202  # pylint: disable=unused-argument
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
        customised: bool = True,
        line_map: dict[int, BasePlugin] | None = None,
    ) -> None:
        """Compile and execute *code_str* in the shared namespace.

        Args:
            code_str (str):
                Python source code to execute.
            out_stream (_SignalStream):
                Stream forwarding stdout to the output signal.
            err_stream (_SignalStream):
                Stream forwarding stderr to the error_output signal.

        Keyword Parameters:
            customised (bool):
                When ``True`` the script has been edited by the user (or loaded
                from a file), so exception tracebacks are filtered to frames
                within the script itself.  When ``False`` the script is auto-
                generated and *line_map* is used to identify the responsible
                sequence-step plugin.
            line_map (dict[int, BasePlugin] | None):
                Mapping of 1-based line numbers to the plugin instance whose
                code occupies that line.  Only consulted when *customised* is
                ``False``.
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
                    exec(compiled, self._namespace)  # noqa: S102  # nosec B102  # pylint: disable=exec-used
            finally:
                sys.settrace(old_tracer)
            self.status_changed.emit("Idle")
            self.script_finished.emit()
        except KeyboardInterrupt:
            self.status_changed.emit("Stopped")
        except SyntaxError as exc:
            self.error_output.emit(f"Syntax error: {exc}")
            self.status_changed.emit("Error")
        except Exception:  # pylint: disable=broad-exception-caught
            exc_type, exc_value, exc_tb = sys.exc_info()
            self._emit_script_error(exc_type, exc_value, exc_tb, code_str, customised, line_map)
            self.status_changed.emit("Error")
        finally:
            self._running_script = False

    def _emit_script_error(
        self,
        exc_type: type,
        exc_value: BaseException,
        exc_tb: object,
        code_str: str,
        customised: bool,
        line_map: dict[int, BasePlugin] | None,
    ) -> None:
        """Format and emit an error arising from script execution.

        The output format depends on whether the script has been customised by
        the user or is still the auto-generated version:

        * **Customised** — emits a traceback filtered to frames inside the
          script (``"<sequence>"``), populated with actual source lines from
          *code_str* so the user can see exactly which line failed.
        * **Auto-generated** — looks up the errant line number in *line_map*
          to identify the responsible sequence-step plugin, and emits a concise
          ``"Error in sequence step: …"`` message.  Falls back to a full
          traceback when attribution is not available (e.g. the error occurred
          in the connect/configure/disconnect infrastructure).

        Args:
            exc_type (type):
                The exception class (from :func:`sys.exc_info`).
            exc_value (BaseException):
                The exception instance.
            exc_tb (object):
                The traceback object (from :func:`sys.exc_info`).
            code_str (str):
                The script source, used to populate :mod:`linecache` for
                customised-script tracebacks.
            customised (bool):
                Whether the script has been user-edited.
            line_map (dict[int, BasePlugin] | None):
                Line-number → plugin mapping for auto-generated scripts.
        """
        if customised:
            # Populate linecache so traceback.format_list can show source lines.
            # Cache entry format: (size, mtime, lines, fullname) — see linecache docs.
            source_lines = code_str.splitlines(True)
            linecache.cache["<sequence>"] = (len(code_str), None, source_lines, "<sequence>")
            try:
                seq_frames = []
                cur_tb = exc_tb
                while cur_tb is not None:
                    if cur_tb.tb_frame.f_code.co_filename == "<sequence>":  # type: ignore[union-attr]
                        seq_frames.append((cur_tb.tb_frame, cur_tb.tb_lineno))  # type: ignore[union-attr]
                    cur_tb = cur_tb.tb_next  # type: ignore[union-attr]

                if seq_frames:
                    stack = traceback.StackSummary.extract(seq_frames, lookup_lines=True)
                    parts: list[str] = ["Traceback (in sequence script):\n"]
                    parts.extend(traceback.format_list(stack))
                    parts.extend(traceback.format_exception_only(exc_type, exc_value))
                    self.error_output.emit("".join(parts).rstrip())
                else:
                    self.error_output.emit(traceback.format_exc().rstrip())
            finally:
                linecache.cache.pop("<sequence>", None)
        else:
            # Auto-generated script — find the innermost <sequence> frame and
            # look up the responsible plugin in the line map.
            responsible_plugin = None
            if line_map:
                seq_lineno: int | None = None
                cur_tb = exc_tb
                while cur_tb is not None:
                    if cur_tb.tb_frame.f_code.co_filename == "<sequence>":  # type: ignore[union-attr]
                        seq_lineno = cur_tb.tb_lineno  # type: ignore[union-attr]
                    cur_tb = cur_tb.tb_next  # type: ignore[union-attr]
                if seq_lineno is not None:
                    responsible_plugin = line_map.get(seq_lineno)

            if responsible_plugin is not None:
                exc_str = "".join(
                    traceback.format_exception_only(exc_type, exc_value)
                ).rstrip()
                msg = (
                    f"Error in sequence step: {responsible_plugin.instance_name}"
                    f" ({responsible_plugin.name})\n{exc_str}"
                )
                self.error_output.emit(msg)
            else:
                self.error_output.emit(traceback.format_exc().rstrip())

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
                    result = eval(source, self._namespace)  # noqa: S307  # nosec B307  # pylint: disable=eval-used
                    if result is not None:
                        out_stream.write(repr(result) + "\n")
                except SyntaxError:
                    exec(source, self._namespace)  # noqa: S102  # nosec B102  # pylint: disable=exec-used
        except Exception:  # pylint: disable=broad-exception-caught
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
        self._log_handler = _QtLogHandler(parent=self)
        logger = logging.getLogger(SEQUENCE_LOGGER_NAME)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(self._log_handler)

        self._namespace = self._make_namespace()
        self._plugin_var_names: dict[str, str] = {}  # ep_name → var_name in namespace

        # Reference to the main plot widget; set by the application after startup.
        # Used by PlotTraceCommand to deliver data directly without manual signal wiring.
        self._plot_widget: Any = None

        self._thread = _EngineThread(namespace=self._namespace, parent=self)
        self._thread.output.connect(self.output)
        self._thread.error_output.connect(self.error_output)
        self._thread.status_changed.connect(self.status_changed)
        self._thread.script_finished.connect(self.script_finished)
        self._thread.start()

    # ------------------------------------------------------------------
    # Plot widget reference
    # ------------------------------------------------------------------

    @property
    def plot_widget(self) -> Any:
        """Reference to the main plot widget for displaying trace data.

        The application sets this attribute after startup so that
        :class:`~stoner_measurement.plugins.command.PlotTraceCommand` instances
        can wire their ``plot_trace`` signal to the widget without requiring
        the application to manually manage signal connections for every step
        plugin.

        Returns:
            (Any):
                The plot widget, or ``None`` if not yet set.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = SequenceEngine()
            >>> engine.plot_widget is None
            True
            >>> engine.shutdown()
        """
        return self._plot_widget

    @plot_widget.setter
    def plot_widget(self, widget: Any) -> None:
        """Set the plot widget reference.

        Args:
            widget (Any):
                The plot widget to attach, or ``None`` to detach.
        """
        self._plot_widget = widget

    # ------------------------------------------------------------------
    # Namespace management
    # ------------------------------------------------------------------

    def _make_namespace(self) -> dict[str, Any]:
        """Create a fresh Python namespace seeded with standard builtins and numpy.

        The namespace is pre-populated with all public numpy functions and
        constants so that sequence scripts and plugin :meth:`eval` calls can
        use numpy mathematical operations (e.g. ``sin``, ``sqrt``, ``linspace``)
        without an explicit ``import numpy`` statement.  ``numpy`` itself is
        also available under the name ``np``.

        A :class:`logging.Logger` instance is also seeded under the name
        ``log`` so that user scripts and plugins can emit log messages via
        ``log.debug(...)``, ``log.info(...)``, etc.

        Returns:
            (dict[str, Any]):
                Initial ``globals`` dict for the interpreter.
        """
        ns: dict[str, Any] = {
            "__builtins__": builtins,
            "__name__": "__sequence__",
            "np": np,
            "numpy": np,
        }
        # Inject all public numpy names so expressions like sin(x) work directly.
        for func_name in np.__all__:
            ns[func_name] = getattr(np, func_name)
        # Seed the logger *after* numpy names so it is not shadowed by numpy.log.
        ns["log"] = logging.getLogger(SEQUENCE_LOGGER_NAME)
        # Master catalogs — populated by _rebuild_data_catalogs() as plugins are registered.
        ns["_traces"] = {}
        ns["_values"] = {}
        return ns

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
            >>> from stoner_measurement.plugins.trace import DummyPlugin
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
        self._rebuild_data_catalogs()

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
            >>> from stoner_measurement.plugins.trace import DummyPlugin
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
        self._rebuild_data_catalogs()

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
            >>> from stoner_measurement.plugins.trace import DummyPlugin
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
        self._rebuild_data_catalogs()

    def _rebuild_data_catalogs(self) -> None:
        """Rebuild the ``_traces`` and ``_values`` namespace entries from all registered plugins.

        Iterates over every plugin currently registered with this engine and merges
        their :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.reported_traces`
        and :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.reported_values`
        dictionaries into two master catalogs which are then stored in the live
        namespace as ``_traces`` and ``_values`` respectively.

        This method is called automatically by :meth:`add_plugin`,
        :meth:`remove_plugin`, and :meth:`rename_plugin` so that the catalogs
        always reflect the current set of registered plugins.
        """
        from stoner_measurement.plugins.base_plugin import BasePlugin

        traces: dict[str, str] = {}
        values: dict[str, str] = {}
        for var_name in self._plugin_var_names.values():
            plugin = self._namespace.get(var_name)
            if isinstance(plugin, BasePlugin):
                traces.update(plugin.reported_traces())
                values.update(plugin.reported_values())
        self._namespace["_traces"] = traces
        self._namespace["_values"] = values

    @property
    def traces_catalog(self) -> dict[str, str]:
        """Master catalog of all trace data produced by registered plugins.

        Returns a snapshot of the ``_traces`` dict in the engine namespace.
        Each entry maps a human-readable name (``"{instance_name}:{channel_name}"``)
        to the Python expression that retrieves the corresponding
        ``(x_array, y_array)`` tuple from the namespace.

        The catalog is rebuilt automatically whenever a plugin is added,
        removed, or renamed.  It is also available directly inside sequence
        scripts and plugin :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`
        calls as the variable ``_traces``.

        Returns:
            (dict[str, str]):
                Snapshot copy of the traces catalog.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> engine = SequenceEngine()
            >>> engine.add_plugin("dummy", DummyPlugin())
            >>> cat = engine.traces_catalog
            >>> "dummy:Dummy" in cat
            True
            >>> cat["dummy:Dummy"]
            "dummy.data['Dummy']"
            >>> engine.shutdown()
        """
        return dict(self._namespace.get("_traces", {}))

    @property
    def values_catalog(self) -> dict[str, str]:
        """Master catalog of all scalar data values produced by registered plugins.

        Returns a snapshot of the ``_values`` dict in the engine namespace.
        Each entry maps a human-readable name (``"{instance_name}:{value_name}"``)
        to the Python expression that retrieves the corresponding scalar value from
        the namespace.

        The catalog is rebuilt automatically whenever a plugin is added,
        removed, or renamed.  It is also available directly inside sequence
        scripts and plugin :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval`
        calls as the variable ``_values``.

        Returns:
            (dict[str, str]):
                Snapshot copy of the values catalog.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_control import StateControlPlugin
            >>> from stoner_measurement.plugins.state_control import CounterPlugin
            >>> engine = SequenceEngine()
            >>> engine.add_plugin("counter", CounterPlugin())
            >>> cat = engine.values_catalog
            >>> any("counter" in k for k in cat)
            True
            >>> engine.shutdown()
        """
        return dict(self._namespace.get("_values", {}))

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

    def run_script(
        self,
        code_str: str,
        customised: bool = True,
        line_map: dict[int, BasePlugin] | None = None,
    ) -> None:
        """Submit *code_str* for execution in the background thread.

        If a script is already running it is allowed to complete (or be stopped
        via :meth:`stop`) before the new script is executed.  To cancel the
        current script call :meth:`stop` before submitting a new one.

        Args:
            code_str (str):
                Python source code to execute.

        Keyword Parameters:
            customised (bool):
                When ``True`` (the default) the script has been user-edited or
                loaded from a file, and exceptions will be reported as a
                traceback filtered to the script's own frames.  When ``False``
                the script is the auto-generated version and exceptions are
                attributed to the responsible sequence-step plugin via
                *line_map*.
            line_map (dict[int, BasePlugin] | None):
                Mapping of 1-based line numbers to the plugin instance
                responsible for that line.  Obtained from
                :meth:`generate_sequence_code` with ``return_line_map=True``.
                Only consulted when *customised* is ``False``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = SequenceEngine()
            >>> engine.run_script("x = 1 + 1")
            >>> engine.shutdown()
        """
        self._thread.submit_script(code_str, customised=customised, line_map=line_map)

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
        logging.getLogger(SEQUENCE_LOGGER_NAME).removeHandler(self._log_handler)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def log_handler(self) -> _QtLogHandler:
        """Qt log handler that forwards sequence log records as a signal.

        Connect :attr:`_QtLogHandler.record_emitted` to a slot that accepts a
        :class:`logging.LogRecord` in order to receive all messages emitted
        via the ``log`` object in the sequence namespace.

        Returns:
            (_QtLogHandler):
                The handler attached to the sequence logger.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> engine = SequenceEngine()
            >>> engine.log_handler is not None
            True
            >>> engine.shutdown()
        """
        return self._log_handler

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

    @overload
    def generate_sequence_code(
        self,
        steps: list,
        plugins: dict[str, BasePlugin],
        *,
        return_line_map: Literal[False] = ...,
    ) -> str: ...

    @overload
    def generate_sequence_code(
        self,
        steps: list,
        plugins: dict[str, BasePlugin],
        *,
        return_line_map: Literal[True],
    ) -> tuple[str, dict[int, BasePlugin]]: ...

    def generate_sequence_code(
        self,
        steps: list,
        plugins: dict[str, BasePlugin],
        *,
        return_line_map: bool = False,
    ) -> str | tuple[str, dict[int, BasePlugin]]:
        """Generate executable Python code from the sequence tree.

        Produces a four-phase script from *steps*:

        0. **Instantiate** — for each unique plugin a conditional block is
           emitted that recreates the plugin from its current configuration
           (using :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.generate_instantiation_code`)
           **only** when the variable is not already present in ``globals()``.
           This makes the generated script self-contained: when it is saved to
           a file and later executed outside the app the plugins will be
           reconstructed from the configuration that was in force at generation
           time, while running the script directly in the app (where the plugins
           are already in the namespace) leaves the live engine instances
           untouched.
        1. **Connect/initialise** — ``connect()`` is called for every unique
           plugin instance found in the tree, in depth-first order.
        2. **Configure** — ``configure()`` is called for every unique plugin
           instance in the same order.
        3. **Action** — the measurement body, wrapped in a single
           ``try/finally`` block.  Each plugin's action is generated by
           calling :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.generate_action_code`
           on the plugin instance, allowing each plugin type to define its own
           code-generation behaviour.

           The ``finally`` block calls ``disconnect()`` on every plugin in
           reverse order so that resources are always released.

        Args:
            steps (list):
                Nested sequence step list from
                :attr:`~stoner_measurement.ui.dock_panel.DockPanel.sequence_steps`.
                Each element is either a plugin instance, a plain entry-point
                name string (legacy), or a ``(plugin_or_ep_name, [sub-steps…])``
                tuple.
            plugins (dict[str, BasePlugin]):
                Mapping of entry-point name → plugin instance used to resolve
                legacy string step entries.

        Keyword Parameters:
            return_line_map (bool):
                When ``True`` the method returns a ``(code, line_map)`` tuple
                instead of just the code string.  *line_map* maps 1-based line
                numbers in the returned script to the plugin instance whose
                generated action code occupies that line.  Only action lines
                (inside the ``try:`` block) are mapped; infrastructure lines
                (instantiate/connect/configure/disconnect) are not included.

        Returns:
            (str):
                Executable Python script representing the sequence tree
                (when *return_line_map* is ``False``).
            (tuple[str, dict[int, BasePlugin]]):
                ``(code, line_map)`` pair when *return_line_map* is ``True``.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> engine = SequenceEngine()
            >>> plugin = DummyPlugin()
            >>> engine.add_plugin("dummy", plugin)
            >>> code = engine.generate_sequence_code(["dummy"], {"dummy": plugin})
            >>> "connect" in code and "configure" in code
            True
            >>> "measure" in code
            True
            >>> "disconnect" in code
            True
            >>> "_BasePlugin.from_json" in code
            True
            >>> code2, lmap = engine.generate_sequence_code(
            ...     ["dummy"], {"dummy": plugin}, return_line_map=True
            ... )
            >>> code2 == code
            True
            >>> any(v is plugin for v in lmap.values())
            True
            >>> engine.shutdown()
        """
        # Import here to avoid circular imports at module level.
        from stoner_measurement.plugins.base_plugin import BasePlugin

        header = [
            "# Sequence script — auto-generated from sequence tree.",
            "# Edit as needed, then click Run.",
            "",
        ]

        if not steps:
            code = "\n".join(header) + "# No sequence steps defined yet.\n"
            return (code, {}) if return_line_map else code

        # ------------------------------------------------------------------
        # Collect all unique plugin instances (depth-first order).
        # ------------------------------------------------------------------

        ordered_plugins: list[BasePlugin] = []
        seen_ids: set[int] = set()

        def _collect_plugins(step: object) -> None:
            """Recursively collect unique plugins from the step tree."""
            if isinstance(step, tuple):
                plugin_or_name, sub_steps = step
            else:
                plugin_or_name = step
                sub_steps = []

            if isinstance(plugin_or_name, BasePlugin):
                plugin: BasePlugin | None = plugin_or_name
            else:
                plugin = plugins.get(plugin_or_name)  # type: ignore[arg-type]

            if plugin is not None and id(plugin) not in seen_ids:
                ordered_plugins.append(plugin)
                seen_ids.add(id(plugin))

            for sub in sub_steps:
                _collect_plugins(sub)

        for step in steps:
            _collect_plugins(step)

        if not ordered_plugins:
            code = "\n".join(header) + "# No sequence steps defined yet.\n"
            return (code, {}) if return_line_map else code

        lines: list[str] = list(header)

        # ------------------------------------------------------------------
        # Phase 0: instantiate plugins from their saved configuration.
        # ------------------------------------------------------------------

        lines.append("# Instantiate plugins from saved configuration (if not already present).")
        lines.append("from stoner_measurement.plugins.base_plugin import BasePlugin as _BasePlugin")
        lines.append("")
        for plugin in ordered_plugins:
            lines.extend(plugin.generate_instantiation_code())

        # ------------------------------------------------------------------
        # Phase 1: connect/initialise all plugins.
        # ------------------------------------------------------------------

        lines.append("# Connect and initialise all plugins.")
        for plugin in ordered_plugins:
            if plugin.has_lifecycle:
                lines.append(f"{plugin.instance_name}.connect()")
        lines.append("")

        # ------------------------------------------------------------------
        # Phase 2: configure all plugins.
        # ------------------------------------------------------------------

        lines.append("# Configure all plugins.")
        for plugin in ordered_plugins:
            if plugin.has_lifecycle:
                lines.append(f"{plugin.instance_name}.configure()")
        lines.append("")

        # ------------------------------------------------------------------
        # Phase 3: action body inside a single try/finally.
        # ------------------------------------------------------------------

        action_lines: list[str] = []
        # Maps action_lines index → plugin that generated the line.
        # Attribution is at the top-level step granularity: all lines produced
        # by a step's _render_action call (including nested sub-steps) are
        # attributed to the outermost plugin for that step.
        _action_line_owner: dict[int, BasePlugin] = {}

        def _render_action(step: object, indent: int) -> list[str]:
            """Resolve *step* to a plugin and delegate to its generate_action_code."""
            prefix = "    " * indent

            if isinstance(step, tuple):
                plugin_or_name, sub_steps = step
            else:
                plugin_or_name = step
                sub_steps = []

            if isinstance(plugin_or_name, BasePlugin):
                plugin = plugin_or_name
            else:
                plugin = plugins.get(plugin_or_name)  # type: ignore[arg-type]

            if plugin is None:
                return [f"{prefix}# {plugin_or_name}: plugin not found"]

            return plugin.generate_action_code(indent, sub_steps, _render_action)

        for step in steps:
            start_idx = len(action_lines)
            action_lines.extend(_render_action(step, 1))
            end_idx = len(action_lines)

            # Determine the plugin for attribution.
            step_plugin_or_name = step[0] if isinstance(step, tuple) else step
            if isinstance(step_plugin_or_name, BasePlugin):
                step_plugin: BasePlugin | None = step_plugin_or_name
            else:
                # step_plugin_or_name is an ep_name string in this branch.
                step_plugin = plugins.get(str(step_plugin_or_name))
            if step_plugin is not None:
                for i in range(start_idx, end_idx):
                    _action_line_owner[i] = step_plugin

        # Trim trailing blank line added by last rendered step.
        while action_lines and action_lines[-1] == "":
            action_lines.pop()

        lines.append("try:")

        if return_line_map:
            # Embed unique markers in action lines so the line_map can be
            # rebuilt after black reformatting.  Markers are inline comments of
            # the form ``# __SM_{idx}__`` appended to the relevant line.  We
            # strip them from the final output after reconstructing the map.
            # The bounds check guards against trailing blank lines that were
            # trimmed from action_lines after _action_line_owner was built.
            for idx in _action_line_owner:
                if idx < len(action_lines) and action_lines[idx].strip():
                    action_lines[idx] = action_lines[idx] + f"  # __SM_{idx}__"

        lines.extend(action_lines)
        lines.append("finally:")
        for plugin in reversed(ordered_plugins):
            if plugin.has_lifecycle:
                lines.append(f"    {plugin.instance_name}.disconnect()")
        lines.append("")

        code = "\n".join(lines)

        # ------------------------------------------------------------------
        # Format the generated code with black for human readability.
        # ------------------------------------------------------------------
        try:
            import black

            code = black.format_str(code, mode=black.Mode(line_length=199))
        except ImportError:
            pass  # black is not installed; fall back to unformatted output.
        except Exception:
            logging.getLogger(SEQUENCE_LOGGER_NAME).warning(
                "black formatting failed; using unformatted code", exc_info=True
            )

        if not return_line_map:
            return code

        # Rebuild the line_map using the embedded markers.  Black preserves
        # inline comments, so markers survive formatting even if line numbers
        # shift.  We then strip the markers from the final code string.
        line_map: dict[int, BasePlugin] = {}
        code_lines = code.splitlines()
        for lineno_0, line_content in enumerate(code_lines):
            m = _SM_MARKER_FIND_RE.search(line_content)
            if m:
                orig_idx = int(m.group(1))
                if orig_idx in _action_line_owner:
                    line_map[lineno_0 + 1] = _action_line_owner[orig_idx]

        code = _SM_MARKER_STRIP_RE.sub("", code)

        return code, line_map
