"""Keithley 2400 series source-meter buffered sweep trace plugin.

Uses a Keithley 2400-series SMU to perform voltage- or current-driven sweeps
with the instrument's internal source sweep, trigger model, and trace buffer.
After the sweep completes, buffered readings are retrieved as a block and
returned as a multicolumn trace containing measured current, voltage,
resistance, power, and timestamp channels.

The active scan generator defines the source values.  These are programmed as a
custom LIST sweep into the 2400 so arbitrary point sequences are supported.
The plugin can run with immediate, bus, external, trigger-link, or timer-based
trigger sources as supported by the driver and instrument firmware.
"""

from __future__ import annotations

import enum
import math
import time
from collections.abc import Generator
from typing import Any

import numpy as np
import pandas as pd
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.keithley.k2400 import (
    FilterType,
    Keithley2400,
    TerminalSelection,
)
from stoner_measurement.instruments.source_meter import (
    SourceMode,
    SourceSweepConfiguration,
    SweepSpacing,
    TriggerModelConfiguration,
    TriggerSource,
)
from stoner_measurement.instruments.transport.gpib_transport import GpibTransport
from stoner_measurement.plugins.trace.base import (
    COLUMN_ROLE_Y,
    COLUMN_ROLE_Z,
    TraceData,
    TracePlugin,
    TraceStatus,
)
from stoner_measurement.scan import FunctionScanGenerator
from stoner_measurement.ui.widgets import FILTER_GPIB, SISpinBox, VisaResourceComboBox

_POLL_INTERVAL: float = 0.1
_TIMEOUT_FACTOR: float = 5.0
_TIMEOUT_MIN: float = 10.0
_LINE_PERIOD_50HZ: float = 0.02
_BUFFER_ELEMENTS: tuple[str, ...] = ("VOLT", "CURR", "RES", "TIME", "STAT")
_CLEANUP_EXCEPTIONS: tuple[type[Exception], ...] = (
    OSError,
    RuntimeError,
)


class ComplianceMode(enum.Enum):
    """How the plugin should determine the 2400 compliance limit."""

    FIXED = "fixed"
    RESISTANCE = "resistance"


class SweepSourceMode(enum.Enum):
    """Independent-variable mode for the Keithley 2400 sweep."""

    VOLTAGE = "voltage"
    CURRENT = "current"


class TriggerRouting(enum.Enum):
    """High-level trigger routing options exposed by the plugin UI."""

    IMMEDIATE = "immediate"
    BUS = "bus"
    EXTERNAL = "external"
    TRIGGER_LINK = "trigger_link"
    TIMER = "timer"


class RangeMode(enum.Enum):
    """Whether a source/sense range is automatically selected or fixed."""

    AUTO = "auto"
    FIXED = "fixed"


class ConnectionMode(enum.Enum):
    """2-wire or 4-wire measurement wiring."""

    TWO_WIRE = "two_wire"
    FOUR_WIRE = "four_wire"


class TerminalMode(enum.Enum):
    """Front or rear Keithley 2400 terminals."""

    FRONT = "front"
    REAR = "rear"


class Keithley2400SweepPlugin(TracePlugin):
    """Run buffered source sweeps on a Keithley 2400 source-meter.

    Use this plugin when one Keithley 2400-series SMU should generate a sweep
    and measure the response at each point. The active scan generator defines
    the source values. During configuration the plugin programs those values
    into the instrument as a LIST sweep, sets up the trigger model and trace
    buffer, then reads the buffered results back as one multicolumn trace after
    the sweep completes.

    The plugin returns one trace channel named ``IV`` containing programmed
    source values on the x-axis together with measured current, measured
    voltage, derived resistance, derived power, and timestamps.

    The Scan tab defines the source-value sequence and can optionally expose
    channel-average and standard-deviation outputs. The Settings tab contains
    nested **Basic** and **Advanced** pages. The **Basic** page contains the
    GPIB resource, source mode, compliance mode, fixed or resistance-derived
    compliance limit, integration time, source and trigger delays, output
    enable during the sweep, and source/measurement range options. The
    **Advanced** page contains terminal selection, 2-wire or 4-wire wiring,
    trigger routing and trigger I/O options, and digital or median filtering.

    The default setup is aimed at common transport-style measurements: current
    sweep mode, fixed 10 V compliance, front terminals, 4-wire remote sense,
    and trigger output enabled on trigger-link line 2.

    Attributes:
        _resource (str):
            VISA/GPIB resource string identifying the Keithley 2400.
        _smu (Keithley2400 | None):
            Connected Keithley 2400 driver instance, if any.
        _source_mode (SweepSourceMode):
            Whether the sweep sources voltage or current.
        _compliance (float):
            Fixed current or voltage compliance limit, depending on source mode.
        _compliance_mode (ComplianceMode):
            Whether compliance is set directly or derived from resistance.
        _compliance_resistance (float):
            Resistance threshold used when resistance-derived compliance is selected.
        _nplc (float):
            Integration time in power-line cycles.
        _source_delay (float):
            Delay after each source update.
        _trigger_delay (float):
            Delay between trigger reception and measurement.
        _enable_output_during_measurement (bool):
            Whether the SMU output is enabled while the sweep runs.
        _trigger_routing (TriggerRouting):
            Selected sweep-trigger routing mode.
        _trigger_count_override (int):
            Optional manual trigger count override.
        _arm_count (int):
            Arm-layer count passed to the instrument trigger model.
        _timer_interval (float):
            Timer interval used in timer-trigger mode.
        _enable_trigger_out (bool):
            Whether trigger output signalling is enabled.
        _trigger_out_line (int):
            Trigger-link output line number.
        _trigger_in_line (int):
            Trigger-link input line number.
        _source_range_mode (RangeMode):
            Whether the source range is automatic or fixed.
        _source_range (float):
            Fixed source range value when enabled.
        _sense_range_mode (RangeMode):
            Whether the sense range is automatic or fixed.
        _sense_range (float):
            Fixed sense range value when enabled.
        _connection_mode (ConnectionMode):
            Whether measurements use 2-wire or 4-wire wiring.
        _terminal_mode (TerminalMode):
            Whether the front or rear terminals are used.
        _filter_enabled (bool):
            Whether the digital filter is enabled.
        _filter_count (int):
            Number of readings used by the digital filter.
        _filter_type (FilterType):
            Digital filter mode used by the instrument.
        _median_filter_enabled (bool):
            Whether the median filter is enabled.
        _last_buffer_raw (tuple[float, ...] | None):
            Most recently retrieved buffered readings.
        _sweep_values (tuple[float, ...] | None):
            Most recently generated source values programmed into the sweep.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Create and inspect a plugin in the console::

            plugin = Keithley2400SweepPlugin()
            plugin._resource = "GPIB0::24::INSTR"
            plugin._source_mode

        Adjust common settings from the console::

            plugin._compliance = 5.0
            plugin._connection_mode = ConnectionMode.FOUR_WIRE
            plugin._trigger_out_line = 2

        Inspect returned trace data after a measurement::

            data = plugin.measure({})
            data["IV"].df.head()
    """

    def __init__(self, parent=None) -> None:
        """Initialise the plugin."""
        super().__init__(parent)
        self._resource: str = ""
        self._smu: Keithley2400 | None = None

        self._source_mode: SweepSourceMode = SweepSourceMode.CURRENT
        self._compliance: float = 10.0
        self._compliance_mode: ComplianceMode = ComplianceMode.FIXED
        self._compliance_resistance: float = 1000.0
        self._nplc: float = 1.0
        self._source_delay: float = 0.01
        self._trigger_delay: float = 0.0
        self._enable_output_during_measurement: bool = True

        self._trigger_routing: TriggerRouting = TriggerRouting.IMMEDIATE
        self._trigger_count_override: int = 0
        self._arm_count: int = 1
        self._timer_interval: float = 0.1
        self._enable_trigger_out: bool = True
        self._trigger_out_line: int = 2
        self._trigger_in_line: int = 1
        self._source_range_mode: RangeMode = RangeMode.AUTO
        self._source_range: float = 1.0
        self._sense_range_mode: RangeMode = RangeMode.AUTO
        self._sense_range: float = 1.0
        self._connection_mode: ConnectionMode = ConnectionMode.FOUR_WIRE
        self._terminal_mode: TerminalMode = TerminalMode.FRONT
        self._filter_enabled: bool = False
        self._filter_count: int = 10
        self._filter_type: FilterType = FilterType.REPEAT
        self._median_filter_enabled: bool = False

        self._last_buffer_raw: tuple[float, ...] | None = None
        self._sweep_values: tuple[float, ...] | None = None
        self.scan_generator = FunctionScanGenerator()
        self._apply_initial_config()

    @property
    def name(self) -> str:
        """Unique identifier for this plugin.

        Returns:
            (str):
                Always ``"Keithley2400Sweep"``.
        """
        return "Keithley2400Sweep"

    @property
    def trace_title(self) -> str:
        """Human-readable title for the returned trace.

        Returns:
            (str):
                Always ``"Keithley 2400 I-V Sweep"``.
        """
        return "Keithley 2400 I-V Sweep"

    @property
    def channel_names(self) -> list[str]:
        """Name of the single multicolumn measurement channel.

        Returns:
            (list[str]):
                Single-element list containing ``"IV"``.
        """
        return ["IV"]

    @property
    def x_units(self) -> str:
        """Units of the programmed source axis.

        Returns:
            (str):
                ``"V"`` in voltage-source mode, otherwise ``"A"``.
        """
        return "V" if self._source_mode is SweepSourceMode.VOLTAGE else "A"

    @property
    def y_units(self) -> str:
        """Primary y-axis units.

        Returns:
            (str):
                ``"A"`` in voltage-source mode, otherwise ``"V"``.
        """
        return "A" if self._source_mode is SweepSourceMode.VOLTAGE else "V"

    @property
    def x_label(self) -> str:
        """Label for the programmed source axis.

        Returns:
            (str):
                ``"Voltage"`` in voltage-source mode, otherwise ``"Current"``.
        """
        return "Voltage" if self._source_mode is SweepSourceMode.VOLTAGE else "Current"

    @property
    def y_label(self) -> str:
        """Label for the primary dependent variable.

        Returns:
            (str):
                ``"Current"`` in voltage-source mode, otherwise ``"Voltage"``.
        """
        return "Current" if self._source_mode is SweepSourceMode.VOLTAGE else "Voltage"

    def reported_values(self) -> dict[str, str]:
        """Return mean/std outputs for each buffered trace column."""
        if not self._report_channel_statistics:
            return {}

        var = self.instance_name
        values: dict[str, str] = {}
        for column in ("Current", "Voltage", "Resistance", "Power", "Timestamp"):
            key = f"IV {column}"
            values[f"{var}:{key} mean"] = (
                f"{var}.get_channel_statistic({key!r}, 'mean')"
            )
            values[f"{var}:{key} std"] = (
                f"{var}.get_channel_statistic({key!r}, 'std')"
            )
        return values

    def connect(self) -> None:
        """Open the SMU connection and verify its identity.

        Raises:
            Exception:
                Propagates connection or identity-verification failures after
                attempting to close any partially opened transport.
        """
        self._set_status(TraceStatus.CONNECTING)
        transport: GpibTransport | None = None
        try:
            transport = GpibTransport.from_resource_string(self._resource, timeout=10.0)
            self._smu = Keithley2400(transport)
            self._smu.connect()
            self._smu.confirm_identity()
        except Exception:
            if transport is not None:
                try:
                    transport.close()
                except _CLEANUP_EXCEPTIONS:
                    pass
            self._smu = None
            self._set_status(TraceStatus.ERROR)
            raise
        self._set_status(TraceStatus.IDLE)

    def configure(self) -> None:
        """Program source mode, sweep list, buffer, and trigger model.

        Raises:
            RuntimeError:
                If the plugin is not connected to an instrument.
            ValueError:
                If the scan generator produces no points or the selected
                compliance mode cannot be resolved for the generated sweep.
        """
        if self._smu is None:
            raise RuntimeError("Not connected — call connect() before configure().")

        self._set_status(TraceStatus.CONFIGURING)
        try:
            values = tuple(float(v) for v in self.scan_generator.generate())
            if not values:
                raise ValueError("Scan generator produced no points.")

            self._sweep_values = values
            n_points = len(values)

            self._smu.reset()
            self._smu.check_error_queue(raise_on_error=False)
            instrument_mode = (
                SourceMode.VOLT if self._source_mode is SweepSourceMode.VOLTAGE else SourceMode.CURR
            )
            self._smu.enable_output(False)
            self._smu.set_source_mode(instrument_mode)
            self._smu.set_nplc(self._nplc)
            self._smu.set_terminal_selection(
                TerminalSelection.FRONT if self._terminal_mode is TerminalMode.FRONT else TerminalSelection.REAR
            )
            self._smu.set_remote_sense(self._connection_mode is ConnectionMode.FOUR_WIRE)
            self._smu.set_source_autorange(self._source_range_mode is RangeMode.AUTO, instrument_mode)
            if self._source_range_mode is RangeMode.FIXED:
                self._smu.set_source_range(self._source_range, instrument_mode)
            self._smu.set_sense_autorange(self._sense_range_mode is RangeMode.AUTO, instrument_mode)
            if self._sense_range_mode is RangeMode.FIXED:
                self._smu.set_sense_range(self._sense_range, instrument_mode)
            self._smu.set_filter_enabled(self._filter_enabled, instrument_mode)
            self._smu.set_filter_count(self._filter_count, instrument_mode)
            self._smu.set_filter_type(self._filter_type, instrument_mode)
            self._smu.set_median_filter_enabled(self._median_filter_enabled, instrument_mode)
            self._smu.set_format_data_ascii()
            self._smu.set_format_elements(_BUFFER_ELEMENTS)
            self._smu.reset_timestamp()
            self._smu.configure_source_sweep(
                SourceSweepConfiguration(
                    spacing=SweepSpacing.LIST,
                    values=values,
                    delay=self._source_delay,
                )
            )
            if self._compliance_mode is ComplianceMode.RESISTANCE:
                if self._compliance_resistance <= 0.0:
                    raise ValueError("Compliance resistance must be positive.")
                if self._source_mode is SweepSourceMode.CURRENT:
                    compliance_limit = max(abs(float(v)) for v in values) * self._compliance_resistance
                else:
                    min_abs_voltage = min(
                        abs(float(v))
                        for v in values
                        if not math.isclose(float(v), 0.0, abs_tol=1e-30)
                    )
                    compliance_limit = min_abs_voltage / self._compliance_resistance
                self._smu.set_compliance(compliance_limit)
            else:
                self._smu.set_compliance(self._compliance)
            self._smu.configure_buffer(n_points, elements=_BUFFER_ELEMENTS)

            trigger_source = {
                TriggerRouting.IMMEDIATE: TriggerSource.IMM,
                TriggerRouting.BUS: TriggerSource.IMM,
                TriggerRouting.EXTERNAL: TriggerSource.IMM,
                TriggerRouting.TRIGGER_LINK: TriggerSource.TLIN,
                TriggerRouting.TIMER: TriggerSource.IMM,
            }[self._trigger_routing]

            trigger_count = self._trigger_count_override if self._trigger_count_override > 0 else n_points
            self._smu.configure_trigger_model(
                TriggerModelConfiguration(
                    trigger_source=trigger_source,
                    trigger_count=trigger_count,
                    trigger_delay=self._trigger_delay,
                    arm_source=TriggerSource.IMM,
                    arm_count=self._arm_count,
                )
            )

            if self._trigger_routing is TriggerRouting.BUS:
                self._smu.write(":ARM:SOUR BUS")
            elif self._trigger_routing is TriggerRouting.EXTERNAL:
                self._smu.write(":ARM:SOUR TLIN")
                self._smu.write(":ARM:TCON:DIR ACC")
                self._smu.write(f":ARM:TCON:ILIN {self._trigger_in_line}")
            elif self._trigger_routing is TriggerRouting.TRIGGER_LINK:
                self._smu.write(":ARM:SOUR TLIN")
                self._smu.write(":ARM:TCON:DIR ACC")
                self._smu.write(f":ARM:TCON:ILIN {self._trigger_in_line}")
            elif self._trigger_routing is TriggerRouting.TIMER:
                self._smu.write(":ARM:SOUR TIM")
                self._smu.write(f":ARM:TIM {self._timer_interval}")
            else:
                self._smu.write(":ARM:SOUR IMM")

            if self._enable_trigger_out:
                self._smu.write(":TRIG:TCON:DIR SOUR")
                self._smu.write(f":TRIG:TCON:OLIN {self._trigger_out_line}")
                self._smu.write(":TRIG:TCON:OUTP DEL")
            else:
                self._smu.write(":TRIG:TCON:OUTP NONE")
            self._smu.check_error_queue()

        except Exception:
            self._set_status(TraceStatus.ERROR)
            raise
        self._set_status(TraceStatus.IDLE)

    def execute(
        self,
        parameters: dict[str, Any],
    ) -> Generator[tuple[float, float]]:
        """Run the configured sweep and yield the primary plotted channel."""
        if self._smu is None:
            raise RuntimeError("Not connected — call connect() before execute().")
        if self._sweep_values is None:
            raise RuntimeError("Not configured — call configure() before execute().")

        n_points = len(self._sweep_values)
        timeout = max(
            _TIMEOUT_MIN,
            n_points
            * (_LINE_PERIOD_50HZ * self._nplc + self._source_delay + self._trigger_delay)
            * _TIMEOUT_FACTOR,
        )

        try:
            if self._enable_output_during_measurement:
                self._smu.enable_output(True)
            self._smu.initiate()

            if self._trigger_routing is TriggerRouting.BUS:
                self._smu.transport.send_group_execute_trigger()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    self._smu.wait_for_operation_complete()
                    break
                except Exception:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(_POLL_INTERVAL)
            while self._smu.get_buffer_count() < n_points:
                if time.monotonic() > deadline:
                    raise RuntimeError(f"Timeout waiting for Keithley 2400 sweep completion after {timeout:.1f} s.")
                time.sleep(_POLL_INTERVAL)

            self._last_buffer_raw = self._smu.read_buffer_records(_BUFFER_ELEMENTS, count=n_points)
            self._smu.set_trace_feed_continuous_never()
            self._smu.check_error_queue()
        except Exception:
            try:
                self._smu.abort()
                self._smu.safe_output_off()
            except _CLEANUP_EXCEPTIONS:
                pass
            raise
        finally:
            if self._enable_output_during_measurement:
                try:
                    self._smu.safe_output_off()
                except _CLEANUP_EXCEPTIONS:
                    pass

        if self._last_buffer_raw is None:
            raise RuntimeError("Sweep completed without buffered readings.")
        current, voltage, _, _, _ = self._records_to_arrays(self._last_buffer_raw, self._sweep_values)
        primary = current if self._source_mode is SweepSourceMode.VOLTAGE else voltage
        yield from zip(self._sweep_values, primary)

    def measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Acquire the sweep and return a single multicolumn trace."""
        self._set_status(TraceStatus.MEASURING)
        try:
            _ = list(self.execute(parameters))
            if self._sweep_values is None or self._last_buffer_raw is None:
                raise RuntimeError("Sweep completed without an active instrument or sweep definition.")
            records = self._last_buffer_raw
        finally:
            self._last_buffer_raw = None
            self._set_status(TraceStatus.DATA_AVAILABLE)

        current, voltage, resistance, power, timestamp = self._records_to_arrays(records, self._sweep_values)
        x_arr = np.asarray(self._sweep_values, dtype=float)

        df = pd.DataFrame(
            {
                "Current": current,
                "Voltage": voltage,
                "Resistance": resistance,
                "Power": power,
                "Timestamp": timestamp,
            },
            index=pd.Index(x_arr, name="x"),
        )
        column_roles = {
            "Current": COLUMN_ROLE_Y if self._source_mode is SweepSourceMode.VOLTAGE else COLUMN_ROLE_Z,
            "Voltage": COLUMN_ROLE_Y if self._source_mode is SweepSourceMode.CURRENT else COLUMN_ROLE_Z,
            "Resistance": COLUMN_ROLE_Z,
            "Power": COLUMN_ROLE_Z,
            "Timestamp": COLUMN_ROLE_Z,
        }
        names = {
            "x": self.x_label,
            "Current": "Current",
            "Voltage": "Voltage",
            "Resistance": "Resistance",
            "Power": "Power",
            "Timestamp": "Timestamp",
        }
        units = {
            "x": self.x_units,
            "Current": "A",
            "Voltage": "V",
            "Resistance": "Ω",
            "Power": "W",
            "Timestamp": "s",
        }
        self.data = {"IV": TraceData(df=df, column_roles=column_roles, names=names, units=units)}
        self._update_channel_statistics()
        return self.data

    def _records_to_arrays(
        self,
        records: tuple[Any, ...],
        sweep_values: tuple[float, ...],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Convert structured buffer records into NumPy arrays."""
        n_points = len(sweep_values)
        if len(records) != n_points:
            raise RuntimeError(f"Expected {n_points} buffered readings but received {len(records)}.")

        voltage = np.array(
            [float(record.voltage) if record.voltage is not None else float("nan") for record in records],
            dtype=float,
        )
        current = np.array(
            [float(record.current) if record.current is not None else float("nan") for record in records],
            dtype=float,
        )
        resistance = np.array(
            [float(record.resistance) if record.resistance is not None else float("nan") for record in records],
            dtype=float,
        )
        power = voltage * current
        if np.isnan(resistance).all():
            with np.errstate(invalid="ignore", divide="ignore"):
                resistance = np.where(np.abs(current) > 1e-30, voltage / current, float("nan"))
        raw_time = [float(record.time) if record.time is not None else float("nan") for record in records]
        timestamp = np.array(raw_time, dtype=float)
        if np.isnan(timestamp).all():
            point_time = self._nplc * _LINE_PERIOD_50HZ + self._source_delay + self._trigger_delay
            timestamp = np.arange(n_points, dtype=float) * point_time
        return current, voltage, resistance, power, timestamp

    def disconnect(self) -> None:
        """Disable output and close the SMU connection."""
        self._set_status(TraceStatus.DISCONNECTING)
        if self._smu is not None:
            try:
                self._smu.safe_output_off()
            except _CLEANUP_EXCEPTIONS:
                pass
            try:
                self._smu.disconnect()
            except _CLEANUP_EXCEPTIONS:
                pass
        self._smu = None
        self._sweep_values = None
        self._last_buffer_raw = None
        self._set_status(TraceStatus.IDLE)

    def to_json(self) -> dict[str, Any]:
        """Serialise plugin state."""
        data = super().to_json()
        data.update(
            {
                "resource": self._resource,
                "source_mode": self._source_mode.value,
                "compliance_mode": self._compliance_mode.value,
                "compliance": self._compliance,
                "compliance_resistance": self._compliance_resistance,
                "nplc": self._nplc,
                "source_delay": self._source_delay,
                "trigger_delay": self._trigger_delay,
                "enable_output_during_measurement": self._enable_output_during_measurement,
                "trigger_routing": self._trigger_routing.value,
                "trigger_count_override": self._trigger_count_override,
                "arm_count": self._arm_count,
                "timer_interval": self._timer_interval,
                "enable_trigger_out": self._enable_trigger_out,
                "trigger_out_line": self._trigger_out_line,
                "trigger_in_line": self._trigger_in_line,
                "source_range_mode": self._source_range_mode.value,
                "source_range": self._source_range,
                "sense_range_mode": self._sense_range_mode.value,
                "sense_range": self._sense_range,
                "connection_mode": self._connection_mode.value,
                "terminal_mode": self._terminal_mode.value,
                "filter_enabled": self._filter_enabled,
                "filter_count": self._filter_count,
                "filter_type": self._filter_type.value,
                "median_filter_enabled": self._median_filter_enabled,
            }
        )
        return data

    def _restore_from_json(self, data: dict) -> None:
        """Restore plugin state from serialised data."""
        super()._restore_from_json(data)
        self._resource = str(data.get("resource", self._resource))
        self._source_mode = SweepSourceMode(str(data.get("source_mode", self._source_mode.value)))
        self._compliance_mode = ComplianceMode(
            str(data.get("compliance_mode", self._compliance_mode.value))
        )
        self._compliance = float(data.get("compliance", self._compliance))
        self._compliance_resistance = float(
            data.get("compliance_resistance", self._compliance_resistance)
        )
        self._nplc = float(data.get("nplc", self._nplc))
        self._source_delay = float(data.get("source_delay", self._source_delay))
        self._trigger_delay = float(data.get("trigger_delay", self._trigger_delay))
        self._enable_output_during_measurement = bool(
            data.get("enable_output_during_measurement", self._enable_output_during_measurement)
        )
        self._trigger_routing = TriggerRouting(str(data.get("trigger_routing", self._trigger_routing.value)))
        self._trigger_count_override = int(data.get("trigger_count_override", self._trigger_count_override))
        self._arm_count = int(data.get("arm_count", self._arm_count))
        self._timer_interval = float(data.get("timer_interval", self._timer_interval))
        self._enable_trigger_out = bool(data.get("enable_trigger_out", self._enable_trigger_out))
        self._trigger_out_line = int(data.get("trigger_out_line", self._trigger_out_line))
        self._trigger_in_line = int(data.get("trigger_in_line", self._trigger_in_line))
        self._source_range_mode = RangeMode(str(data.get("source_range_mode", self._source_range_mode.value)))
        self._source_range = float(data.get("source_range", self._source_range))
        self._sense_range_mode = RangeMode(str(data.get("sense_range_mode", self._sense_range_mode.value)))
        self._sense_range = float(data.get("sense_range", self._sense_range))
        self._connection_mode = ConnectionMode(str(data.get("connection_mode", self._connection_mode.value)))
        self._terminal_mode = TerminalMode(str(data.get("terminal_mode", self._terminal_mode.value)))
        self._filter_enabled = bool(data.get("filter_enabled", self._filter_enabled))
        self._filter_count = int(data.get("filter_count", self._filter_count))
        self._filter_type = FilterType(str(data.get("filter_type", self._filter_type.value)))
        self._median_filter_enabled = bool(data.get("median_filter_enabled", self._median_filter_enabled))

    def _plugin_config_tabs(self) -> QWidget:
        """Return the plugin settings widget."""
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(4, 4, 4, 4)

        tab_widget = QTabWidget()
        root_layout.addWidget(tab_widget)

        basic_page = QWidget()
        basic_layout = QVBoxLayout(basic_page)
        basic_layout.setContentsMargins(0, 0, 0, 0)
        conn_group = QGroupBox("Connection")
        conn_form = QFormLayout(conn_group)
        resource_combo = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        resource_combo.setCurrentText(self._resource)
        resource_combo.currentTextChanged.connect(lambda text: setattr(self, "_resource", text.strip()))
        conn_form.addRow("2400 GPIB resource:", resource_combo)
        basic_layout.addWidget(conn_group)

        src_group = QGroupBox("Source / Sense")
        src_form = QFormLayout(src_group)

        mode_combo = QComboBox()
        mode_combo.addItem("Voltage sweep", SweepSourceMode.VOLTAGE)
        mode_combo.addItem("Current sweep", SweepSourceMode.CURRENT)
        mode_combo.setCurrentIndex(0 if self._source_mode is SweepSourceMode.VOLTAGE else 1)
        mode_combo.currentIndexChanged.connect(
            lambda idx: setattr(self, "_source_mode", mode_combo.itemData(idx))
        )

        compliance_text = (
            "Compliance current:" if self._source_mode is SweepSourceMode.VOLTAGE else "Compliance voltage:"
        )
        compliance_mode_combo = QComboBox()
        compliance_mode_combo.addItem("Fixed limit", ComplianceMode.FIXED)
        compliance_mode_combo.addItem("Resistance-derived", ComplianceMode.RESISTANCE)
        compliance_mode_combo.setCurrentIndex(0 if self._compliance_mode is ComplianceMode.FIXED else 1)

        compliance_label = QLabel(compliance_text)
        compliance_sb = SISpinBox(
            suffix="A" if self._source_mode is SweepSourceMode.VOLTAGE else "V",
            value=self._compliance,
        )
        compliance_sb.setMinimum(1e-9)
        compliance_sb.setMaximum(210.0)
        compliance_sb.valueChanged.connect(lambda value: setattr(self, "_compliance", value))
        compliance_sb.setVisible(self._compliance_mode is ComplianceMode.FIXED)

        compliance_r_label = QLabel(
            "Min resistance:" if self._source_mode is SweepSourceMode.VOLTAGE else "Max resistance:"
        )
        compliance_r_sb = SISpinBox(suffix="Ω", value=self._compliance_resistance)
        compliance_r_sb.setMinimum(1e-9)
        compliance_r_sb.setMaximum(1e12)
        compliance_r_sb.valueChanged.connect(lambda value: setattr(self, "_compliance_resistance", value))
        compliance_r_sb.setVisible(self._compliance_mode is ComplianceMode.RESISTANCE)
        compliance_r_label.setVisible(self._compliance_mode is ComplianceMode.RESISTANCE)

        def _on_mode_changed(index: int) -> None:
            self._source_mode = mode_combo.itemData(index)
            if self._source_mode is SweepSourceMode.VOLTAGE:
                compliance_label.setText("Compliance current:")
                compliance_sb.setSuffix("A")
                compliance_r_label.setText("Min resistance:")
            else:
                compliance_label.setText("Compliance voltage:")
                compliance_sb.setSuffix("V")
                compliance_r_label.setText("Max resistance:")

        def _on_compliance_mode_changed(index: int) -> None:
            self._compliance_mode = compliance_mode_combo.itemData(index)
            is_fixed = self._compliance_mode is ComplianceMode.FIXED
            compliance_sb.setVisible(is_fixed)
            compliance_r_sb.setVisible(not is_fixed)
            compliance_r_label.setVisible(not is_fixed)

        mode_combo.currentIndexChanged.connect(_on_mode_changed)
        compliance_mode_combo.currentIndexChanged.connect(_on_compliance_mode_changed)

        nplc_combo = QComboBox()
        for option in (0.01, 0.1, 1.0, 10.0):
            nplc_combo.addItem(f"{option:g} PLC", option)
        nplc_index = 0
        for idx in range(nplc_combo.count()):
            if math.isclose(float(nplc_combo.itemData(idx)), self._nplc, rel_tol=0.0, abs_tol=1e-12):
                nplc_index = idx
                break
        nplc_combo.setCurrentIndex(nplc_index)
        nplc_combo.currentIndexChanged.connect(lambda idx: setattr(self, "_nplc", float(nplc_combo.itemData(idx))))

        source_delay_sb = SISpinBox(suffix="s", value=self._source_delay)
        source_delay_sb.setMinimum(0.0)
        source_delay_sb.setMaximum(9999.0)
        source_delay_sb.valueChanged.connect(lambda value: setattr(self, "_source_delay", value))

        trigger_delay_sb = SISpinBox(suffix="s", value=self._trigger_delay)
        trigger_delay_sb.setMinimum(0.0)
        trigger_delay_sb.setMaximum(9999.0)
        trigger_delay_sb.valueChanged.connect(lambda value: setattr(self, "_trigger_delay", value))

        output_chk = QCheckBox()
        output_chk.setChecked(self._enable_output_during_measurement)
        output_chk.toggled.connect(lambda state: setattr(self, "_enable_output_during_measurement", state))

        src_form.addRow("Sweep mode:", mode_combo)
        src_form.addRow("Compliance mode:", compliance_mode_combo)
        src_form.addRow(compliance_label, compliance_sb)
        src_form.addRow(compliance_r_label, compliance_r_sb)
        src_form.addRow("Integration time (NPLC):", nplc_combo)
        src_form.addRow("Source delay:", source_delay_sb)
        src_form.addRow("Trigger delay:", trigger_delay_sb)
        src_form.addRow("Enable output during sweep:", output_chk)
        basic_layout.addWidget(src_group)

        ranges_group = QGroupBox("Ranges")
        ranges_form = QFormLayout(ranges_group)

        source_range_mode_combo = QComboBox()
        source_range_mode_combo.addItem("Auto", RangeMode.AUTO)
        source_range_mode_combo.addItem("Fixed", RangeMode.FIXED)
        source_range_mode_combo.setCurrentIndex(0 if self._source_range_mode is RangeMode.AUTO else 1)
        source_range_sb = SISpinBox(
            suffix="V" if self._source_mode is SweepSourceMode.VOLTAGE else "A",
            value=self._source_range,
        )
        source_range_sb.setMinimum(1e-12)
        source_range_sb.setMaximum(1e6)
        source_range_sb.setVisible(self._source_range_mode is RangeMode.FIXED)
        source_range_sb.valueChanged.connect(lambda value: setattr(self, "_source_range", value))

        sense_range_mode_combo = QComboBox()
        sense_range_mode_combo.addItem("Auto", RangeMode.AUTO)
        sense_range_mode_combo.addItem("Fixed", RangeMode.FIXED)
        sense_range_mode_combo.setCurrentIndex(0 if self._sense_range_mode is RangeMode.AUTO else 1)
        sense_range_sb = SISpinBox(
            suffix="A" if self._source_mode is SweepSourceMode.VOLTAGE else "V",
            value=self._sense_range,
        )
        sense_range_sb.setMinimum(1e-12)
        sense_range_sb.setMaximum(1e6)
        sense_range_sb.setVisible(self._sense_range_mode is RangeMode.FIXED)
        sense_range_sb.valueChanged.connect(lambda value: setattr(self, "_sense_range", value))

        def _on_source_range_mode_changed(index: int) -> None:
            self._source_range_mode = source_range_mode_combo.itemData(index)
            source_range_sb.setVisible(self._source_range_mode is RangeMode.FIXED)

        def _on_sense_range_mode_changed(index: int) -> None:
            self._sense_range_mode = sense_range_mode_combo.itemData(index)
            sense_range_sb.setVisible(self._sense_range_mode is RangeMode.FIXED)

        source_range_mode_combo.currentIndexChanged.connect(_on_source_range_mode_changed)
        sense_range_mode_combo.currentIndexChanged.connect(_on_sense_range_mode_changed)

        ranges_form.addRow("Source range mode:", source_range_mode_combo)
        ranges_form.addRow("Source fixed range:", source_range_sb)
        ranges_form.addRow("Measure range mode:", sense_range_mode_combo)
        ranges_form.addRow("Measure fixed range:", sense_range_sb)
        basic_layout.addWidget(ranges_group)
        basic_layout.addStretch()

        trig_group = QGroupBox("Triggering")
        trig_form = QFormLayout(trig_group)

        trig_combo = QComboBox()
        trig_combo.addItem("Immediate", TriggerRouting.IMMEDIATE)
        trig_combo.addItem("Bus", TriggerRouting.BUS)
        trig_combo.addItem("External input", TriggerRouting.EXTERNAL)
        trig_combo.addItem("Trigger link", TriggerRouting.TRIGGER_LINK)
        trig_combo.addItem("Timer", TriggerRouting.TIMER)
        trig_index = 0
        for idx in range(trig_combo.count()):
            if trig_combo.itemData(idx) is self._trigger_routing:
                trig_index = idx
                break
        trig_combo.setCurrentIndex(trig_index)

        trigger_count_sb = QSpinBox()
        trigger_count_sb.setMinimum(0)
        trigger_count_sb.setMaximum(100000)
        trigger_count_sb.setValue(self._trigger_count_override)

        arm_count_sb = QSpinBox()
        arm_count_sb.setMinimum(1)
        arm_count_sb.setMaximum(100000)
        arm_count_sb.setValue(self._arm_count)

        timer_sb = SISpinBox(suffix="s", value=self._timer_interval)
        timer_sb.setMinimum(1e-6)
        timer_sb.setMaximum(9999.0)
        timer_sb.setEnabled(self._trigger_routing is TriggerRouting.TIMER)

        trig_in_sb = QSpinBox()
        trig_in_sb.setMinimum(1)
        trig_in_sb.setMaximum(6)
        trig_in_sb.setValue(self._trigger_in_line)
        trig_in_sb.setEnabled(self._trigger_routing in (TriggerRouting.EXTERNAL, TriggerRouting.TRIGGER_LINK))

        trig_out_chk = QCheckBox()
        trig_out_chk.setChecked(self._enable_trigger_out)

        trig_out_sb = QSpinBox()
        trig_out_sb.setMinimum(1)
        trig_out_sb.setMaximum(6)
        trig_out_sb.setValue(self._trigger_out_line)
        trig_out_sb.setEnabled(self._enable_trigger_out)

        def _on_trigger_changed(index: int) -> None:
            self._trigger_routing = trig_combo.itemData(index)
            timer_sb.setEnabled(self._trigger_routing is TriggerRouting.TIMER)
            trig_in_sb.setEnabled(self._trigger_routing in (TriggerRouting.EXTERNAL, TriggerRouting.TRIGGER_LINK))

        def _on_trigger_out_toggled(state: bool) -> None:
            self._enable_trigger_out = state
            trig_out_sb.setEnabled(state)

        trig_combo.currentIndexChanged.connect(_on_trigger_changed)
        trigger_count_sb.valueChanged.connect(lambda value: setattr(self, "_trigger_count_override", value))
        arm_count_sb.valueChanged.connect(lambda value: setattr(self, "_arm_count", value))
        timer_sb.valueChanged.connect(lambda value: setattr(self, "_timer_interval", value))
        trig_in_sb.valueChanged.connect(lambda value: setattr(self, "_trigger_in_line", value))
        trig_out_chk.toggled.connect(_on_trigger_out_toggled)
        trig_out_sb.valueChanged.connect(lambda value: setattr(self, "_trigger_out_line", value))

        trig_form.addRow("Trigger source:", trig_combo)
        trig_form.addRow("Trigger count override (0 = sweep length):", trigger_count_sb)
        trig_form.addRow("Arm count:", arm_count_sb)
        trig_form.addRow("Timer interval:", timer_sb)
        trig_form.addRow("Trigger input line:", trig_in_sb)
        trig_form.addRow("Enable trigger output:", trig_out_chk)
        trig_form.addRow("Trigger output line:", trig_out_sb)

        advanced_page = QWidget()
        advanced_layout = QVBoxLayout(advanced_page)
        advanced_layout.setContentsMargins(0, 0, 0, 0)

        terminals_group = QGroupBox("Terminals and Wiring")
        terminals_form = QFormLayout(terminals_group)

        terminal_combo = QComboBox()
        terminal_combo.addItem("Front terminals", TerminalMode.FRONT)
        terminal_combo.addItem("Rear terminals", TerminalMode.REAR)
        terminal_combo.setCurrentIndex(0 if self._terminal_mode is TerminalMode.FRONT else 1)
        terminal_combo.currentIndexChanged.connect(
            lambda idx: setattr(self, "_terminal_mode", terminal_combo.itemData(idx))
        )

        connection_combo = QComboBox()
        connection_combo.addItem("2-wire", ConnectionMode.TWO_WIRE)
        connection_combo.addItem("4-wire remote sense", ConnectionMode.FOUR_WIRE)
        connection_combo.setCurrentIndex(0 if self._connection_mode is ConnectionMode.TWO_WIRE else 1)
        connection_combo.currentIndexChanged.connect(
            lambda idx: setattr(self, "_connection_mode", connection_combo.itemData(idx))
        )

        terminals_form.addRow("Terminal selection:", terminal_combo)
        terminals_form.addRow("Measurement wiring:", connection_combo)
        advanced_layout.addWidget(terminals_group)
        advanced_layout.addWidget(trig_group)

        filter_group = QGroupBox("Filtering")
        filter_form = QFormLayout(filter_group)

        filter_enabled_chk = QCheckBox()
        filter_enabled_chk.setChecked(self._filter_enabled)
        filter_enabled_chk.toggled.connect(lambda state: setattr(self, "_filter_enabled", state))

        filter_count_sb = QSpinBox()
        filter_count_sb.setMinimum(1)
        filter_count_sb.setMaximum(100)
        filter_count_sb.setValue(self._filter_count)
        filter_count_sb.valueChanged.connect(lambda value: setattr(self, "_filter_count", value))

        filter_type_combo = QComboBox()
        filter_type_combo.addItem("Repeat", FilterType.REPEAT)
        filter_type_combo.addItem("Moving", FilterType.MOVING)
        filter_type_combo.setCurrentIndex(0 if self._filter_type is FilterType.REPEAT else 1)
        filter_type_combo.currentIndexChanged.connect(
            lambda idx: setattr(self, "_filter_type", filter_type_combo.itemData(idx))
        )

        median_filter_chk = QCheckBox()
        median_filter_chk.setChecked(self._median_filter_enabled)
        median_filter_chk.toggled.connect(lambda state: setattr(self, "_median_filter_enabled", state))

        filter_form.addRow("Enable digital filter:", filter_enabled_chk)
        filter_form.addRow("Digital filter count:", filter_count_sb)
        filter_form.addRow("Digital filter type:", filter_type_combo)
        filter_form.addRow("Enable median filter:", median_filter_chk)
        advanced_layout.addWidget(filter_group)
        advanced_layout.addStretch()

        tab_widget.addTab(basic_page, "Basic")
        tab_widget.addTab(advanced_page, "Advanced")
        return root

    def _about_html(self) -> str:
        """Return HTML for the About tab."""
        return (
            "<h3>Keithley 2400 &mdash; Buffered Source Sweep</h3>"
            "<p>This plugin uses a Keithley 2400-series source-meter to execute a "
            "built-in buffered sweep. The active scan generator defines the source "
            "list, which is programmed into the SMU as a LIST sweep.</p>"
            "<p>During the sweep the instrument measures both voltage and current. "
            "After completion the readings are retrieved from the internal trace "
            "buffer and expanded into Current, Voltage, Resistance, Power, and "
            "Timestamp columns.</p>"
            "<p>Trigger source options include immediate, bus, external, trigger-link, "
            "and timer modes. Optional trigger output routing can be enabled for "
            "experiments that need the 2400 to signal downstream hardware.</p>"
            "<p>Compliance can be specified as a fixed current/voltage limit or "
            "derived from a resistance threshold.</p>"
        )
