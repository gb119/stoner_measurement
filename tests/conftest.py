"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from stoner_measurement.core.plugin_manager import PluginManager
from stoner_measurement.core.runner import SequenceRunner
from stoner_measurement.plugins.dummy import DummyPlugin


@pytest.fixture(scope="session")
def qapp():
    """Provide a single QApplication instance for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def plugin_manager(qapp):
    """Return a PluginManager pre-loaded with the DummyPlugin."""
    pm = PluginManager()
    pm.register("Dummy", DummyPlugin())
    return pm


@pytest.fixture
def runner(qapp):
    """Return a fresh SequenceRunner."""
    return SequenceRunner()
