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


def trace_channel_items(traces: dict[str, str]) -> dict[str, str]:
    """Return labelled x/y expressions for every trace catalogue entry."""
    return {
        f"{key} ({axis})": f"{expression}.{axis}"
        for key, expression in traces.items()
        for axis in ("x", "y")
    }


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
        columns = plugin._get_trace_columns(plugin.trace_key)
        column_combo.blockSignals(True)
        plugin._populate_column_combo(column_combo, plugin.trace_key)
        if plugin.column_key not in columns:
            plugin.column_key = ""
        column_combo.blockSignals(False)

    items = trace_channel_items(traces)
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
        selected_name = next(
            (name for name in items if name.endswith(f" ({preferred_axis})")),
            None,
        )
    selected_name = selected_name or next(iter(items))
    combo.setCurrentText(selected_name)
    setattr(plugin, attribute, items[selected_name])
    combo.blockSignals(False)
