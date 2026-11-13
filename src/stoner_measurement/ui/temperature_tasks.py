"""Serial background operations for temperature-panel hardware requests."""

import logging
import threading
import weakref
from collections import deque

from qtpy.QtCore import QObject, Qt, Signal, Slot

logger = logging.getLogger(__name__)


class TemperatureTasks(QObject):
    """Own queued hardware work; deliver results only on the Qt owner thread.

    One queue serves both sessions and every open panel. Engine transaction
    locks also serialise each request with polling and synchronous plugin calls.
    Construct and submit on the GUI thread; workers never access widgets.

    Args:
        service: Owning temperature service QObject.
    """

    finished = Signal(int, object, object)
    changed = Signal()

    def __init__(self, service):
        super().__init__(service)
        self._lock = threading.Lock()
        self._jobs = deque()
        self._callbacks = {}
        self._latest = {}
        self._epochs = {}
        self._worker = None
        self._closed = False
        self._serial = 0
        self.finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def submit(self, owner, key, session, work, done, failed, *, context=None, lifecycle=False):
        """Queue a request, coalescing duplicates and invalidating obsolete results.

        Args:
            owner: QObject whose lifetime limits delivery of the result.
            key: Logical operation key scoped to that owner.
            session: Controller session whose transaction lock protects work.
            work: Callable receiving no arguments, run on the worker thread.
            done: GUI-thread callable receiving the successful return value.
            failed: GUI-thread callable receiving a raised exception.

        Keyword Parameters:
            context: Immutable selection used to distinguish replacement requests.
            lifecycle (bool): Invalidate older work for this session before
                scheduling a connection change.

        Returns:
            (bool): Whether work was accepted, rather than coalesced or closed.
        """
        if self._closed:
            return False
        if lifecycle:
            self._epochs[session] = self._epochs.get(session, 0) + 1
        epoch = self._epochs.get(session, 0)
        driver = session.connected_driver
        identity = (id(driver), epoch, context)
        key = (id(owner), key)
        previous = self._latest.get(key)
        if previous is not None and previous[1] == identity:
            return False
        self._serial += 1
        serial = self._serial
        self._latest[key] = (serial, identity)
        self._callbacks[serial] = (weakref.ref(owner), key, session, epoch, driver, lifecycle, done, failed)
        with self._lock:
            self._jobs.append((serial, session, epoch, driver, lifecycle, work))
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name="temperature-ui", daemon=True)
                try:
                    self._worker.start()
                except BaseException:
                    self._worker = None
                    self._jobs.pop()
                    self._callbacks.pop(serial, None)
                    self._latest.pop(key, None)
                    raise
        self.changed.emit()
        return True

    def _run(self):
        while True:
            with self._lock:
                if self._closed or not self._jobs:
                    self._worker = None
                    return
                serial, session, epoch, driver, lifecycle, work = self._jobs.popleft()
            result, error = None, None
            try:
                with session._engine_lock:
                    if self._closed or epoch != self._epochs.get(session, 0):
                        continue
                    if not lifecycle and session.connected_driver is not driver:
                        continue
                    result = work()
            except BaseException as exc:
                logger.exception("Temperature operation failed (%s): %s", type(exc).__name__, exc)
                error = exc
            finally:
                self.finished.emit(serial, result, error)

    @Slot(int, object, object)
    def _deliver(self, serial, result, error):
        try:
            self._deliver_result(serial, result, error)
        finally:
            self.changed.emit()

    def _deliver_result(self, serial, result, error):
        """Discard superseded callbacks before applying a result to a live owner."""
        request = self._callbacks.pop(serial, None)
        if request is None or self._closed:
            return
        owner, key, session, epoch, driver, lifecycle, done, failed = request
        latest = self._latest.get(key)
        if latest is None or latest[0] != serial:
            return
        del self._latest[key]
        widget = owner()
        if widget is None or epoch != self._epochs.get(session, 0):
            return
        try:
            widget.thread()  # A Python wrapper can outlive its deleted Qt widget.
        except RuntimeError:
            return
        if not lifecycle and session.connected_driver is not driver:
            return
        if error is None:
            try:
                done(result)
            except Exception as exc:
                logger.exception("Temperature result could not be displayed: %s", exc)
                failed(exc)
        else:
            failed(error)

    def connection_pending(self, session):
        """Whether a connection change for this session is awaiting delivery."""
        return any(request[2] is session and request[5] for request in self._callbacks.values())

    def invalidate(self, owner, key):
        """Prevent a pending result from populating a repurposed editor."""
        self._latest.pop((id(owner), key), None)

    def close(self):
        """Drop queued jobs and callbacks; let any native operation finish."""
        with self._lock:
            self._closed = True
            self._jobs.clear()
        self._callbacks.clear()
        self._latest.clear()

    @property
    def idle(self):
        """Whether all submitted operations have delivered or discarded results."""
        return not self._callbacks

    def join(self):
        """Drain the running operation during service shutdown."""
        with self._lock:
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join()


def tasks_for(session):
    """Return the shared service's GUI-created operation queue."""
    service = getattr(session, "_service", None) or session
    tasks = getattr(service, "_temperature_tasks", None)
    if tasks is None:
        tasks = TemperatureTasks(service)
        service._temperature_tasks = tasks
    return tasks


def invalidate_request(session, owner, key):
    """Invalidate an editor's pending result without constructing a worker queue."""
    service = getattr(session, "_service", None) or session
    tasks = getattr(service, "_temperature_tasks", None)
    if tasks is not None:
        tasks.invalidate(owner, key)


def read_session(session):
    """Read one session without taking the peer controller's transaction lock."""
    from stoner_measurement.temperature_control.engine import _ControllerSession

    state = _ControllerSession.read_controller_state(session, publish=False, evaluate_stability=False)
    service = getattr(session, "_service", None) or session
    service.publisher.state_updated.emit(service.get_engine_state())
    return state
