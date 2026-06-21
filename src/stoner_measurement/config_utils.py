"""Shared configuration helper functions."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from *path*, returning an empty dict on failure."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError):
        logger.warning("Failed to read YAML at %s.", path, exc_info=True)
        return {}
    except yaml.YAMLError:
        logger.warning("Failed to parse YAML at %s.", path, exc_info=True)
        return {}

    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        logger.warning(
            "Ignoring YAML file %s because its top-level value is not a mapping.",
            path,
        )
        return {}
    return dict(raw)


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Return *base* merged with *overlay*, recursing into nested mappings."""
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged