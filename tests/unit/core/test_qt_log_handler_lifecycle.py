"""Qt log-handler ownership during explicit and cyclic engine teardown."""

import gc
import logging
from weakref import ref

import pytest
from qtpy.QtCore import QCoreApplication, QEvent, QObject

from stoner_measurement.core.sequence_engine import SequenceEngine, _QtLogHandler


def _delete_parent(parent, qapp):
    parent.deleteLater()
    event_types = getattr(QEvent, "Type", QEvent)
    QCoreApplication.sendPostedEvents(None, event_types.DeferredDelete)
    qapp.processEvents()


def test_closed_handler_can_be_collected_before_its_qt_parent(qapp):
    parent = QObject()
    handler = _QtLogHandler(parent=parent)
    handler_ref = ref(handler)
    handler.close()
    del handler
    gc.collect()
    try:
        # Qt's destroyed callback must not keep an unused handler alive or
        # resurrect it while cyclic GC is clearing its engine/emitter graph.
        assert handler_ref() is None
    finally:
        _delete_parent(parent, qapp)


def test_native_parent_deletion_detaches_only_its_live_handler(qapp):
    logger = logging.getLogger("stoner_measurement.test.lifecycle")
    parent = QObject()
    handler = _QtLogHandler(parent=parent)
    other = logging.NullHandler()
    logger.addHandler(handler)
    logger.addHandler(other)
    try:
        _delete_parent(parent, qapp)
        assert handler not in logger.handlers
        assert other in logger.handlers
        assert handler._qt_closed
    finally:
        logger.removeHandler(handler)
        logger.removeHandler(other)
        handler.close()
        other.close()


def test_shutdown_engine_and_handler_are_reclaimed_together(qapp):
    engine = SequenceEngine()
    engine_ref = ref(engine)
    handler_ref = ref(engine.log_handler)
    engine.shutdown()
    del engine
    gc.collect()
    qapp.processEvents()
    assert engine_ref() is None
    assert handler_ref() is None



def test_explicit_close_disconnects_parent_destruction_callback(qapp, monkeypatch):
    parent = QObject()
    handler = _QtLogHandler(parent=parent)
    callbacks = []
    monkeypatch.setattr(handler, "_detach_from_loggers", lambda: callbacks.append(True))
    handler.close()
    _delete_parent(parent, qapp)
    # Closed handlers have already left their loggers. There must be no Python
    # callback left for QObject destruction to invoke during cyclic collection.
    assert not callbacks


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "--pdb"]))
