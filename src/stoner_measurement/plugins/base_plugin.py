"""Abstract base class for all measurement plugins.

A plugin must:

1. Inherit from :class:`BasePlugin`.
2. Override :attr:`name` to provide a unique string identifier.
3. Optionally override :meth:`config_widget` to supply a configuration
   :class:`~PyQt6.QtWidgets.QWidget` that will appear as a tab in the
   right-hand panel.
4. Optionally override :meth:`config_tabs` to contribute multiple labelled
   tabs to the configuration panel.
5. Optionally override :meth:`monitor_widget` to contribute a live-status
   widget to the left dock panel.

Concrete plugin behaviour is added by subclassing one of the six specialised
sub-types: :class:`~stoner_measurement.plugins.trace.base.TracePlugin`,
:class:`~stoner_measurement.plugins.state_control.base.StateControlPlugin`,
:class:`~stoner_measurement.plugins.monitor.base.MonitorPlugin`,
:class:`~stoner_measurement.plugins.transform.base.TransformPlugin`,
:class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`, or
:class:`~stoner_measurement.plugins.command.base.CommandPlugin`.
"""

from __future__ import annotations

import importlib
import json
import logging
from abc import ABC, ABCMeta, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import asteval
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFormLayout, QLabel, QLineEdit, QTextBrowser, QWidget

if TYPE_CHECKING:
    from stoner_measurement.core.sequence_engine import SequenceEngine



class _ABCQObjectMeta(type(QObject), ABCMeta):
    """Combined metaclass that resolves the conflict between QObject and ABCMeta."""


class BasePlugin(ABC):
    """Abstract root class shared by all measurement plugins.

    Subclasses must implement :attr:`name`.  Subclasses may optionally
    override :meth:`config_widget`, :meth:`config_tabs`, and
    :meth:`monitor_widget` to provide richer UI integration.

    Rather than subclassing :class:`BasePlugin` directly, prefer one of the
    six specialised sub-types:

    * :class:`~stoner_measurement.plugins.trace.TracePlugin` — collects (x, y)
      traces from instruments.
    * :class:`~stoner_measurement.plugins.state_control.StateControlPlugin` —
      controls experimental state (field, temperature, etc.).
    * :class:`~stoner_measurement.plugins.monitor.MonitorPlugin` — passively
      records auxiliary quantities.
    * :class:`~stoner_measurement.plugins.transform.TransformPlugin` — performs
      pure-computation transforms on collected data.
    * :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin` —
      acts as a branch node in the sequence tree, containing nested sub-steps.
    * :class:`~stoner_measurement.plugins.command.CommandPlugin` — executes a
      single action in the sequence without instrument lifecycle steps.

    Attributes:
        plugin_type (str):
            Short tag identifying the sub-type.  Overridden by each
            specialised base class.
        has_lifecycle (bool):
            ``True`` for plugins that participate in the connect/configure/
            disconnect lifecycle emitted by the sequence engine.  Returns
            ``False`` for :class:`~stoner_measurement.plugins.command.CommandPlugin`
            subclasses, which only contribute an action call.
        instance_name (str):
            Per-instance variable name used in the sequence engine namespace.
            Defaults to a sanitised form of :attr:`name` (lowercase, spaces
            and hyphens replaced with underscores).  Must be a valid Python
            identifier.  Setting this attribute emits
            ``instance_name_changed(old_name, new_name)`` in QObject
            sub-types.
        sequence_engine (SequenceEngine | None):
            Reference to the :class:`~stoner_measurement.core.sequence_engine.SequenceEngine`
            that owns this plugin, or ``None`` if the plugin is not currently
            loaded into an engine.  Set automatically by
            :meth:`~stoner_measurement.core.sequence_engine.SequenceEngine.add_plugin`
            and cleared by
            :meth:`~stoner_measurement.core.sequence_engine.SequenceEngine.remove_plugin`.
            Plugin lifecycle methods (``connect``, ``configure``, ``measure``,
            etc.) can read values set by other parts of the measurement sequence
            via :attr:`engine_namespace`.
    """

    #: Reference to the owning SequenceEngine; set by add_plugin / remove_plugin.
    sequence_engine: SequenceEngine | None = None

    @property
    def engine_namespace(self) -> dict:
        """Live view of the sequence engine's interpreter namespace.

        Returns the *live* ``globals`` dict used by the sequence engine so that
        plugin lifecycle methods (``connect``, ``configure``, ``measure``, etc.)
        can read or write variables that were set by other parts of the
        measurement sequence.

        Because this is the live dict (not a copy), reads always reflect the
        current state of the namespace even during a running script.  Writes
        are also immediately visible to the executing script.

        When the plugin is not attached to an engine (i.e.
        :attr:`sequence_engine` is ``None``) an empty dict is returned so that
        callers do not need to guard against ``None``.

        Returns:
            (dict):
                The live interpreter namespace dict, or ``{}`` when detached.

        Examples:
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> plugin.engine_namespace   # detached — returns empty dict
            {}
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> engine.add_plugin("dummy", plugin)
            >>> engine._namespace["sweep_start"] = 0.5
            >>> plugin.engine_namespace["sweep_start"]
            0.5
            >>> engine.shutdown()
        """
        if self.sequence_engine is None:
            return {}
        return self.sequence_engine._namespace  # noqa: SLF001

    @property
    def log(self) -> logging.Logger:
        """Logger for this plugin.

        When the plugin is attached to a sequence engine, returns the shared
        ``log`` :class:`logging.Logger` from the engine namespace so that all
        plugin code and user scripts share a single logger whose records are
        routed through the engine's Qt log handler.

        When the plugin is not attached (i.e. :attr:`sequence_engine` is
        ``None``), returns a module-level logger named after the plugin's class
        so that standalone plugin code still has a functional logger.

        Returns:
            (logging.Logger):
                A :class:`logging.Logger` instance.

        Examples:
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> import logging
            >>> isinstance(plugin.log, logging.Logger)
            True
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> engine.add_plugin("dummy", plugin)
            >>> plugin.log is engine._namespace["log"]
            True
            >>> engine.shutdown()
        """
        ns_log = self.engine_namespace.get("log")
        if isinstance(ns_log, logging.Logger):
            return ns_log
        return logging.getLogger(f"{type(self).__module__}.{type(self).__qualname__}")

    def eval(self, expr: str) -> Any:
        """Evaluate a Python expression using the sequence engine namespace.

        The expression is evaluated via :class:`asteval.Interpreter` — a safe,
        restricted evaluator that supports the full mathematical subset of
        Python syntax.  The live engine namespace (including all numpy functions
        seeded at startup and any variables set by earlier sequence steps) is
        used as the interpreter symbol table, so expressions like ``"sqrt(x)"``
        or ``"linspace(0, field_max, 100)"`` work without any additional imports.

        This method must only be called while the plugin is attached to a
        sequence engine (i.e. :attr:`sequence_engine` is not ``None``).

        Args:
            expr (str):
                A single Python expression to evaluate.

        Returns:
            (Any):
                The value produced by evaluating *expr*.

        Raises:
            RuntimeError:
                If the plugin is not currently attached to a sequence engine.
            SyntaxError:
                If *expr* is not a valid Python expression.
            Exception:
                Any exception raised during evaluation of *expr*.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> plugin = DummyPlugin()
            >>> engine.add_plugin("dummy", plugin)
            >>> plugin.eval("1 + 1")
            2
            >>> plugin.eval("sqrt(9.0)")
            3.0
            >>> engine.shutdown()
        """
        if self.sequence_engine is None:
            raise RuntimeError(
                f"{type(self).__name__}.eval() called while not attached to a "
                "sequence engine.  Attach the plugin via "
                "SequenceEngine.add_plugin() before calling eval()."
            )
        # A fresh Interpreter is created on each call so that its internal
        # error list starts empty and any state from a previous evaluation
        # cannot leak into subsequent calls.  The engine namespace dict is
        # passed by reference, so the Interpreter always sees the current live
        # variable state without copying.
        #
        # asteval.Interpreter.__init__ unconditionally injects its own
        # ``_printer`` method into the symtable under the key ``'print'``.
        # If the engine namespace is passed directly, this permanently
        # overwrites the built-in ``print``, causing subsequent ``print()``
        # calls in scripts and REPL commands to bypass the redirected
        # ``sys.stdout`` and write to the terminal instead of the console
        # widget.  Save and restore the ``'print'`` entry so that the
        # engine namespace is not polluted by asteval's injection.
        ns = self.engine_namespace
        _sentinel = object()
        saved_print = ns.get("print", _sentinel)
        try:
            interp = asteval.Interpreter(symtable=ns, use_numpy=False)
            return interp.eval(expr, raise_errors=True)
        finally:
            if saved_print is _sentinel:
                ns.pop("print", None)
            else:
                ns["print"] = saved_print

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique human-readable name for this plugin."""

    # ------------------------------------------------------------------
    # Per-instance name
    # ------------------------------------------------------------------

    @property
    def instance_name(self) -> str:
        """Variable name for this instance in the sequence engine namespace.

        Defaults to a sanitised form of :attr:`name` (lowercase, spaces and
        hyphens replaced with underscores).  May be changed at runtime to
        support multiple instances of the same plugin type.

        Returns:
            (str):
                A valid Python identifier.

        Examples:
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> plugin.instance_name
            'dummy'
        """
        try:
            return self._instance_name
        except AttributeError:
            return self.name.lower().replace(" ", "_").replace("-", "_")

    @instance_name.setter
    def instance_name(self, value: str) -> None:
        """Set the instance name, notifying listeners if it changed.

        Args:
            value (str):
                New variable name.  Must be a valid Python identifier.

        Raises:
            ValueError:
                If *value* is not a valid Python identifier.
        """
        if not value or not value.isidentifier():
            raise ValueError(
                f"instance_name must be a valid Python identifier, got {value!r}"
            )
        old = self.instance_name
        if value == old:
            return
        self._instance_name = value
        self._on_instance_name_changed(old, value)

    def _on_instance_name_changed(self, old_name: str, new_name: str) -> None:
        """Hook called after :attr:`instance_name` changes.

        The default implementation is a no-op.  QObject sub-types override
        this to emit the ``instance_name_changed`` signal.

        Args:
            old_name (str):
                Previous instance name.
            new_name (str):
                New instance name.
        """

    # ------------------------------------------------------------------
    # JSON serialisation
    # ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Serialise this plugin's configuration to a JSON-compatible dict.

        The returned dict contains at minimum:

        * ``"type"`` — the plugin sub-type tag (e.g. ``"trace"``, ``"state"``).
        * ``"class"`` — the fully qualified class path
          ``"module:ClassName"`` used by :meth:`from_json` to reconstruct the
          exact subclass.
        * ``"instance_name"`` — the current :attr:`instance_name`.

        Subclasses should call ``super().to_json()`` and then add their own
        configuration keys to the returned dict.

        Returns:
            (dict[str, Any]):
                A JSON-serialisable dictionary representing this plugin's
                current configuration.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> d = plugin.to_json()
            >>> d["type"]
            'trace'
            >>> d["instance_name"]
            'dummy'
            >>> "class" in d
            True
        """
        cls = type(self)
        return {
            "type": self.plugin_type,
            "class": f"{cls.__module__}:{cls.__qualname__}",
            "instance_name": self.instance_name,
        }

    @classmethod
    def from_json(
        cls, data: dict[str, Any], parent: QObject | None = None
    ) -> BasePlugin:
        """Reconstruct a plugin from a serialised dict produced by :meth:`to_json`.

        Uses the ``"class"`` field to import the concrete plugin class, creates
        a new instance, restores :attr:`instance_name`, and calls
        :meth:`_restore_from_json` so that subclasses can restore additional
        state such as the active scan generator.

        Args:
            data (dict[str, Any]):
                Serialised plugin dict as produced by :meth:`to_json`.

        Keyword Parameters:
            parent (QObject | None):
                Optional Qt parent for QObject-based plugin subclasses.

        Returns:
            (BasePlugin):
                A fully configured plugin instance of the correct concrete type.

        Raises:
            KeyError:
                If ``data`` does not contain a ``"class"`` key.
            ImportError:
                If the module specified in ``"class"`` cannot be imported.
            AttributeError:
                If the class name specified in ``"class"`` is not found in the
                module.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> original = DummyPlugin()
            >>> original.instance_name = "my_dummy"
            >>> restored = BasePlugin.from_json(original.to_json())
            >>> restored.instance_name
            'my_dummy'
            >>> type(restored).__name__
            'DummyPlugin'
        """
        class_path = data["class"]
        module_name, class_name = class_path.rsplit(":", 1)
        module = importlib.import_module(module_name)
        plugin_cls = getattr(module, class_name)
        try:
            instance: BasePlugin = plugin_cls(parent=parent)
        except TypeError:
            instance = plugin_cls()
        if "instance_name" in data:
            instance.instance_name = data["instance_name"]
        instance._restore_from_json(data)  # noqa: SLF001
        return instance

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore additional plugin state from *data* after construction.

        Called by :meth:`from_json` after the instance is created and
        :attr:`instance_name` is set.  The default implementation is a no-op.
        Subclasses with extra persistent state (e.g. a scan generator)
        should override this method.

        Args:
            data (dict[str, Any]):
                Serialised plugin dict as produced by :meth:`to_json`.
        """

    # ------------------------------------------------------------------
    # General config widget (instance name editor)
    # ------------------------------------------------------------------

    def _general_config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a widget containing the instance-name editor and plugin-type display.

        This widget is included as a *General* tab in :meth:`config_tabs` so
        that users can rename the sequence-engine variable for this plugin
        instance.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                A :class:`~PyQt6.QtWidgets.QWidget` with a
                :class:`~PyQt6.QtWidgets.QLineEdit` for editing
                :attr:`instance_name` and a label showing the plugin type.
        """
        widget = QWidget(parent)
        layout = QFormLayout(widget)

        name_edit = QLineEdit(self.instance_name, widget)
        name_edit.setToolTip(
            "Python variable name used to access this plugin in the sequence engine"
        )

        def _apply() -> None:
            new_name = name_edit.text().strip()
            if new_name and new_name.isidentifier():
                name_edit.setStyleSheet("")
                self.instance_name = new_name
            else:
                # Highlight the field and revert to the current valid value.
                name_edit.setStyleSheet("border: 1px solid red;")
                name_edit.setToolTip(
                    f"{new_name!r} is not a valid Python identifier. "
                    "Use only letters, digits and underscores, "
                    "and do not start with a digit."
                )
                name_edit.setText(self.instance_name)

        name_edit.editingFinished.connect(_apply)

        # Keep the name field in sync with the authoritative instance_name
        # so that an external revert (e.g. collision detected by the dock
        # panel) is immediately visible to the user.  Only plugins that
        # sub-class QObject carry the instance_name_changed signal.
        if hasattr(self, "instance_name_changed"):
            # Disconnect any stale sync callback left by a previous call
            # (relevant when config_tabs() recreates the widget on every
            # selection rather than caching it).
            prev_sync = getattr(self, "_name_edit_sync", None)
            if prev_sync is not None:
                try:
                    self.instance_name_changed.disconnect(prev_sync)  # type: ignore[attr-defined]
                except (TypeError, RuntimeError):
                    pass

            def _sync_name_edit(_old: str, _new: str) -> None:  # noqa: ARG001
                # Read the authoritative value rather than trusting `_new`.
                # When a rename is reverted (due to a collision), the revert
                # fires a nested instance_name_changed before this outer
                # handler returns.  By the time this callback runs, the
                # authoritative instance_name may already have been reset to
                # the reverted value; using `_new` would show stale text.
                current = self.instance_name
                try:
                    name_edit.setText(current)
                    name_edit.setStyleSheet("")
                except RuntimeError:
                    # The underlying C++ widget has been destroyed; remove
                    # this stale connection.
                    try:
                        self.instance_name_changed.disconnect(_sync_name_edit)  # type: ignore[attr-defined]
                    except (TypeError, RuntimeError):
                        pass

            self.instance_name_changed.connect(_sync_name_edit)  # type: ignore[attr-defined]
            self._name_edit_sync = _sync_name_edit  # type: ignore[attr-defined]

        layout.addRow("Instance name:", name_edit)
        layout.addRow("Plugin type:", QLabel(self.plugin_type, widget))
        widget.setLayout(layout)
        return widget

    @property
    def plugin_type(self) -> str:
        """Short tag identifying the plugin sub-type.

        Returns:
            (str):
                ``"base"`` for direct :class:`BasePlugin` subclasses.
                Overridden to ``"trace"``, ``"state"``, ``"monitor"``,
                ``"transform"``, or ``"command"`` by the respective
                specialised sub-types.
        """
        return "base"

    @property
    def has_lifecycle(self) -> bool:
        """Whether this plugin participates in the connect/configure/disconnect lifecycle.

        The sequence engine checks this flag when generating code so that
        :class:`~stoner_measurement.plugins.command.CommandPlugin` subclasses
        (which execute a single action without hardware lifecycle steps) are
        omitted from the connect, configure, and disconnect phases.

        Returns:
            (bool):
                ``True`` for all plugin types except
                :class:`~stoner_measurement.plugins.command.CommandPlugin`,
                which overrides this to return ``False``.

        Examples:
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> DummyPlugin().has_lifecycle
            True
        """
        return True

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a :class:`QWidget` for configuring this plugin.

        The default implementation returns a simple label.  Override this
        method to provide a richer configuration interface.  This method is
        called by the default :meth:`config_tabs` implementation to supply the
        single tab widget.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The configuration widget for this plugin.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> widget = plugin.config_widget()
            >>> widget is not None
            True
        """
        label = QLabel(f"<i>No configuration available for <b>{self.name}</b></i>")
        label.setParent(parent)
        return label

    def _about_html(self) -> str | None:
        """Return an HTML string for the *About* tab, or ``None`` to omit the tab.

        The default implementation returns ``None`` so that no *About* tab is
        shown.  Override in a subclass to provide plugin-specific documentation
        or instructions rendered in a
        :class:`~PyQt6.QtWidgets.QTextBrowser`.

        Returns:
            (str | None):
                HTML-formatted documentation string, or ``None`` to omit the
                *About* tab entirely.

        Examples:
            >>> from stoner_measurement.plugins.base_plugin import BasePlugin
            >>> class _Minimal(BasePlugin):
            ...     @property
            ...     def name(self): return "Minimal"
            >>> _Minimal()._about_html() is None
            True
        """
        return None

    def _make_about_tab(self) -> tuple[str, QWidget] | None:
        """Return an *About* tab tuple if :meth:`_about_html` returns content, else ``None``.

        Builds a ``(title, widget)`` pair for the *About* tab using the HTML
        returned by :meth:`_about_html`.  The widget is a
        :class:`~PyQt6.QtWidgets.QTextBrowser` pre-loaded with the HTML.

        Returns:
            (tuple[str, QWidget] | None):
                ``(tab_title, QTextBrowser)`` when :meth:`_about_html` returns
                a non-``None`` string; ``None`` when there is no About content.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.base_plugin import BasePlugin
            >>> class _Minimal(BasePlugin):
            ...     @property
            ...     def name(self): return "Minimal"
            >>> _Minimal()._make_about_tab() is None
            True
        """
        about_html = self._about_html()
        if about_html is None:
            return None
        about_widget = QTextBrowser()
        about_widget.setHtml(about_html)
        return (f"{self.name} \u2013 About", about_widget)

    def config_tabs(
        self, parent: QWidget | None = None
    ) -> list[tuple[str, QWidget]]:
        """Return a list of ``(tab_title, widget)`` pairs for the config panel.

        Each pair contributes one tab to the right-hand configuration panel.
        The default implementation wraps :meth:`config_widget` in a list using
        :attr:`name` as the tab title, appends a *General* tab containing
        the instance-name editor, and optionally appends an *About* tab whose
        HTML content is provided by :meth:`_about_html`.

        Override this method when a plugin needs to contribute more than one
        tab, or when a custom tab title is desired.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget passed to each tab widget.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.base_plugin import BasePlugin
            >>> class _Minimal(BasePlugin):
            ...     @property
            ...     def name(self): return "Minimal"
            >>> plugin = _Minimal()
            >>> tabs = plugin.config_tabs()
            >>> len(tabs)
            2
            >>> tabs[0][0]
            'Minimal'
            >>> tabs[1][0]
            'General'
        """
        tabs = [
            (self.name, self.config_widget(parent=parent)),
            ("General", self._general_config_widget(parent=parent)),
        ]
        about_tab = self._make_about_tab()
        if about_tab is not None:
            tabs.append(about_tab)
        return tabs

    def tooltip(self) -> str:
        """Return a short tooltip description for this plugin.

        The default implementation extracts the first non-empty line of the
        class docstring and returns it (stripped of leading/trailing whitespace).
        Subclasses may override this to provide alternative tooltip text.

        Returns:
            (str):
                A one-line description of the plugin, or an empty string if no
                docstring is available.

        Examples:
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> tooltip = plugin.tooltip()
            >>> isinstance(tooltip, str)
            True
            >>> len(tooltip) > 0
            True
        """
        doc = type(self).__doc__
        if not doc:
            return ""
        for line in doc.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return ""

    def monitor_widget(self, parent: QWidget | None = None) -> QWidget | None:
        """Return an optional live-status widget for the left dock panel.

        The widget will be displayed in the monitoring section of the
        :class:`~stoner_measurement.ui.dock_panel.DockPanel` while the plugin
        is registered.  The default implementation returns ``None``, meaning
        the plugin contributes no monitoring widget.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget | None):
                A monitoring widget, or ``None`` if the plugin provides none.

        Examples:
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> plugin.monitor_widget() is None
            True
        """
        return None

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return the action code lines for this plugin at the given indentation level.

        The sequence engine calls this method when building the action body of
        the generated script.  The default implementation emits a comment
        indicating an unknown plugin type.  Specialised sub-types
        (:class:`~stoner_measurement.plugins.trace.TracePlugin`,
        :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`,
        etc.) override this method to produce the appropriate code.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Raw sub-step descriptors from the sequence tree (strings or
                ``(plugin_or_name, [sub-steps…])`` tuples).  Leaf plugins
                (e.g. :class:`~stoner_measurement.plugins.trace.TracePlugin`)
                can ignore this; container plugins should call *render_sub_step*
                for each entry.
            render_sub_step (Callable):
                Callback with signature ``(step, indent) -> list[str]`` provided
                by the sequence engine.  Container plugins call this to render
                each nested step at the appropriate indentation level.

        Returns:
            (list[str]):
                Lines of Python source code (without trailing newlines) that
                implement this plugin's action phase.

        Examples:
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> lines = plugin.generate_action_code(1, [], lambda s, i: [])
            >>> "dummy.measure" in "\\n".join(lines)
            True
        """
        prefix = "    " * indent
        return [
            f"{prefix}# {self.instance_name}: unknown plugin type",
            "",
        ]

    def generate_instantiation_code(self) -> list[str]:
        """Return Python code lines that conditionally instantiate this plugin from its config.

        The generated code checks whether the plugin's
        :attr:`instance_name` variable already exists in ``globals()`` (i.e. was
        injected into the namespace by the sequence engine) and, only if it does
        not, recreates the plugin from its serialised configuration using
        :meth:`from_json`.

        This ensures that a saved script is self-contained: when run outside
        the app (e.g. loaded from a file into a fresh Python session), the plugin
        is reconstructed from the configuration that was current at the time the
        script was generated.  When the script is run by the app with the
        plugin already registered in the engine namespace, the existing instance
        is kept unchanged so that live engine state (such as the
        :attr:`sequence_engine` back-reference) is preserved.

        The caller (:meth:`~stoner_measurement.core.sequence_engine.SequenceEngine.generate_sequence_code`)
        is responsible for emitting the following one-time imports before calling
        this method for any plugin::

            import json as _json
            from stoner_measurement.plugins.base_plugin import BasePlugin as _BasePlugin

        Returns:
            (list[str]):
                Lines of Python source code (without trailing newlines).

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.trace import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> lines = plugin.generate_instantiation_code()
            >>> lines[0]
            "if 'dummy' not in globals():"
            >>> '_BasePlugin.from_json' in lines[1]
            True
            >>> '_json.loads' in lines[1]
            True
        """
        var_name = self.instance_name
        config_json = json.dumps(self.to_json())
        return [
            f"if {var_name!r} not in globals():",
            f"    {var_name} = _BasePlugin.from_json(_json.loads({config_json!r}))",
            "",
        ]

    def reported_traces(self) -> dict[str, str]:
        """Return a mapping of trace names to Python expressions for accessing trace data.

        Each entry in the returned dict describes one data trace produced by this plugin.
        The key is a human-readable name of the form ``"{instance_name}:{trace_name}"``
        and the value is the Python expression that retrieves the corresponding
        ``(x_array, y_array)`` tuple from the sequence engine namespace.

        The sequence engine merges the dicts from all registered plugins to build a
        master catalogue of available traces (see
        :attr:`~stoner_measurement.core.sequence_engine.SequenceEngine.traces_catalog`).
        This catalogue can be used by downstream plugins (e.g. plot plugins) to
        discover what data is available without hard-coding variable names.

        The default implementation returns an empty dict.  Subclasses that produce
        trace data (e.g. :class:`~stoner_measurement.plugins.trace.TracePlugin`)
        override this method to enumerate their channels.

        Returns:
            (dict[str, str]):
                Mapping of ``"{instance_name}:{trace_name}"`` → Python expression
                string.  Empty dict for plugins that produce no traces.

        Examples:
            >>> from stoner_measurement.plugins.base_plugin import BasePlugin
            >>> class _Minimal(BasePlugin):
            ...     @property
            ...     def name(self): return "Minimal"
            >>> _Minimal().reported_traces()
            {}
        """
        return {}

    def reported_values(self) -> dict[str, str]:
        """Return a mapping of value names to Python expressions for accessing scalar data.

        Each entry describes one scalar data value produced by this plugin during a
        measurement sequence.  The key is a human-readable name of the form
        ``"{instance_name}:{value_name}"`` and the value is the Python expression that
        retrieves the current scalar from the sequence engine namespace.

        The sequence engine merges the dicts from all registered plugins to build a
        master catalogue of available scalar values (see
        :attr:`~stoner_measurement.core.sequence_engine.SequenceEngine.values_catalog`).
        This catalogue can be used by downstream plugins (e.g. plot plugins) to
        discover what scalar data is available.

        The default implementation returns an empty dict.  Subclasses that produce
        scalar values (e.g.
        :class:`~stoner_measurement.plugins.monitor.MonitorPlugin`,
        :class:`~stoner_measurement.plugins.state_control.StateControlPlugin`)
        override this method to enumerate their quantities.

        Returns:
            (dict[str, str]):
                Mapping of ``"{instance_name}:{value_name}"`` → Python expression
                string.  Empty dict for plugins that produce no scalar values.

        Examples:
            >>> from stoner_measurement.plugins.base_plugin import BasePlugin
            >>> class _Minimal(BasePlugin):
            ...     @property
            ...     def name(self): return "Minimal"
            >>> _Minimal().reported_values()
            {}
        """
        return {}
