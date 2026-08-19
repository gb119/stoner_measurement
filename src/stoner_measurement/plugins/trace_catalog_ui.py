"""Qt helpers for keeping trace-catalogue selection controls up to date."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from qtpy.QtCore import QObject
from qtpy.QtWidgets import QComboBox, QWidget

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin


_NO_TRACES = "(no traces available)"
_NO_CHANNELS = "(no channels available)"


class _TraceCatalogBinding(QObject):
    """Own a catalogue-signal connection for the lifetime of a config widget."""

    def __init__(
        self,
        signal: Any,
        callback: Callable[[dict[str, str]], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._callback = callback
        signal.connect(self._catalog_changed)

    def _catalog_changed(self, catalog: dict[str, str]) -> None:
        self._callback(dict(catalog))


def bind_trace_catalog_updates(
    plugin: BasePlugin,
    widget: QWidget,
    callback: Callable[[dict[str, str]], None],
) -> None:
    """Call *callback* when the owning engine rebuilds its trace catalogue."""
    engine = plugin.sequence_engine
    signal = getattr(engine, "traces_catalog_changed", None)
    if signal is None:
        return
    binding = _TraceCatalogBinding(signal, callback, widget)
    bindings = getattr(widget, "_trace_catalog_bindings", [])
    bindings.append(binding)
    widget._trace_catalog_bindings = bindings  # type: ignore[attr-defined]


def _channel_label(trace_key: str, column: Any, *, names: dict, units: dict) -> str:
    """Return the canonical ``trace:column (unit)`` channel label."""
    name = names.get(column) or str(column)
    unit = units.get(column, "")
    return f"{trace_key}:{name} ({unit})"


def _configured_trace_channels(
    plugin: Any, trace_key: str, expression: str
) -> dict[str, str] | None:
    """Return configured x/y labels when a trace has not been acquired yet."""
    producer_name = expression.partition(".")[0]
    producer = plugin.engine_namespace.get(producer_name)
    if producer is None:
        return None
    try:
        return {
            f"{trace_key}:{producer.x_label} ({producer.x_units})": f"{expression}.x",
            f"{trace_key}:{producer.y_label} ({producer.y_units})": f"{expression}.y",
        }
    except (AttributeError, TypeError, ValueError):
        return None


def trace_channel_items(plugin: Any, traces: dict[str, str]) -> dict[str, str]:
    """Return canonical expressions for every available column in each trace.

    Live :class:`TraceData` metadata supplies the human-readable column names
    and units.  A trace that is not currently evaluable retains the legacy
    x/y choices until data become available.
    """
    items: dict[str, str] = {}
    for trace_key, expression in traces.items():
        try:
            trace_data = plugin.eval(expression)
            frame = trace_data.df
            names = dict(getattr(trace_data, "names", {}) or {})
            units = dict(getattr(trace_data, "units", {}) or {})
        except Exception:  # noqa: BLE001  # the catalogue may precede acquisition
            configured = _configured_trace_channels(plugin, trace_key, expression)
            if configured is not None:
                items.update(configured)
            else:
                items[f"{trace_key} (x)"] = f"{expression}.x"
                items[f"{trace_key} (y)"] = f"{expression}.y"
            continue

        items[_channel_label(trace_key, "x", names=names, units=units)] = f"{expression}.x"
        for column in frame.columns:
            label = _channel_label(trace_key, column, names=names, units=units)
            items[label] = f"{expression}.df[{column!r}].to_numpy()"
    return items


def trace_target_column_items(
    plugin: Any, traces: dict[str, str], trace_key: str
) -> dict[str, str]:
    """Return user-facing labels mapped to target keys for one source trace.

    The x axis maps to ``"x"``. Stored DataFrame columns map to their stable
    column keys. Before acquisition, a configured producer's y channel maps to
    ``""``, the existing sentinel for the trace's primary y-role column.
    """
    if not trace_key or trace_key not in traces:
        return {}
    expression = traces[trace_key]
    try:
        trace_data = plugin.eval(expression)
        frame = trace_data.df
        names = dict(getattr(trace_data, "names", {}) or {})
        units = dict(getattr(trace_data, "units", {}) or {})
    except Exception:  # noqa: BLE001  # the catalogue may precede acquisition
        configured = _configured_trace_channels(plugin, trace_key, expression)
        if configured is None:
            return {
                f"{trace_key} (x)": "x",
                f"{trace_key} (y)": "",
            }
        return {
            label: "x" if channel_expression.endswith(".x") else ""
            for label, channel_expression in configured.items()
        }

    items = {_channel_label(trace_key, "x", names=names, units=units): "x"}
    y_columns = list(getattr(trace_data, "get_columns_by_role", lambda _role: [])("y"))
    default_y = y_columns[0] if y_columns else None
    for column in frame.columns:
        target_key = "" if column == default_y else str(column)
        items[_channel_label(trace_key, column, names=names, units=units)] = target_key
    return items


def refresh_trace_source_widgets(
    plugin: Any,
    widgets: dict[str, Any],
    traces: dict[str, str],
    *,
    show_column_selector: bool = True,
    prefer_y_channel: bool = False,
) -> None:
    """Refresh common trace, column, and advanced x/y source selectors."""
    trace_keys = list(traces)
    trace_combo: QComboBox = widgets["trace_combo"]
    trace_combo.blockSignals(True)
    trace_combo.clear()
    if trace_keys:
        trace_combo.addItems(trace_keys)
        plugin.trace_key = plugin.trace_key if plugin.trace_key in trace_keys else trace_keys[0]
        trace_combo.setCurrentText(plugin.trace_key)
    else:
        trace_combo.addItem(_NO_TRACES)
        plugin.trace_key = ""
    trace_combo.blockSignals(False)

    column_combo = widgets.get("column_combo")
    if show_column_selector and column_combo is not None:
        column_combo.blockSignals(True)
        plugin._populate_column_combo(column_combo, plugin.trace_key)
        column_combo.blockSignals(False)

    items = trace_channel_items(plugin, traces)
    widgets["channel_items"].clear()
    widgets["channel_items"].update(items)
    _refresh_channel_combo(plugin, widgets["x_combo"], items, "x_expr", preferred_axis="x")
    _refresh_channel_combo(
        plugin,
        widgets["y_combo"],
        items,
        "y_expr",
        preferred_axis="y" if prefer_y_channel else None,
    )


def _refresh_channel_combo(
    plugin: Any,
    combo: QComboBox,
    items: dict[str, str],
    attribute: str,
    *,
    preferred_axis: str | None,
) -> None:
    """Refresh one channel combo while preserving a still-valid expression."""
    current_expression = getattr(plugin, attribute)
    combo.blockSignals(True)
    combo.clear()
    if not items:
        combo.addItem(_NO_CHANNELS)
        setattr(plugin, attribute, "")
        combo.blockSignals(False)
        return
    combo.addItems(items)
    selected_name = next(
        (name for name, expression in items.items() if expression == current_expression),
        None,
    )
    if selected_name is None and preferred_axis is not None:
        if preferred_axis == "x":
            selected_name = next(
                (name for name, expression in items.items() if expression.endswith(".x")),
                None,
            )
        else:
            selected_name = next(
                (name for name, expression in items.items() if not expression.endswith(".x")),
                None,
            )
    selected_name = selected_name or next(iter(items))
    combo.setCurrentText(selected_name)
    setattr(plugin, attribute, items[selected_name])
    combo.blockSignals(False)
