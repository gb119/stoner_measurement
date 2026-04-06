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

Concrete plugin behaviour is added by subclassing one of the five specialised
sub-types: :class:`~stoner_measurement.plugins.trace.TracePlugin`,
:class:`~stoner_measurement.plugins.state_control.StateControlPlugin`,
:class:`~stoner_measurement.plugins.monitor.MonitorPlugin`,
:class:`~stoner_measurement.plugins.transform.TransformPlugin`, or
:class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin`.
"""

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

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
    five specialised sub-types:

    * :class:`~stoner_measurement.plugins.trace.TracePlugin` — collects (x, y)
      traces from instruments.
    * :class:`~stoner_measurement.plugins.state_control.StateControlPlugin` —
      controls experimental state (field, temperature, etc.).
    * :class:`~stoner_measurement.plugins.monitor.MonitorPlugin` — passively
      records auxiliary quantities.
    * :class:`~stoner_measurement.plugins.transform.TransformPlugin` — performs
      pure-computation transforms on collected data.
    * :class:`~stoner_measurement.plugins.sequence_plugin.SequencePlugin` —
      acts as a branch node in the sequence tree, containing nested sub-steps.

    Attributes:
        plugin_type (str):
            Short tag identifying the sub-type.  Overridden by each
            specialised base class.
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
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
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
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
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
                Overridden to ``"trace"``, ``"state"``, ``"monitor"``, or
                ``"transform"`` by the respective specialised sub-types.
        """
        return "base"

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
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
            >>> plugin = DummyPlugin()
            >>> widget = plugin.config_widget()
            >>> widget is not None
            True
        """
        label = QLabel(f"<i>No configuration available for <b>{self.name}</b></i>")
        label.setParent(parent)
        return label

    def config_tabs(
        self, parent: QWidget | None = None
    ) -> list[tuple[str, QWidget]]:
        """Return a list of ``(tab_title, widget)`` pairs for the config panel.

        Each pair contributes one tab to the right-hand configuration panel.
        The default implementation wraps :meth:`config_widget` in a list using
        :attr:`name` as the tab title, and appends a *General* tab containing
        the instance-name editor.

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
        return [
            (self.name, self.config_widget(parent=parent)),
            ("General", self._general_config_widget(parent=parent)),
        ]

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
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
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
            >>> from stoner_measurement.plugins.dummy import DummyPlugin
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
