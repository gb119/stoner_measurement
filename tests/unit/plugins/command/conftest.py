"""Shared fixtures for command-plugin tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def suppress_message_box_warnings(monkeypatch):
    """Prevent modal warning dialogs from blocking headless command-plugin tests."""
    monkeypatch.setattr(
        "qtpy.QtWidgets.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )
