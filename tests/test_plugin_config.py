"""Tests for YAML-backed plugin configuration loading."""

from __future__ import annotations

from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.plugin_config import load_plugin_config, machine_config_path
from stoner_measurement.plugins.trace import DummyPlugin


class TestPluginConfigHelpers:
    """Tests for standalone plugin-config helper functions."""

    def test_machine_config_path_normalises_plugin_name(self, monkeypatch, tmp_path):
        """machine_config_path should resolve via the shared resources helper."""
        root = tmp_path / "config-root" / "stoner_measurement"
        monkeypatch.setattr("stoner_measurement.resources.user_config_root", lambda: root.parent)

        path = machine_config_path("Plot Trace")

        assert path == root.parent / "plugins" / "plot_trace.yaml"

    def test_load_plugin_config_merges_bundled_and_machine_yaml(self, monkeypatch, tmp_path):
        """Bundled plugin defaults should be deep-merged with machine overrides."""
        bundled_cfg = tmp_path / "bundled" / "dummy.yaml"
        bundled_cfg.parent.mkdir()
        bundled_cfg.write_text(
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

        machine_cfg = tmp_path / "machine" / "plugins" / "dummy.yaml"
        machine_cfg.parent.mkdir(parents=True)
        machine_cfg.write_text(
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
            "stoner_measurement.plugins.plugin_config.bundled_resource_path",
            lambda subdir, name: bundled_cfg,
        )
        monkeypatch.setattr(
            "stoner_measurement.plugins.plugin_config.user_resource_file",
            lambda subdir, name: machine_cfg,
        )

        config = load_plugin_config("Dummy")

        assert config["critical_current"] == "5.0"
        assert config["scan_generator"]["amplitude"] == 2.0
        assert config["scan_generator"]["offset"] == 0.0


class TestPluginConfigIntegration:
    """Tests for plugin initialisation and JSON restore overlay order."""

    def test_dummy_plugin_applies_initial_yaml_config(self, monkeypatch, qapp):  # pylint: disable=unused-argument
        """Plugin construction should apply initial YAML-backed defaults."""
        monkeypatch.setattr(
            "stoner_measurement.plugins.base_plugin.load_plugin_config",
            lambda plugin_name, *, machine_only=False: {"critical_current": "3.0"},
        )

        plugin = DummyPlugin()

        assert plugin.to_json()["critical_current"] == "3.0"

    def test_from_json_reapplies_machine_overlay_after_script_restore(self, monkeypatch, qapp):  # pylint: disable=unused-argument
        """Machine-only YAML should override restored JSON values on reload."""
        def _fake_load_plugin_config(_plugin_name, *, machine_only=False):
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
