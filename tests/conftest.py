"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import gc
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from qtpy.QtCore import QCoreApplication
from qtpy.QtWidgets import QApplication

from stoner_measurement import resources
from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.plugins.trace import DummyPlugin


@pytest.fixture(scope="session")
def qapp():
    """Provide a single QApplication instance for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def suppress_modal_message_boxes(monkeypatch):
    """Prevent modal QMessageBox displays from blocking headless tests."""

    def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("qtpy.QtWidgets.QMessageBox.warning", _noop)
    monkeypatch.setattr("qtpy.QtWidgets.QMessageBox.critical", _noop)
    monkeypatch.setattr("qtpy.QtWidgets.QMessageBox.information", _noop)
    monkeypatch.setattr("qtpy.QtWidgets.QMessageBox.about", _noop)


@pytest.fixture(autouse=True)
def isolate_persistent_test_state(monkeypatch, qapp):
    """Sandbox user config files for every test."""
    _ = qapp
    sandbox_root = Path.cwd() / ".pytest-runtime" / str(uuid4())
    config_root = sandbox_root / "user-config"
    monkeypatch.setattr(resources, "user_config_root", lambda: config_root)
    yield
    shutil.rmtree(sandbox_root, ignore_errors=True)


@pytest.fixture(autouse=True)
def cleanup_top_level_qt_widgets(qapp):
    """Destroy top-level test widgets and flush deferred Qt cleanup work."""
    existing_widgets = {id(widget) for widget in QApplication.topLevelWidgets()}
    yield
    for widget in QApplication.topLevelWidgets():
        if id(widget) in existing_widgets:
            continue
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, 0)
    qapp.processEvents()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, 0)
    qapp.processEvents()


@pytest.fixture
def plugin_manager(qapp):
    """Return a PluginManager pre-loaded with the DummyPlugin."""
    pm = PluginManager()
    pm.register("Dummy", DummyPlugin())
    return pm


@pytest.fixture
def engine(qapp):
    """Return a fresh SequenceEngine that is shut down after the test."""
    eng = SequenceEngine()
    yield eng
    eng.shutdown()
