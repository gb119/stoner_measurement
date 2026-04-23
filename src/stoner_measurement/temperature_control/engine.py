"""Singleton temperature controller engine.

Provides :class:`TemperatureControllerEngine`, a singleton
:class:`~PyQt6.QtCore.QObject` that owns all hardware communication with a
:class:`~stoner_measurement.instruments.temperature_controller.TemperatureController`
driver.  The engine runs a polling :class:`~PyQt6.QtCore.QTimer`, calculates
derived quantities (rate of change, stability flags), and publishes results
via a :class:`~stoner_measurement.temperature_control.pubsub.TemperaturePublisher`.

UI panels and sequence plugins interact with the engine through its public
command API; they never talk to instrument drivers directly.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime

from PyQt6.QtCore import QObject, QTimer, pyqtSlot

from stoner_measurement.temperature_control.pubsub import TemperaturePublisher
from stoner_measurement.temperature_control.types import (
    EngineStatus,
    StabilityConfig,
    TemperatureChannelReading,
    TemperatureEngineState,
)

logger = logging.getLogger(__name__)

#: Number of timestamped readings kept per channel for rate-of-change estimation.
_HISTORY_SIZE = 60

#: Default polling interval in milliseconds.
_DEFAULT_POLL_INTERVAL_MS = 2000


class TemperatureControllerEngine(QObject):
    """Singleton engine that mediates all communication with a temperature controller.

    The engine owns the hardware driver reference and a polling :class:`~PyQt6.QtCore.QTimer`
    that queries the instrument, computes derived quantities, and publishes
    results via its :attr:`publisher`.  It persists for the lifetime of the
    application and continues polling when the UI panel is closed.

    Obtain the singleton instance via :meth:`instance`.  Destroy it by calling
    :meth:`shutdown` (also called automatically on
    :attr:`~PyQt6.QtWidgets.QApplication.aboutToQuit`).

    Attributes:
        publisher (TemperaturePublisher):
            The pub/sub bus; connect to its signals to receive live data.

    Examples:
        >>> from PyQt6.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
        >>> engine = TemperatureControllerEngine.instance()
        >>> engine is TemperatureControllerEngine.instance()
        True
        >>> from stoner_measurement.temperature_control.types import EngineStatus
        >>> engine.status
        <EngineStatus.DISCONNECTED: 'disconnected'>
        >>> engine.shutdown()
        >>> engine.status
        <EngineStatus.STOPPED: 'stopped'>
    """

    _singleton: TemperatureControllerEngine | None = None

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialise the engine.

        Args:
            parent (QObject | None):
                Optional Qt parent.
        """
        super().__init__(parent)

        self.publisher: TemperaturePublisher = TemperaturePublisher(self)

        self._driver = None  # TemperatureController | None
        self._status: EngineStatus = EngineStatus.DISCONNECTED
        self._stability_config: StabilityConfig = StabilityConfig()

        # Per-channel rolling history: deque of (datetime, float) pairs.
        self._history: dict[str, deque[tuple[datetime, float]]] = {}
        # Per-loop time when the loop first became "at setpoint" in this
        # continuous run (None means not currently at setpoint).
        self._at_setpoint_since: dict[int, datetime | None] = {}
        # Per-loop time when stability was last lost (used for hysteresis).
        self._unstable_since: dict[int, datetime | None] = {}
        # Current stable flags (persisted across polls for hysteresis).
        self._stable: dict[int, bool] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(_DEFAULT_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> TemperatureControllerEngine:
        """Return the singleton engine, creating it on first call.

        Returns:
            (TemperatureControllerEngine):
                The singleton engine instance.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
            >>> e1 = TemperatureControllerEngine.instance()
            >>> e2 = TemperatureControllerEngine.instance()
            >>> e1 is e2
            True
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
    def status(self) -> EngineStatus:
        """The current operational status of the engine.

        Returns:
            (EngineStatus):
                Current :class:`~stoner_measurement.temperature_control.types.EngineStatus`.
        """
        return self._status

    # ------------------------------------------------------------------
    # Public command API
    # ------------------------------------------------------------------

    def connect_instrument(self, driver) -> None:
        """Connect to a temperature controller driver and start polling.

        Args:
            driver (TemperatureController):
                A fully constructed and already-opened
                :class:`~stoner_measurement.instruments.temperature_controller.TemperatureController`
                instance.

        Raises:
            RuntimeError:
                If the engine has been shut down.
        """
        if self._status == EngineStatus.STOPPED:
            raise RuntimeError("Engine has been shut down and cannot accept new connections.")
        self._timer.stop()
        self._driver = driver
        self._history.clear()
        self._at_setpoint_since.clear()
        self._unstable_since.clear()
        self._stable.clear()
        self._set_status(EngineStatus.CONNECTED)
        self._timer.start()
        logger.info("TemperatureControllerEngine: connected to %s", type(driver).__name__)

    def disconnect_instrument(self) -> None:
        """Stop polling and release the driver reference."""
        self._timer.stop()
        self._driver = None
        self._history.clear()
        self._at_setpoint_since.clear()
        self._unstable_since.clear()
        self._stable.clear()
        self._set_status(EngineStatus.DISCONNECTED)
        logger.info("TemperatureControllerEngine: disconnected.")

    def set_setpoint(self, loop: int, value: float) -> None:
        """Set the temperature setpoint for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            value (float):
                Desired setpoint in Kelvin.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_setpoint(loop, value)
        except Exception:
            logger.exception("Failed to set setpoint for loop %d", loop)

    def set_heater_range(self, loop: int, range_: int) -> None:
        """Set the heater range index for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            range_ (int):
                Heater range index (instrument-specific; ``0`` = heater off).
        """
        if self._driver is None:
            return
        try:
            self._driver.set_heater_range(loop, range_)
        except Exception:
            logger.exception("Failed to set heater range for loop %d", loop)

    def set_pid(self, loop: int, p: float, i: float, d: float) -> None:
        """Set the PID parameters for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            p (float):
                Proportional gain.
            i (float):
                Integral gain.
            d (float):
                Derivative gain.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_pid(loop, p, i, d)
        except Exception:
            logger.exception("Failed to set PID for loop %d", loop)

    def set_ramp(self, loop: int, rate: float, enabled: bool) -> None:
        """Configure setpoint ramping for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            rate (float):
                Ramp rate in Kelvin per minute.
            enabled (bool):
                ``True`` to activate the ramp function.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_ramp_rate(loop, rate)
            self._driver.set_ramp_enabled(loop, enabled)
        except Exception:
            logger.exception("Failed to set ramp for loop %d", loop)

    def set_loop_mode(self, loop: int, mode) -> None:
        """Set the control mode for *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            mode (ControlMode):
                Desired control mode.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_loop_mode(loop, mode)
        except Exception:
            logger.exception("Failed to set loop mode for loop %d", loop)

    def set_needle_valve(self, position: float) -> None:
        """Set the cryogen gas-flow (needle valve) position.

        Only available when the driver advertises ``has_cryogen_control``.
        Silently ignored otherwise.

        Args:
            position (float):
                Desired valve opening as a percentage (0–100 %).
        """
        if self._driver is None:
            return
        try:
            caps = self._driver.get_capabilities()
            if caps.has_cryogen_control:
                self._driver.set_gas_flow(position)
        except Exception:
            logger.exception("Failed to set needle valve position")

    def set_stability_config(self, config: StabilityConfig) -> None:
        """Replace the stability-evaluation configuration.

        Args:
            config (StabilityConfig):
                New stability configuration to apply immediately.
        """
        self._stability_config = config
        # Reset stability tracking so the new parameters take effect cleanly.
        self._at_setpoint_since.clear()
        self._unstable_since.clear()
        self._stable.clear()

    def set_poll_interval(self, ms: int) -> None:
        """Set the polling interval.

        Args:
            ms (int):
                Polling interval in milliseconds (minimum 100 ms).
        """
        ms = max(100, ms)
        self._timer.setInterval(ms)

    @pyqtSlot()
    def shutdown(self) -> None:
        """Stop polling, release the driver, and mark the engine as stopped.

        After calling this method the engine can no longer be used.  The
        singleton reference is also cleared so :meth:`instance` will create a
        fresh instance if called again.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
            >>> e = TemperatureControllerEngine()
            >>> e.shutdown()
            >>> e.status
            <EngineStatus.STOPPED: 'stopped'>
        """
        self._timer.stop()
        if self._driver is not None:
            try:
                self._driver.disconnect()
            except Exception:
                logger.exception("Error while disconnecting temperature controller on shutdown")
        self._driver = None
        self._set_status(EngineStatus.STOPPED)
        if TemperatureControllerEngine._singleton is self:
            TemperatureControllerEngine._singleton = None
        logger.info("TemperatureControllerEngine: shut down.")

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
            logger.exception("TemperatureControllerEngine: poll error")
            self._set_status(EngineStatus.ERROR)
            return

        self._set_status(EngineStatus.POLLING)

        for reading in state.readings.values():
            self.publisher.channel_reading.emit(reading)
        self.publisher.state_updated.emit(state)

    def _build_state(self) -> TemperatureEngineState:
        """Query the driver and return a full :class:`TemperatureEngineState`.

        Returns:
            (TemperatureEngineState):
                Snapshot incorporating readings, setpoints, heater outputs,
                needle valve, derived rates, and stability flags.
        """
        driver = self._driver
        caps = driver.get_capabilities()
        now = datetime.now(tz=UTC)

        # --- Sensor readings ---
        readings: dict[str, TemperatureChannelReading] = {}
        for ch in caps.input_channels:
            raw = driver.get_temperature_reading(ch)
            history = self._history.setdefault(ch, deque(maxlen=_HISTORY_SIZE))
            history.append((now, raw.value))
            rate = _compute_rate(history)
            readings[ch] = TemperatureChannelReading(
                channel=ch,
                value=raw.value,
                timestamp=now,
                status=raw.status,
                units=raw.units,
                rate_of_change=rate,
            )

        # --- Loop data ---
        setpoints: dict[int, float] = {}
        heater_outputs: dict[int, float] = {}
        loop_modes: dict[int, object] = {}
        for lp in caps.loop_numbers:
            setpoints[lp] = driver.get_setpoint(lp)
            heater_outputs[lp] = driver.get_heater_output(lp)
            loop_modes[lp] = driver.get_loop_mode(lp)

        # --- Needle valve ---
        needle_valve: float | None = None
        if caps.has_cryogen_control:
            needle_valve = driver.get_gas_flow()

        # --- Stability evaluation ---
        at_setpoint, stable = self._evaluate_stability(readings, setpoints, caps.loop_numbers, now)

        return TemperatureEngineState(
            readings=readings,
            setpoints=setpoints,
            heater_outputs=heater_outputs,
            needle_valve=needle_valve,
            loop_modes=loop_modes,
            at_setpoint=at_setpoint,
            stable=stable,
            engine_status=EngineStatus.POLLING,
        )

    def _evaluate_stability(
        self,
        readings: dict[str, TemperatureChannelReading],
        setpoints: dict[int, float],
        loop_numbers: tuple[int, ...],
        now: datetime,
    ) -> tuple[dict[int, bool], dict[int, bool]]:
        """Evaluate at-setpoint and stable flags for all loops.

        Args:
            readings (dict[str, TemperatureChannelReading]):
                Current channel readings.
            setpoints (dict[int, float]):
                Current setpoints, keyed by loop number.
            loop_numbers (tuple[int, ...]):
                Ordered loop numbers to evaluate.
            now (datetime):
                Current UTC timestamp.

        Returns:
            (tuple[dict[int, bool], dict[int, bool]]):
                ``(at_setpoint, stable)`` mappings keyed by loop number.
        """
        cfg = self._stability_config
        at_setpoint: dict[int, bool] = {}
        stable: dict[int, bool] = {}

        for lp in loop_numbers:
            sp = setpoints.get(lp, 0.0)
            # Use the first available channel reading as the process variable.
            pv = next(iter(readings.values())).value if readings else sp
            rate = next(iter(readings.values())).rate_of_change if readings else 0.0

            currently_at = abs(pv - sp) < cfg.tolerance_k
            at_setpoint[lp] = currently_at

            if currently_at:
                if self._at_setpoint_since.get(lp) is None:
                    self._at_setpoint_since[lp] = now
                elapsed = (now - self._at_setpoint_since[lp]).total_seconds()
                rate_ok = abs(rate) < cfg.min_rate
                if elapsed >= cfg.window_s and rate_ok:
                    self._unstable_since[lp] = None
                    self._stable[lp] = True
                else:
                    # Not yet stable — apply hysteresis before clearing flag.
                    self._try_clear_stable(lp, now, cfg)
            else:
                self._at_setpoint_since[lp] = None
                self._try_clear_stable(lp, now, cfg)

            stable[lp] = self._stable.get(lp, False)

        return at_setpoint, stable

    def _try_clear_stable(self, loop: int, now: datetime, cfg: StabilityConfig) -> None:
        """Clear the stable flag for *loop* after the holdoff period has elapsed.

        Args:
            loop (int):
                Loop number to evaluate.
            now (datetime):
                Current UTC timestamp.
            cfg (StabilityConfig):
                Active stability configuration.
        """
        if not self._stable.get(loop, False):
            return
        if self._unstable_since.get(loop) is None:
            self._unstable_since[loop] = now
        holdoff_elapsed = (now - self._unstable_since[loop]).total_seconds() >= cfg.unstable_holdoff_s
        if holdoff_elapsed:
            self._stable[loop] = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_status(self, status: EngineStatus) -> None:
        """Update the engine status and emit the change signal if it changed.

        Args:
            status (EngineStatus):
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
    """Compute the rate of temperature change in Kelvin per minute.

    Uses a simple linear fit (least-squares slope) over the available
    timestamped history.  Returns ``0.0`` when fewer than two readings are
    available.

    Args:
        history (deque[tuple[datetime, float]]):
            Ordered sequence of ``(timestamp, value)`` pairs; oldest first.

    Returns:
        (float):
            Estimated rate of change in Kelvin per minute.
    """
    if len(history) < 2:
        return 0.0

    # Convert to (seconds_offset, value) pairs relative to the first point.
    t0, v0 = history[0]
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
    return slope_per_second * 60.0  # convert K/s → K/min
