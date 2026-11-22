"""TransformPlugin — abstract base class for data-transformation plugins.

Transform plugins perform pure computation on collected data without accessing
hardware.  Examples include resistance calculations from (V, I) traces,
background subtraction, smoothing, FFT analysis, and unit conversion.

A :class:`TransformPlugin` can consume existing traces after acquisition.
Direct callers supply required inputs to ``run(data)``. Generated actions call
``run({})``; transforms selecting their own source through configured namespace
expressions normally declare ``required_inputs=[]``. The wrapper stores the
returned result mapping on the transform instance.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from qtpy.QtCore import QObject
from qtpy.QtWidgets import QFrame, QVBoxLayout, QWidget

from stoner_measurement.core.plugin_outputs import (
    PluginOutputs,
    legacy_output_property,
    output_view,
    project_outputs,
    transform_outputs,
)
from stoner_measurement.plugins.base_plugin import BasePlugin, _ABCQObjectMeta
from stoner_measurement.qt_compat import pyqtSignal


class TransformPlugin(QObject, BasePlugin, metaclass=_ABCQObjectMeta):
    """Abstract base class for plugins that transform or reduce data.

    A :class:`TransformPlugin` accepts a dictionary of named input
    arrays/scalars, validates that all required keys are present, and returns a
    dictionary of named output arrays/scalars.  Subclasses must implement
    :attr:`name`, :attr:`required_inputs`, :meth:`declared_outputs`, and
    :meth:`transform`. The old output-name properties remain supported for
    legacy plugins and are derived views for unified declarations.

    The class provides:

    * **Input validation** — :meth:`validate_inputs` raises :exc:`ValueError`
      if any key listed in :attr:`required_inputs` is missing from the data
      dict.  It is called automatically by the default :meth:`run` helper.
    * **Run helper** — :meth:`run` validates inputs, calls :meth:`transform`,
      emits :attr:`transform_complete`, and returns the result dict.
    * **Description** — :attr:`description` provides a human-readable summary
      of the computation performed.

    Attributes:
        transform_complete (pyqtSignal[dict]):
            Emitted after :meth:`transform` returns successfully, with the
            result dict as its argument.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.transform import TransformPlugin
        >>> class _Scale(TransformPlugin):
        ...     @property
        ...     def name(self): return "Scale"
        ...     @property
        ...     def required_inputs(self): return ["y"]
        ...     @property
        ...     def output_names(self): return ["y_scaled"]
        ...     def transform(self, data):
        ...         return {"y_scaled": [v * 2 for v in data["y"]]}
        >>> p = _Scale()
        >>> p.plugin_type
        'transform'
        >>> p.description
        ''
        >>> result = p.run({"y": [1.0, 2.0, 3.0]})
        >>> result["y_scaled"]
        [2.0, 4.0, 6.0]
    """

    transform_complete = pyqtSignal(dict)
    instance_name_changed = pyqtSignal(str, str)
    comment_changed = pyqtSignal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy."""
        super().__init__(parent)
        self.data: dict[str, Any] = {}

    def _on_instance_name_changed(self, old_name: str, new_name: str) -> None:
        """Emit :attr:`instance_name_changed` when the instance name changes."""
        self.instance_name_changed.emit(old_name, new_name)

    def _on_comment_changed(self, old_comment: str, new_comment: str) -> None:
        """Emit :attr:`comment_changed` when the comment changes."""
        self.comment_changed.emit(old_comment, new_comment)

    @property
    def plugin_type(self) -> str:
        """Short tag identifying this plugin as a transform.

        Returns:
            (str):
                Always ``"transform"``.
        """
        return "transform"

    @property
    @abstractmethod
    def required_inputs(self) -> list[str]:
        """Names of input datasets that :meth:`transform` requires.

        :meth:`validate_inputs` raises :exc:`ValueError` if any of these keys
        are absent from the data dict passed to :meth:`transform`.

        Returns:
            (list[str]):
                Ordered list of required input key names.
        """

    @property
    @output_view
    def output_names(self) -> list[str]:
        """Return the compatibility view of unified output declarations."""
        return project_outputs(self, "output_names")

    @property
    @output_view
    def output_trace_names(self) -> list[str]:
        """Return the compatibility view of unified output declarations."""
        return project_outputs(self, "output_trace_names")

    @property
    @output_view
    def output_value_names(self) -> list[str]:
        """Return the compatibility view of unified output declarations."""
        return project_outputs(self, "output_value_names")

    @abstractmethod
    def transform(self, data: dict[str, Any]) -> dict[str, Any]:
        """Compute the transform and return the result.

        Args:
            data (dict[str, Any]):
                Named input arrays or scalars.  All keys listed in
                :attr:`required_inputs` are guaranteed to be present when
                called via :meth:`run`.

        Returns:
            (dict[str, Any]):
                Named output arrays or scalars.  Should contain at least the
                keys listed in :attr:`output_names`.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _Negate(TransformPlugin):
            ...     @property
            ...     def name(self): return "Negate"
            ...     @property
            ...     def required_inputs(self): return ["y"]
            ...     @property
            ...     def output_names(self): return ["y_neg"]
            ...     def transform(self, data): return {"y_neg": [-v for v in data["y"]]}
            >>> p = _Negate()
            >>> p.transform({"y": [1.0, -2.0]})
            {'y_neg': [-1.0, 2.0]}
        """

    @property
    def description(self) -> str:
        """Human-readable summary of the computation performed.

        Returns:
            (str):
                Descriptive text; default is an empty string.
        """
        return ""

    def validate_inputs(self, data: dict[str, Any]) -> None:
        """Raise :exc:`ValueError` if any required input keys are missing.

        Args:
            data (dict[str, Any]):
                The data dict to validate.

        Raises:
            ValueError:
                If one or more keys from :attr:`required_inputs` are absent
                from *data*.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _T(TransformPlugin):
            ...     @property
            ...     def name(self): return "T"
            ...     @property
            ...     def required_inputs(self): return ["a", "b"]
            ...     @property
            ...     def output_names(self): return ["c"]
            ...     def transform(self, data): return {"c": data["a"]}
            >>> p = _T()
            >>> p.validate_inputs({"a": 1, "b": 2})  # no error
            >>> import pytest
            >>> with pytest.raises(ValueError, match="b"):
            ...     p.validate_inputs({"a": 1})
        """
        missing = [k for k in self.required_inputs if k not in data]
        if missing:
            raise ValueError(f"Missing required inputs: {missing}")

    def run(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate *data*, run :meth:`transform`, emit the result, and return it.

        This is the preferred entry point for the sequence engine: it combines
        input validation, the computation, and signal emission in a single call.

        Args:
            data (dict[str, Any]):
                Named input arrays or scalars.

        Returns:
            (dict[str, Any]):
                The dict returned by :meth:`transform`.

        Raises:
            ValueError:
                If any key in :attr:`required_inputs` is absent from *data*.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _Double(TransformPlugin):
            ...     @property
            ...     def name(self): return "Double"
            ...     @property
            ...     def required_inputs(self): return ["x"]
            ...     @property
            ...     def output_names(self): return ["x2"]
            ...     def transform(self, data): return {"x2": data["x"] * 2}
            >>> p = _Double()
            >>> p.run({"x": 3})
            {'x2': 6}
        """
        self.validate_inputs(data)
        result = self.transform(data)
        self.data = result
        self.transform_complete.emit(result)
        return result

    def rename_trace_output(self, old_name: str, new_name: str) -> None:
        """Rename a trace output and propagate its catalogue identity downstream."""
        if old_name == new_name:
            return
        if old_name in self.data:
            self.data[new_name] = self.data.pop(old_name)
        if self.sequence_engine is None:
            return
        var = self.instance_name
        self.sequence_engine.rename_trace_output(
            f"{var}:{old_name}",
            f"{var}:{new_name}",
            f"{var}.data[{old_name!r}]",
            f"{var}.data[{new_name!r}]",
        )

    @property
    def has_lifecycle(self) -> bool:
        """Transform plugins have no instrument lifecycle.

        Returns:
            (bool):
                Always ``False``.  The sequence engine therefore omits
                ``connect()``, ``configure()``, and ``disconnect()`` calls
                for transform plugins when generating sequence code.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _T(TransformPlugin):
            ...     @property
            ...     def name(self): return "T"
            ...     @property
            ...     def required_inputs(self): return []
            ...     @property
            ...     def output_names(self): return []
            ...     def transform(self, data): return {}
            >>> _T().has_lifecycle
            False
        """
        return False

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return action code lines that run this transform plugin.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Ignored for :class:`TransformPlugin` (leaf node).
            render_sub_step (Callable):
                Ignored for :class:`TransformPlugin`.

        Returns:
            (list[str]):
                Lines calling ``run({})`` on the plugin instance.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _T(TransformPlugin):
            ...     @property
            ...     def name(self): return "T"
            ...     @property
            ...     def required_inputs(self): return []
            ...     @property
            ...     def output_names(self): return []
            ...     def transform(self, data): return {}
            >>> t = _T()
            >>> lines = t.generate_action_code(1, [], lambda s, i: [])
            >>> "    t.run({})" in lines
            True
        """
        prefix = "    " * indent
        var_name = self.instance_name
        return [
            f"{prefix}{var_name}.run({{}})",
            "",
        ]

    def declared_outputs(self) -> PluginOutputs:
        """Adapt old transform naming properties to typed declarations."""
        names = legacy_output_property(self, "output_names", [])
        traces = legacy_output_property(self, "output_trace_names", [])
        values = legacy_output_property(self, "output_value_names", names)
        return transform_outputs(self, traces, values)

    # ------------------------------------------------------------------
    # Configuration tabs
    # ------------------------------------------------------------------

    def _build_data_tab(self, parent: QWidget | None = None) -> QWidget:
        """Build the *Data* selection widget for this transform plugin.

        The default implementation returns an empty :class:`QWidget`.
        Subclasses should override this method to add data-selection controls
        relevant to the specific transform they implement.  The widget returned
        here is embedded at the bottom of the combined *Data* tab produced by
        :meth:`config_tabs`; the instance-name editor from
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin._general_config_widget`
        is always placed above it.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                Widget containing data-selection controls.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _T(TransformPlugin):
            ...     @property
            ...     def name(self): return "T"
            ...     @property
            ...     def required_inputs(self): return []
            ...     @property
            ...     def output_names(self): return []
            ...     def transform(self, data): return {}
            >>> w = _T()._build_data_tab()
            >>> w is not None
            True
        """
        return QWidget(parent)

    def config_tabs(self, parent: QWidget | None = None) -> list[tuple[str, QWidget]]:
        """Return configuration tabs for this transform plugin.

        Produces a single *Data* tab that places the instance-name editor
        (from :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin._general_config_widget`)
        at the top, followed by a horizontal separator and the data-selection
        widget returned by :meth:`_build_data_tab`.  An optional *About* tab is
        appended when :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin._about_html`
        returns non-``None`` content.

        Subclasses that need additional tabs (e.g. a *Fit Function* or
        *Parameters* tab) should call ``super().config_tabs(parent)`` to obtain
        the base *Data* tab and then insert their extra tabs before the optional
        *About* tab.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (list[tuple[str, QWidget]]):
                List of ``(tab_title, widget)`` pairs starting with the
                combined *Data* tab.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _T(TransformPlugin):
            ...     @property
            ...     def name(self): return "T"
            ...     @property
            ...     def required_inputs(self): return []
            ...     @property
            ...     def output_names(self): return []
            ...     def transform(self, data): return {}
            >>> tabs = _T().config_tabs()
            >>> tabs[0][0]
            'Data'
            >>> 'General' not in [t for t, _ in tabs]
            True
        """

        def _build_tabs() -> list[tuple[str, QWidget]]:
            outer = QWidget(parent)
            outer_layout = QVBoxLayout(outer)
            outer_layout.setContentsMargins(0, 0, 0, 0)
            outer_layout.addWidget(self._general_config_widget(parent=outer))
            separator = QFrame(outer)
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setFrameShadow(QFrame.Shadow.Sunken)
            outer_layout.addWidget(separator)
            outer_layout.addWidget(self._build_data_tab(parent=outer))
            outer_layout.addStretch()
            outer.setLayout(outer_layout)

            tabs: list[tuple[str, QWidget]] = [("Data", outer)]
            about_tab = self._make_about_tab()
            if about_tab is not None:
                tabs.append(about_tab)
            return tabs

        return self._get_cached_config_tabs(_build_tabs)
