"""Tests for Thorlabs Kinesis USB dependency diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest

from stoner_measurement.instruments.thorlabs import (
    ThorlabsKDC101KPRMTE,
    _kinesis_base,
)


def test_missing_pyft232_reports_actionable_error(monkeypatch):
    """A missing FT232 backend should not look like a Kinesis assembly failure."""
    def _missing_ft232(name):
        assert name == "ft232"
        raise ModuleNotFoundError("No module named 'ft232'", name="ft232")

    monkeypatch.setattr(_kinesis_base, "import_module", _missing_ft232)
    driver = ThorlabsKDC101KPRMTE("27500125")

    with pytest.raises(RuntimeError, match="pyft232.*Kinesis .NET assemblies are not used"):
        driver._build_motor()  # noqa: SLF001


def test_kinesis_directory_is_added_to_windows_dll_search(tmp_path, monkeypatch):
    """The configured Kinesis directory should be registered before import."""
    dll = tmp_path / "ftd2xx.dll"
    dll.write_bytes(b"test")
    added = []
    handle = object()
    monkeypatch.setenv("THORLABS_KINESIS_DIR", str(tmp_path))
    monkeypatch.setattr(_kinesis_base.os, "name", "nt")
    monkeypatch.setattr(
        _kinesis_base.os,
        "add_dll_directory",
        lambda directory: added.append(directory) or handle,
        raising=False,
    )
    monkeypatch.setattr(_kinesis_base, "_DLL_DIRECTORY_HANDLES", [])
    monkeypatch.setattr(_kinesis_base, "_DLL_DIRECTORIES", set())

    _kinesis_base._configure_ftdi_dll_search_path()  # noqa: SLF001

    assert added == [str(Path(tmp_path).resolve())]
    assert _kinesis_base._DLL_DIRECTORY_HANDLES == [handle]  # noqa: SLF001


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
