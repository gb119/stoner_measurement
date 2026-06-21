"""Helpers for loading magnet-controller engine configuration."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

import platformdirs
import yaml

from stoner_measurement.config_utils import deep_merge, load_yaml_mapping

_BUNDLED_CONFIG_PACKAGE = "stoner_measurement.conf"
_MAX_CONFIG_BACKUPS = 20


def machine_config_path() -> Path:
    root = Path(platformdirs.user_config_dir("stoner_measurement"))
    return root / "magnet_controller.yaml"


def load_magnet_controller_config() -> dict[str, Any]:
    bundled = load_yaml_mapping(
        resources.files(_BUNDLED_CONFIG_PACKAGE).joinpath("magnet_controller.yaml")
    )
    machine = load_yaml_mapping(machine_config_path())
    return deep_merge(bundled, machine)


def save_magnet_controller_config(config: dict[str, Any]) -> Path:
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