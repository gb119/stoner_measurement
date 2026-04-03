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

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the Qt object hierarchy."""
        super().__init__(parent)

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
        self.transform_complete.emit(result)
        return result
