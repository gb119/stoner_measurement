"""Helpers for loading per-plugin YAML configuration overlays.

This module supports a two-layer configuration scheme for plugins:

* bundled defaults shipped inside :mod:`stoner_measurement.conf.plugins`
* per-machine overrides stored in the user's configuration directory

Machine-specific values take precedence over the bundled defaults.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import platformdirs
from collections.abc import Mapping

from stoner_measurement.config_utils import deep_merge, load_yaml_mapping

_BUNDLED_CONFIG_PACKAGE = "stoner_measurement.conf.plugins"


def _plugin_config_stem(plugin_name: str) -> str:
    """Return the normalised file stem used for *plugin_name*."""
    text = plugin_name.strip()
    if not text:
        raise ValueError("plugin_name must not be empty")
    return text.lower().replace(" ", "_").replace("-", "_")


_load_yaml_mapping = load_yaml_mapping
_deep_merge = deep_merge


def machine_config_path(plugin_name: str) -> Path:
    """Return the per-machine YAML config path for *plugin_name*."""
    root = Path(platformdirs.user_config_dir("stoner_measurement"))
    return root / "plugins" / f"{_plugin_config_stem(plugin_name)}.yaml"


def _load_bundled_config(plugin_name: str) -> dict[str, Any]:
    """Load the bundled YAML config for *plugin_name* if present."""
    config_file = resources.files(_BUNDLED_CONFIG_PACKAGE).joinpath(
        f"{_plugin_config_stem(plugin_name)}.yaml"
    )
    return _load_yaml_mapping(config_file)


def load_plugin_config(plugin_name: str, *, machine_only: bool = False) -> dict[str, Any]:
    """Load the merged YAML configuration for *plugin_name*.

    Args:
        plugin_name (str):
            Human-readable plugin identifier.

    Keyword Parameters:
        machine_only (bool):
            When ``True``, only the per-machine overlay is loaded.

    Returns:
        (dict[str, Any]):
            Deep-merged configuration mapping.
    """
    machine_config = _load_yaml_mapping(machine_config_path(plugin_name))
    if machine_only:
        return machine_config

    bundled_config = _load_bundled_config(plugin_name)
    return _deep_merge(bundled_config, machine_config)
