"""Base classes for state-sweep generators.

Provides the abstract :class:`BaseSweepGenerator` API used by state-sweep
plugins, including iteration/signalling behaviour and JSON serialisation hooks
for concrete sweep-generator implementations.
"""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from qtpy.QtCore import QObject
from stoner_measurement.qt_compat import pyqtSignal
from qtpy.QtWidgets import QWidget

if TYPE_CHECKING:
    from stoner_measurement.plugins.state_sweep.base import StateSweepPlugin


class _ABCQObjectMeta(type(QObject), ABCMeta):
    """Combined metaclass for QObject and ABCMeta."""


class BaseSweepGenerator(QObject, metaclass=_ABCQObjectMeta):
    """Abstract base class for generators used by state-sweep plugins.

    Iteration yields ``(index, value, stage, measure_flag)`` tuples. On each
    yielded point:

    - :attr:`current_value_changed` emits the current value
    - :attr:`current_point_changed` emits ``(index, value, stage)``

    The additional *stage* field lets preview widgets disambiguate repeated
    values that may occur in different sweep segments.

    Args:
        state_sweep (StateSweepPlugin | None):
            Owning state-sweep plugin used by the generator to query and/or
            drive the controlled state.
        parent (QObject | None):
            Optional Qt parent object.

    Attributes:
        values_changed:
            Qt signal emitted when the configured sweep values change and any
            dependent preview or cached iteration state should be refreshed.
        current_value_changed:
            Qt signal emitted with the current numeric value after each yielded
            point.
        current_point_changed:
            Qt signal emitted with ``(index, value, stage)`` after each yielded
            point.

    Notes:
        Concrete subclasses must implement :meth:`iter_points`,
        :meth:`config_widget`, and :meth:`_from_json_data`.
    """

    values_changed = pyqtSignal()
    current_value_changed = pyqtSignal(float)
    current_point_changed = pyqtSignal(int, float, int)

    def __init__(self, *, state_sweep: StateSweepPlugin | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state_sweep = state_sweep
        self._iterator: Iterator[tuple[int, float, int, bool]] | None = None

    @property
    def state_sweep(self) -> StateSweepPlugin | None:
        """Return the owning state-sweep plugin.

        Returns:
            (StateSweepPlugin | None):
                The owning state-sweep plugin, or ``None`` if this generator is
                not currently attached to one.
        """
        return self._state_sweep

    @state_sweep.setter
    def state_sweep(self, plugin: StateSweepPlugin | None) -> None:
        """Attach the generator to a state-sweep plugin.

        Args:
            plugin (StateSweepPlugin | None):
                Owning state-sweep plugin, or ``None`` to detach the generator.
        """
        self._state_sweep = plugin
        self.reset()

    def reset(self) -> None:
        """Reset cached iteration state."""
        self._iterator = None

    def __iter__(self) -> BaseSweepGenerator:
        """Return an iterator over sweep points.

        Returns:
            (BaseSweepGenerator):
                ``self``, reset to the beginning of the configured sweep.
        """
        self.reset()
        return self

    def __next__(self) -> tuple[int, float, int, bool]:
        """Return the next sweep point and emit the corresponding signals.

        Returns:
            (tuple[int, float, int, bool]):
                The next ``(index, value, stage, measure_flag)`` tuple from the
                concrete generator implementation.

        Raises:
            StopIteration:
                If the underlying point iterator is exhausted.
        """
        if self._iterator is None:
            self._iterator = iter(self.iter_points())
        ix, value, stage, measure_flag = next(self._iterator)
        self.current_value_changed.emit(float(value))
        self.current_point_changed.emit(int(ix), float(value), int(stage))
        return int(ix), float(value), int(stage), bool(measure_flag)

    @abstractmethod
    def iter_points(self) -> Iterator[tuple[int, float, int, bool]]:
        """Yield configured sweep points.

        Yields:
            (tuple[int, float, int, bool]):
                Successive ``(index, value, stage, measure_flag)`` tuples.
        """

    @abstractmethod
    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return a Qt widget for configuring this generator.

        Args:
            parent (QWidget | None):
                Optional parent widget.

        Returns:
            (QWidget):
                Configuration widget bound to this generator instance.
        """

    def _invalidate(self) -> None:
        """Reset cached iteration state and notify observers."""
        self.reset()
        self.values_changed.emit()

    @property
    def rate_time_scale_seconds(self) -> float:
        """Return seconds represented by one unit of configured rate time.

        This hook lets generator timing remain generic while concrete
        state-sweep plugins define the time basis used by their rate values.
        For example, a plugin using ``T/min`` or ``K/min`` rates can return
        ``60.0``, while a plugin using ``deg/s`` rates can return ``1.0``.

        Returns:
            (float):
                Multiplicative factor converting ``distance / rate`` into
                seconds.
        """
        plugin = self.state_sweep
        if plugin is None:
            return 1.0
        return max(0.0, float(getattr(plugin, "sweep_rate_time_scale_seconds", 1.0)))

    def duration_seconds_for_distance_rate(self, distance: float, rate: float) -> float:
        """Return the duration in seconds for *distance* travelled at *rate*.

        Args:
            distance (float):
                Absolute or signed travel distance in the controlled quantity's
                native units.
            rate (float):
                Travel rate expressed in the owning plugin's configured rate
                units, such as ``T/min``, ``K/min``, or ``deg/s``.

        Returns:
            (float): Travel duration in seconds, or ``inf`` for zero rate.
        """
        rate_magnitude = abs(float(rate))
        if rate_magnitude <= 0.0:
            return float("inf")
        return abs(float(distance)) / rate_magnitude * self.rate_time_scale_seconds

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
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.sweep import MonitorAndFilterSweepGenerator
            >>> import math
            >>> gen = MonitorAndFilterSweepGenerator()
            >>> math.isinf(gen.estimated_duration())
            True
        """
        return float("inf")

    def to_json(self) -> dict[str, Any]:
        """Serialise this generator configuration.

        Returns:
            (dict[str, Any]):
                JSON-serialisable configuration mapping.
        """
        return {"type": type(self).__name__}

    @classmethod
    def from_json(
        cls,
        data: dict[str, Any],
        *,
        state_sweep: StateSweepPlugin | None = None,
        parent: QObject | None = None,
    ) -> BaseSweepGenerator:
        """Reconstruct a sweep generator from serialised data.

        Args:
            data (dict[str, Any]):
                Serialised generator configuration.
            state_sweep (StateSweepPlugin | None):
                Owning state-sweep plugin for the reconstructed generator.
            parent (QObject | None):
                Optional Qt parent object.

        Returns:
            (BaseSweepGenerator):
                Reconstructed concrete sweep-generator instance.

        Raises:
            ValueError:
                If ``data`` names an unknown generator type.
        """
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
        """Reconstruct an instance of this generator class from serialised data.

        Args:
            data (dict[str, Any]):
                Serialised generator configuration.
            state_sweep (StateSweepPlugin | None):
                Owning state-sweep plugin for the reconstructed generator.
            parent (QObject | None):
                Optional Qt parent object.

        Raises:
            NotImplementedError:
                Always, unless overridden by a concrete subclass.
        """
        raise NotImplementedError(f"{cls.__name__} must implement _from_json_data().")
