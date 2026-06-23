"""Helpers for resolving bundled and user configuration resources.

This module centralises path resolution, file lookup, YAML loading, and YAML
writing for configuration and resource files that may exist either in the
per-user configuration area or in the bundled application resources.

The helpers in this module are intentionally small and composable. They provide
the single supported code path for resolving toolbar configuration, predefined
sequences, toolbar icons, and the default sequence template.
"""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path
from typing import Any

import platformdirs
import yaml

logger = logging.getLogger(__name__)

_BUNDLED_CONFIG_PACKAGE = "stoner_measurement.conf"
_DEFAULT_SEQUENCE_TEMPLATE_NAME = "sequence_template.json"


def user_config_root() -> Path:
    """Return the root directory for per-user application configuration.

    Returns:
        (Path):
            The directory containing user override files such as
            ``toolbar.yaml`` and the ``resources`` and ``sequences``
            subdirectories.
    """
    root = Path(platformdirs.user_config_path("stoner_measurement")).parent
    logger.debug("Resolved user configuration root: %s", root)
    return root


def user_config_file(name: str) -> Path:
    """Return the path of a per-user top-level configuration file.

    Args:
        name (str):
            Configuration filename such as ``toolbar.yaml``.

    Returns:
        (Path):
            The resolved per-user file path.
    """
    path = user_config_root() / name
    logger.debug("Resolved user configuration file %r to %s", name, path)
    return path


def user_resource_file(subdir: str, name: str) -> Path:
    """Return the path of a named file within a user resource subdirectory.

    Args:
        subdir (str):
            Subdirectory name beneath the user configuration root, such as
            ``resources`` or ``sequences``.
        name (str):
            Target filename.

    Returns:
        (Path):
            The resolved per-user resource path.
    """
    path = user_config_root() / subdir / name
    logger.debug("Resolved user resource file %r/%r to %s", subdir, name, path)
    return path


def bundled_resource_path(subdir: str, name: str) -> Path | None:
    """Return a filesystem path to a bundled resource, if available.

    Args:
        subdir (str):
            Subdirectory name within ``stoner_measurement.conf``. Use an empty
            string for top-level bundled files.
        name (str):
            Resource filename.

    Returns:
        (Path | None):
            A filesystem path to the bundled resource if it exists, otherwise
            ``None``.
    """
    try:
        resource = importlib.resources.files(_BUNDLED_CONFIG_PACKAGE).joinpath(subdir).joinpath(name)
        with importlib.resources.as_file(resource) as path:
            if path.exists():
                logger.debug(
                    "Located bundled resource %r/%r at %s",
                    subdir,
                    name,
                    path,
                )
                return path
    except Exception as exc:
        logger.error(
            "Failed to resolve bundled resource %r/%r: %s",
            subdir,
            name,
            exc,
        )
        return None
    logger.debug("Bundled resource %r/%r was not found.", subdir, name)
    return None


def load_user_or_bundled_yaml(name: str) -> dict[str, Any]:
    """Load a YAML mapping from the user config or bundled fallback.

    Args:
        name (str):
            Top-level YAML configuration filename.

    Returns:
        (dict[str, Any]):
            The parsed YAML mapping. If the file is missing, invalid, or not a
            mapping, an empty dictionary is returned.
    """
    path = user_config_file(name)
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.error("Failed to load user YAML file %s: %s", path, exc)
            return {}
        if isinstance(data, dict):
            logger.info("Loaded user YAML configuration from %s", path)
            return dict(data)
        logger.error("Ignoring user YAML file %s because it does not contain a mapping.", path)
        return {}
    bundled = bundled_resource_path("", name)
    if bundled is None:
        logger.debug("No user or bundled YAML file was found for %r.", name)
        return {}
    try:
        data = yaml.safe_load(bundled.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.error("Failed to load bundled YAML file %s: %s", bundled, exc)
        return {}
    if isinstance(data, dict):
        logger.info("Loaded bundled YAML configuration from %s", bundled)
        return dict(data)
    logger.error(
        "Ignoring bundled YAML file %s because it does not contain a mapping.",
        bundled,
    )
    return {}


def save_user_yaml(name: str, config: dict[str, Any]) -> Path:
    """Write a YAML mapping to the per-user configuration directory.

    Args:
        name (str):
            Top-level YAML configuration filename.
        config (dict[str, Any]):
            Mapping to serialise.

    Returns:
        (Path):
            The file written to disk.
    """
    path = user_config_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    logger.info("Saved user YAML configuration to %s", path)
    return path


def normalise_toolbar_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a toolbar config with a guaranteed list-valued ``buttons`` key.

    Args:
        config (dict[str, Any]):
            Raw toolbar configuration mapping.

    Returns:
        (dict[str, Any]):
            Normalised toolbar configuration.
    """
    result = dict(config)
    buttons = result.get("buttons")
    result["buttons"] = buttons if isinstance(buttons, list) else []
    return result


def toolbar_config_path() -> Path:
    """Return the per-user toolbar configuration path.

    Returns:
        (Path):
            User override path for ``toolbar.yaml``.
    """
    return user_config_file("toolbar.yaml")


def load_toolbar_config() -> dict[str, Any]:
    """Load and normalise the effective toolbar configuration.

    Returns:
        (dict[str, Any]):
            Toolbar configuration mapping with a guaranteed list-valued
            ``buttons`` entry.
    """
    config = normalise_toolbar_config(load_user_or_bundled_yaml("toolbar.yaml"))
    logger.debug("Loaded normalised toolbar configuration: %s", config)
    return config


def save_toolbar_config(config: dict[str, Any]) -> Path:
    """Save toolbar configuration to the per-user override file.

    Args:
        config (dict[str, Any]):
            Toolbar configuration mapping to write.

    Returns:
        (Path):
            Path written to disk.
    """
    return save_user_yaml("toolbar.yaml", config)


def find_toolbar_icon(name: str) -> Path | None:
    """Locate a toolbar icon by filename in user or bundled resources."""
    user_icon = user_resource_file("resources", name)
    if user_icon.exists():
        logger.debug("Located user toolbar icon %r at %s", name, user_icon)
        return user_icon
    return bundled_resource_path("resources", name)


def find_predefined_sequence(name: str) -> Path | None:
    """Locate a predefined sequence by filename in user or bundled sequences."""
    user_seq = user_resource_file("sequences", name)
    if user_seq.exists():
        logger.debug("Located user predefined sequence %r at %s", name, user_seq)
        return user_seq
    return bundled_resource_path("sequences", name)


def find_sequence_template() -> Path | None:
    """Locate the default sequence template in user or bundled sequences."""
    return find_predefined_sequence(_DEFAULT_SEQUENCE_TEMPLATE_NAME)
