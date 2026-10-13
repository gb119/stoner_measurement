"""Thread-safe scheduling for shared controller engines."""

from __future__ import annotations

import logging
import threading
import time
from functools import wraps

from qtpy.QtCore import Qt, QThread, QTimer, Signal, Slot

logger = logging.getLogger(__name__)


def controller_action(action):
    """Serialize a controller transaction with polling and connection changes."""

    @wraps(action)
    def perform(engine, *args, **kwargs):
        with engine._engine_lock:
            return action(engine, *args, **kwargs)

    return perform


class ControllerPoller:
    """Run at most one scheduled hardware read off the GUI thread.

    Direct command reads retain the engine transaction lock. Requests queued
    while a scheduled read is pending are covered by that read, not accumulated.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = False
        self._closed = False
        self._worker = None
        self.revision = 0
        self.result = None

    def request(self, read):
        """Schedule a read without waiting for a controller or its lock."""
        with self._lock:
            if self._pending or self._closed:
                return
            self._pending = True
            worker = threading.Thread(
                target=self._run, args=(read,), daemon=True, name="controller-poll"
            )
            self._worker = worker
            try:
                worker.start()
            except BaseException:
                self._pending = False
                self._worker = None
                raise

    def _run(self, read):
        try:
            with self._lock:
                closed = self._closed
            if not closed:
                read()
        except Exception:
            logger.exception("Scheduled controller read failed")
        finally:
            with self._lock:
                self._pending = False

    def close(self):
        """Reject new scheduled reads during shutdown without taking engine locks."""
        with self._lock:
            self._closed = True

    def join(self):
        """Drain the owned worker after releasing the engine transaction lock."""
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join()


def coordinated_read(read):
    """Share an overlapping fresh read while retaining transaction ordering.

    The result revision is advanced inside the engine lock, before setters can
    run. A read requested after a setter therefore cannot reuse a pre-setter
    result. Failure results are shared too, never substituted with old success.
    """

    @wraps(read)
    def refresh(engine, *args, **kwargs):
        poller = engine._controller_poller
        revision = poller.revision
        with engine._engine_lock:
            if not args and not kwargs and poller.revision != revision:
                return poller.result
            result = read(engine, *args, **kwargs)
            poller.result = result
            poller.revision += 1
            return result

    return refresh


class ControllerUpdates:
    """Revision notifications for completed state publications, including failures.

    Waiting does not perform I/O. Consumers retain a bounded fresh-read fallback
    when automatic polling is disabled, slow, or unavailable.
    """

    def __init__(self, publisher):
        self._condition = threading.Condition()
        self._revision = 0
        publisher.state_updated.connect(self._published, Qt.ConnectionType.DirectConnection)

    def _published(self, _state):
        with self._condition:
            self._revision += 1
            self._condition.notify_all()

    @property
    def revision(self):
        """Return the latest publication revision."""
        with self._condition:
            return self._revision

    def wait(self, revision, timeout, stop_event=None):
        """Wait for a newer snapshot or cancellation; return whether it arrived."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._revision == revision:
                if stop_event is not None and stop_event.is_set():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(remaining, 0.05))
            return True


class ControllerTimer(QTimer):
    """Apply timer requests on its owner thread without blocking hardware workers.

    Queued notifications apply the latest desired state, so an old start request
    cannot restart a timer after a subsequent disconnect or shutdown.
    """

    _changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._request_lock = threading.RLock()
        self._requested_active = False
        self._requested_interval = super().interval()
        self._changed.connect(self._apply_request)

    def start(self, msec=None):
        """Request polling, optionally changing the interval."""
        with self._request_lock:
            if msec is not None:
                self._requested_interval = int(msec)
            self._requested_active = True
        self._dispatch()

    def stop(self):
        """Request polling to stop."""
        with self._request_lock:
            self._requested_active = False
        self._dispatch()

    def setInterval(self, msec):  # noqa: N802 - Qt API
        """Request an interval change on the owner thread."""
        with self._request_lock:
            self._requested_interval = int(msec)
        self._dispatch()

    def interval(self):
        """Return the requested interval even before queued delivery."""
        with self._request_lock:
            return self._requested_interval

    def _dispatch(self):
        if QThread.currentThread() == self.thread():
            self._apply_request()
        else:
            self._changed.emit()

    @Slot()
    def _apply_request(self):
        with self._request_lock:
            interval = self._requested_interval
            active = self._requested_active
            if super().interval() != interval:
                super().setInterval(interval)
            if active and not super().isActive():
                super().start()
            elif not active and super().isActive():
                super().stop()
