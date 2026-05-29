"""Tests for YAML-backed plugin configuration loading."""

from __future__ import annotations

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.plugin_config import load_plugin_config, machine_config_path
from stoner_measurement.plugins.trace import DummyPlugin


class TestPluginConfigHelpers:
    """Tests for standalone plugin-config helper functions."""

    def test_machine_config_path_normalises_plugin_name(self, monkeypatch, tmp_path):
        root = tmp_path / "config-root"
        monkeypatch.setattr(
            "stoner_measurement.plugins.plugin_config.platformdirs.user_config_dir",
            lambda appname: str(root),
        )

        path = machine_config_path("Plot Trace")

        assert path == root / "plugins" / "plot_trace.yaml"

    def test_load_plugin_config_merges_bundled_and_machine_yaml(self, monkeypatch, tmp_path):
        bundled_dir = tmp_path / "bundled"
        bundled_dir.mkdir()
        (bundled_dir / "dummy.yaml").write_text(
            "\n".join(
                [
                    'critical_current: "1.0"',
                    "scan_generator:",
                    "  amplitude: 1.0",
                    "  offset: 0.0",
                ]
            ),
            encoding="utf-8",
        )

        machine_root = tmp_path / "machine"
        machine_path = machine_root / "plugins"
        machine_path.mkdir(parents=True)
        (machine_path / "dummy.yaml").write_text(
            "\n".join(
                [
                    'critical_current: "5.0"',
                    "scan_generator:",
                    "  amplitude: 2.0",
                ]
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            "stoner_measurement.plugins.plugin_config.resources.files",
            lambda package: bundled_dir,
        )
        monkeypatch.setattr(
            "stoner_measurement.plugins.plugin_config.platformdirs.user_config_dir",
            lambda appname: str(machine_root),
        )

        config = load_plugin_config("Dummy")

        assert config["critical_current"] == "5.0"
        assert config["scan_generator"]["amplitude"] == 2.0
        assert config["scan_generator"]["offset"] == 0.0


class TestPluginConfigIntegration:
    """Tests for plugin initialisation and JSON restore overlay order."""

    def test_dummy_plugin_applies_initial_yaml_config(self, monkeypatch, qapp):
        monkeypatch.setattr(
            "stoner_measurement.plugins.base_plugin.load_plugin_config",
            lambda plugin_name, *, machine_only=False: {"critical_current": "3.0"},
        )

        plugin = DummyPlugin()

        assert plugin.to_json()["critical_current"] == "3.0"

    def test_from_json_reapplies_machine_overlay_after_script_restore(self, monkeypatch, qapp):
        def _fake_load_plugin_config(plugin_name, *, machine_only=False):
            if machine_only:
                return {"critical_current": "9.0"}
            return {"critical_current": "4.0"}

        monkeypatch.setattr(
            "stoner_measurement.plugins.base_plugin.load_plugin_config",
            _fake_load_plugin_config,
        )

        plugin = DummyPlugin()
        data = plugin.to_json()
        data["critical_current"] = "2.0"

        restored = BasePlugin.from_json(data)

        assert isinstance(restored, DummyPlugin)
        assert restored.to_json()["critical_current"] == "9.0"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "--pdb"]))
