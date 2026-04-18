"""Abstract base class for scan generators.

Scan generators produce a sequence of values that are sent to instruments
to control an experiment. All generators share a common iterator interface,
a caching mechanism, and a Qt widget for configuration.
"""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget

if TYPE_CHECKING:
    pass


class _ABCQObjectMeta(type(QObject), ABCMeta):
    """Combined metaclass that resolves the conflict between QObject and ABCMeta."""


class BaseScanGenerator(QObject, metaclass=_ABCQObjectMeta):
    """Abstract base class for all scan generators.

    A scan generator produces a sequence of output values that are sent to
    instruments to control an experiment.  Subclasses must implement
    :meth:`generate`, :meth:`measure_flags`, and :meth:`config_widget`.

    The class provides:

    * **Iterator interface** — :meth:`__iter__` and :meth:`__next__` allow
      direct iteration over the generated values; :meth:`reset` restarts
      iteration.  Each step yields a ``(index, value, measure, stage)``
      tuple, where *index* is the point number, *value* is the scan value,
      *measure* indicates whether to collect data at that point, and *stage*
      identifies the originating stage.
    * **Value caching** — :attr:`values` calls :meth:`generate` on first
      access and caches the result until a parameter changes.  :attr:`flags`
      similarly caches the result of :meth:`measure_flags`.
    * **Change notification** — the :attr:`values_changed` signal is emitted
      whenever a parameter is updated; :attr:`current_value_changed` is
      emitted on every iteration step with the current output value.
    * **Units** — the :attr:`units` property stores a physical unit string
      (e.g. ``"V"``, ``"T"``).  When set, :attr:`units_changed` is emitted
      so that connected configuration widgets can update their spinbox
      suffixes to display the new unit.

    Attributes:
        values_changed (pyqtSignal):
            Emitted when the sequence of values changes due to a parameter
            update.
        current_value_changed (pyqtSignal):
            Emitted on each iteration step with the current output value as
            a ``float`` argument.  Consumers can connect this signal to a
            display widget to show the current scan position.
        units_changed (pyqtSignal):
            Emitted with the new unit string whenever :attr:`units` is set.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.scan.ramp_generator import RampScanGenerator
        >>> gen = RampScanGenerator()
        >>> gen.units
        ''
        >>> gen.units = 'V'
        >>> gen.units
        'V'
    """

    values_changed = pyqtSignal()
    current_value_changed = pyqtSignal(float)
    units_changed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the generator state."""
        super().__init__(parent)
        self._cache: np.ndarray | None = None
        self._flags_cache: np.ndarray | None = None
        self._stage_indices_cache: np.ndarray | None = None
        self._index: int = 0
        self._units: str = ""

    # ------------------------------------------------------------------
    # Units property
    # ------------------------------------------------------------------

    @property
    def units(self) -> str:
        """Physical unit string displayed on value spinboxes (e.g. ``"V"``).

        Setting this property emits :attr:`units_changed` so that connected
        configuration widgets can refresh their spinbox suffixes.  An empty
        string (the default) means no unit is displayed.  The signal is only
        emitted when the value actually changes.

        Returns:
            (str):
                The current unit string.
        """
        return self._units

    @units.setter
    def units(self, value: str) -> None:
        new_units = str(value)
        if new_units != self._units:
            self._units = new_units
            self.units_changed.emit(self._units)

    @abstractmethod
    def to_json(self) -> dict[str, Any]:
        """Serialise the generator's configuration to a JSON-compatible dict.

        The returned dict must contain at least a ``"type"`` key whose value is
        the generator's class name (e.g. ``"SteppedScanGenerator"``).  All
        parameters needed to exactly recreate the current configuration must
        also be included so that a round-trip through :meth:`from_json` is
        lossless.

        Returns:
            (dict[str, Any]):
                A JSON-serialisable dictionary representing the generator's
                current state.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.scan.stepped_generator import SteppedScanGenerator
            >>> gen = SteppedScanGenerator(start=1.0, stages=[(2.0, 0.5, True)])
            >>> d = gen.to_json()
            >>> d["type"]
            'SteppedScanGenerator'
            >>> d["start"]
            1.0
        """

    @classmethod
    def from_json(cls, data: dict[str, Any], parent: QObject | None = None) -> BaseScanGenerator:
        """Reconstruct a scan generator from a serialised dict produced by :meth:`to_json`.

        Dispatches to the appropriate concrete subclass based on the value of
        ``data["type"]``.  Raises :exc:`ValueError` if the type is unknown.

        Args:
            data (dict[str, Any]):
                Serialised generator dict as produced by :meth:`to_json`.

        Keyword Parameters:
            parent (QObject | None):
                Optional Qt parent for the new generator instance.

        Returns:
            (BaseScanGenerator):
                A fully configured scan generator instance.

        Raises:
            ValueError:
                If ``data["type"]`` does not match any registered generator class.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.scan.stepped_generator import SteppedScanGenerator
            >>> gen = SteppedScanGenerator(start=0.5, stages=[(1.0, 0.25, True)])
            >>> restored = BaseScanGenerator.from_json(gen.to_json())
            >>> restored.start
            0.5
            >>> restored.stages
            [(1.0, 0.25, True)]
        """
        from stoner_measurement.scan.arbitrary_function_generator import (
            ArbitraryFunctionScanGenerator,
        )
        from stoner_measurement.scan.function_generator import FunctionScanGenerator
        from stoner_measurement.scan.list_generator import ListScanGenerator
        from stoner_measurement.scan.ramp_generator import RampScanGenerator
        from stoner_measurement.scan.stepped_generator import SteppedScanGenerator

        _REGISTRY: dict[str, type[BaseScanGenerator]] = {
            "ArbitraryFunctionScanGenerator": ArbitraryFunctionScanGenerator,
            "FunctionScanGenerator": FunctionScanGenerator,
            "ListScanGenerator": ListScanGenerator,
            "RampScanGenerator": RampScanGenerator,
            "SteppedScanGenerator": SteppedScanGenerator,
        }
        type_name = data.get("type", "")
        gen_cls = _REGISTRY.get(type_name)
        if gen_cls is None:
            raise ValueError(f"Unknown scan generator type: {type_name!r}. " f"Expected one of: {sorted(_REGISTRY)}")
        return gen_cls._from_json_data(data, parent)  # noqa: SLF001

    @classmethod
    def _from_json_data(cls, data: dict[str, Any], parent: QObject | None = None) -> BaseScanGenerator:
        """Reconstruct an instance of *this* class from *data*.

        Concrete subclasses must override this classmethod to read their
        specific parameters from *data* and return a fully configured instance.

        Args:
            data (dict[str, Any]):
                Serialised generator dict as produced by :meth:`to_json`.

        Keyword Parameters:
            parent (QObject | None):
                Optional Qt parent for the new generator instance.

        Returns:
            (BaseScanGenerator):
                A fully configured instance of this generator class.
        """
        raise NotImplementedError(f"{cls.__name__} must implement _from_json_data()")

    @abstractmethod
    def generate(self) -> np.ndarray:
        """Compute and return the full sequence of output values.

        Returns:
            (np.ndarray):
                A 1-D array of values representing the scan sequence.
        """

    @abstractmethod
    def measure_flags(self) -> np.ndarray:
        """Compute and return the per-point measure flags.

        Each element in the returned array corresponds to the point at the
        same index in :meth:`generate` and indicates whether that point
        should be recorded as a measurement (``True``) or used only to
        update experimental state without being recorded (``False``).

        Returns:
            (np.ndarray):
                A 1-D boolean array of the same length as :meth:`generate`.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.scan.function_generator import FunctionScanGenerator
            >>> gen = FunctionScanGenerator(num_points=5)
            >>> flags = gen.measure_flags()
            >>> flags.dtype == bool
            True
            >>> flags.tolist()
            [True, True, True, True, True]
        """

    @abstractmethod
    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a :class:`QWidget` for configuring this scan generator.

        Keyword Parameters:
            parent (QWidget | None):
                Optional Qt parent widget.

        Returns:
            (QWidget):
                The configuration widget for this generator.
        """

    @property
    def values(self) -> np.ndarray:
        """Cached sequence of output values.

        The result of :meth:`generate` is cached on first access and
        invalidated whenever a parameter changes (via
        :meth:`_invalidate_cache`).

        Returns:
            (np.ndarray):
                A 1-D array of generated values.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> import numpy as np
            >>> from stoner_measurement.scan.function_generator import FunctionScanGenerator
            >>> gen = FunctionScanGenerator()
            >>> isinstance(gen.values, np.ndarray)
            True
        """
        if self._cache is None:
            self._cache = self.generate()
        return self._cache

    @property
    def flags(self) -> np.ndarray:
        """Cached per-point measure flags.

        The result of :meth:`measure_flags` is cached on first access and
        invalidated whenever a parameter changes (via
        :meth:`_invalidate_cache`).  Each element is ``True`` when the
        corresponding point should be recorded as a measurement.

        Returns:
            (np.ndarray):
                A 1-D boolean array of per-point measure flags.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.scan.function_generator import FunctionScanGenerator
            >>> gen = FunctionScanGenerator(num_points=3)
            >>> gen.flags.tolist()
            [True, True, True]
        """
        if self._flags_cache is None:
            self._flags_cache = self.measure_flags()
        return self._flags_cache

    def _invalidate_cache(self) -> None:
        """Invalidate the cached values and flags, and emit :attr:`values_changed`."""
        self._cache = None
        self._flags_cache = None
        self._stage_indices_cache = None
        self.values_changed.emit()

    def stage_indices(self) -> np.ndarray:
        """Compute and return per-point stage indices.

        The default implementation reports all points as belonging to stage
        ``0``.  Scan generators with explicit stage boundaries should override
        this method.

        Returns:
            (np.ndarray):
                A 1-D integer array of the same length as :meth:`generate`.
        """
        return np.zeros(len(self.values), dtype=int)

    @property
    def point_stage_indices(self) -> np.ndarray:
        """Cached per-point stage indices.

        Returns:
            (np.ndarray):
                A 1-D integer array aligned with :attr:`values`.
        """
        if self._stage_indices_cache is None:
            self._stage_indices_cache = self.stage_indices()
        return self._stage_indices_cache

    def reset(self) -> None:
        """Reset the iterator to the beginning of the sequence.

        After calling :meth:`reset`, the next call to :meth:`__next__` will return
        the first value in the sequence.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.scan.function_generator import FunctionScanGenerator
            >>> gen = FunctionScanGenerator(num_points=5)
            >>> it = iter(gen)
            >>> _ = next(it)
            >>> _ = next(it)
            >>> gen.reset()
            >>> gen._index
            0
        """
        self._index = 0

    def __len__(self) -> int:
        """Return the number of points in the sequence.

        Returns:
            (int):
                The number of values produced by this generator.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.scan.function_generator import FunctionScanGenerator
            >>> gen = FunctionScanGenerator(num_points=10)
            >>> len(gen)
            10
        """
        return len(self.values)

    def __iter__(self) -> BaseScanGenerator:
        """Reset the internal index and return *self* as an iterator.

        Returns:
            (BaseScanGenerator):
                This generator, ready to iterate from the first value.
        """
        self._index = 0
        return self

    def __next__(self) -> tuple[int, float, bool, int]:
        """Return index, value, measure flag, and stage for the next point.

        Also emits :attr:`current_value_changed` with the current output
        value so that connected widgets can update a position indicator.

        Returns:
            (int):
                The zero-based index of the current point in the sequence.
            (float):
                The next output value.
            (bool):
                Whether this point should be recorded as a measurement.
            (int):
                Stage index from which this point originates.

        Raises:
            StopIteration:
                When all values have been yielded.
        """
        if self._index >= len(self.values):
            raise StopIteration
        index = self._index
        value = float(self.values[self._index])
        measure = bool(self.flags[self._index])
        stage = int(self.point_stage_indices[self._index])
        self._index += 1
        self.current_value_changed.emit(value)
        return index, value, measure, stage
