"""Shared fixtures for UI widget tests."""

from __future__ import annotations

import gc

import pytest
from qtpy.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _flush_qt_after_test(qapp):
    """Force GC and flush Qt events after every widget test.

    Python-subclassed QGraphicsItems (e.g. _SafeErrorBarItem) can leave
    deferred scene-paint events in the Qt queue when their parent widget is
    garbage-collected.  On Python 3.14, those events land in a later test's
    event-processing loop and cause a fatal abort.  Running gc.collect() and
    processEvents() during teardown ensures that any such events are
    processed immediately, while the C++ objects are still valid.
    """
    yield
    gc.collect()
    QApplication.processEvents()
