"""Ordered plotting requests, GUI dispatch and thread-safe completion tickets."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, replace
from threading import Condition, RLock
from typing import Any

from qtpy.QtCore import QObject, Qt, QThread  # type: ignore[attr-defined]

from stoner_measurement.core.plotting.contracts import (
    ClearPlot,
    PlotData,
    PlotRequest,
    PlotResult,
    RemoveSeries,
    ResultStatus,
    SeriesDescription,
    SeriesUpdate,
    UpdateMode,
)
from stoner_measurement.qt_compat import pyqtSignal, pyqtSlot


class UnsupportedDisplayOperation(RuntimeError):
    """The active display cannot represent an optional compatibility operation."""


class CompletionTicket:
    """Wait for one terminal request result without touching any GUI object.

    Args:
        request_id (str): Unique submission identity.
    """

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self._condition = Condition()
        self._result: PlotResult | None = None
        self._gui_thread = None
        self.value: Any = None

    def wait(self, timeout: float | None = None) -> PlotResult | None:
        """Return the result, or None on wait timeout; never cancel implicitly."""
        with self._condition:
            if (
                self._result is None
                and timeout != 0
                and QThread.currentThread() == self._gui_thread
            ):
                raise RuntimeError("GUI callers must not wait for queued plotting work.")
            self._condition.wait_for(lambda: self._result is not None, timeout=timeout)
            return self._result

    def finish(self, result: PlotResult, value: Any = None) -> bool:
        """Record completion once and wake worker waiters."""
        with self._condition:
            if self._result is not None:
                return False
            self.value = value
            self._result = result
            self._condition.notify_all()
            return True


@dataclass(frozen=True)
class LegacyCall:
    """Internal Cartesian compatibility call; not a portable display message."""

    name: str
    args: tuple
    kwargs: dict


class PlotService(QObject):
    """Own ordered plotting state while borrowing a GUI-thread renderer bridge.

    Args:
        bridge (object | None): Cartesian bridge implementing validate/apply and
            public descriptions. None preserves headless execution.
        parent (QObject | None): Application owner, never an acquisition plugin.
        max_pending (int): Maximum accepted outstanding requests.

    Notes:
        Construct on the GUI thread. submit is thread-safe and asynchronous;
        apply_now is the synchronous GUI compatibility path. Rendering is
        always confined to this object's thread. Completed tickets are released
        by the service, while IDs remain reserved for its lifetime.
    """

    _wake = pyqtSignal()
    result_ready = pyqtSignal(object)
    descriptions_changed = pyqtSignal()

    def __init__(self, bridge=None, parent=None, *, max_pending: int = 128) -> None:
        super().__init__(parent)
        if max_pending < 1:
            raise ValueError("max_pending must be positive.")
        self._bridge = bridge
        self._lock = RLock()
        self._queue: deque[tuple[PlotRequest, LegacyCall | None]] = deque()
        self._pending: dict[str, CompletionTicket] = {}
        self._seen: set[str] = set()
        self._active: str | None = None
        self._closed = False
        self._switching = False
        self._max_pending = max_pending
        self._generation = 1 if bridge is not None else 0
        self._series: dict[str, SeriesUpdate] = {}
        self._chunks: dict[str, list[PlotData]] = {}
        self._axes = ()
        self._descriptions = ()
        self._wake.connect(self._drain, Qt.ConnectionType.QueuedConnection)
        if bridge is not None:
            bridge.changed.connect(self._refresh_descriptions)
            self._refresh_descriptions()

    def is_gui_thread(self) -> bool:
        """Return whether the caller may execute the synchronous GUI path."""
        return QThread.currentThread() == self.thread()

    def submit(self, request: PlotRequest) -> CompletionTicket:
        """Accept an immutable request and return its asynchronous ticket."""
        return self._enqueue(request)

    def _enqueue(self, request: PlotRequest, legacy: LegacyCall | None = None) -> CompletionTicket:
        with self._lock:
            if self._switching:
                raise RuntimeError("Display replacement is in progress; retry after it finishes.")
            if request.request_id in self._seen:
                raise ValueError("A plotting request ID cannot be reused.")
            if len(self._pending) >= self._max_pending:
                raise RuntimeError("Plot request queue is full.")
            self._seen.add(request.request_id)
            ticket = CompletionTicket(request.request_id)
            ticket._gui_thread = self.thread()
            self._pending[request.request_id] = ticket
            if self._closed:
                self._finish(request, ResultStatus.CANCELLED, "Plot service has shut down.")
            else:
                self._queue.append((request, legacy))
                self._wake.emit()
            return ticket

    def apply_now(self, request: PlotRequest) -> CompletionTicket:
        """Apply through ordered dispatch on the GUI thread without waiting."""
        if not self.is_gui_thread():
            raise RuntimeError("apply_now is reserved for GUI callers.")
        if self._active is not None:
            raise RuntimeError("Synchronous plotting cannot re-enter an active request.")
        ticket = self.submit(request)
        self._drain()
        return ticket

    def invoke_legacy(self, call: LegacyCall) -> CompletionTicket:
        """Route an allowlisted compatibility operation through the same queue."""
        if self.is_gui_thread() and self._active is not None:
            raise RuntimeError("Synchronous plotting cannot re-enter an active request.")
        request = PlotRequest(ClearPlot())  # Internal identity envelope only.
        ticket = self._enqueue(request, call)
        if self.is_gui_thread():
            self._drain()
        return ticket

    def _finish(self, request, status, message="", value=None) -> None:
        with self._lock:
            ticket = self._pending.get(request.request_id)
            if ticket is None:
                return
            marker_id = (
                value
                if status == ResultStatus.APPLIED
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value > 0
                else None
            )
            result = PlotResult(
                request.request_id, request.target, self._generation, status, message, marker_id
            )
            if ticket.finish(result, value):
                self._pending.pop(request.request_id, None)
                self.result_ready.emit(result)

    @pyqtSlot()
    def _drain(self) -> None:
        if not self.is_gui_thread():
            raise RuntimeError("Plot dispatch must run on the GUI thread.")
        while True:
            with self._lock:
                if self._active is not None or not self._queue:
                    return
                request, legacy = self._queue.popleft()
                if request.request_id not in self._pending:
                    continue
                self._active = request.request_id
            try:
                if request.target != "main":
                    self._finish(request, ResultStatus.UNSUPPORTED, "Unknown display target.")
                elif self._bridge is None:
                    self._finish(request, ResultStatus.NO_DISPLAY)
                else:
                    self._apply(request, legacy)
            except UnsupportedDisplayOperation as exc:
                self._finish(request, ResultStatus.UNSUPPORTED, str(exc))
            except Exception as exc:  # Results must also acknowledge renderer failures.
                self._finish(request, ResultStatus.FAILED, f"{type(exc).__name__}: {exc}")
            finally:
                with self._lock:
                    self._active = None

    def _apply(self, request: PlotRequest, legacy: LegacyCall | None) -> None:
        if legacy is not None:
            legacy = self._bridge.normalize_legacy(legacy)
            if legacy.name in {"append_point", "set_trace", "set_trace_with_errors"}:
                with self._lock:
                    existing = self._series.get(legacy.args[0])
                update = self._bridge.legacy_update(legacy, existing)
                self._apply(
                    PlotRequest(update, target=request.target, request_id=request.request_id), None
                )
                return
            value = self._bridge.call_legacy(legacy)
            with self._lock:
                if legacy.name == "clear_all":
                    self._series.clear()
                    self._chunks.clear()
                elif legacy.name == "remove_trace":
                    self._series.pop(legacy.args[0], None)
                    self._chunks.pop(legacy.args[0], None)
                elif legacy.name == "rename_trace" and legacy.args[0] in self._series:
                    old, new = legacy.args[:2]
                    self._series[new] = replace(self._series.pop(old), series_id=new)
                    self._chunks[new] = self._chunks.pop(old)
            self._refresh_descriptions()
            self._finish(request, ResultStatus.APPLIED, value=value)
            return
        reasons = self._bridge.capabilities.unsupported_reasons(request)
        if reasons:
            self._finish(request, ResultStatus.UNSUPPORTED, " ".join(reasons))
            return
        payload = request.payload
        with self._lock:
            existing = self._series.get(getattr(payload, "series_id", ""))
        if (
            isinstance(payload, SeriesUpdate)
            and payload.mode == UpdateMode.APPEND
            and existing is not None
        ):
            if (
                payload.binding != existing.binding
                or payload.coordinates != existing.coordinates
                or set(payload.data.channels) != set(existing.data.channels)
                or payload.data.metadata != existing.data.metadata
                or set(payload.data.uncertainties) != set(existing.data.uncertainties)
            ):
                raise ValueError(
                    "Append must preserve channel schema, metadata and coordinate binding."
                )
        self._bridge.validate(payload)
        value = self._bridge.apply(payload)
        with self._lock:
            if isinstance(payload, SeriesUpdate):
                self._series[payload.series_id] = payload
                if payload.mode == UpdateMode.APPEND and existing is not None:
                    self._chunks[payload.series_id].append(payload.data)
                else:
                    self._chunks[payload.series_id] = [payload.data]
            elif isinstance(payload, RemoveSeries):
                self._series.pop(payload.series_id, None)
                self._chunks.pop(payload.series_id, None)
            elif isinstance(payload, ClearPlot):
                self._series.clear()
                self._chunks.clear()
        self._refresh_descriptions()
        self._finish(request, ResultStatus.APPLIED, value=value)

    @pyqtSlot()
    def _refresh_descriptions(self) -> None:
        if self._bridge is None:
            return
        axes, descriptions = self._bridge.descriptions()
        with self._lock:
            self._axes = axes
            self._descriptions = tuple(
                replace(
                    description,
                    binding=self._series[description.series_id].binding,
                    coordinates=self._series[description.series_id].coordinates,
                )
                if description.series_id in self._series
                else description
                for description in descriptions
            )
        self.descriptions_changed.emit()

    def axes(self, target="main") -> tuple:
        """Return a thread-safe axis-description snapshot."""
        with self._lock:
            return self._axes if target == "main" else ()

    def series(self, target="main") -> tuple[SeriesDescription, ...]:
        """Return public series descriptions without graphics references."""
        with self._lock:
            return self._descriptions if target == "main" else ()

    def capabilities(self, target="main"):
        """Return fixed-renderer capabilities, or None without that display."""
        return self._bridge.capabilities if target == "main" and self._bridge is not None else None

    def is_busy_for_data(self) -> bool:
        """Report whether accepted requests remain outstanding."""
        with self._lock:
            return bool(self._pending)

    def cancel_pending(self, message="Plot request cancelled.") -> None:
        """Cancel queued work once; an operation already applying may finish."""
        with self._lock:
            queued = list(self._queue)
            self._queue.clear()
            for request, _legacy in queued:
                self._finish(request, ResultStatus.CANCELLED, message)

    def cancel(self, ticket: CompletionTicket, message="Plot request cancelled.") -> None:
        """Cancel one queued ticket without affecting other producers."""
        with self._lock:
            remaining: deque[tuple[PlotRequest, LegacyCall | None]] = deque()
            for request, legacy in self._queue:
                if request.request_id == ticket.request_id:
                    self._finish(request, ResultStatus.CANCELLED, message)
                else:
                    remaining.append((request, legacy))
            self._queue = remaining

    def shutdown(self) -> None:
        """Cancel pending requests without closing the borrowed widget."""
        with self._lock:
            self._closed = True
            self.cancel_pending("Plot service has shut down.")
        if self._bridge is not None:
            self._bridge.changed.disconnect(self._refresh_descriptions)
            self._bridge = None

    def data_snapshot(self, series_id: str) -> PlotData:
        """Assemble plotted chunks only when explicitly requested, not on append."""
        import numpy as np

        with self._lock:
            chunks = tuple(self._chunks[series_id])
        channels = {
            key: np.concatenate([chunk.channels[key] for chunk in chunks])
            for key in chunks[0].channels
        }
        errors = {
            key: np.concatenate(
                [
                    chunk.uncertainties.get(key, np.zeros(len(chunk.channels[key])))
                    for chunk in chunks
                ]
            )
            for key in set().union(*(chunk.uncertainties for chunk in chunks))
        }
        return PlotData(channels, chunks[0].metadata, errors)

    @contextmanager
    def replacement_guard(self):
        """Reserve an idle dispatcher; reject new work during candidate hydration."""
        if not self.is_gui_thread():
            raise RuntimeError("Display replacement must run on the GUI thread.")
        with self._lock:
            if self._closed or self._switching or self._pending or self._active is not None:
                raise RuntimeError("Display replacement requires an idle plot service.")
            self._switching = True
        try:
            yield
        finally:
            with self._lock:
                self._switching = False

    def export_state(self, renderer_state):
        """Combine explicit renderer presentation with canonical source channels."""
        from stoner_measurement.core.plotting.state import SeriesState

        series = []
        for entry in renderer_state.series:
            update = entry.update
            source = self._series.get(update.series_id)
            if source is not None:
                update = replace(
                    update,
                    data=self.data_snapshot(update.series_id),
                    binding=source.binding,
                    coordinates=source.coordinates,
                    presentation=source.presentation,
                )
            series.append(SeriesState(update, entry.visible))
        return replace(renderer_state, series=tuple(series))

    def commit_replacement(self, state, descriptions) -> None:
        """Advance generation and adopt hydrated shared state without new tickets."""
        if not self.is_gui_thread() or not self._switching:
            raise RuntimeError("Replacement must hold the GUI dispatcher reservation.")
        with self._lock:
            self._series = {entry.update.series_id: entry.update for entry in state.series}
            self._chunks = {key: [update.data] for key, update in self._series.items()}
            self._generation += 1
            self._axes, rendered = descriptions
            self._descriptions = tuple(
                replace(
                    entry,
                    binding=self._series[entry.series_id].binding,
                    coordinates=self._series[entry.series_id].coordinates,
                )
                if entry.series_id in self._series
                else entry
                for entry in rendered
            )
        self.descriptions_changed.emit()


def submit_from_plugin(plugin, payload, *, required=True) -> bool:
    """Submit one complete producer operation, preserving legacy fallback.

    Returns:
        (bool): True when a service handled the operation; False for legacy
            signal routing. GUI calls apply synchronously without event waits.
    """
    engine = plugin.sequence_engine
    client = getattr(engine, "plot_client", None)
    if client is None:
        return False
    request = PlotRequest(payload)
    try:
        ticket = client.apply_now(request) if client.is_gui_thread() else client.submit(request)
        result = engine.wait_for_plot_ticket(ticket)
    except Exception as exc:
        if required:
            raise
        plugin.log.warning("Optional plot annotation failed: %s", exc)
        return True
    if result is None or result.status == ResultStatus.CANCELLED:
        return True
    if result.status not in (ResultStatus.APPLIED, ResultStatus.NO_DISPLAY):
        message = f"Plot request {request.request_id}: {result.message}"
        if required:
            raise RuntimeError(message)
        plugin.log.warning(message)
    return True
