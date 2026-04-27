"""Singleton magnet controller engine.

Provides :class:`MagnetControllerEngine`, a singleton
:class:`~PyQt6.QtCore.QObject` that owns all hardware communication with a
:class:`~stoner_measurement.instruments.magnet_controller.MagnetController`
driver.  The engine runs a polling :class:`~PyQt6.QtCore.QTimer`, calculates
derived quantities (field rate of change, at-target stability), and publishes
results via a :class:`~stoner_measurement.magnet_control.pubsub.MagnetPublisher`.

UI panels and sequence plugins interact with the engine through its public
command API; they never talk to instrument drivers directly.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer, pyqtSlot

from stoner_measurement.magnet_control.pubsub import MagnetPublisher
from stoner_measurement.magnet_control.types import (
    MagnetEngineState,
    MagnetEngineStatus,
    MagnetReading,
    MagnetStabilityConfig,
)

if TYPE_CHECKING:
    from stoner_measurement.instruments.magnet_controller import MagnetController, MagnetLimits

logger = logging.getLogger(__name__)

#: Number of timestamped field readings kept for rate-of-change estimation.
_HISTORY_SIZE = 60

#: Default polling interval in milliseconds.
_DEFAULT_POLL_INTERVAL_MS = 1000


class MagnetControllerEngine(QObject):
    """Singleton engine that mediates all communication with a magnet controller.

    The engine owns the hardware driver reference and a polling
    :class:`~PyQt6.QtCore.QTimer` that queries the instrument, computes
    derived quantities, and publishes results via its :attr:`publisher`.  It
    persists for the lifetime of the application and continues polling when
    the UI panel is closed.

    Obtain the singleton instance via :meth:`instance`.  Destroy it by calling
    :meth:`shutdown` (also called automatically on
    :attr:`~PyQt6.QtWidgets.QApplication.aboutToQuit`).

    Attributes:
        publisher (MagnetPublisher):
            The pub/sub bus; connect to its signals to receive live data.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.magnet_control.engine import MagnetControllerEngine
        >>> engine = MagnetControllerEngine.instance()
        >>> engine is MagnetControllerEngine.instance()
        True
        >>> from stoner_measurement.magnet_control.types import MagnetEngineStatus
        >>> engine.status
        <MagnetEngineStatus.DISCONNECTED: 'disconnected'>
        >>> engine.shutdown()
        >>> engine.status
        <MagnetEngineStatus.STOPPED: 'stopped'>
    """

    _singleton: MagnetControllerEngine | None = None

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the engine.

        Args:
            parent (QObject | None):
                Optional Qt parent.
        """
        super().__init__(parent)

        self.publisher: MagnetPublisher = MagnetPublisher(self)

        self._driver = None  # MagnetController | None
        self._status: MagnetEngineStatus = MagnetEngineStatus.DISCONNECTED
        self._stability_config: MagnetStabilityConfig = MagnetStabilityConfig()

        # Rolling field history: deque of (datetime, float) pairs.
        self._history: deque[tuple[datetime, float]] = deque(maxlen=_HISTORY_SIZE)

        # Stability tracking.
        self._at_target_since: datetime | None = None
        self._unstable_since: datetime | None = None
        self._stable: bool = False

        # Cached target/ramp settings (updated when commands are issued).
        self._target_field: float | None = None
        self._target_current: float | None = None
        self._ramp_rate_field: float | None = None
        self._ramp_rate_current: float | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(_DEFAULT_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> MagnetControllerEngine:
        """Return the singleton engine, creating it on first call.

        Returns:
            (MagnetControllerEngine):
                The singleton engine instance.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.magnet_control.engine import MagnetControllerEngine
            >>> e1 = MagnetControllerEngine.instance()
            >>> e2 = MagnetControllerEngine.instance()
            >>> e1 is e2
            True
            >>> e1.shutdown()
        """
        if cls._singleton is None:
            cls._singleton = cls()
            app = _qapp()
            if app is not None:
                app.aboutToQuit.connect(cls._singleton.shutdown)
        return cls._singleton

    # ------------------------------------------------------------------
    # Status property
    # ------------------------------------------------------------------

    @property
    def status(self) -> MagnetEngineStatus:
        """The current operational status of the engine.

        Returns:
            (MagnetEngineStatus):
                Current :class:`~stoner_measurement.magnet_control.types.MagnetEngineStatus`.
        """
        return self._status

    # ------------------------------------------------------------------
    # Public command API
    # ------------------------------------------------------------------

    def connect_instrument(self, driver: MagnetController) -> None:
        """Connect to a magnet controller driver and start polling.

        Args:
            driver (MagnetController):
                A fully constructed and already-opened
                :class:`~stoner_measurement.instruments.magnet_controller.MagnetController`
                instance.

        Raises:
            RuntimeError:
                If the engine has been shut down.
        """
        if self._status == MagnetEngineStatus.STOPPED:
            raise RuntimeError("Engine has been shut down and cannot accept new connections.")
        self._timer.stop()
        self._driver = driver
        self._history.clear()
        self._at_target_since = None
        self._unstable_since = None
        self._stable = False
        self._set_status(MagnetEngineStatus.CONNECTED)
        self._timer.start()
        logger.info("MagnetControllerEngine: connected to %s", type(driver).__name__)

    def disconnect_instrument(self) -> None:
        """Stop polling and release the driver reference."""
        self._timer.stop()
        self._driver = None
        self._history.clear()
        self._at_target_since = None
        self._unstable_since = None
        self._stable = False
        self._set_status(MagnetEngineStatus.DISCONNECTED)
        logger.info("MagnetControllerEngine: disconnected.")

    def set_target_field(self, field: float) -> None:
        """Set the target magnetic field.

        Args:
            field (float):
                Desired target field in tesla.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_target_field(field)
            self._target_field = field
        except Exception:
            logger.exception("Failed to set target field to %s T", field)

    def set_target_current(self, current: float) -> None:
        """Set the target output current.

        Args:
            current (float):
                Desired target current in amps.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_target_current(current)
            self._target_current = current
        except Exception:
            logger.exception("Failed to set target current to %s A", current)

    def set_ramp_rate_field(self, rate: float) -> None:
        """Set the field ramp rate.

        Args:
            rate (float):
                Ramp rate in tesla per minute.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_ramp_rate_field(rate)
            self._ramp_rate_field = rate
        except Exception:
            logger.exception("Failed to set field ramp rate to %s T/min", rate)

    def set_ramp_rate_current(self, rate: float) -> None:
        """Set the current ramp rate.

        Args:
            rate (float):
                Ramp rate in amps per minute.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_ramp_rate_current(rate)
            self._ramp_rate_current = rate
        except Exception:
            logger.exception("Failed to set current ramp rate to %s A/min", rate)

    def set_magnet_constant(self, tesla_per_amp: float) -> None:
        """Set the magnet constant used for field/current conversion.

        Args:
            tesla_per_amp (float):
                Magnet constant in tesla per amp.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_magnet_constant(tesla_per_amp)
        except Exception:
            logger.exception("Failed to set magnet constant to %s T/A", tesla_per_amp)

    def set_limits(self, limits: MagnetLimits) -> None:
        """Set operating limits for the connected magnet supply.

        Args:
            limits (MagnetLimits):
                Maximum current, field, and ramp rate limits.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_limits(limits)
        except Exception:
            logger.exception("Failed to set magnet limits")

    def ramp_to_target(self) -> None:
        """Start ramping to the currently programmed target."""
        if self._driver is None:
            return
        try:
            self._driver.ramp_to_target()
        except Exception:
            logger.exception("Failed to start ramp to target")

    def ramp_to_field(self, field: float) -> None:
        """Set a new target field and begin ramping.

        Args:
            field (float):
                Desired target field in tesla.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_target_field(field)
            self._target_field = field
            self._driver.ramp_to_target()
        except Exception:
            logger.exception("Failed to ramp to field %s T", field)

    def pause_ramp(self) -> None:
        """Pause an active ramp, holding the output at its current value."""
        if self._driver is None:
            return
        try:
            self._driver.pause_ramp()
        except Exception:
            logger.exception("Failed to pause ramp")

    def abort_ramp(self) -> None:
        """Abort an active ramp immediately."""
        if self._driver is None:
            return
        try:
            self._driver.abort_ramp()
        except Exception:
            logger.exception("Failed to abort ramp")

    def heater_on(self) -> None:
        """Energise the persistent switch heater."""
        if self._driver is None:
            return
        try:
            self._driver.heater_on()
        except Exception:
            logger.exception("Failed to turn heater on")

    def heater_off(self) -> None:
        """De-energise the persistent switch heater."""
        if self._driver is None:
            return
        try:
            self._driver.heater_off()
        except Exception:
            logger.exception("Failed to turn heater off")

    def set_stability_config(self, config: MagnetStabilityConfig) -> None:
        """Replace the stability-evaluation configuration.

        Args:
            config (MagnetStabilityConfig):
                New stability configuration to apply immediately.
        """
        self._stability_config = config
        self._at_target_since = None
        self._unstable_since = None
        self._stable = False

    def set_poll_interval(self, ms: int) -> None:
        """Set the polling interval.

        Args:
            ms (int):
                Polling interval in milliseconds (minimum 100 ms).
        """
        ms = max(100, ms)
        self._timer.setInterval(ms)

    def get_engine_state(self) -> MagnetEngineState:
        """Return a snapshot of the current engine state without polling.

        Returns:
            (MagnetEngineState):
                Current engine state snapshot.  The ``reading`` field is
                ``None`` when no instrument is connected.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.magnet_control.engine import MagnetControllerEngine
            >>> engine = MagnetControllerEngine.instance()
            >>> state = engine.get_engine_state()
            >>> state.reading is None
            True
            >>> engine.shutdown()
        """
        return MagnetEngineState(
            reading=None,
            target_field=self._target_field,
            target_current=self._target_current,
            ramp_rate_field=self._ramp_rate_field,
            ramp_rate_current=self._ramp_rate_current,
            magnet_constant=self._driver.magnet_constant if self._driver is not None else None,
            at_target=self._stable,
            engine_status=self._status,
        )

    @pyqtSlot()
    def shutdown(self) -> None:
        """Stop polling, release the driver, and mark the engine as stopped.

        After calling this method the engine can no longer be used.  The
        singleton reference is also cleared so :meth:`instance` will create a
        fresh instance if called again.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.magnet_control.engine import MagnetControllerEngine
            >>> e = MagnetControllerEngine()
            >>> e.shutdown()
            >>> e.status
            <MagnetEngineStatus.STOPPED: 'stopped'>
        """
        self._timer.stop()
        if self._driver is not None:
            try:
                self._driver.disconnect()
            except Exception:
                logger.exception("Error while disconnecting magnet controller on shutdown")
        self._driver = None
        self._set_status(MagnetEngineStatus.STOPPED)
        if MagnetControllerEngine._singleton is self:
            MagnetControllerEngine._singleton = None
        logger.info("MagnetControllerEngine: shut down.")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _poll(self) -> None:
        """Query the instrument, compute derived quantities, and publish results."""
        if self._driver is None:
            return
        try:
            state = self._build_state()
        except Exception:
            logger.exception("MagnetControllerEngine: poll error")
            self._set_status(MagnetEngineStatus.ERROR)
            return

        self._set_status(MagnetEngineStatus.POLLING)
        self.publisher.reading_updated.emit(state.reading)
        self.publisher.state_updated.emit(state)

    def _build_state(self) -> MagnetEngineState:
        """Query the driver and return a full :class:`MagnetEngineState`.

        Returns:
            (MagnetEngineState):
                Snapshot incorporating instrument readings and derived
                stability flags.
        """
        driver = self._driver
        status = driver.status
        now = datetime.now(tz=UTC)

        field_val: float | None = status.field
        if field_val is not None:
            self._history.append((now, field_val))

        field_rate = _compute_rate(self._history)

        # Evaluate stability.
        self._evaluate_stability(field_val, now)

        reading = MagnetReading(
            timestamp=now,
            field=field_val,
            current=status.current,
            voltage=status.voltage,
            heater_on=status.heater_on,
            state=status.state,
            at_target=status.at_target,
            field_rate=field_rate,
        )

        try:
            magnet_constant: float | None = driver.magnet_constant
        except Exception:
            magnet_constant = None

        return MagnetEngineState(
            reading=reading,
            target_field=self._target_field,
            target_current=self._target_current,
            ramp_rate_field=self._ramp_rate_field,
            ramp_rate_current=self._ramp_rate_current,
            magnet_constant=magnet_constant,
            at_target=self._stable,
            engine_status=MagnetEngineStatus.POLLING,
        )

    def _evaluate_stability(self, field: float | None, now: datetime) -> None:
        """Update the stability flag based on the current field reading.

        Args:
            field (float | None):
                Current field in tesla, or ``None`` if unavailable.
            now (datetime):
                Current UTC timestamp.
        """
        cfg = self._stability_config
        if field is None or self._target_field is None:
            self._at_target_since = None
            self._try_clear_stable(now, cfg)
            return

        currently_at = abs(field - self._target_field) < cfg.tolerance_t
        field_rate = _compute_rate(self._history)

        if currently_at:
            if self._at_target_since is None:
                self._at_target_since = now
            elapsed = (now - self._at_target_since).total_seconds()
            rate_ok = abs(field_rate) < cfg.min_rate
            if elapsed >= cfg.window_s and rate_ok:
                self._unstable_since = None
                self._stable = True
            else:
                self._try_clear_stable(now, cfg)
        else:
            self._at_target_since = None
            self._try_clear_stable(now, cfg)

    def _try_clear_stable(self, now: datetime, cfg: MagnetStabilityConfig) -> None:
        """Clear the stable flag after the holdoff period has elapsed.

        Args:
            now (datetime):
                Current UTC timestamp.
            cfg (MagnetStabilityConfig):
                Active stability configuration.
        """
        if not self._stable:
            return
        if self._unstable_since is None:
            self._unstable_since = now
        holdoff_elapsed = (now - self._unstable_since).total_seconds() >= cfg.unstable_holdoff_s
        if holdoff_elapsed:
            self._stable = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_status(self, status: MagnetEngineStatus) -> None:
        """Update the engine status and emit the change signal if it changed.

        Args:
            status (MagnetEngineStatus):
                New status to apply.
        """
        if status != self._status:
            self._status = status
            self.publisher.engine_status_changed.emit(status)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _qapp():
    """Return the running QApplication instance, or None."""
    try:
        from PyQt6.QtWidgets import QApplication

        return QApplication.instance()
    except Exception:
        return None


def _compute_rate(history: deque[tuple[datetime, float]]) -> float:
    """Compute the rate of field change in tesla per minute.

    Uses a simple linear fit (least-squares slope) over the available
    timestamped history.  Returns ``0.0`` when fewer than two readings are
    available.

    Args:
        history (deque[tuple[datetime, float]]):
            Ordered sequence of ``(timestamp, value)`` pairs; oldest first.

    Returns:
        (float):
            Estimated rate of change in tesla per minute.
    """
    if len(history) < 2:
        return 0.0

    t0, _ = history[0]
    xs = []
    ys = []
    for ts, val in history:
        dt = (ts - t0).total_seconds()
        xs.append(dt)
        ys.append(val)

    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0.0:
        return 0.0
    slope_per_second = (n * sum_xy - sum_x * sum_y) / denom
    return slope_per_second * 60.0  # convert T/s → T/min
