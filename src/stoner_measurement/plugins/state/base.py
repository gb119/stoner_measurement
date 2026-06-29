"""StatePlugin — abstract common ancestor for state-scan and state-sweep plugins.

Both :class:`~stoner_measurement.plugins.state_scan.base.StateScanPlugin` and
:class:`~stoner_measurement.plugins.state_sweep.base.StateSweepPlugin` share a
common set of fields and methods that are defined here once and inherited by
both families:

* iteration state (``ix``, ``value``, ``stage``, ``meas_flag``)
* data-collection settings and the collected :class:`~pandas.DataFrame`
* ``collect()`` / ``clear_data()`` lifecycle helpers
* ``instance_name_changed`` signal with auto-update of ``collect_filter``
* ``state_changed``, ``state_reached``, ``state_error`` progress signals
* ``limits`` property (default: no limits)
* abstract ``state_name`` and ``units`` properties
* NOP instrument-lifecycle hooks (``connect``, ``configure``, ``disconnect``)
* ``reported_values()`` helper
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, SupportsInt

import pandas as pd
from qtpy.QtCore import QObject
from stoner_measurement.qt_compat import pyqtSignal

from stoner_measurement.plugins.base_plugin import BasePlugin, _ABCQObjectMeta
from stoner_measurement.plugins.sequence.base import SequencePlugin


class StatePlugin(QObject, SequencePlugin, metaclass=_ABCQObjectMeta):
    """Abstract base class shared by :class:`~stoner_measurement.plugins.state_scan.base.StateScanPlugin`
    and :class:`~stoner_measurement.plugins.state_sweep.base.StateSweepPlugin`.

    This class owns all state, data-collection infrastructure, and abstract
    interface that is common to both plugin families.  It should not be
    subclassed directly — use :class:`~stoner_measurement.plugins.state_scan.base.StateScanPlugin`
    for discrete-step, ramp-to-target scanning, or
    :class:`~stoner_measurement.plugins.state_sweep.base.StateSweepPlugin` for
    generator-driven continuous-sweep loops.

    Attributes:
        ix (int):
            Zero-based index of the current iteration step.
        value (float):
            Current set-point value at the most recent iteration step.
        stage (int):
            Stage index within the current iteration step.
        meas_flag (bool):
            Whether the current step should be recorded as a measurement.
        collect_data (bool):
            When ``True``, :meth:`collect` is called at each iteration step.
            Defaults to ``False``.
        clear_on_start (bool):
            When ``True``, :meth:`clear_data` is called before the loop begins.
            Defaults to ``True``.
        collect_filter (str):
            Python expression evaluated by :meth:`collect` to decide whether
            a data point should be stored.  Defaults to
            ``"{instance_name}.meas_flag"``.
        clear_filter (str):
            Python expression evaluated by :meth:`clear_data` to decide
            whether the collected data should be cleared.  Defaults to
            ``"True"``.
        data (pandas.DataFrame):
            Accumulated measurement data.  The index is :attr:`ix`; the first
            two columns are ``value`` and ``stage``; subsequent columns are the
            evaluated outputs from the sequence engine's values catalogue.
        instance_name_changed (pyqtSignal[str, str]):
            Emitted when :attr:`~stoner_measurement.plugins.base_plugin.BasePlugin.instance_name`
            changes.  Arguments are the old name and the new name.
        state_changed (pyqtSignal[float]):
            Emitted with the current measured value each time the hardware
            state is sampled during a ramp or sweep.
        state_reached (pyqtSignal[float]):
            Emitted once when the target set-point has been reached.
        state_error (pyqtSignal[str]):
            Emitted if the hardware faults, a timeout is exceeded, or a
            measured value falls outside :attr:`limits`.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.state_scan import StateScanPlugin
        >>> class _S(StateScanPlugin):
        ...     @property
        ...     def name(self): return "S"
        ...     @property
        ...     def state_name(self): return "X"
        ...     @property
        ...     def units(self): return "au"
        ...     def set_state(self, v): self._v = float(v)
        ...     def get_state(self): return getattr(self, "_v", 0.0)
        ...     def is_at_target(self): return True
        >>> import pandas as pd
        >>> p = _S()
        >>> isinstance(p.data, pd.DataFrame)
        True
        >>> p.data.empty
        True
        >>> p.limits
        (-inf, inf)
    """

    instance_name_changed = pyqtSignal(str, str)
    comment_changed = pyqtSignal(str, str)
    state_changed = pyqtSignal(float)
    state_reached = pyqtSignal(float)
    state_error = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise shared iteration state and data-collection fields."""
        super().__init__(parent)
        self.ix: int = 0
        self.value: float = 0.0
        self.meas_flag: bool = False
        self.stage: int = 0
        self.collect_data: bool = False
        self.clear_on_start: bool = True
        self.collect_filter: str = f"{self.instance_name}.meas_flag"
        self.clear_filter: str = "True"
        self.collect_outputs: list[str] | None = None
        self._data: pd.DataFrame = pd.DataFrame()
        self._cached_config_tabs: list | None = None

    @property
    def index(self) -> int:
        """Current zero-based iteration index.

        Returns:
            (int):
                The current iteration index.
        """
        return int(self.ix)

    @index.setter
    def index(self, value: SupportsInt) -> None:
        """Set the current zero-based iteration index from an int-coercible value.

        Args:
            value (typing.SupportsInt):
                The value to coerce and store as the current iteration index.
        """
        self.ix = int(value)

    def _on_instance_name_changed(self, old_name: str, new_name: str) -> None:
        """Emit :attr:`instance_name_changed` and auto-update :attr:`collect_filter`."""
        default_filter = f"{old_name}.meas_flag"
        if self.collect_filter == default_filter:
            self.collect_filter = f"{new_name}.meas_flag"
        self.instance_name_changed.emit(old_name, new_name)

    def _on_comment_changed(self, old_comment: str, new_comment: str) -> None:
        """Emit :attr:`comment_changed` when the comment changes."""
        self.comment_changed.emit(old_comment, new_comment)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def state_name(self) -> str:
        """Human-readable name of the controlled or swept physical quantity.

        Returns:
            (str):
                E.g. ``"Magnetic Field"``, ``"Temperature"``, ``"Time"``.
        """

    @property
    @abstractmethod
    def units(self) -> str:
        """Physical unit of the controlled or swept quantity.

        Returns:
            (str):
                E.g. ``"T"``, ``"K"``, ``"s"``.
        """

    # ------------------------------------------------------------------
    # Limits
    # ------------------------------------------------------------------

    @property
    def limits(self) -> tuple[float, float]:
        """Allowed set-point or measured-value range ``(minimum, maximum)``.

        Subclasses may override this to enforce hardware safety limits.
        The default is ``(-inf, inf)`` (no limits).

        :class:`~stoner_measurement.plugins.state_scan.base.StateScanPlugin`
        uses this in :meth:`~stoner_measurement.plugins.state_scan.base.StateScanPlugin.ramp_to`
        to reject out-of-range targets.
        :class:`~stoner_measurement.plugins.state_sweep.base.StateSweepPlugin`
        uses this in its iteration loop to stop the sweep if a sampled value
        goes out of range.

        Returns:
            (tuple[float, float]):
                ``(min_value, max_value)`` in the units of :attr:`units`.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> CounterPlugin().limits
            (-inf, inf)
        """
        return (float("-inf"), float("inf"))

    # ------------------------------------------------------------------
    # Instrument lifecycle NOPs
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open instrument connections (NOP default)."""

    def configure(self) -> None:
        """Configure the instrument (NOP default)."""

    def disconnect(self) -> None:
        """Release instrument resources (NOP default)."""

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------

    @property
    def data(self) -> pd.DataFrame:
        """Accumulated measurement data collected during the iteration loop.

        The :class:`~pandas.DataFrame` index is the iterator index
        (:attr:`ix`).  The first two columns are ``value`` and ``stage``;
        subsequent columns contain the evaluated outputs from the sequence
        engine's values catalogue.  Populated by :meth:`collect` and reset by
        :meth:`clear_data`.

        Returns:
            (pandas.DataFrame):
                The accumulated data, or an empty DataFrame if no data has
                been collected or the data has been cleared.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> p = CounterPlugin()
            >>> import pandas as pd
            >>> isinstance(p.data, pd.DataFrame)
            True
            >>> p.data.empty
            True
        """
        return self._data

    def clear_data(self) -> None:
        """Clear the collected data if :attr:`clear_filter` evaluates to ``True``.

        Evaluates :attr:`clear_filter` in the sequence engine namespace.  If
        the result is truthy, :attr:`data` is reset to an empty
        :class:`~pandas.DataFrame`.  If the plugin is not attached to an engine
        the data is always cleared unconditionally.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> import pandas as pd
            >>> p = CounterPlugin()
            >>> p._data = pd.DataFrame([{"value": 1.0}])
            >>> p.clear_data()
            >>> p.data.empty
            True
        """
        try:
            should_clear = bool(self.eval(self.clear_filter))
        except RuntimeError:
            should_clear = True
        if should_clear:
            self._data = pd.DataFrame()

    def collect(self, outputs: list[str] | None = None) -> None:
        """Append a row of current output values to :attr:`data`.

        Only collects when :attr:`meas_flag` is ``True`` **and** the plugin is
        attached to a sequence engine (i.e. :attr:`sequence_engine` is not
        ``None``).  Both conditions must be met.  Evaluates
        :attr:`collect_filter`; if truthy, appends a row to :attr:`data` keyed
        by :attr:`ix`.  The row contains :attr:`value` and :attr:`stage`,
        followed by evaluated outputs from the engine's values catalogue.

        Keyword Parameters:
            outputs (list[str] | None):
                Optional list of output names to include.  Resolution order is:
                explicit ``outputs`` argument first; then
                :attr:`collect_outputs` when set; otherwise all values-catalogue
                entries.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> from stoner_measurement.core.sequence_engine import SequenceEngine
            >>> engine = SequenceEngine()
            >>> p = CounterPlugin()
            >>> engine.add_plugin("counter", p)
            >>> p.collect_filter = "True"
            >>> p.meas_flag = True
            >>> p.ix = 0
            >>> p.value = 1.5
            >>> p.collect()
            >>> p.data.index.tolist()
            [0]
            >>> float(p.data["value"].iloc[0])
            1.5
            >>> engine.shutdown()
        """
        if not self.meas_flag or self.sequence_engine is None:
            return
        try:
            should_collect = bool(self.eval(self.collect_filter))
        except (RuntimeError, SyntaxError, ValueError):
            should_collect = False
        if not should_collect:
            return

        ns = self.engine_namespace
        values_cat: dict[str, str] = ns.get("_values", {})
        if outputs is not None:
            keys = [k for k in outputs if k in values_cat]
        elif self.collect_outputs is None:
            keys = list(values_cat.keys())
        else:
            keys = [k for k in self.collect_outputs if k in values_cat]

        row: dict[str, Any] = {"value": self.value, "stage": self.stage}
        for key in keys:
            expr = values_cat[key]
            try:
                row[key] = self.eval(expr)
            except (RuntimeError, SyntaxError, ValueError, NameError, AttributeError) as exc:
                self.log.warning("collect(): failed to evaluate %r: %s", expr, exc)
                row[key] = None

        new_row = pd.DataFrame([row], index=[self.ix])
        self._data = new_row if self._data.empty else pd.concat([self._data, new_row])

    # ------------------------------------------------------------------
    # JSON serialisation (shared fields)
    # ------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """Serialise shared data-collection settings into the plugin dict.

        Extends the base :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`
        dict with ``collect_data``, ``clear_on_start``, ``collect_filter``, and
        ``clear_filter``.  Subclasses call ``super().to_json()`` and add their
        own generator-specific keys.

        Returns:
            (dict[str, Any]):
                JSON-serialisable dict with the shared data-collection keys.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> d = CounterPlugin().to_json()
            >>> d["collect_data"]
            False
            >>> d["clear_on_start"]
            True
        """
        data = super().to_json()
        data["collect_data"] = self.collect_data
        data["clear_on_start"] = self.clear_on_start
        data["collect_filter"] = self.collect_filter
        data["clear_filter"] = self.clear_filter
        data["collect_outputs"] = None if self.collect_outputs is None else list(self.collect_outputs)
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore shared data-collection settings from *data*.

        Called by :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.from_json`.
        Subclasses should call ``super()._restore_from_json(data)`` and then
        restore their own generator-specific fields.

        Args:
            data (dict[str, Any]):
                Serialised plugin dict as produced by :meth:`to_json`.
        """
        super()._restore_from_json(data)
        if "collect_data" in data:
            self.collect_data = bool(data["collect_data"])
        if "clear_on_start" in data:
            self.clear_on_start = bool(data["clear_on_start"])
        if "collect_filter" in data:
            self.collect_filter = str(data["collect_filter"])
        if "clear_filter" in data:
            self.clear_filter = str(data["clear_filter"])
        if "collect_outputs" in data:
            raw = data["collect_outputs"]
            if raw is None:
                self.collect_outputs = None
            elif isinstance(raw, list):
                self.collect_outputs = [str(item) for item in raw]
            else:
                self.collect_outputs = None

    # ------------------------------------------------------------------
    # Member plugins
    # ------------------------------------------------------------------

    def member_plugins(self) -> list[BasePlugin]:
        """Return child :class:`~stoner_measurement.plugins.base_plugin.BasePlugin` instances from sub-steps.

        Both :class:`~stoner_measurement.plugins.state_scan.base.StateScanPlugin`
        and :class:`~stoner_measurement.plugins.state_sweep.base.StateSweepPlugin`
        are sequence containers that may own nested child plugins as sub-steps.
        This override exposes those child plugin instances so that
        :meth:`~stoner_measurement.core.sequence_engine.SequenceEngine.sequence_plugins`
        can discover them recursively.

        Only the **direct** children stored in :attr:`sub_steps` are returned;
        recursion into their own sub-steps is handled by the engine calling
        :meth:`member_plugins` on each returned child in turn.

        Returns:
            (list[BasePlugin]):
                Ordered list of directly owned child plugin instances.  Returns
                an empty list when :attr:`sub_steps` is empty or contains only
                string entry-point descriptors.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> p = CounterPlugin()
            >>> p.member_plugins()
            []
        """
        result: list[BasePlugin] = []
        for step in self.sub_steps:
            plugin_or_name = step[0] if isinstance(step, tuple) else step
            if isinstance(plugin_or_name, BasePlugin):
                result.append(plugin_or_name)
        return result

    # ------------------------------------------------------------------
    # Reported values
    # ------------------------------------------------------------------

    def reported_values(self) -> dict[str, str]:
        """Return a mapping of the state quantity to a Python expression.

        Reports the current iteration set-point as a scalar value, accessible
        via ``"{instance_name}.value"``, and the current iteration index via
        ``"{instance_name}.index"``.

        Returns:
            (dict[str, str]):
                Two-entry dict with ``"{instance_name}:{state_name}"`` and
                ``"{instance_name}:Index"`` mappings.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> p = CounterPlugin()
            >>> vals = p.reported_values()
            >>> list(vals.keys())
            ['counter:Value', 'counter:Index']
            >>> vals['counter:Value']
            'counter.value'
            >>> vals['counter:Index']
            'counter.index'
        """
        var = self.instance_name
        return {
            f"{var}:{self.state_name}": f"{var}.value",
            f"{var}:Index": f"{var}.index",
        }
