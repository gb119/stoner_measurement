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
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QTimer, pyqtSlot

from stoner_measurement.temperature_control.pubsub import TemperaturePublisher
from stoner_measurement.temperature_control.types import (
    EngineStatus,
    LoopSettings,
    StabilityConfig,
    TemperatureChannelReading,
    TemperatureEngineState,
)

if TYPE_CHECKING:
    from stoner_measurement.instruments.temperature_controller import InputChannelSettings, ZoneEntry

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

    def get_needle_valve(self) -> float | None:
        """Return the current cryogen gas-flow (needle valve) position.

        Only available when the driver advertises ``has_cryogen_control``.
        Returns ``None`` when no instrument is connected or when the driver
        does not support cryogen control.

        Returns:
            (float | None):
                Valve opening as a percentage (0–100 %), or ``None`` if
                unavailable.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
            >>> engine = TemperatureControllerEngine.instance()
            >>> engine.get_needle_valve() is None  # no driver connected
            True
            >>> engine.shutdown()
        """
        if self._driver is None:
            return None
        try:
            caps = self._driver.get_capabilities()
            if caps.has_cryogen_control:
                return self._driver.get_gas_flow()
        except Exception:
            logger.exception("Failed to read needle valve position")
        return None

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

    def set_gas_auto(self, auto: bool) -> None:
        """Enable or disable automatic gas-flow control on the connected instrument.

        Only available when the driver advertises ``has_gas_auto_mode``.
        Silently ignored otherwise.

        Args:
            auto (bool):
                ``True`` to engage automatic gas-flow control; ``False`` for
                manual.
        """
        if self._driver is None:
            return
        try:
            caps = self._driver.get_capabilities()
            if caps.has_gas_auto_mode:
                self._driver.set_gas_auto(auto)
        except Exception:
            logger.exception("Failed to set gas auto mode")

    def set_input_channel(self, loop: int, channel: str) -> None:
        """Assign a sensor channel as the input for control *loop*.

        Args:
            loop (int):
                Control loop number (1-based).
            channel (str):
                Sensor channel identifier to assign.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_input_channel(loop, channel)
        except Exception:
            logger.exception("Failed to set input channel for loop %d", loop)

    def set_all_loop_settings(  # pylint: disable=too-many-arguments
        self,
        loop: int,
        *,
        setpoint: float,
        mode,
        input_channel: str,
        ramp_enabled: bool,
        ramp_rate: float,
        pid_p: float,
        pid_i: float,
        pid_d: float,
        heater_range: int,
    ) -> None:
        """Apply all control-loop settings in a single call.

        Sends setpoint, control mode, input channel assignment, ramp
        configuration, PID gains, and heater range to the instrument.

        Args:
            loop (int):
                Control loop number (1-based).

        Keyword Parameters:
            setpoint (float):
                Target setpoint in Kelvin.
            mode (ControlMode):
                Desired control mode.
            input_channel (str):
                Sensor channel to assign as the loop input.
            ramp_enabled (bool):
                ``True`` to activate setpoint ramping.
            ramp_rate (float):
                Ramp rate in Kelvin per minute.
            pid_p (float):
                Proportional gain.
            pid_i (float):
                Integral gain.
            pid_d (float):
                Derivative gain.
            heater_range (int):
                Heater range index.
        """
        if self._driver is None:
            return
        try:
            self._driver.set_setpoint(loop, setpoint)
        except Exception:
            logger.exception("Failed to set setpoint for loop %d", loop)
        try:
            self._driver.set_loop_mode(loop, mode)
        except Exception:
            logger.exception("Failed to set loop mode for loop %d", loop)
        try:
            self._driver.set_input_channel(loop, input_channel)
        except Exception:
            logger.exception("Failed to set input channel for loop %d", loop)
        try:
            self._driver.set_ramp_rate(loop, ramp_rate)
            self._driver.set_ramp_enabled(loop, ramp_enabled)
        except Exception:
            logger.exception("Failed to set ramp for loop %d", loop)
        try:
            self._driver.set_pid(loop, pid_p, pid_i, pid_d)
        except Exception:
            logger.exception("Failed to set PID for loop %d", loop)
        try:
            self._driver.set_heater_range(loop, heater_range)
        except Exception:
            logger.exception("Failed to set heater range for loop %d", loop)

    def set_manual_heater_output(self, loop: int, output: float) -> None:
        """Set the manual heater output for open-loop control of *loop*.

        Delegates to
        :meth:`~stoner_measurement.instruments.temperature_controller.TemperatureController.set_manual_heater_output`.
        A :class:`NotImplementedError` from the driver is caught and logged as a
        warning (driver does not support manual heater output control).  Any other
        exception is logged as an error.

        Args:
            loop (int):
                Control loop number (1-based).
            output (float):
                Desired heater output as a percentage (0–100 %).

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
            >>> engine = TemperatureControllerEngine.instance()
            >>> engine.set_manual_heater_output(1, 25.0)  # no driver connected — silently ignored
            >>> engine.shutdown()
        """
        if self._driver is None:
            return
        try:
            self._driver.set_manual_heater_output(loop, output)
        except NotImplementedError:
            logger.warning("Driver does not support setting manual heater output for loop %d", loop)
        except Exception:
            logger.exception("Failed to set manual heater output for loop %d", loop)

    def get_zone_table(self, loop: int) -> list[ZoneEntry] | None:
        """Query the hardware for the complete zone table of control *loop*.

        Returns ``None`` when no instrument is connected.  If the driver's
        :meth:`~stoner_measurement.instruments.temperature_controller.TemperatureController.get_num_zones`
        raises or returns ``0``, an empty list is returned.  Individual zone
        reads that raise are logged and the entry is skipped.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (list[ZoneEntry] | None):
                Ordered list of zone-table entries (index 0 = zone 1), or
                ``None`` if disconnected.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
            >>> engine = TemperatureControllerEngine.instance()
            >>> engine.get_zone_table(1) is None  # no driver connected
            True
            >>> engine.shutdown()
        """
        if self._driver is None:
            return None
        try:
            num = self._driver.get_num_zones(loop)
        except Exception:
            logger.exception("Failed to read number of zones for loop %d", loop)
            return []
        if not num:
            return []
        entries = []
        for i in range(1, num + 1):
            try:
                entries.append(self._driver.get_zone(loop, i))
            except Exception:
                logger.exception("Failed to read zone %d for loop %d", i, loop)
        return entries

    def set_zone_table(self, loop: int, entries: list[ZoneEntry]) -> None:
        """Write a complete zone table for control *loop*.

        Iterates over *entries* (first entry → zone index 1) and calls
        :meth:`~stoner_measurement.instruments.temperature_controller.TemperatureController.set_zone`
        for each one.  Individual write failures are logged without aborting
        the remaining writes.  Silently returns if no instrument is connected.

        Args:
            loop (int):
                Control loop number (1-based).
            entries (list[ZoneEntry]):
                Ordered list of zone-table entries to write.  Index 0 is
                written as zone 1, index 1 as zone 2, etc.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
            >>> engine = TemperatureControllerEngine.instance()
            >>> engine.set_zone_table(1, [])  # no-op when no driver
            >>> engine.shutdown()
        """
        if self._driver is None:
            return
        for i, entry in enumerate(entries, start=1):
            try:
                self._driver.set_zone(loop, i, entry)
            except Exception:
                logger.exception("Failed to write zone %d for loop %d", i, loop)

    def get_input_channel_settings(self, channel: str) -> InputChannelSettings | None:
        """Query the hardware for the input configuration of sensor *channel*.

        Returns ``None`` when no instrument is connected.  Any exception from
        the driver is logged and ``None`` is returned.

        Args:
            channel (str):
                Sensor channel identifier.

        Returns:
            (InputChannelSettings | None):
                Current input configuration for *channel*, or ``None`` if
                disconnected or if the driver raised an error.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
            >>> engine = TemperatureControllerEngine.instance()
            >>> engine.get_input_channel_settings("A") is None  # no driver connected
            True
            >>> engine.shutdown()
        """
        if self._driver is None:
            return None
        try:
            return self._driver.get_input_channel_settings(channel)
        except Exception:
            logger.exception("Failed to read input channel settings for channel %s", channel)
            return None

    def set_input_channel_settings(self, channel: str, settings: InputChannelSettings) -> None:
        """Apply input configuration settings to sensor *channel*.

        Delegates to the driver; any exception is logged.  Silently returns
        if no instrument is connected.

        Args:
            channel (str):
                Sensor channel identifier.
            settings (InputChannelSettings):
                Configuration to apply.  ``None`` fields are preserved from
                current hardware state.

        Examples:
            >>> from PyQt6.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from stoner_measurement.temperature_control.engine import TemperatureControllerEngine
            >>> from stoner_measurement.instruments.temperature_controller import InputChannelSettings
            >>> engine = TemperatureControllerEngine.instance()
            >>> settings = InputChannelSettings()  # doctest: +SKIP
            >>> engine.set_input_channel_settings("A", settings)  # no-op when no driver  # doctest: +SKIP
            >>> engine.shutdown()
        """
        if self._driver is None:
            return
        try:
            self._driver.set_input_channel_settings(channel, settings)
        except Exception:
            logger.exception("Failed to set input channel settings for channel %s", channel)

    def _safe_read_loop(self, func, loop: int, description: str, default):
        """Invoke *func(loop)*, returning *default* and logging on any error.

        Args:
            func:
                Callable that accepts a single loop-number argument.
            loop (int):
                Control loop number forwarded to *func*.
            description (str):
                Human-readable name of the setting (used in the log message).
            default:
                Value returned when *func* raises any exception.

        Returns:
            The value returned by *func*, or *default* on failure.
        """
        try:
            return func(loop)
        except Exception:
            logger.exception("Failed to read %s for loop %d", description, loop)
            return default

    def get_loop_settings(self, loop: int) -> LoopSettings | None:
        """Query the hardware for all configurable settings of control *loop*.

        Returns ``None`` when no instrument is connected.  Individual setting
        reads that fail are logged and sensible defaults are substituted.

        Args:
            loop (int):
                Control loop number (1-based).

        Returns:
            (LoopSettings | None):
                Current hardware settings for *loop*, or ``None`` if
                disconnected.
        """
        if self._driver is None:
            return None
        from stoner_measurement.instruments.temperature_controller import ControlMode

        setpoint = self._safe_read_loop(self._driver.get_setpoint, loop, "setpoint", 0.0)
        mode = self._safe_read_loop(
            self._driver.get_loop_mode, loop, "loop mode", ControlMode.CLOSED_LOOP
        )
        input_channel = self._safe_read_loop(
            self._driver.get_input_channel, loop, "input channel", ""
        )
        ramp_enabled = self._safe_read_loop(
            self._driver.get_ramp_enabled, loop, "ramp enabled", False
        )
        ramp_rate = self._safe_read_loop(self._driver.get_ramp_rate, loop, "ramp rate", 0.0)

        try:
            pid = self._driver.get_pid(loop)
            pid_p, pid_i, pid_d = pid.p, pid.i, pid.d
        except Exception:
            logger.exception("Failed to read PID for loop %d", loop)
            pid_p = pid_i = pid_d = 0.0

        try:
            heater_range: int | None = self._driver.get_heater_range(loop)
        except Exception:
            heater_range = None

        manual_output: float | None = None
        if mode == ControlMode.OPEN_LOOP:
            # In open-loop mode the heater output is under direct manual
            # control, so the current heater output percentage *is* the
            # manual output setting.
            manual_output = self._safe_read_loop(
                self._driver.get_heater_output, loop, "heater output", None
            )

        return LoopSettings(
            setpoint=setpoint,
            mode=mode,
            input_channel=input_channel,
            ramp_enabled=ramp_enabled,
            ramp_rate=ramp_rate,
            pid_p=pid_p,
            pid_i=pid_i,
            pid_d=pid_d,
            heater_range=heater_range,
            manual_output=manual_output,
        )

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

        readings = self._collect_readings(driver, caps, now)
        setpoints, heater_outputs, heater_ranges, loop_modes, input_channels = self._collect_loop_data(
            driver, caps
        )
        needle_valve = self._read_needle_valve(driver, caps)
        gas_auto_mode = self._read_gas_auto(driver, caps)
        at_setpoint, stable = self._evaluate_stability(readings, setpoints, caps.loop_numbers, now)

        return TemperatureEngineState(
            readings=readings,
            setpoints=setpoints,
            heater_outputs=heater_outputs,
            heater_ranges=heater_ranges,
            needle_valve=needle_valve,
            gas_auto_mode=gas_auto_mode,
            loop_modes=loop_modes,
            input_channels=input_channels,
            at_setpoint=at_setpoint,
            stable=stable,
            engine_status=EngineStatus.POLLING,
        )

    def _collect_readings(self, driver, caps, now) -> dict[str, TemperatureChannelReading]:
        """Query all sensor channels and return timestamped readings with rate-of-change."""
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
        return readings

    def _collect_loop_data(self, driver, caps):
        """Query all control-loop data from the driver.

        Returns:
            (tuple):
                ``(setpoints, heater_outputs, heater_ranges, loop_modes, input_channels)``
                dicts keyed by loop number.
        """
        setpoints: dict[int, float] = {}
        heater_outputs: dict[int, float] = {}
        heater_ranges: dict[int, int] = {}
        loop_modes: dict[int, object] = {}
        input_channels: dict[int, str] = {}
        for lp in caps.loop_numbers:
            setpoints[lp] = driver.get_setpoint(lp)
            heater_outputs[lp] = driver.get_heater_output(lp)
            loop_modes[lp] = driver.get_loop_mode(lp)
            try:
                input_channels[lp] = driver.get_input_channel(lp)
            except (ConnectionError, ValueError, AttributeError):
                logger.exception("Failed to read input channel for loop %d during poll", lp)
            try:
                heater_ranges[lp] = driver.get_heater_range(lp)
            except NotImplementedError:
                pass
            except (ConnectionError, ValueError, AttributeError):
                logger.exception("Failed to read heater range for loop %d during poll", lp)
        return setpoints, heater_outputs, heater_ranges, loop_modes, input_channels

    def _read_needle_valve(self, driver, caps) -> float | None:
        """Return the current needle-valve position, or ``None`` if unavailable."""
        if caps.has_cryogen_control:
            return driver.get_gas_flow()
        return None

    def _read_gas_auto(self, driver, caps) -> bool | None:
        """Return the current gas-auto-mode state, or ``None`` if unavailable."""
        if not caps.has_gas_auto_mode:
            return None
        try:
            return driver.get_gas_auto()
        except (ConnectionError, ValueError, AttributeError):
            logger.exception("Failed to read gas auto mode during poll")
            return None

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
