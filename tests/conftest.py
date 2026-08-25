"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

import pytest
from qtpy.QtCore import QCoreApplication, QEvent
from qtpy.QtWidgets import QApplication, QMessageBox, QWidget

from stoner_measurement import resources
from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.core.sequence_engine import SequenceEngine
from stoner_measurement.plugins.trace import DummyPlugin

_WidgetT = TypeVar("_WidgetT", bound=QWidget)


@pytest.fixture(scope="session")
def qapp():
    """Provide a single QApplication instance for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def managed_qt_widget(qapp):
    """Retain and deterministically destroy widgets created by a test.

    pytest-qt processes the event queue immediately after the test function
    returns, before fixture teardown.  Keeping strong references here prevents
    a widget's Python wrapper from disappearing while Qt still has deferred
    events queued for its children.
    """
    widgets: list[QWidget] = []

    def manage(widget: _WidgetT) -> _WidgetT:
        widgets.append(widget)
        return widget

    yield manage

    for widget in reversed(widgets):
        try:
            widget.close()
        except RuntimeError:
            pass
    qapp.processEvents()

    for widget in reversed(widgets):
        try:
            widget.deleteLater()
        except RuntimeError:
            pass
    event_types = getattr(QEvent, "Type", QEvent)
    QCoreApplication.sendPostedEvents(None, event_types.DeferredDelete)
    qapp.processEvents()
    widgets.clear()


@pytest.fixture
def managed_measurement_app(managed_qt_widget):
    """Create application windows and shut down all owned resources first.

    ``MeasurementApp.close()`` can legitimately be rejected when a sequence
    document is dirty.  Tests therefore call the application's unconditional
    shutdown path before the generic widget fixture closes and deletes the Qt
    object hierarchy.
    """
    from stoner_measurement.app import MeasurementApp

    apps: list[MeasurementApp] = []

    def create() -> MeasurementApp:
        app = managed_qt_widget(MeasurementApp())
        apps.append(app)
        return app

    yield create

    for app in reversed(apps):
        app.shutdown()


@pytest.fixture(autouse=True)
def suppress_modal_message_boxes(monkeypatch):
    """Prevent modal QMessageBox displays from blocking headless tests."""

    def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("qtpy.QtWidgets.QMessageBox.warning", _noop)
    monkeypatch.setattr("qtpy.QtWidgets.QMessageBox.critical", _noop)
    monkeypatch.setattr("qtpy.QtWidgets.QMessageBox.information", _noop)
    monkeypatch.setattr("qtpy.QtWidgets.QMessageBox.about", _noop)
    monkeypatch.setattr(
        "qtpy.QtWidgets.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )


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
