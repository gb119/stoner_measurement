"""Tests for :mod:`stoner_measurement.app_config`."""

from __future__ import annotations

from stoner_measurement import app_config


def test_load_app_config_merges_defaults_bundled_and_user(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled.yaml"
    user = tmp_path / "application.yaml"
    bundled.write_text(
        "app:\n  default_data_directory: D:/LabData/\nfeatures:\n  pressure: false\n",
        encoding="utf-8",
    )
    user.write_text(
        "app:\n  theme: light\nfeatures:\n  magnetic_field: false\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(app_config, "bundled_resource_path", lambda _subdir, _name: bundled)
    monkeypatch.setattr(app_config, "app_config_path", lambda: user)

    config = app_config.load_app_config()

    assert config["app"]["default_data_directory"] == "D:/LabData/"
    assert config["app"]["theme"] == "light"
    assert config["features"]["temperature"] is True
    assert config["features"]["magnetic_field"] is False
    assert config["features"]["pressure"] is False


def test_feature_enabled_reads_named_feature_from_config():
    config = {
        "features": {
            "temperature": True,
            "magnetic_field": False,
            "motor_position": True,
            "pressure": False,
        }
    }

    assert app_config.feature_enabled("temperature", config=config) is True
    assert app_config.feature_enabled("magnetic_field", config=config) is False


def test_set_app_config_value_creates_nested_mapping():
    config: dict[str, object] = {}

    app_config.set_app_config_value(config, app_config.KEY_DEFAULT_DATA_DIR, "C:/Data/")

    assert config == {"app": {"default_data_directory": "C:/Data/"}}
