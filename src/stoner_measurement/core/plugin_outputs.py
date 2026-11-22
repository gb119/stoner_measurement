"""Configuration-time output declarations and legacy plugin adapters."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from functools import wraps
from typing import Any

from stoner_measurement.core.trace_data import TraceData


@dataclass(frozen=True)
class ScalarOutput:
    """A scalar access expression with units and an optional stored-result key.

    Args:
        expression (str): Expression evaluated by consumers at runtime.
        units (str): Physical unit, or an empty string when unspecified.
        result_key (str | None): Key in the plugin's result dictionary; omit
            for attributes, monitor readings and computed statistic projections.
    """

    expression: str
    units: str = ""
    result_key: str | None = None


@dataclass(frozen=True)
class TraceOutput:
    """A trace expression with an optional empty schema or deferred factory.

    Args:
        expression (str): Runtime expression returning the acquired TraceData.
        result_key (str | None): Local key for mapping-backed trace results.
        schema (TraceData | None): Complete empty configured table, if known.
        schema_factory (Callable | None): Configuration-only zero-argument
            builder. Called after scalar catalogues are available. Supply
            either this or schema; neither is needed for unknown schemas.
    """

    expression: str
    result_key: str | None = None
    schema: TraceData | None = None
    schema_factory: Callable[[], TraceData | None] | None = None

    def configured_data(self) -> TraceData | None:
        """Materialise the configured schema without evaluating the expression.

        Returns:
            (TraceData | None): Independent empty schema, or unknown schema.

        Raises:
            ValueError: If both schema forms are supplied, the builder returns
                a non-TraceData object, or a schema contains acquired rows.
        """
        if self.schema is not None and self.schema_factory is not None:
            raise ValueError("Specify either schema or schema_factory, not both.")
        schema = self.schema_factory() if self.schema_factory is not None else self.schema
        if schema is not None:
            if not isinstance(schema, TraceData) or schema.row_count:
                raise ValueError("Configured output schemas must be empty TraceData tables.")
            snapshot = TraceData(
                schema.df, column_roles=schema.column_roles, names=schema.names, units=schema.units
            )
            snapshot.set_expected_schema(schema)
            return snapshot
        return schema


@dataclass
class PluginOutputs:
    """Ordered trace and scalar declarations keyed by existing catalogue identity.

    ``result_order`` optionally preserves interleaved transform result names.
    Expressions and schemas are derived configuration, never persisted results.

    Args:
        traces (dict[str, TraceOutput]): Ordered trace declarations by catalogue
            identifier. Defaults to an independent empty mapping.
        values (dict[str, ScalarOutput]): Ordered scalar declarations by
            catalogue identifier. Defaults to an independent empty mapping.
        result_order (tuple[str, ...] | None): Optional local-result order.
            Listed known keys come first, followed by remaining declared keys.

    Notes:
        Without explicit ordering, combined result names put scalar result
        keys before trace result keys. Projections without a result_key are
        excluded. The trace and scalar mappings may share a catalogue key.
        Descriptor records are frozen; the mappings can be extended when
        implementing super().declared_outputs() in a subclass.

    Examples:
        >>> outputs = PluginOutputs(values={
        ...     "source:Resistance": ScalarOutput("source.resistance", "Ω")
        ... })
        >>> outputs.values["source:Resistance"].units
        'Ω'
    """

    traces: dict[str, TraceOutput] = field(default_factory=dict)
    values: dict[str, ScalarOutput] = field(default_factory=dict)
    result_order: tuple[str, ...] | None = None

    def result_keys(self, kind: str | None = None) -> list[str]:
        """Return stored result keys, excluding computed projections.

        Args:
            kind (str | None): Select ``trace``, ``value`` or all results.

        Returns:
            (list[str]): Unique result keys in configured order.
        """
        entries = (
            self.traces.values()
            if kind == "trace"
            else self.values.values()
            if kind == "value"
            else [*self.values.values(), *self.traces.values()]
        )
        keys = list(
            dict.fromkeys(item.result_key for item in entries if item.result_key is not None)
        )
        if self.result_order is not None:
            ordered = [key for key in self.result_order if key in keys]
            keys = [*ordered, *(key for key in keys if key not in ordered)]
        return keys

    def configured_traces(self) -> dict[str, TraceData]:
        """Resolve optional schemas after the scalar catalogue is available.

        Returns:
            (dict[str, TraceData]): Empty schemas keyed by catalogue identifier.

        Raises:
            ValueError: If an output supplies an invalid configured schema.
        """
        schemas = {}
        for key, output in self.traces.items():
            schema = output.configured_data()
            if schema is not None:
                schemas[key] = schema
        return schemas


@dataclass
class _ResolvedOutputs(PluginOutputs):
    unified: bool = False


_ACTIVE: ContextVar[tuple[tuple[object, PluginOutputs], ...]] = ContextVar(
    "plugin_outputs", default=()
)
_VIEWS = ("reported_traces", "reported_values", "reported_value_units", "configured_trace_data")


def output_view(method: Callable) -> Callable:
    """Mark a compatibility projection so it is never treated as a legacy hook."""
    method._output_view = True
    return method


def legacy_output_hook(method: Callable, owner: type) -> Callable:
    """Give direct legacy super calls the same canonical baseline as adaptation."""

    @wraps(method)
    def legacy(self, *args, **kwargs):
        for plugin, outputs in reversed(_ACTIVE.get()):
            if plugin is self:
                if _canonical_view_wins(self, owner, outputs):
                    return project_outputs(self, method.__name__)
                return method(self, *args, **kwargs)
        outputs = resolve_outputs(self, adapt_legacy=False)
        token = _ACTIVE.set((*_ACTIVE.get(), (self, outputs)))
        try:
            if _canonical_view_wins(self, owner, outputs):
                return project_outputs(self, method.__name__)
            return method(self, *args, **kwargs)
        finally:
            _ACTIVE.reset(token)

    return legacy


def _canonical_view_wins(plugin: Any, owner: type, outputs: PluginOutputs) -> bool:
    index, _method = _definition(plugin, "declared_outputs")
    return (
        isinstance(outputs, _ResolvedOutputs)
        and outputs.unified
        and type(plugin).__mro__.index(owner) >= index
    )


def _definition(plugin: Any, name: str) -> tuple[int, Any]:
    for index, cls in enumerate(type(plugin).__mro__):
        if name in cls.__dict__:
            return index, cls.__dict__[name]
    return len(type(plugin).__mro__), None


def legacy_output_property(plugin: Any, name: str, default: Any) -> Any:
    """Read an old naming property without re-entering a compatibility view."""
    _index, attribute = _definition(plugin, name)
    method = attribute.fget if isinstance(attribute, property) else attribute
    if attribute is None or getattr(method, "_output_view", False):
        return default
    return getattr(plugin, name)


def project_outputs(plugin: Any, name: str) -> Any:
    """Project a legacy method/property from the resolved declarations."""
    outputs = resolve_outputs(plugin)
    if name == "reported_traces":
        return {key: item.expression for key, item in outputs.traces.items()}
    if name == "reported_values":
        return {key: item.expression for key, item in outputs.values.items()}
    if name == "reported_value_units":
        return {key: item.units for key, item in outputs.values.items()}
    if name == "configured_trace_data":
        return outputs.configured_traces()
    if name in {"trace_names", "output_trace_names"}:
        return outputs.result_keys("trace")
    if name == "output_value_names":
        return outputs.result_keys("value")
    if name == "output_names":
        return outputs.result_keys()
    raise ValueError(f"Unknown output view {name!r}")


def trace_outputs(plugin: Any, names: list[str]) -> PluginOutputs:
    """Declare mapping-backed traces, retaining legacy trace-name overrides."""
    var = plugin.instance_name
    defaults = PluginOutputs(
        traces={
            f"{var}:{name}": TraceOutput(f"{var}.data[{name!r}]", result_key=name) for name in names
        }
    )
    token = _ACTIVE.set((*_ACTIVE.get(), (plugin, defaults)))
    try:
        names = legacy_output_property(plugin, "trace_names", names)
    finally:
        _ACTIVE.reset(token)
    return PluginOutputs(
        traces={
            f"{var}:{name}": TraceOutput(f"{var}.data[{name!r}]", result_key=name) for name in names
        }
    )


def transform_outputs(plugin: Any, traces: list[str], values: list[str]) -> PluginOutputs:
    """Declare typed transform results, retaining old naming-property overrides."""
    var = plugin.instance_name
    defaults = PluginOutputs(
        traces={
            f"{var}:{name}": TraceOutput(f"{var}.data[{name!r}]", result_key=name)
            for name in traces
        },
        values={
            f"{var}:{name}": ScalarOutput(f"{var}.data[{name!r}]", result_key=name)
            for name in values
        },
    )
    token = _ACTIVE.set((*_ACTIVE.get(), (plugin, defaults)))
    try:
        all_names = legacy_output_property(plugin, "output_names", None)
        if all_names is not None:
            if traces and not values:
                traces = all_names
            elif values and not traces:
                values = all_names
        traces = legacy_output_property(plugin, "output_trace_names", traces)
        values = legacy_output_property(plugin, "output_value_names", values)
    finally:
        _ACTIVE.reset(token)
    all_names = [*values, *traces] if all_names is None else all_names
    return PluginOutputs(
        traces={
            f"{var}:{name}": TraceOutput(f"{var}.data[{name!r}]", result_key=name)
            for name in traces
        },
        values={
            f"{var}:{name}": ScalarOutput(f"{var}.data[{name!r}]", result_key=name)
            for name in values
        },
        result_order=tuple(all_names),
    )


def _legacy_hook(plugin: Any, name: str, declared_index: int, declared: bool) -> Callable | None:
    index, method = _definition(plugin, name)
    if method is None or getattr(method, "_output_view", False):
        return None
    if declared and index == declared_index:
        logging.getLogger(__name__).warning(
            "%s defines both declared_outputs and %s; the unified declaration takes precedence",
            type(plugin).__name__,
            name,
        )
        return None
    return getattr(plugin, name) if not declared or index < declared_index else None


def _apply_legacy_views(plugin: Any, outputs: PluginOutputs, index: int, declared: bool) -> None:
    hooks = {name: _legacy_hook(plugin, name, index, declared) for name in _VIEWS}
    if hooks["reported_traces"] is not None:
        old = outputs.traces
        outputs.traces = {
            key: replace(old[key], expression=expression) if key in old else TraceOutput(expression)
            for key, expression in hooks["reported_traces"]().items()
        }
    if hooks["reported_values"] is not None:
        old = outputs.values
        outputs.values = {
            key: replace(old[key], expression=expression)
            if key in old
            else ScalarOutput(expression)
            for key, expression in hooks["reported_values"]().items()
        }
    if hooks["reported_value_units"] is not None:
        units = hooks["reported_value_units"]()
        outputs.values = {
            key: replace(item, units=units.get(key, "")) for key, item in outputs.values.items()
        }
    if hooks["configured_trace_data"] is not None:
        # Materialise this legacy hook once, after the engine has built _values.
        cached = []
        parent = _ResolvedOutputs(
            dict(outputs.traces),
            dict(outputs.values),
            outputs.result_order,
            isinstance(outputs, _ResolvedOutputs) and outputs.unified,
        )

        def schema(key: str) -> TraceData | None:
            if not cached:
                token = _ACTIVE.set((*_ACTIVE.get(), (plugin, parent)))
                try:
                    cached.append(hooks["configured_trace_data"]())
                finally:
                    _ACTIVE.reset(token)
            return cached[0].get(key)

        outputs.traces = {
            key: replace(item, schema=None, schema_factory=lambda key=key: schema(key))
            for key, item in outputs.traces.items()
        }


def resolve_outputs(plugin: Any, *, adapt_legacy: bool = True) -> PluginOutputs:
    """Resolve one plugin's declarations and more-specific legacy overrides.

    Active declarations back ``super().reported_*()`` calls during legacy
    adaptation, preventing recursion and duplicate declaration evaluation.
    An explicit empty PluginOutputs is authoritative; None selects adaptation.

    Args:
        plugin (BasePlugin): Plugin whose current outputs are requested.

    Keyword Parameters:
        adapt_legacy (bool): Apply more-specific legacy overrides. The direct
            legacy-call wrapper disables this to construct its super baseline.

    Returns:
        (PluginOutputs): Fresh declaration mappings with compatibility applied.

    Raises:
        TypeError: If a plugin returns invalid declaration types.
    """
    for active_plugin, outputs in reversed(_ACTIVE.get()):
        if active_plugin is plugin:
            return outputs
    active = _ACTIVE.get()
    token = _ACTIVE.set((*active, (plugin, PluginOutputs())))
    try:
        index, _method = _definition(plugin, "declared_outputs")
        declared = plugin.declared_outputs()
        if declared is not None and not isinstance(declared, PluginOutputs):
            raise TypeError("declared_outputs() must return PluginOutputs or None")
        outputs = (
            _ResolvedOutputs()
            if declared is None
            else _ResolvedOutputs(
                dict(declared.traces), dict(declared.values), declared.result_order, True
            )
        )
        _ACTIVE.set((*active, (plugin, outputs)))
        if adapt_legacy:
            _apply_legacy_views(plugin, outputs, index, declared is not None)
        for entries, expected in ((outputs.traces, TraceOutput), (outputs.values, ScalarOutput)):
            for key, item in entries.items():
                if (
                    not isinstance(key, str)
                    or not isinstance(item, expected)
                    or not isinstance(item.expression, str)
                ):
                    raise TypeError(
                        "Output declarations require string keys and typed expression descriptors"
                    )
        return outputs
    finally:
        _ACTIVE.reset(token)
