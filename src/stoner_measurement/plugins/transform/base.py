"""TransformPlugin — abstract base class for data-transformation plugins.

Transform plugins perform pure computation on collected data without accessing
hardware.  Examples include resistance calculations from (V, I) traces,
background subtraction, smoothing, FFT analysis, and unit conversion.

A :class:`TransformPlugin` is chained after trace acquisition: the sequence
engine passes the collected data dict through the transform pipeline and stores
the resulting outputs alongside the raw traces.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from stoner_measurement.plugins.base_plugin import BasePlugin, _ABCQObjectMeta


class TransformPlugin(QObject, BasePlugin, metaclass=_ABCQObjectMeta):
    """Abstract base class for plugins that transform or reduce data.

    A :class:`TransformPlugin` accepts a dictionary of named input
    arrays/scalars, validates that all required keys are present, and returns a
    dictionary of named output arrays/scalars.  Subclasses must implement
    :attr:`name`, :attr:`required_inputs`, :attr:`output_names`, and
    :meth:`transform`.

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
        >>> from PyQt6.QtWidgets import QApplication
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

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy."""
        super().__init__(parent)
        self.data: dict[str, Any] = {}

    def _on_instance_name_changed(self, old_name: str, new_name: str) -> None:
        """Emit :attr:`instance_name_changed` when the instance name changes."""
        self.instance_name_changed.emit(old_name, new_name)

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
    @abstractmethod
    def output_names(self) -> list[str]:
        """Names of the datasets produced by :meth:`transform`.

        Returns:
            (list[str]):
                Ordered list of output key names present in the dict returned
                by :meth:`transform`.
        """

    @property
    def output_trace_names(self) -> list[str]:
        """Subset of :attr:`output_names` that are (x, y) trace arrays.

        The default implementation returns an empty list, meaning all outputs are
        treated as scalar values.  Override this in a subclass to declare which
        output keys hold ``(x_array, y_array)`` pairs that should appear in the
        :attr:`~stoner_measurement.core.sequence_engine.SequenceEngine.traces_catalog`.

        Returns:
            (list[str]):
                Output names that are traces.  Must be a subset of
                :attr:`output_names`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _T(TransformPlugin):
            ...     @property
            ...     def name(self): return "T"
            ...     @property
            ...     def required_inputs(self): return []
            ...     @property
            ...     def output_names(self): return ["curve", "rms"]
            ...     @property
            ...     def output_trace_names(self): return ["curve"]
            ...     def transform(self, data): return {}
            >>> _T().output_trace_names
            ['curve']
        """
        return []

    @property
    def output_value_names(self) -> list[str]:
        """Subset of :attr:`output_names` that are scalar data values.

        The default implementation returns all of :attr:`output_names`, meaning
        every output is treated as a scalar value.  Override this in a subclass
        when only a subset of outputs are scalars; in particular, any name listed
        in :attr:`output_trace_names` that is also a scalar can be included here.

        Returns:
            (list[str]):
                Output names that are scalar values.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _T(TransformPlugin):
            ...     @property
            ...     def name(self): return "T"
            ...     @property
            ...     def required_inputs(self): return []
            ...     @property
            ...     def output_names(self): return ["curve", "rms"]
            ...     @property
            ...     def output_trace_names(self): return ["curve"]
            ...     @property
            ...     def output_value_names(self): return ["rms"]
            ...     def transform(self, data): return {}
            >>> _T().output_value_names
            ['rms']
        """
        return list(self.output_names)

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
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> from PyQt6.QtWidgets import QApplication
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

    def generate_action_code(
        self,
        indent: int,
        sub_steps: list,
        render_sub_step: Callable,
    ) -> list[str]:
        """Return a commented action stub for this transform plugin.

        Args:
            indent (int):
                Number of four-space indentation levels for the emitted lines.
            sub_steps (list):
                Ignored for :class:`TransformPlugin` (leaf node).
            render_sub_step (Callable):
                Ignored for :class:`TransformPlugin`.

        Returns:
            (list[str]):
                A single commented-out ``run(data)`` call.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
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
            >>> "# result = t.run(data)" in lines
            True
        """
        prefix = "    " * indent
        var_name = self.instance_name
        return [
            f"{prefix}# result = {var_name}.run(data)",
            "",
        ]

    def reported_traces(self) -> dict[str, str]:
        """Return a mapping of trace output names to Python expressions.

        Reports each name in :attr:`output_trace_names` as a trace, using
        ``"{instance_name}.data['{output_name}']"`` as the access expression.
        The default is an empty dict because :attr:`output_trace_names` defaults
        to ``[]``.  Override :attr:`output_trace_names` in a subclass to
        populate this automatically.

        Returns:
            (dict[str, str]):
                Mapping of ``"{instance_name}:{output_name}"`` → expression for
                each name in :attr:`output_trace_names`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _T(TransformPlugin):
            ...     @property
            ...     def name(self): return "Fit"
            ...     @property
            ...     def required_inputs(self): return []
            ...     @property
            ...     def output_names(self): return ["fitted_curve", "residual"]
            ...     @property
            ...     def output_trace_names(self): return ["fitted_curve"]
            ...     def transform(self, data): return {}
            >>> t = _T()
            >>> traces = t.reported_traces()
            >>> list(traces.keys())
            ['fit:fitted_curve']
            >>> traces['fit:fitted_curve']
            "fit.data['fitted_curve']"
        """
        var = self.instance_name
        return {f"{var}:{name}": f"{var}.data['{name}']" for name in self.output_trace_names}

    def reported_values(self) -> dict[str, str]:
        """Return a mapping of scalar output names to Python expressions.

        Reports each name in :attr:`output_value_names` as a scalar value, using
        ``"{instance_name}.data['{output_name}']"`` as the access expression.
        By default this covers all of :attr:`output_names`.  Override
        :attr:`output_value_names` in a subclass to restrict which outputs are
        reported as scalar values.

        Returns:
            (dict[str, str]):
                Mapping of ``"{instance_name}:{output_name}"`` → expression for
                each name in :attr:`output_value_names`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.transform import TransformPlugin
            >>> class _T(TransformPlugin):
            ...     @property
            ...     def name(self): return "Fit"
            ...     @property
            ...     def required_inputs(self): return []
            ...     @property
            ...     def output_names(self): return ["fitted_curve", "residual"]
            ...     @property
            ...     def output_trace_names(self): return ["fitted_curve"]
            ...     @property
            ...     def output_value_names(self): return ["residual"]
            ...     def transform(self, data): return {}
            >>> t = _T()
            >>> vals = t.reported_values()
            >>> list(vals.keys())
            ['fit:residual']
            >>> vals['fit:residual']
            "fit.data['residual']"
        """
        var = self.instance_name
        return {f"{var}:{name}": f"{var}.data['{name}']" for name in self.output_value_names}

