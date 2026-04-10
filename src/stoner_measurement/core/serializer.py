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

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stoner_measurement.plugins.base_plugin import BasePlugin

# Recursive type alias matching dock_panel._SequenceStep.
type _SequenceStep = BasePlugin | tuple[BasePlugin, list[_SequenceStep]]


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
        >>> from PyQt6.QtWidgets import QApplication
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


def sequence_from_json(data: dict[str, Any]) -> list[_SequenceStep]:
    """Reconstruct a sequence tree from a JSON dict produced by :func:`sequence_to_json`.

    Rebuilds each plugin instance using
    :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.from_json` and
    recursively reconstructs nested sub-steps.

    Args:
        data (dict[str, Any]):
            JSON dict as produced by :func:`sequence_to_json` and loaded from
            a file with :func:`json.loads` or :func:`json.load`.

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
        >>> from PyQt6.QtWidgets import QApplication
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
    steps_data: list[dict[str, Any]] = data.get("steps", [])
    return [_step_from_json(s) for s in steps_data]


def _step_from_json(step_data: dict[str, Any]) -> _SequenceStep:
    """Reconstruct a single sequence step from its serialised dict."""
    from stoner_measurement.plugins.base_plugin import BasePlugin

    plugin = BasePlugin.from_json(step_data["plugin"])
    sub_steps_data: list[dict[str, Any]] = step_data.get("sub_steps", [])
    if sub_steps_data:
        return (plugin, [_step_from_json(s) for s in sub_steps_data])
    return plugin
