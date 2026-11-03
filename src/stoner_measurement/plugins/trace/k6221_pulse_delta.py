"""Native Keithley 6221/2182A Pulse Delta current-list trace acquisition."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from qtpy.QtCore import QEvent, QLineF, QPointF, QRectF, Qt
from qtpy.QtGui import QColor, QPainter, QPainterPath, QPen
from qtpy.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from stoner_measurement.instruments.keithley.k6221 import Keithley6221
from stoner_measurement.instruments.transport.gpib_transport import GpibTransport
from stoner_measurement.plugins.base_plugin import BasePlugin
from stoner_measurement.plugins.trace.base import TracePlugin, TraceStatus
from stoner_measurement.plugins.trace.k6221_2182a import (
    ComplianceMode,
    Keithley6221_2182APlugin,
    SourceRangeMode,
)
from stoner_measurement.ui.widgets import FILTER_GPIB, SISpinBox, VisaResourceComboBox


@dataclass(frozen=True)
class _PulseCycleTiming:
    """Nominal mains-spaced timing, excluding the initial trigger synchronisation."""

    width: float
    delay: float
    period: float
    mains: float

    @property
    def before_high(self) -> float:
        """Time from the first low pulse to the start of the high pulse."""
        return 1.0 / self.mains

    @property
    def after_high(self) -> float:
        """Low time from the falling edge to the end of this cycle."""
        return self.period - self.before_high - self.width

    @property
    def duty_cycle(self) -> float:
        """Percentage of the complete cycle spent at the high current."""
        return 100.0 * self.width / self.period

    @property
    def falling_edge_to_v3(self) -> float:
        """Delay from returning low to the final baseline measurement start."""
        return self.before_high + self.delay - self.width


def _preview_time(value: float) -> str:
    """Format a time label using a readable SI scale."""
    if value == 0:
        return "0 s"
    if abs(value) < 1e-3:
        return f"{value * 1e6:.4g} us"
    if abs(value) < 1:
        return f"{value * 1e3:.4g} ms"
    return f"{value:.4g} s"


class _PulsePreview(QWidget):
    """Show a cycle-scale waveform and its linked, expanded measurement window."""

    def __init__(self, plugin: Keithley6221PulseDeltaPlugin) -> None:
        super().__init__()
        self.plugin = plugin
        self._size_for_font()
        self.setAccessibleName("Pulse Delta timing preview")

    def _size_for_font(self) -> None:
        """Reserve enough space for timing labels at the current application font."""
        self.setMinimumWidth(
            max(
                680,
                self.fontMetrics().horizontalAdvance(
                    "Before high: 16.67 ms; High: 110 us; Low after high: 83.22 ms"
                )
                + 16,
            )
        )
        self.setFixedHeight(self.fontMetrics().height() * 18)

    def changeEvent(self, event) -> None:
        """Resize the schematic when the application's font changes."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._size_for_font()

    def cycle_timing(self) -> _PulseCycleTiming:
        """Return preview timing, rejecting expressions and impossible nominal cycles.

        Returns:
            (_PulseCycleTiming): Timing based on the selected preview mains frequency.

        Raises:
            ValueError: If numeric settings are unavailable or the sequence cannot fit.
        """
        values = (
            self.plugin._pulse_width,
            self.plugin._pulse_source_delay,
            self.plugin._pulse_period,
            self.plugin._preview_mains_frequency,
        )
        if any(isinstance(value, str) for value in values):
            raise ValueError(
                "Timing expressions are evaluated during configuration; numeric preview unavailable."
            )
        width, delay, period, mains = (float(value) for value in values)
        if not all(math.isfinite(value) for value in (width, delay, period, mains)):
            raise ValueError("Use finite numeric timing settings for the preview.")
        if width <= 0 or delay < 0 or delay >= width or mains not in (50, 60) or period <= 0:
            raise ValueError("Choose a positive pulse width and a shorter settling delay.")
        if period < 2 / mains + width:
            raise ValueError(
                f"Cycle too short for this nominal mains-spaced sequence: allow at least "
                f"{_preview_time(2 / mains + width)}. Verify short-cycle behaviour on the instrument."
            )
        return _PulseCycleTiming(width, delay, period, mains)

    def paintEvent(self, event) -> None:
        """Paint the complete cycle at true scale and link its pulse to a zoom."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().text().color(), 1))
        try:
            timing = self.cycle_timing()
        except ValueError as exc:
            painter.drawText(
                QRectF(self.rect()).adjusted(5, 5, -5, -5),
                Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                str(exc),
            )
        else:
            self._draw_cycle(painter, timing)
            self._draw_detail(painter, timing)
        painter.end()

    def _draw_cycle(self, painter: QPainter, timing: _PulseCycleTiming) -> None:
        """Draw the pulse, measurement markers and pre/post delays on one cycle axis."""
        line = self.fontMetrics().height()
        left, right = 55.0, self.width() - 25.0
        scale = (right - left) / timing.period
        start = left + timing.before_high * scale
        end = start + timing.width * scale
        high, low = line * 4.0, line * 6.0
        painter.drawText(
            5,
            line,
            f"Duty cycle: {timing.duty_cycle:.4g}%; Cycle: {_preview_time(timing.period)}",
        )
        painter.drawText(
            5,
            line * 2,
            f"Before high: {_preview_time(timing.before_high)}; "
            f"High: {_preview_time(timing.width)}; Low after high: {_preview_time(timing.after_high)}",
        )
        self._waveform(painter, left, right, start, end, high, low)
        painter.drawText(5, int(high), "I[n]")
        painter.drawText(5, int(low), "0 A")
        for offset, label, y in (
            (0, "V1", low),
            (timing.before_high, "V2", high),
            (2 * timing.before_high, "V3" if self.plugin._low_measurements == 2 else "V3 off", low),
        ):
            x = left + (offset + timing.delay) * scale
            painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
            painter.drawText(int(x) + 5, int(y) - line // 2, label)
        painter.drawText(int(left), line * 7, "0")
        label = _preview_time(timing.period)
        painter.drawText(int(right) - self.fontMetrics().horizontalAdvance(label), line * 7, label)
        # The cycle remains to scale; only the linked detail below is expanded.
        pen = painter.pen()
        painter.setPen(QPen(QColor(45, 160, 200, 110), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QLineF(start, low + 4, 130, line * 9))
        painter.drawLine(QLineF(end, low + 4, right - 25, line * 9))
        painter.setPen(pen)

    @staticmethod
    def _waveform(
        painter: QPainter,
        left: float,
        right: float,
        start: float,
        end: float,
        high: float,
        low: float,
    ) -> None:
        """Draw a pulse without inflating subpixel widths on the cycle axis."""
        path = QPainterPath(QPointF(left, low))
        for x, y in ((start, low), (start, high), (end, high), (end, low), (right, low)):
            path.lineTo(x, y)
        painter.drawPath(path)

    def _draw_detail(self, painter: QPainter, timing: _PulseCycleTiming) -> None:
        """Expand the same high pulse to explain its settling and measurement window."""
        line = self.fontMetrics().height()
        start, end = 130.0, self.width() - 50.0
        split = start + (end - start) * timing.delay / timing.width
        high, low = line * 10.0, line * 13.0
        painter.drawText(5, line * 8, "High pulse detail (expanded from the cycle above)")
        painter.drawText(int(start), line * 9 - 3, f"Pulse width: {_preview_time(timing.width)}")
        painter.drawLine(QLineF(start, line * 9, end, line * 9))
        painter.fillRect(QRectF(start, high, split - start, low - high), QColor(220, 155, 45, 65))
        painter.fillRect(QRectF(split, high, end - split, low - high), QColor(45, 160, 200, 65))
        self._waveform(painter, start - 25, end + 25, start, end, high, low)
        painter.drawLine(QLineF(split, high, split, low))
        painter.drawText(
            5,
            line * 14,
            f"Amber: settling {_preview_time(timing.delay)}; "
            f"Blue: available measurement window {_preview_time(timing.width - timing.delay)}",
        )
        painter.drawText(
            5,
            line * 15,
            f"Nominal {timing.mains:g} Hz timing; initial trigger-to-mains wait excluded.",
        )
        painter.drawText(
            5,
            line * 16,
            "V1/V2/V3 mark measurement starts. The 6221 sets the actual integration time.",
        )
        final_low = (
            f"After returning low: {_preview_time(timing.falling_edge_to_v3)} until V3 starts."
            if self.plugin._low_measurements == 2
            else "V3 is disabled; the pulse and cycle timing remain the same."
        )
        painter.drawText(5, line * 17, final_low)


class Keithley6221PulseDeltaPlugin(Keithley6221_2182APlugin):
    """Measure a custom current sweep using native 6221/2182A Pulse Delta.

    Choose **6221/2182 Pulse Delta Trace** for short current pulses with
    baseline subtraction. The **Scan** tab defines the high-current list.
    **Settings** selects the 6221 GPIB resource, voltage compliance, source
    ranging, 2182A voltage range, pulse width (50 us to 12 ms), settling delay
    within each pulse, complete cycle period, and one or two low measurements.
    A cycle-scale waveform and linked pulse zoom show duty cycle, the delay
    before the high pulse and the low time after it. The 50/60 Hz preview
    selector describes the mains supply; it does not change the instrument.
    These are nominal timings, excluding the initial trigger-to-mains wait.
    Numeric timing controls also accept
    expressions, evaluated during configure; expression previews are schematic.

    The baseline current is zero. Two low measurements give
    V = Vhigh - (Vbefore + Vafter)/2; one gives Vhigh - Vbefore.
    The IV trace contains current x, corrected V, R = V/I (NaN at zero),
    and peak P = I*V, rather than cycle-average power. Integration is set by
    the 6221. The 2182A must be connected by RS-232 and Trigger Link; there
    is no direct-GPIB meter or auxiliary-meter mode. The dedicated native
    handshake does not provide the existing plugin's auxiliary timing contract.

    Configure arms the source; measure starts one complete sweep and aborts
    it afterwards, returning the output to zero/off. Repeated measurements
    re-arm the same configuration. Disconnect aborts and closes owned resources.

    Args:
        parent (QObject | None): Optional Qt parent.

    Attributes:
        instance_name (str): Sequence variable name.
        sequence_engine (SequenceEngine | None): Owning engine and expression context.
        scan_generator (BaseScanGenerator): High pulse currents in amps.
        data (dict[str, TraceData]): Most recent completed IV trace.
        status (TraceStatus): Current lifecycle phase.
        _6221_resource (str): Source GPIB resource.
        _pulse_width (float | str): High/low pulse width in seconds; default 110 us.
        _pulse_source_delay (float | str): Settling delay in seconds; default 16 us.
        _pulse_period (float | str): Requested cycle period in seconds; default 0.1 s.
        _low_measurements (int): Baseline measurements, 1 or 2; default 2.
        _preview_mains_frequency (int): Preview assumption, 50 or 60 Hz; default 50.
        _compliance (float | str): Voltage compliance; default 10 V.
        _source_range_mode (SourceRangeMode): BEST, AUTO or FIXED.
        _source_range (float | str): Fixed current range in amps.
        _voltage_range (float): 2182A range in volts; zero means automatic.

    Raises:
        ValueError: If pulse settings, current values or saved modes are invalid.
        RuntimeError: If instruments are unavailable or acquisition times out.

    Examples:
        With an existing sequence instance named ``pulse_trace``::

            pulse_trace._pulse_width = 500e-6
            pulse_trace._pulse_source_delay = 20e-6
            pulse_trace._pulse_period = "cycle_time"
            # Define cycle_time in the engine before configuration.
            # After the sequence measures, inspect pulse_trace.data["IV"].
    """

    DISPLAY_NAME = "6221/2182 Pulse Delta Trace"
    _k6221: Keithley6221 | None

    def __init__(self, parent=None) -> None:
        self._pulse_width: float | str = 110e-6
        self._pulse_source_delay: float | str = 16e-6
        self._pulse_period: float | str = 0.1
        self._low_measurements = 2
        self._preview_mains_frequency = 50
        self._configured_period = 0.1
        self._pulse_armed = False
        self._nominal_sweep_values = None
        super().__init__(parent)

    @property
    def name(self) -> str:
        """Return the registered Pulse Delta plugin identifier."""
        return "k6221_pulse_delta"

    def _validate_modes(self) -> None:
        """Reject unsupported inherited modes, including console changes."""
        if self._secondary_enabled or self._differential_mode:
            raise ValueError("Pulse Delta does not support auxiliary meters or differential mode.")
        if self._compliance_mode is not ComplianceMode.VOLTAGE:
            raise ValueError("Pulse Delta uses fixed voltage compliance.")

    def connect(self) -> None:
        """Open only the source session and check its serial-connected 2182A."""
        self._validate_modes()
        self._set_status(TraceStatus.CONNECTING)
        transport = None
        try:
            transport = GpibTransport.from_resource_string(self._6221_resource, timeout=10.0)
            self._k6221 = Keithley6221(transport)
            self._k6221.connect()
            self._k6221.confirm_identity()
            if not self._k6221.pulse_delta_present():
                raise RuntimeError(
                    "Pulse Delta requires a compatible 2182A on the 6221 RS-232 port."
                )
        except BaseException:
            self._set_status(TraceStatus.ERROR)
            # Keep the driver reference if close fails so cleanup can be retried.
            if transport is not None:
                transport.close()
            self._k6221 = None
            raise
        self._set_status(TraceStatus.IDLE)

    def configure(self) -> None:
        """Validate expressions and programme and arm one native pulse sweep."""
        self._sweep_values = None
        self._validate_modes()
        if self._k6221 is None:
            raise RuntimeError("Not connected; call connect() before configure().")
        source = self._k6221
        self._set_status(TraceStatus.CONFIGURING)
        try:
            values = tuple(float(v) for v in self.scan_generator.generate())
            timing = dict(
                width=self.eval_float(self._pulse_width),
                source_delay=self.eval_float(self._pulse_source_delay),
                period=self.eval_float(self._pulse_period),
            )
            source.validate_pulse_delta_sweep(
                values, low_measurements=self._low_measurements, **timing
            )
            compliance = self.eval_float(self._compliance)
            if not math.isfinite(compliance) or not 0.1 <= compliance <= 105:
                raise ValueError("Compliance voltage must be between 0.1 and 105 V.")
            self._abort_source(source)
            source.reset()
            source.set_pulse_delta_voltage_range(self._voltage_range)
            source.configure_pulse_delta_sweep(
                values, low_measurements=self._low_measurements, **timing
            )
            source.set_compliance_voltage(compliance)
            if self._source_range_mode is SourceRangeMode.FIXED:
                source.set_fixed_range(self.eval_float(self._source_range))
            source.set_sweep_range_mode(self._source_range_mode.name)
            source.prepare_pulse_delta_buffer(len(values))
            source.pulse_delta_arm()
            self._pulse_armed = True
            self._configured_period = timing["period"]
            self._sweep_values = np.asarray(values)
        except BaseException:
            self._set_status(TraceStatus.ERROR)
            self._abort_source(source)
            raise
        self._set_status(TraceStatus.IDLE)

    def _acquire_pairs(self, parameters: dict[str, Any]) -> list[tuple[float, float]]:
        """Collect the 6221's corrected voltages rather than raw meter samples."""
        del parameters
        self._validate_modes()
        if self._k6221 is None or self._sweep_values is None:
            raise RuntimeError("Call connect() and configure() before measure().")
        source = self._k6221
        count = len(self._sweep_values)
        self.data = {}
        self.channel_statistics = {}
        timeout = max(10.0, count * max(self._configured_period, 0.06) * 1.5 + 5)
        try:
            if not self._pulse_armed:
                source.prepare_pulse_delta_buffer(count)
                source.pulse_delta_arm()
                self._pulse_armed = True
            source.sweep_init()
            deadline = time.monotonic() + timeout
            while source.pulse_delta_buffer_count() < count:
                engine_thread = getattr(self.sequence_engine, "_thread", None)
                stop = getattr(engine_thread, "_stop_event", None)
                if stop is not None and stop.is_set():
                    raise RuntimeError("Pulse Delta acquisition stopped.")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Pulse Delta buffer did not fill within {timeout:.1f} s.")
                time.sleep(0.05)
            voltages = source.read_pulse_delta_buffer(count)
            return list(zip(self._sweep_values, voltages, strict=True))
        finally:
            self._abort_source(source)

    def _abort_source(self, source: Keithley6221) -> None:
        """Disarm and attempt output-off even when the native abort fails."""
        self._pulse_armed = False
        try:
            source.sweep_abort()
        finally:
            source.enable_output(False)

    def disconnect(self) -> None:
        """Abort and close the owned session, propagating cleanup failures."""
        self._set_status(TraceStatus.DISCONNECTING)
        source = self._k6221
        self._pulse_armed = False
        self._sweep_values = None
        try:
            if source is not None:
                try:
                    self._abort_source(source)
                finally:
                    source.disconnect()
                    self._k6221 = None
        except BaseException:
            self._set_status(TraceStatus.ERROR)
            raise
        self._set_status(TraceStatus.IDLE)

    def to_json(self) -> dict[str, Any]:
        """Save supported pulse and scan settings without DC-only controls."""
        data = TracePlugin.to_json(self)
        for key, attr in self._setting_attributes().items():
            data[key] = getattr(self, attr)
        data["source_range_mode"] = self._source_range_mode.value
        return data

    @staticmethod
    def _setting_attributes() -> dict[str, str]:
        """Map supported persisted values to their editable attributes."""
        return {
            "resource_6221": "_6221_resource",
            "compliance": "_compliance",
            "source_range": "_source_range",
            "voltage_range": "_voltage_range",
            "pulse_width": "_pulse_width",
            "pulse_source_delay": "_pulse_source_delay",
            "pulse_period": "_pulse_period",
            "low_measurements": "_low_measurements",
            "preview_mains_frequency": "_preview_mains_frequency",
        }

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore pulse settings, preserving unevaluated timing expressions."""
        if data.get("secondary_nanovoltmeter", {}).get("enabled") or data.get("differential_mode"):
            raise ValueError("Pulse Delta cannot restore auxiliary meters or differential mode.")
        TracePlugin._restore_from_json(self, data)
        for key, attr in self._setting_attributes().items():
            if key in data:
                setattr(self, attr, data[key])
        self._source_range_mode = SourceRangeMode(
            data.get("source_range_mode", self._source_range_mode.value)
        )

    def _plugin_config_tabs(self) -> QWidget:
        """Build top-packed pulse controls and an automatically updated preview."""
        root = QWidget()
        layout = QVBoxLayout(root)
        form = QFormLayout()
        layout.addLayout(form)
        resource = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        resource.setCurrentText(self._6221_resource)
        resource.currentTextChanged.connect(lambda value: setattr(self, "_6221_resource", value))
        form.addRow("6221 GPIB resource:", resource)
        preview = _PulsePreview(self)
        fields = (
            ("Pulse width:", "_pulse_width", "s", 50e-6, 12e-3),
            ("Settling delay within pulse:", "_pulse_source_delay", "s", 16e-6, 11.966e-3),
            ("Complete cycle period:", "_pulse_period", "s", 1e-3, 999999.999),
            ("Voltage compliance:", "_compliance", "V", 0.1, 105),
            ("Fixed source range:", "_source_range", "A", 2e-9, 0.1),
        )
        for label, attr, unit, minimum, maximum in fields:
            spin = SISpinBox(
                value=getattr(self, attr),
                suffix=unit,
                siPrefix=True,
                bounds=(minimum, maximum),
                allow_expressions=True,
            )
            spin.setObjectName(attr.removeprefix("_"))
            spin.sigValueChanged.connect(
                lambda widget, attribute=attr: self._update_setting(
                    attribute, widget.value(), preview
                )
            )
            form.addRow(label, spin)
        for label, attr, choices in (
            (
                "Source ranging:",
                "_source_range_mode",
                [(mode.name, mode) for mode in SourceRangeMode],
            ),
            (
                "2182A voltage range:",
                "_voltage_range",
                [("Auto", 0.0)] + [(f"{v:g} V", v) for v in (0.01, 0.1, 1.0, 10.0, 100.0)],
            ),
            (
                "Baseline measurements:",
                "_low_measurements",
                [("Two (before and after)", 2), ("One (before only)", 1)],
            ),
            (
                "Mains frequency (preview only):",
                "_preview_mains_frequency",
                [("50 Hz", 50), ("60 Hz", 60)],
            ),
        ):
            combo = QComboBox()
            combo.setObjectName(attr.removeprefix("_"))
            for text, value in choices:
                combo.addItem(text, value)
            combo.setCurrentIndex(combo.findData(getattr(self, attr)))
            combo.currentIndexChanged.connect(
                lambda _, widget=combo, attribute=attr: self._update_setting(
                    attribute, widget.currentData(), preview
                )
            )
            form.addRow(label, combo)
        range_spin = root.findChild(SISpinBox, "source_range")
        range_mode = root.findChild(QComboBox, "source_range_mode")
        range_spin.setEnabled(self._source_range_mode is SourceRangeMode.FIXED)
        range_mode.currentIndexChanged.connect(
            lambda _: range_spin.setEnabled(self._source_range_mode is SourceRangeMode.FIXED)
        )
        note = QLabel(
            "Zero-current baseline. Connect 2182A by RS-232 and Trigger Link.\n"
            "The 6221 sets integration time. Auxiliary meters are not supported.\n"
            "Timing expressions are evaluated during configuration; their preview is schematic."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(preview)
        layout.addStretch()
        return root

    def _update_setting(self, attr: str, value: Any, preview: _PulsePreview) -> None:
        """Store a control value and refresh the pulse diagram."""
        setattr(self, attr, value)
        preview.update()

    def _about_html(self) -> str | None:
        """Render this plugin's documentation instead of the DC About page."""
        return BasePlugin._about_html(self)
