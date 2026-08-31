"""Qt helpers for keeping trace-catalogue selection controls up to date."""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from qtpy.QtCore import QObject
from qtpy.QtWidgets import QComboBox, QWidget

from stoner_measurement.core.trace_data import COLUMN_ROLE_X, COLUMN_ROLE_Y

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin


_NO_TRACES = "(no traces available)"
_NO_CHANNELS = "(no channels available)"


def remap_catalog_text(current_text: str, available_texts: list[str]) -> str | None:
    """Return the unique renamed item matching *current_text*'s stable suffix."""
    if not current_text:
        return None
    if current_text in available_texts:
        return current_text
    separator_positions = [
        position
        for separator in (":", ".")
        if (position := current_text.find(separator)) >= 0
    ]
    if not separator_positions:
        return None
    suffix = current_text[min(separator_positions) :]
    matches = [text for text in available_texts if text.endswith(suffix)]
    return matches[0] if len(matches) == 1 else None


def _expression_channel(expression: str) -> tuple[str, str | None, Any | None]:
    """Return an expression's trace base, shorthand role, and DataFrame column."""
    if expression.endswith(".x"):
        return expression[:-2], COLUMN_ROLE_X, None
    if expression.endswith(".y"):
        return expression[:-2], COLUMN_ROLE_Y, None
    marker = ".df["
    marker_index = expression.rfind(marker)
    suffix = "].to_numpy()"
    if marker_index < 0 or not expression.endswith(suffix):
        return expression, None, None
    column_text = expression[marker_index + len(marker) : -len(suffix)]
    try:
        column = ast.literal_eval(column_text)
    except (SyntaxError, ValueError):
        return expression, None, None
    role = COLUMN_ROLE_X if column == "x" else None
    return expression[:marker_index], role, column


def channel_name_for_expression(
    items: dict[str, str],
    roles: dict[str, str],
    expression: str,
) -> str | None:
    """Find the displayed channel matching a saved expression semantically.

    Before acquisition, configured channels use ``.x``/``.y`` expressions;
    live catalogues use DataFrame expressions. Match those representations by
    trace, role, and canonical channel name without overwriting the saved
    expression merely because the representation has changed.
    """
    exact = next((name for name, item_expr in items.items() if item_expr == expression), None)
    if exact is not None:
        return exact

    source_base, source_role, source_column = _expression_channel(expression)
    matches = []
    for name, item_expr in items.items():
        item_base, item_role, item_column = _expression_channel(item_expr)
        item_role = roles.get(item_expr) or item_role
        if item_base != source_base:
            continue
        if source_column is not None and item_column == source_column:
            matches.append(name)
            continue
        if source_column is not None and item_column is None:
            channel_label = name.rsplit(":", 1)[-1].rsplit(" (", 1)[0]
            expected_role = COLUMN_ROLE_X if source_column == "x" else COLUMN_ROLE_Y
            if item_role == expected_role and (
                source_column == "x" or channel_label == str(source_column)
            ):
                matches.append(name)
            continue
        if source_column is None and source_role is not None and item_role == source_role:
            matches.append(name)
    return matches[0] if len(matches) == 1 else None


class TraceChannelComboBox(QComboBox):
    """Channel selector that owns display-name and expression conversion."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel_items: dict[str, str] = {}

    @property
    def selected_expression(self) -> str:
        """Return the expression represented by the current display item."""
        return self._channel_items.get(self.currentText(), "")

    def set_channels(
        self,
        items: dict[str, str],
        roles: dict[str, str],
        expression: str,
        *,
        preferred_role: str,
        preserve_current_text: bool = False,
    ) -> str:
        """Replace the catalogue and return the expression to retain.

        A still-valid visible selection wins during refresh. Otherwise the
        saved expression is matched semantically across configured ``.x/.y``
        and live DataFrame forms. Defaults are used only when neither survives.
        """
        current_text = self.currentText() if preserve_current_text else ""
        self.blockSignals(True)
        self.clear()
        self._channel_items = dict(items)
        if not items:
            self.addItem(_NO_CHANNELS)
            self.blockSignals(False)
            return expression

        self.addItems(items)
        if current_text in items:
            selected_name = current_text
            selected_expression = items[selected_name]
        else:
            selected_name = channel_name_for_expression(items, roles, expression)
            selected_expression = expression
            if selected_name is None and preserve_current_text:
                selected_name = remap_catalog_text(current_text, list(items))
                if selected_name is not None:
                    selected_expression = items[selected_name]
            if selected_name is None:
                selected_name = next(
                    (
                        name
                        for name, item_expression in items.items()
                        if roles.get(item_expression) == preferred_role
                    ),
                    next(iter(items)),
                )
                selected_expression = items[selected_name]
        self.setCurrentText(selected_name)
        self.blockSignals(False)
        return selected_expression


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


def bind_value_catalog_updates(
    plugin: BasePlugin,
    widget: QWidget,
    callback: Callable[[dict[str, str]], None],
) -> None:
    """Call *callback* when the owning engine rebuilds its scalar-value catalogue."""
    engine = plugin.sequence_engine
    signal = getattr(engine, "values_catalog_changed", None)
    if signal is None:
        return
    binding = _TraceCatalogBinding(signal, callback, widget)
    bindings = getattr(widget, "_value_catalog_bindings", [])
    bindings.append(binding)
    widget._value_catalog_bindings = bindings  # type: ignore[attr-defined]


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
            columns = getattr(trace_data, "expected_columns", list(trace_data.df.columns))
            names = dict(getattr(trace_data, "expected_names", trace_data.names) or {})
            units = dict(getattr(trace_data, "expected_units", trace_data.units) or {})
        except Exception:  # noqa: BLE001  # the catalogue may precede acquisition
            configured = _configured_trace_channels(plugin, trace_key, expression)
            if configured is not None:
                items.update(configured)
            else:
                items[f"{trace_key} (x)"] = f"{expression}.x"
                items[f"{trace_key} (y)"] = f"{expression}.y"
            continue

        for column in columns:
            label = _channel_label(trace_key, column, names=names, units=units)
            items[label] = f"{expression}.df[{column!r}].to_numpy()"
    return items


def trace_channel_roles(plugin: Any, traces: dict[str, str]) -> dict[str, str]:
    """Return each selectable channel expression's role."""
    roles: dict[str, str] = {}
    for trace_key, expression in traces.items():
        try:
            trace_data = plugin.eval(expression)
            columns = getattr(trace_data, "expected_columns", list(trace_data.df.columns))
            expected_roles = getattr(
                trace_data, "expected_column_roles", trace_data.column_roles
            )
            for column in columns:
                channel_expression = f"{expression}.df[{column!r}].to_numpy()"
                roles[channel_expression] = expected_roles.get(column, "")
        except Exception:  # noqa: BLE001  # the catalogue may precede acquisition
            configured = _configured_trace_channels(plugin, trace_key, expression)
            if configured is not None:
                for channel_expression in configured.values():
                    roles[channel_expression] = (
                        COLUMN_ROLE_X if channel_expression.endswith(".x") else COLUMN_ROLE_Y
                    )
            else:
                roles[f"{expression}.x"] = COLUMN_ROLE_X
                roles[f"{expression}.y"] = COLUMN_ROLE_Y
    return roles


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
        columns = getattr(trace_data, "expected_columns", list(trace_data.df.columns))
        roles = getattr(trace_data, "expected_column_roles", trace_data.column_roles)
        names = dict(getattr(trace_data, "expected_names", trace_data.names) or {})
        units = dict(getattr(trace_data, "expected_units", trace_data.units) or {})
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

    y_columns = list(
        column for column in columns if roles.get(column) == COLUMN_ROLE_Y
    )
    default_y = y_columns[0] if y_columns else None
    x_columns = list(
        column for column in columns if roles.get(column) == COLUMN_ROLE_X
    )
    x_column = x_columns[0] if x_columns else None
    items = {}
    for column in columns:
        if column == x_column:
            target_key = "x"
        else:
            target_key = "" if column == default_y else str(column)
        items[_channel_label(trace_key, column, names=names, units=units)] = target_key
    return items


def refresh_trace_source_widgets(
    plugin: Any,
    widgets: dict[str, Any],
    traces: dict[str, str],
    *,
    show_column_selector: bool = True,
    show_advanced_inputs: bool = True,
    prefer_y_channel: bool = False,
) -> None:
    """Refresh common trace, column, and advanced x/y source selectors."""
    trace_keys = list(traces)
    trace_combo: QComboBox = widgets["trace_combo"]
    current_trace_text = trace_combo.currentText()
    trace_combo.blockSignals(True)
    trace_combo.clear()
    if trace_keys:
        trace_combo.addItems(trace_keys)
        if current_trace_text in trace_keys:
            plugin.trace_key = current_trace_text
        elif plugin.trace_key not in trace_keys:
            plugin.trace_key = (
                remap_catalog_text(current_trace_text, trace_keys)
                or remap_catalog_text(plugin.trace_key, trace_keys)
                or trace_keys[0]
            )
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

    if show_advanced_inputs:
        items = trace_channel_items(plugin, traces)
        roles = trace_channel_roles(plugin, traces)
        widgets["channel_items"].clear()
        widgets["channel_items"].update(items)
        _refresh_channel_combo(
            plugin, widgets["x_combo"], items, roles, "x_expr", preferred_axis="x"
        )
        _refresh_channel_combo(
            plugin,
            widgets["y_combo"],
            items,
            roles,
            "y_expr",
            preferred_axis="y" if prefer_y_channel else None,
        )


def _refresh_channel_combo(
    plugin: Any,
    combo: QComboBox,
    items: dict[str, str],
    roles: dict[str, str],
    attribute: str,
    *,
    preferred_axis: str | None,
) -> None:
    """Refresh one channel combo, preferring its still-valid displayed text."""
    if isinstance(combo, TraceChannelComboBox):
        preferred_role = (
            COLUMN_ROLE_X if preferred_axis == "x" else COLUMN_ROLE_Y
        )
        expression = combo.set_channels(
            items,
            roles,
            getattr(plugin, attribute),
            preferred_role=preferred_role,
            preserve_current_text=True,
        )
        setattr(plugin, attribute, expression)
        return

    current_text = combo.currentText()
    current_expression = getattr(plugin, attribute)
    combo.blockSignals(True)
    combo.clear()
    if not items:
        combo.addItem(_NO_CHANNELS)
        setattr(plugin, attribute, "")
        combo.blockSignals(False)
        return
    combo.addItems(items)
    selected_name = current_text if current_text in items else None
    if selected_name is None:
        selected_name = channel_name_for_expression(items, roles, current_expression)
    if selected_name is None:
        selected_name = remap_catalog_text(current_text, list(items))
    if selected_name is None and preferred_axis is not None:
        if preferred_axis == "x":
            selected_name = next(
                (
                    name
                    for name, expression in items.items()
                    if roles.get(expression) == COLUMN_ROLE_X
                ),
                None,
            )
        else:
            selected_name = next(
                (
                    name
                    for name, expression in items.items()
                    if roles.get(expression) == COLUMN_ROLE_Y
                ),
                None,
            )
    selected_name = selected_name or next(iter(items))
    combo.setCurrentText(selected_name)
    setattr(plugin, attribute, items[selected_name])
    combo.blockSignals(False)
