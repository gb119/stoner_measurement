"""StatePlugin — abstract common ancestor for state-scan and state-sweep plugins.

Both :class:`~stoner_measurement.plugins.state_scan.base.StateScanPlugin` and
:class:`~stoner_measurement.plugins.state_sweep.base.StateSweepPlugin` share a
common set of fields and methods that are defined here once and inherited by
both families:

* iteration state (``ix``, ``value``, ``stage``, ``meas_flag``)
* data-collection settings and the collected :class:`~stoner_measurement.core.TraceData`
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

from stoner_measurement.core.trace_data import (
    COLUMN_ROLE_D,
    COLUMN_ROLE_E,
    COLUMN_ROLE_X,
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
)
from stoner_measurement.plugins.base_plugin import BasePlugin, _ABCQObjectMeta
from stoner_measurement.plugins.sequence.base import SequencePlugin
from stoner_measurement.qt_compat import pyqtSignal


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
        collect_output_roles (dict[str, str]):
            Per-output role choices from the configuration table. ``"x"``
            promotes a measured readback to the trace x axis; ``"d"``,
            ``"y"``, and ``"e"`` set data-column roles; ``"-"`` leaves the
            role unspecified for the normal fallback heuristics.
        data (TraceData):
            Accumulated measurement data.  The controlled state is the shared
            x axis; ``iteration`` and ``stage`` are auxiliary columns and the
            remaining columns are evaluated sequence outputs.
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
        >>> p = _S()
        >>> isinstance(p.data, TraceData)
        True
        >>> p.data.df.empty
        True
        >>> p.limits
        (-inf, inf)
    """

    @property
    def is_loop_container(self) -> bool:
        """Return ``True`` because scan and sweep children run in a loop."""
        return True

    instance_name_changed = pyqtSignal(str, str)
    comment_changed = pyqtSignal(str, str)
    state_changed = pyqtSignal(float)
    state_reached = pyqtSignal(float)
    state_error = pyqtSignal(str)
    engine_cache_max_age_seconds: float = 5.0

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise shared iteration state and data-collection fields."""
        super().__init__(parent)
        self.ix: int = 0
        self.value: float = 0.0
        self.meas_flag: bool = False
        self.stage: int = 0
        self._collect_data: bool = False
        self.clear_on_start: bool = True
        self.start_from_current_value: bool = False
        self.collect_filter: str = f"{self.instance_name}.meas_flag"
        self.clear_filter: str = "True"
        self.collect_outputs: list[str] | None = None
        self.collect_output_roles: dict[str, str] = {}
        # Subclass state metadata may depend on fields initialised after
        # ``super().__init__`` (for example a source-mode selector).
        self._data = TraceData()
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

    @property
    def collect_data(self) -> bool:
        """Whether this state plugin collects and publishes a trace table."""
        return self._collect_data

    @collect_data.setter
    def collect_data(self, enabled: bool) -> None:
        """Enable collection and refresh the engine catalogues when attached."""
        new_value = bool(enabled)
        changed = new_value != getattr(self, "_collect_data", False)
        self._collect_data = new_value
        engine = self.sequence_engine
        if changed and engine is not None:
            engine.refresh_data_catalogs()

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
    def data(self) -> TraceData:
        """Accumulated measurement data collected during the iteration loop.

        The :class:`TraceData` x axis is the controlled or swept physical
        state.  The ``iteration`` and ``stage`` columns retain loop bookkeeping;
        subsequent columns contain evaluated outputs from the sequence engine's
        values catalogue.  Populated by :meth:`collect` and reset by
        :meth:`clear_data`.

        Returns:
            (TraceData):
                The accumulated data, or an empty TraceData if no data has
                been collected or the data has been cleared.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> import numpy as np
            >>> p = CounterPlugin()
            >>> from stoner_measurement.core import TraceData
            >>> isinstance(p.data, TraceData)
            True
            >>> p.data.df.empty
            True
        """
        if self._data.row_count == 0 and self.sequence_engine is not None:
            self._data.set_expected_schema(self.configured_trace_data())
        return self._data

    def _empty_trace_data(self) -> TraceData:
        """Return an empty collected-data table with state-axis metadata."""
        frame = pd.DataFrame({"x": pd.Series(dtype=float)})
        return TraceData(
            frame,
            column_roles={"x": COLUMN_ROLE_X},
            names={"x": self.state_name},
            units={"x": self.units},
        )

    def clear_data(self) -> None:
        """Clear the collected data if :attr:`clear_filter` evaluates to ``True``.

        Evaluates :attr:`clear_filter` in the sequence engine namespace.  If
        the result is truthy, :attr:`data` is reset to an empty
        :class:`TraceData`.  If the plugin is not attached to an engine
        the data is always cleared unconditionally.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.plugins.state_scan import CounterPlugin
            >>> import numpy as np
            >>> p = CounterPlugin()
            >>> p._data = TraceData.from_xy(np.array([0.0]), np.array([1.0]))
            >>> p.clear_data()
            >>> p.data.df.empty
            True
        """
        try:
            should_clear = bool(self.eval(self.clear_filter))
        except RuntimeError:
            should_clear = True
        if should_clear:
            self._data = self._empty_trace_data()

    def collect(self, outputs: list[str] | None = None) -> None:
        """Append a row of current output values to :attr:`data`.

        Only collects when :attr:`meas_flag` is ``True`` **and** the plugin is
        attached to a sequence engine (i.e. :attr:`sequence_engine` is not
        ``None``).  Both conditions must be met.  Evaluates
        :attr:`collect_filter`; if truthy, appends a row to :attr:`data` at the
        current state value.  The row contains ``iteration`` and ``stage``,
        followed by evaluated outputs from the engine's values catalogue. If
        a selected output has an explicit ``"x"`` role, its evaluated readback
        becomes the x axis and the commanded value is retained in an auxiliary
        ``state`` column.

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
            >>> p.data.x.tolist()
            [1.5]
            >>> int(p.data.df["iteration"].iloc[0])
            0
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
        keys = self._resolve_collect_keys(values_cat, outputs)
        output_values = self._evaluate_collect_outputs(values_cat, keys)
        explicit_x = next((key for key in keys if self.collect_output_roles.get(key) == "x"), None)
        row: dict[str, Any] = {"iteration": self.ix, "stage": self.stage}
        if explicit_x is None:
            x_value = self.value
        else:
            x_value = output_values.pop(explicit_x)
            row["state"] = self.value
        row.update(output_values)

        row = {"x": x_value, **row}
        if self._data.row_count == 0:
            self._data = self._build_collected_trace(pd.DataFrame([row]), explicit_x)
            self._data.reserve_rows(256)
        else:
            self._data.append_row(row)

    def _resolve_collect_keys(
        self, values_cat: dict[str, str], outputs: list[str] | None
    ) -> list[str]:
        """Resolve requested output keys against the current values catalogue."""
        if outputs is not None:
            requested = outputs
        elif self.collect_outputs is None:
            return list(values_cat)
        else:
            requested = self.collect_outputs
        return [key for key in requested if key in values_cat]

    def _evaluate_collect_outputs(
        self, values_cat: dict[str, str], keys: list[str]
    ) -> dict[str, Any]:
        """Evaluate selected catalogue expressions, retaining failed values as ``None``."""
        output_values: dict[str, Any] = {}
        for key in keys:
            expr = values_cat[key]
            try:
                output_values[key] = self.eval(expr)
            except (RuntimeError, SyntaxError, ValueError, NameError, AttributeError) as exc:
                self.log.warning("collect(): failed to evaluate %r: %s", expr, exc)
                output_values[key] = None
        return output_values

    def _build_collected_trace(self, frame: pd.DataFrame, explicit_x: str | None) -> TraceData:
        """Build collected trace metadata around the accumulated data frame."""
        output_columns = [
            column
            for column in frame.columns
            if column not in {"x", "iteration", "stage", "state"}
        ]
        roles = {"x": COLUMN_ROLE_X, "iteration": COLUMN_ROLE_Z, "stage": COLUMN_ROLE_Z}
        if "state" in frame.columns:
            roles["state"] = COLUMN_ROLE_Z
        role_constants = {"d": COLUMN_ROLE_D, "y": COLUMN_ROLE_Y, "e": COLUMN_ROLE_E}
        for column in output_columns:
            configured_role = self.collect_output_roles.get(column)
            if configured_role in role_constants:
                roles[column] = role_constants[configured_role]
            elif configured_role == "-":
                roles[column] = COLUMN_ROLE_Z
            else:
                roles[column] = COLUMN_ROLE_Y
        names = {
            "x": explicit_x or self.state_name,
            "iteration": "Iteration",
            "stage": "Stage",
        }
        if "state" in frame.columns:
            names["state"] = self.state_name
        names.update({column: str(column) for column in output_columns})
        units = {key: "" for key in names}
        units["state" if explicit_x is not None else "x"] = self.units
        values_cat: dict[str, str] = self.engine_namespace.get("_values", {})
        units.update(
            {
                column: str(getattr(values_cat.get(column), "units", "") or "")
                for column in output_columns
            }
        )
        return TraceData(frame, column_roles=roles, names=names, units=units)

    def configured_trace_data(self) -> TraceData:
        """Return the configured collected-data schema before acquisition.

        State scan and sweep traces are initially empty, so their live
        :class:`TraceData` cannot yet advertise the selected catalogue outputs.
        Configuration UIs use this schema-only trace to offer those channels
        before the first row has been collected.
        """
        values_cat: dict[str, str] = self.engine_namespace.get("_values", {})
        keys = self._resolve_collect_keys(values_cat, self.collect_outputs)
        explicit_x = next(
            (key for key in keys if self.collect_output_roles.get(key) == "x"), None
        )
        columns = ["x", "iteration", "stage"]
        if explicit_x is not None:
            columns.append("state")
        columns.extend(key for key in keys if key != explicit_x)
        frame = pd.DataFrame({column: pd.Series(dtype=float) for column in columns})
        return self._build_collected_trace(frame, explicit_x)

    def inferred_output_roles(self, outputs: list[str]) -> dict[str, str]:
        """Return the automatic roles used when all catalogue outputs are selected.

        The commanded scan or sweep parameter supplies the implicit x axis, so
        catalogue values retain the existing behaviour of being primary y data.
        """
        return dict.fromkeys(outputs, COLUMN_ROLE_Y)

    def reported_traces(self) -> dict[str, str]:
        """Expose collected state data through the shared trace catalogue."""
        if not self.collect_data:
            return {}
        variable = self.instance_name
        return {f"{variable}.data": f"{variable}.data"}

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
        data["start_from_current_value"] = self.start_from_current_value
        data["collect_filter"] = self.collect_filter
        data["clear_filter"] = self.clear_filter
        data["collect_outputs"] = None if self.collect_outputs is None else list(self.collect_outputs)
        data["collect_output_roles"] = dict(self.collect_output_roles)
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
        if "start_from_current_value" in data:
            self.start_from_current_value = bool(data["start_from_current_value"])
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
        raw_roles = data.get("collect_output_roles", {})
        if isinstance(raw_roles, dict):
            valid_roles = {"-", "x", "d", "y", "e"}
            roles = {
                str(key): str(role)
                for key, role in raw_roles.items()
                if str(role) in valid_roles
            }
            x_keys = [key for key, role in roles.items() if role == "x"]
            for key in x_keys[1:]:
                del roles[key]
            self.collect_output_roles = roles
        else:
            self.collect_output_roles = {}

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

    def reported_value_units(self) -> dict[str, str]:
        """Report the physical unit of the state value; the index is unitless."""
        return {f"{self.instance_name}:{self.state_name}": self.units}
