"""Abstract base class for scan generators.

Scan generators produce a sequence of values that are sent to instruments
to control an experiment. All generators share a common iterator interface,
a caching mechanism, and a Qt widget for configuration.
"""

from __future__ import annotations

from abc import ABCMeta, abstractmethod

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget


class _ABCQObjectMeta(type(QObject), ABCMeta):
    """Combined metaclass that resolves the conflict between QObject and ABCMeta."""


class BaseScanGenerator(QObject, metaclass=_ABCQObjectMeta):
    """Abstract base class for all scan generators.

    A scan generator produces a sequence of output values that are sent to
    instruments to control an experiment.  Subclasses must implement
    :meth:`generate` and :meth:`config_widget`.

    The class provides:

    * **Iterator interface** — :meth:`__iter__` and :meth:`__next__` allow
      direct iteration over the generated values; :meth:`reset` restarts
      iteration.
    * **Value caching** — :attr:`values` calls :meth:`generate` on first
      access and caches the result until a parameter changes.
    * **Change notification** — the :attr:`values_changed` signal is emitted
      whenever a parameter is updated.

    Attributes:
        values_changed (pyqtSignal):
            Emitted when the sequence of values changes due to a parameter
            update.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.
    """

    values_changed = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the generator state."""
        super().__init__(parent)
        self._cache: np.ndarray | None = None
        self._index: int = 0

    @abstractmethod
    def generate(self) -> np.ndarray:
        """Compute and return the full sequence of output values.

        Returns:
            (np.ndarray):
                A 1-D array of values representing the scan sequence.
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

    def _invalidate_cache(self) -> None:
        """Invalidate the cached values and emit :attr:`values_changed`."""
        self._cache = None
        self.values_changed.emit()

    def reset(self) -> None:
        """Reset the iterator to the beginning of the sequence.

        After calling :meth:`reset`, the next call to :func:`next` will return
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

    def __next__(self) -> float:
        """Return the next value in the sequence.

        Returns:
            (float):
                The next output value.

        Raises:
            StopIteration:
                When all values have been yielded.
        """
        if self._index >= len(self.values):
            raise StopIteration
        value = float(self.values[self._index])
        self._index += 1
        return value
