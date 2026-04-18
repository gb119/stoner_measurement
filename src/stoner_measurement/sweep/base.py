"""Base classes for state-sweep generators."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QWidget

if TYPE_CHECKING:
    from stoner_measurement.plugins.state_sweep.base import StateSweepPlugin


class _ABCQObjectMeta(type(QObject), ABCMeta):
    """Combined metaclass for QObject and ABCMeta."""


class BaseSweepGenerator(QObject, metaclass=_ABCQObjectMeta):
    """Abstract base class for generators used by state-sweep plugins."""

    values_changed = pyqtSignal()
    current_value_changed = pyqtSignal(float)

    def __init__(self, *, state_sweep: StateSweepPlugin | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state_sweep = state_sweep
        self._iterator: Iterator[tuple[int, float, int, bool]] | None = None

    @property
    def state_sweep(self) -> StateSweepPlugin | None:
        """Owning state-sweep plugin."""
        return self._state_sweep

    @state_sweep.setter
    def state_sweep(self, plugin: StateSweepPlugin | None) -> None:
        self._state_sweep = plugin
        self.reset()

    def reset(self) -> None:
        """Reset iteration state."""
        self._iterator = None

    def __iter__(self) -> BaseSweepGenerator:
        self.reset()
        return self

    def __next__(self) -> tuple[int, float, int, bool]:
        if self._iterator is None:
            self._iterator = iter(self.iter_points())
        ix, value, stage, measure_flag = next(self._iterator)
        self.current_value_changed.emit(float(value))
        return int(ix), float(value), int(stage), bool(measure_flag)

    @abstractmethod
    def iter_points(self) -> Iterator[tuple[int, float, int, bool]]:
        """Yield ``(index, value, stage, measure_flag)`` tuples."""

    @abstractmethod
    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a Qt widget for configuring this generator."""

    def _invalidate(self) -> None:
        """Reset cached iteration state and notify observers."""
        self.reset()
        self.values_changed.emit()

    def estimated_duration(self) -> float:
        """Return an estimate of how long the sweep will take, in seconds.

        The default implementation returns ``float("inf")`` (unknown duration),
        which effectively disables any timeout that is calculated from this
        value.  Concrete generators that have enough information to predict
        their duration should override this method.

        Returns:
            (float):
                Estimated sweep duration in seconds, or ``float("inf")`` if
                the duration cannot be determined.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.sweep import MonitorAndFilterSweepGenerator
            >>> import math
            >>> gen = MonitorAndFilterSweepGenerator()
            >>> math.isinf(gen.estimated_duration())
            True
        """
        return float("inf")

    def to_json(self) -> dict[str, Any]:
        """Serialise this generator configuration."""
        return {"type": type(self).__name__}

    @classmethod
    def from_json(
        cls,
        data: dict[str, Any],
        *,
        state_sweep: StateSweepPlugin | None = None,
        parent: QObject | None = None,
    ) -> BaseSweepGenerator:
        """Reconstruct a sweep generator from serialised data."""
        from stoner_measurement.sweep.monitor_and_filter_generator import (
            MonitorAndFilterSweepGenerator,
        )
        from stoner_measurement.sweep.multisegment_ramp_generator import (
            MultiSegmentRampSweepGenerator,
        )

        registry: dict[str, type[BaseSweepGenerator]] = {
            "MonitorAndFilterSweepGenerator": MonitorAndFilterSweepGenerator,
            "MultiSegmentRampSweepGenerator": MultiSegmentRampSweepGenerator,
        }
        type_name = str(data.get("type", ""))
        gen_cls = registry.get(type_name)
        if gen_cls is None:
            raise ValueError(f"Unknown sweep generator type: {type_name!r}. Expected one of: {sorted(registry)}")
        return gen_cls._from_json_data(data, state_sweep=state_sweep, parent=parent)

    @classmethod
    def _from_json_data(
        cls,
        data: dict[str, Any],
        *,
        state_sweep: StateSweepPlugin | None = None,
        parent: QObject | None = None,
    ) -> BaseSweepGenerator:
        """Reconstruct an instance of this generator class from serialised data."""
        raise NotImplementedError(f"{cls.__name__} must implement _from_json_data().")
