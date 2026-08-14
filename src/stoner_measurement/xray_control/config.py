"""Load and save the per-machine X-ray controller configuration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from stoner_measurement.config_utils import deep_merge, load_yaml_mapping
from stoner_measurement.resources import bundled_resource_path, user_config_file

_MAX_CONFIG_BACKUPS = 20


def machine_config_path() -> Path:
    return user_config_file("xray_controller.yaml")


def load_xray_controller_config() -> dict[str, Any]:
    bundled = load_yaml_mapping(
        bundled_resource_path("", "xray_controller.yaml") or Path("__missing__")
    )
    return deep_merge(bundled, load_yaml_mapping(machine_config_path()))


def save_xray_controller_config(config: dict[str, Any]) -> Path:
    path = machine_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")  # nosemgrep
        path.replace(path.with_name(f"{path.stem}.{timestamp}{path.suffix}"))
        backups = sorted(path.parent.glob(f"{path.stem}.*{path.suffix}"))
        while len(backups) > _MAX_CONFIG_BACKUPS:
            backups.pop(0).unlink(missing_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(config, stream, sort_keys=False)
    temporary.replace(path)
    return path
