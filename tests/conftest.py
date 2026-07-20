"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import pytest
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
    # Schedule the plot widget for Qt deletion then flush the event queue
    # so every deferred scene-paint event is processed while the C++ side
    # is still valid.  Without this, Python-subclassed QGraphicsItems
    # (e.g. _SafeErrorBarItem) leave pending events that land in a later
    # test's _process_events loop and cause a fatal abort on Python 3.14.
    pw = eng.plot_widget
    if pw is not None:
        eng.plot_widget = None
        pw.deleteLater()
        del pw
        QApplication.processEvents()
