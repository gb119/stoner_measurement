"""Tests for guarding destructive sequence operations."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from qtpy.QtWidgets import QMessageBox

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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
