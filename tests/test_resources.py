"""Targeted tests for :mod:`stoner_measurement.resources`."""

from __future__ import annotations

from pathlib import Path

from stoner_measurement import resources


class TestUserPathHelpers:
    """Tests for user configuration path helper functions."""

    def test_user_config_file_uses_user_config_root(self, monkeypatch, tmp_path):
        """user_config_file should append the filename to the resolved root."""
        monkeypatch.setattr(resources, "user_config_root", lambda: tmp_path)

        assert resources.user_config_file("toolbar.yaml") == tmp_path / "toolbar.yaml"

    def test_user_resource_file_uses_user_config_root(self, monkeypatch, tmp_path):
        """user_resource_file should append subdirectory and filename to the root."""
        monkeypatch.setattr(resources, "user_config_root", lambda: tmp_path)

        assert resources.user_resource_file("plugins", "dummy.yaml") == (
            tmp_path / "plugins" / "dummy.yaml"
        )


class TestYamlHelpers:
    """Tests for YAML loading and saving helpers."""

    def test_load_user_or_bundled_yaml_prefers_user_file(self, monkeypatch, tmp_path):
        """User YAML should take precedence over a bundled fallback file."""
        user_cfg = tmp_path / "toolbar.yaml"
        bundled_cfg = tmp_path / "bundled-toolbar.yaml"
        user_cfg.write_text("buttons:\n  - name: User\n", encoding="utf-8")
        bundled_cfg.write_text("buttons:\n  - name: Bundled\n", encoding="utf-8")

        monkeypatch.setattr(resources, "user_config_file", lambda name: user_cfg)
        monkeypatch.setattr(resources, "bundled_resource_path", lambda subdir, name: bundled_cfg)

        config = resources.load_user_or_bundled_yaml("toolbar.yaml")

        assert config["buttons"][0]["name"] == "User"

    def test_load_user_or_bundled_yaml_falls_back_to_bundled_file(self, monkeypatch, tmp_path):
        """Bundled YAML should be used when no user override file exists."""
        user_cfg = tmp_path / "toolbar.yaml"
        bundled_cfg = tmp_path / "bundled-toolbar.yaml"
        bundled_cfg.write_text("buttons:\n  - name: Bundled\n", encoding="utf-8")

        monkeypatch.setattr(resources, "user_config_file", lambda name: user_cfg)
        monkeypatch.setattr(resources, "bundled_resource_path", lambda subdir, name: bundled_cfg)

        config = resources.load_user_or_bundled_yaml("toolbar.yaml")

        assert config["buttons"][0]["name"] == "Bundled"

    def test_load_user_or_bundled_yaml_returns_empty_dict_for_missing_files(
        self,
        monkeypatch,
        tmp_path,
    ):
        """Missing user and bundled YAML files should produce an empty mapping."""
        user_cfg = tmp_path / "toolbar.yaml"

        monkeypatch.setattr(resources, "user_config_file", lambda name: user_cfg)
        monkeypatch.setattr(resources, "bundled_resource_path", lambda subdir, name: None)

        assert resources.load_user_or_bundled_yaml("toolbar.yaml") == {}

    def test_load_user_or_bundled_yaml_returns_empty_dict_for_non_mapping_user_yaml(
        self,
        monkeypatch,
        tmp_path,
    ):
        """Non-mapping YAML content should be rejected as invalid config data."""
        user_cfg = tmp_path / "toolbar.yaml"
        user_cfg.write_text("- not\n- a mapping\n", encoding="utf-8")

        monkeypatch.setattr(resources, "user_config_file", lambda name: user_cfg)

        assert resources.load_user_or_bundled_yaml("toolbar.yaml") == {}

    def test_save_user_yaml_writes_to_user_config_directory(self, monkeypatch, tmp_path):
        """save_user_yaml should serialise the mapping to the resolved path."""
        output_path = tmp_path / "toolbar.yaml"
        monkeypatch.setattr(resources, "user_config_file", lambda name: output_path)

        written = resources.save_user_yaml("toolbar.yaml", {"buttons": [{"name": "Saved"}]})

        assert written == output_path
        assert "Saved" in output_path.read_text(encoding="utf-8")


class TestToolbarConfigHelpers:
    """Tests for toolbar-specific resource helpers."""

    def test_normalise_toolbar_config_replaces_non_list_buttons(self):
        """Toolbar config should always expose a list-valued buttons entry."""
        assert resources.normalise_toolbar_config({"buttons": None}) == {"buttons": []}
        assert resources.normalise_toolbar_config({"buttons": "bad"}) == {"buttons": []}

    def test_load_toolbar_config_normalises_buttons(self, monkeypatch):
        """load_toolbar_config should normalise invalid buttons values."""
        monkeypatch.setattr(resources, "load_user_or_bundled_yaml", lambda name: {"buttons": None})

        assert resources.load_toolbar_config() == {"buttons": []}

    def test_save_toolbar_config_writes_user_toolbar_yaml(self, monkeypatch, tmp_path):
        """save_toolbar_config should write to the user toolbar override file."""
        output_path = tmp_path / "toolbar.yaml"
        captured: dict[str, object] = {}

        def _fake_save_user_yaml(name: str, config: dict[str, object]) -> Path:
            captured["name"] = name
            captured["config"] = config
            return output_path

        monkeypatch.setattr(resources, "save_user_yaml", _fake_save_user_yaml)

        written = resources.save_toolbar_config({"buttons": None})

        assert written == output_path
        assert captured["name"] == "toolbar.yaml"
        assert captured["config"] == {"buttons": None}

    def test_toolbar_config_path_returns_user_toolbar_yaml(self, monkeypatch, tmp_path):
        """toolbar_config_path should resolve the per-user toolbar YAML path."""
        monkeypatch.setattr(resources, "user_config_file", lambda name: tmp_path / name)

        assert resources.toolbar_config_path() == tmp_path / "toolbar.yaml"


class TestLookupHelpers:
    """Tests for icon and sequence lookup precedence."""

    def test_find_toolbar_icon_prefers_user_resource(self, monkeypatch, tmp_path):
        """User toolbar icons should override bundled icons with the same name."""
        user_icon = tmp_path / "resources" / "icon.png"
        bundled_icon = tmp_path / "bundled" / "icon.png"
        user_icon.parent.mkdir(parents=True)
        bundled_icon.parent.mkdir(parents=True)
        user_icon.write_bytes(b"user")
        bundled_icon.write_bytes(b"bundled")

        monkeypatch.setattr(resources, "user_resource_file", lambda subdir, name: user_icon)
        monkeypatch.setattr(resources, "bundled_resource_path", lambda subdir, name: bundled_icon)

        assert resources.find_toolbar_icon("icon.png") == user_icon

    def test_find_toolbar_icon_falls_back_to_bundled_resource(self, monkeypatch, tmp_path):
        """Bundled toolbar icons should be used when no user override exists."""
        user_icon = tmp_path / "resources" / "icon.png"
        bundled_icon = tmp_path / "bundled" / "icon.png"
        bundled_icon.parent.mkdir(parents=True)
        bundled_icon.write_bytes(b"bundled")

        monkeypatch.setattr(resources, "user_resource_file", lambda subdir, name: user_icon)
        monkeypatch.setattr(resources, "bundled_resource_path", lambda subdir, name: bundled_icon)

        assert resources.find_toolbar_icon("icon.png") == bundled_icon

    def test_find_predefined_sequence_prefers_user_resource(self, monkeypatch, tmp_path):
        """User predefined sequences should override bundled sequences."""
        user_seq = tmp_path / "sequences" / "test.json"
        bundled_seq = tmp_path / "bundled" / "test.json"
        user_seq.parent.mkdir(parents=True)
        bundled_seq.parent.mkdir(parents=True)
        user_seq.write_text("{}", encoding="utf-8")
        bundled_seq.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(resources, "user_resource_file", lambda subdir, name: user_seq)
        monkeypatch.setattr(resources, "bundled_resource_path", lambda subdir, name: bundled_seq)

        assert resources.find_predefined_sequence("test.json") == user_seq

    def test_find_predefined_sequence_falls_back_to_bundled_resource(
        self,
        monkeypatch,
        tmp_path,
    ):
        """Bundled predefined sequences should be used as the fallback layer."""
        user_seq = tmp_path / "sequences" / "test.json"
        bundled_seq = tmp_path / "bundled" / "test.json"
        bundled_seq.parent.mkdir(parents=True)
        bundled_seq.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(resources, "user_resource_file", lambda subdir, name: user_seq)
        monkeypatch.setattr(resources, "bundled_resource_path", lambda subdir, name: bundled_seq)

        assert resources.find_predefined_sequence("test.json") == bundled_seq

    def test_find_sequence_template_uses_fixed_template_filename(self, monkeypatch, tmp_path):
        """Sequence template lookup should always use sequence_template.json."""
        template_path = tmp_path / "sequences" / "sequence_template.json"
        template_path.parent.mkdir(parents=True)
        template_path.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(
            resources,
            "find_predefined_sequence",
            lambda name: template_path if name == "sequence_template.json" else None,
        )

        assert resources.find_sequence_template() == template_path
