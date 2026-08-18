"""Tests for guarding destructive sequence operations."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from qtpy.QtWidgets import QFileDialog, QMessageBox

from stoner_measurement.app import MeasurementApp


def _fake_app(*, current_digest: str, clean_digest: str, save_result: bool = True):
    commits: list[bool] = []
    saves: list[bool] = []
    config_panel = SimpleNamespace(commit_pending_changes=lambda: commits.append(True))
    fake = SimpleNamespace(
        _main_window=SimpleNamespace(config_panel=config_panel),
        _measurement_clean_digest=clean_digest,
        _measurement_digest=lambda: current_digest,
        _on_save_as_measurement=lambda: saves.append(True) or save_result,
    )
    return fake, commits, saves


def test_unchanged_sequence_continues_without_prompt(monkeypatch):
    fake, commits, saves = _fake_app(current_digest="same", clean_digest="same")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: pytest.fail("unchanged sequence should not prompt"),
    )

    assert MeasurementApp._confirm_discard_measurement_changes(fake) is True
    assert commits == [True]
    assert saves == []


@pytest.mark.parametrize(
    ("answer", "expected", "save_result", "expected_saves"),
    [
        (QMessageBox.StandardButton.No, True, True, []),
        (QMessageBox.StandardButton.Cancel, False, True, []),
        (QMessageBox.StandardButton.Yes, True, True, [True]),
        (QMessageBox.StandardButton.Yes, False, False, [True]),
    ],
)
def test_changed_sequence_honours_prompt_choice(
    monkeypatch, answer, expected, save_result, expected_saves
):
    fake, commits, saves = _fake_app(
        current_digest="changed", clean_digest="original", save_result=save_result
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: answer)

    assert MeasurementApp._confirm_discard_measurement_changes(fake) is expected
    assert commits == [True]
    assert saves == expected_saves


@pytest.mark.parametrize(
    ("migrated", "expected_calls"),
    [
        (False, ["clean"]),
        (True, ["dirty"]),
    ],
)
def test_loaded_sequence_migration_controls_clean_baseline(migrated, expected_calls):
    calls: list[str] = []
    fake = SimpleNamespace(
        _mark_measurement_clean=lambda: calls.append("clean"),
        _mark_measurement_dirty=lambda: calls.append("dirty"),
    )

    MeasurementApp._set_loaded_measurement_baseline(fake, migrated=migrated)

    assert calls == expected_calls


def test_mark_measurement_dirty_clears_saved_digest():
    title_updates: list[bool] = []
    fake = SimpleNamespace(
        _measurement_clean_digest="saved-sha256",
        _update_window_title=lambda: title_updates.append(True),
    )

    MeasurementApp._mark_measurement_dirty(fake)

    assert fake._measurement_clean_digest == ""
    assert title_updates == [True]


def test_import_data_loads_reconstructed_sequence_and_marks_it_dirty(monkeypatch, tmp_path):
    import stoner_measurement.core.sequence_metadata as sequence_metadata_module

    data_path = tmp_path / "measurement.txt"
    reconstructed = {"version": "test", "steps": [{"plugin": {"instance_name": "step"}}]}
    events: list[object] = []
    document = object()
    fake = SimpleNamespace(
        _current_measurement_path=Path("previous.json"),
        _app_config={},
        _sequence_steps_from_json=lambda data: ([object()], False)
        if data is reconstructed
        else None,
        _store_active_sequence=lambda: events.append("store"),
        _new_sequence_document=lambda data, dirty: document
        if data is reconstructed and dirty
        else None,
        _add_sequence_document=lambda added: events.append(("add", added)),
        _engine=SimpleNamespace(is_running=False),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args: (str(data_path), "Saved Data"),
    )
    monkeypatch.setattr(
        sequence_metadata_module,
        "sequence_json_from_data_file",
        lambda path: reconstructed if path == data_path else None,
    )

    MeasurementApp._on_import_sequence_from_data(fake)

    assert events == ["store", ("add", document)]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
