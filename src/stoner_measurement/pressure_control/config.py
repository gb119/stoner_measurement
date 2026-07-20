"""Helpers for loading pressure-controller engine configuration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from stoner_measurement.config_utils import deep_merge, load_yaml_mapping
from stoner_measurement.resources import bundled_resource_path, user_config_file

_MAX_CONFIG_BACKUPS = 20


def machine_config_path() -> Path:
    """Return the per-machine pressure-controller config path."""
    return user_config_file("pressure_controller.yaml")


def load_pressure_controller_config() -> dict[str, Any]:
    """Load merged bundled and per-machine engine configuration."""
    bundled = load_yaml_mapping(
        bundled_resource_path("", "pressure_controller.yaml") or Path("__missing__")
    )
    machine = load_yaml_mapping(machine_config_path())
    return deep_merge(bundled, machine)


def save_pressure_controller_config(config: dict[str, Any]) -> Path:
    """Save machine-specific pressure-controller configuration."""
    path = machine_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.stem}.{timestamp}{path.suffix}")
        path.replace(backup)

        backups = sorted(path.parent.glob(f"{path.stem}.*{path.suffix}"))
        while len(backups) > _MAX_CONFIG_BACKUPS:
            backups.pop(0).unlink(missing_ok=True)

    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(config, stream, sort_keys=False)
    tmp_path.replace(path)
    return path
