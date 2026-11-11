"""Offline guide extraction and failure handling."""

from pathlib import Path

import pytest

from stoner_measurement import user_guide


def test_guide_is_kept_in_local_cache_after_launch(tmp_path, monkeypatch):
    package = tmp_path / "package"
    source = package / "help" / user_guide.HELP_FILENAME
    source.parent.mkdir(parents=True)
    source.write_bytes(b"ITSFguide")
    monkeypatch.setattr(user_guide.sys, "platform", "win32")
    monkeypatch.setattr(user_guide.importlib.resources, "files", lambda _: package)
    monkeypatch.setattr(user_guide, "user_cache_path", lambda *a, **k: tmp_path / "cache")
    opened = []
    monkeypatch.setattr(user_guide.os, "startfile", opened.append, raising=False)
    user_guide.open_user_guide()
    source.unlink()
    assert Path(opened[0]).read_bytes() == b"ITSFguide"
    assert Path(opened[0]).is_relative_to(tmp_path / "cache")


def test_missing_guide_explains_package_requirement(tmp_path, monkeypatch):
    monkeypatch.setattr(user_guide.sys, "platform", "win32")
    monkeypatch.setattr(user_guide.importlib.resources, "files", lambda _: tmp_path)
    with pytest.raises(FileNotFoundError, match="does not include"):
        user_guide.open_user_guide()


def test_non_windows_reports_unsupported_platform(monkeypatch):
    monkeypatch.setattr(user_guide.sys, "platform", "linux")
    with pytest.raises(OSError, match="requires Windows"):
        user_guide.open_user_guide()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
