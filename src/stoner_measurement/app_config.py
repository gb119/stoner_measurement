"""Application-level configuration helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stoner_measurement.config_utils import deep_merge, load_yaml_mapping
from stoner_measurement.resources import bundled_resource_path, save_user_yaml, user_config_file
from stoner_measurement.ui.theme import DEFAULT_THEME

APP_CONFIG_FILENAME = "application.yaml"

KEY_DEFAULT_DATA_DIR = "app/default_data_directory"
KEY_THEME = "app/theme"

FEATURE_DEFINITIONS: tuple[dict[str, str], ...] = (
    {"key": "temperature", "label": "Temperature", "config_key": "features/temperature"},
    {"key": "magnetic_field", "label": "Magnetic field", "config_key": "features/magnetic_field"},
    {"key": "motor_position", "label": "Motor position", "config_key": "features/motor_position"},
    {"key": "pressure", "label": "Pressure", "config_key": "features/pressure"},
)

FEATURE_KEYS: dict[str, str] = {
    entry["key"]: entry["config_key"] for entry in FEATURE_DEFINITIONS
}

DEFAULT_APP_CONFIG: dict[str, Any] = {
    "app": {
        "default_data_directory": "C:/Data/",
        "theme": DEFAULT_THEME,
    },
    "features": {
        entry["key"]: True for entry in FEATURE_DEFINITIONS
    },
}


def app_config_path() -> Path:
    """Return the per-user application configuration path."""
    return user_config_file(APP_CONFIG_FILENAME)


def load_app_config() -> dict[str, Any]:
    """Load merged bundled and per-user application configuration."""
    bundled = load_yaml_mapping(
        bundled_resource_path("", APP_CONFIG_FILENAME) or Path("__missing__")
    )
    user = load_yaml_mapping(app_config_path())
    return deep_merge(deep_merge(DEFAULT_APP_CONFIG, bundled), user)


def save_app_config(config: dict[str, Any]) -> Path:
    """Persist the application configuration to the per-user override file."""
    return save_user_yaml(APP_CONFIG_FILENAME, config)


def _split_key(key: str) -> tuple[str, ...]:
    return tuple(part for part in key.split("/") if part)


def get_app_config_value(
    key: str,
    default: Any = None,
    *,
    config: dict[str, Any] | None = None,
) -> Any:
    """Return a nested application config value addressed by slash-delimited *key*."""
    current: Any = load_app_config() if config is None else config
    for part in _split_key(key):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def set_app_config_value(config: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    """Set a nested slash-delimited config key in *config*."""
    current: dict[str, Any] = config
    parts = _split_key(key)
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value
    return config


def default_data_directory(*, config: dict[str, Any] | None = None) -> str:
    """Return the configured default data directory."""
    return str(get_app_config_value(KEY_DEFAULT_DATA_DIR, "", config=config) or "").strip()


def theme_setting(*, config: dict[str, Any] | None = None) -> str:
    """Return the configured theme name."""
    value = str(get_app_config_value(KEY_THEME, DEFAULT_THEME, config=config) or "").strip().lower()
    return value or DEFAULT_THEME


def feature_enabled(feature: str, *, config: dict[str, Any] | None = None) -> bool:
    """Return whether a named controller feature is enabled."""
    return bool(get_app_config_value(FEATURE_KEYS[feature], True, config=config))
