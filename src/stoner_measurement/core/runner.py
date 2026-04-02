"""Sequence runner — executes a :class:`~stoner_measurement.core.sequence.Sequence`
in a background :class:`QThread` and emits data/status signals.
"""

from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from stoner_measurement.core.sequence import Sequence, SequenceStep

logger = logging.getLogger(__name__)


class _WorkerThread(QThread):
    """Background thread that iterates over sequence steps."""

    data_ready = pyqtSignal(float, float)
    status_changed = pyqtSignal(str)
    step_started = pyqtSignal(int, str)   # (step_index, plugin_name)
    step_finished = pyqtSignal(int)       # step_index
    finished_all = pyqtSignal()

    def __init__(
        self,
        sequence: Sequence,
        plugins: dict[str, Any],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._sequence = sequence
        self._plugins = plugins
        self._stop_requested = False

    def request_stop(self) -> None:
        """Ask the worker to stop after the current step."""
        self._stop_requested = True

    def run(self) -> None:  # pragma: no cover  (runs in separate thread)
        """Execute the sequence, emitting signals for each step."""
        self.status_changed.emit("Running…")
        for index, step in enumerate(self._sequence):
            if self._stop_requested:
                self.status_changed.emit("Stopped")
                return

            self.step_started.emit(index, step.plugin_name)
            plugin = self._plugins.get(step.plugin_name)
            if plugin is None:
                logger.warning("No plugin found for step %r", step.plugin_name)
                self.step_finished.emit(index)
                continue

            try:
                for x, y in plugin.execute(step.parameters):
                    if self._stop_requested:
                        self.status_changed.emit("Stopped")
                        return
                    self.data_ready.emit(float(x), float(y))
            except Exception as exc:
                logger.error("Step %d failed: %s", index, exc)
                self.status_changed.emit(f"Error in step {index}: {exc}")
                return

            self.step_finished.emit(index)

        self.status_changed.emit("Finished")
        self.finished_all.emit()


class SequenceRunner(QObject):
    """Controls execution of a :class:`~stoner_measurement.core.sequence.Sequence`.

    Signals
    -------
    data_ready(x, y):
        Emitted for every data point produced by a plugin step.
    status_changed(message):
        Emitted whenever the runner status changes.
    step_started(index, plugin_name):
        Emitted at the start of each step.
    step_finished(index):
        Emitted when a step completes successfully.
    finished:
        Emitted when the whole sequence has run to completion.
    """

    data_ready = pyqtSignal(float, float)
    status_changed = pyqtSignal(str)
    step_started = pyqtSignal(int, str)
    step_finished = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sequence: Sequence = Sequence()
        self._plugins: dict[str, Any] = {}
        self._worker: _WorkerThread | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def sequence(self) -> Sequence:
        """The sequence that will be executed on the next :meth:`start` call."""
        return self._sequence

    @sequence.setter
    def sequence(self, value: Sequence) -> None:
        self._sequence = value

    def set_plugins(self, plugins: dict[str, Any]) -> None:
        """Provide the plugin instances needed to execute the sequence."""
        self._plugins = plugins

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """``True`` while a sequence is executing."""
        return self._worker is not None and self._worker.isRunning()

    def start(self) -> None:
        """Start executing the current sequence in a background thread."""
        if self.is_running:
            logger.warning("Sequence is already running")
            return

        self._worker = _WorkerThread(
            sequence=self._sequence,
            plugins=self._plugins,
        )
        self._worker.data_ready.connect(self.data_ready)
        self._worker.status_changed.connect(self.status_changed)
        self._worker.step_started.connect(self.step_started)
        self._worker.step_finished.connect(self.step_finished)
        self._worker.finished_all.connect(self.finished)
        self._worker.start()

    def stop(self) -> None:
        """Request the running sequence to stop after the current step."""
        if self._worker is not None:
            self._worker.request_stop()
            self._worker.wait(2000)
