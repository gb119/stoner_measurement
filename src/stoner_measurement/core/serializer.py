"""Sequence serialiser — converts sequence trees to/from JSON.

Provides :func:`sequence_to_json` and :func:`sequence_from_json` for
persisting and restoring measurement sequence trees.  The JSON format
embeds the application version number so that files can be identified
and forward-compatibility checks can be added in the future.

Each step in the tree is represented by a ``{"plugin": {...}}`` dict;
steps that are :class:`~stoner_measurement.plugins.sequence.base.SequencePlugin`
containers with children also carry a ``"sub_steps"`` list that follows
the same recursive structure.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin

# Recursive type alias matching dock_panel._SequenceStep.
type _SequenceStep = BasePlugin | tuple[BasePlugin, list[_SequenceStep]]

_RENAME_SKIP_KEYS = frozenset({"class", "type", "version"})
logger = logging.getLogger(__name__)


def sequence_to_json(steps: list[_SequenceStep]) -> dict[str, Any]:
    """Serialise a sequence tree to a JSON-compatible dict.

    The returned dict has the following structure::

        {
            "version": "<app version>",
            "steps": [
                {"plugin": {...}},
                {"plugin": {...}, "sub_steps": [{"plugin": {...}}, ...]},
                ...
            ]
        }

    Each ``"plugin"`` value is the dict produced by
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.to_json`.

    Args:
        steps (list[_SequenceStep]):
            The sequence steps as returned by
            :attr:`~stoner_measurement.ui.dock_panel.DockPanel.sequence_steps`.
            Each element is either a plugin instance or a
            ``(plugin, [sub-steps…])`` tuple.

    Returns:
        (dict[str, Any]):
            A JSON-serialisable dictionary suitable for writing to a file
            with :func:`json.dumps`.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.trace import DummyPlugin
        >>> plugin = DummyPlugin()
        >>> data = sequence_to_json([plugin])
        >>> "version" in data
        True
        >>> len(data["steps"])
        1
        >>> data["steps"][0]["plugin"]["type"]
        'trace'
    """
    from stoner_measurement import __version__

    return {
        "version": __version__,
        "steps": [_step_to_json(step) for step in steps],
    }


def _step_to_json(step: _SequenceStep) -> dict[str, Any]:
    """Convert a single sequence step to a JSON-compatible dict."""
    if isinstance(step, tuple):
        plugin, sub_steps = step
        return {
            "plugin": plugin.to_json(),
            "sub_steps": [_step_to_json(s) for s in sub_steps],
        }
    return {"plugin": step.to_json()}


def sequence_from_json(
    data: dict[str, Any],
    *,
    on_reserved_name_renamed: Callable[[str, str], None] | None = None,
) -> list[_SequenceStep]:
    """Reconstruct a sequence tree from a JSON dict produced by :func:`sequence_to_json`.

    Rebuilds each plugin instance using
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.from_json` and
    recursively reconstructs nested sub-steps.  If an older sequence uses an
    instance name that is now reserved, the loader chooses a valid non-conflicting
    replacement, updates identifier references throughout the in-memory JSON,
    and retries reconstruction.

    Args:
        data (dict[str, Any]):
            JSON dict as produced by :func:`sequence_to_json` and loaded from
            a file with :func:`json.loads` or :func:`json.load`.

    Keyword Parameters:
        on_reserved_name_renamed (Callable[[str, str], None] | None):
            Optional callback invoked with each old and replacement instance
            name when loading requires an automatic migration.

    Returns:
        (list[_SequenceStep]):
            Sequence steps in the same nested format accepted by
            :meth:`~stoner_measurement.ui.dock_panel.DockPanel.load_sequence`.

    Raises:
        KeyError:
            If any plugin entry is missing the required ``"class"`` key.
        ImportError:
            If a plugin class specified in ``"class"`` cannot be imported.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.plugins.trace import DummyPlugin
        >>> plugin = DummyPlugin()
        >>> plugin.instance_name = "test_dummy"
        >>> data = sequence_to_json([plugin])
        >>> steps = sequence_from_json(data)
        >>> len(steps)
        1
        >>> steps[0].instance_name
        'test_dummy'
    """
    from stoner_measurement.plugins.base_plugin import ReservedInstanceNameError

    load_data = data
    while True:
        steps_data: list[dict[str, Any]] = load_data.get("steps", [])
        try:
            return [_step_from_json(s) for s in steps_data]
        except ReservedInstanceNameError as exc:
            replacement = _available_instance_name(load_data, exc.instance_name)
            logger.warning(
                "Renaming reserved instance name %r to %r while loading sequence JSON.",
                exc.instance_name,
                replacement,
            )
            if on_reserved_name_renamed is not None:
                on_reserved_name_renamed(exc.instance_name, replacement)
            load_data = rename_identifier_references(
                load_data,
                exc.instance_name,
                replacement,
            )


def _available_instance_name(data: dict[str, Any], old_name: str) -> str:
    """Return a valid replacement for a reserved instance name."""
    from stoner_measurement.plugins.base_plugin import instance_name_validation_error

    used_names = _instance_names(data)
    candidate = f"{old_name}_"
    suffix = 2
    while candidate in used_names or instance_name_validation_error(candidate) is not None:
        candidate = f"{old_name}_{suffix}"
        suffix += 1
    return candidate


def _instance_names(value: Any) -> set[str]:
    """Collect all serialised instance names from a nested JSON value."""
    if isinstance(value, dict):
        names = {
            instance_name
            for instance_name in (value.get("instance_name"),)
            if isinstance(instance_name, str)
        }
        for child in value.values():
            names.update(_instance_names(child))
        return names
    if isinstance(value, list):
        names: set[str] = set()
        for child in value:
            names.update(_instance_names(child))
        return names
    return set()


def rename_identifier_references(
    data: dict[str, Any],
    old_name: str,
    new_name: str,
) -> dict[str, Any]:
    """Return a deep-copied sequence JSON mapping with strict identifier rewrites.

    Only exact identifier-token matches are replaced, so renaming ``field`` to
    ``temp`` updates strings such as ``field.value`` or ``field`` but leaves
    ``field_2``, ``b_field``, and ``Field`` untouched.
    """
    if old_name == new_name:
        return copy.deepcopy(data)

    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old_name)}(?![A-Za-z0-9_])")

    def _rewrite(value: Any, *, key: str | None = None) -> Any:
        if isinstance(value, dict):
            rewritten = {}
            for child_key, child_value in value.items():
                rewritten_key = (
                    pattern.sub(new_name, child_key)
                    if key == "trace_selection"
                    else child_key
                )
                rewritten[rewritten_key] = _rewrite(child_value, key=child_key)
            return rewritten
        if isinstance(value, list):
            return [_rewrite(item, key=key) for item in value]
        if isinstance(value, str):
            if key in _RENAME_SKIP_KEYS:
                return value
            return pattern.sub(new_name, value)
        return value

    return _rewrite(copy.deepcopy(data))


def _step_from_json(step_data: dict[str, Any]) -> _SequenceStep:
    """Reconstruct a single sequence step from its serialised dict."""
    from stoner_measurement.plugins.base_plugin import BasePlugin

    plugin = BasePlugin.from_json(step_data["plugin"])
    sub_steps_data: list[dict[str, Any]] = step_data.get("sub_steps", [])
    if sub_steps_data:
        return (plugin, [_step_from_json(s) for s in sub_steps_data])
    return plugin
