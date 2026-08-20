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
from typing import Any

import numpy as np
import pandas as pd
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.core.trace_data import COLUMN_ROLE_Y, COLUMN_ROLE_Z, TraceData
from stoner_measurement.instruments.keithley.k2400 import (
    FilterType,
    Keithley2400,
    TerminalSelection,
)
from stoner_measurement.instruments.nanovoltmeter import (
    Nanovoltmeter,
    NanovoltmeterTriggerSource,
)
from stoner_measurement.instruments.source_meter import (
    SourceMode,
    SourceSweepConfiguration,
    SweepSpacing,
    TriggerModelConfiguration,
    TriggerSource,
)
from stoner_measurement.instruments.transport.gpib_transport import GpibTransport
from stoner_measurement.plugins.trace._differential import (
    modulate_current_sweep,
    reduce_differential_readings,
)
from stoner_measurement.plugins.trace._nanovoltmeter_support import (
    NANOVOLTMETER_DRIVER_LABELS,
    NANOVOLTMETER_DRIVERS,
)
from stoner_measurement.plugins.trace.base import (
    TracePlugin,
    TraceStatus,
)
from stoner_measurement.scan import FunctionScanGenerator
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.widgets import FILTER_GPIB, SISpinBox, VisaResourceComboBox

_TIMEOUT_FACTOR: float = 5.0
_TIMEOUT_MIN: float = 10.0
_LINE_PERIOD_50HZ: float = 0.02
_SECONDARY_POST_SWEEP_DELAY_MIN: float = 0.05
_SECONDARY_READ_POLL: float = 0.01
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
    buffer, and enables the output ready for repeated measurements. Each
    subsequent measurement starts the programmed sweep and reads the buffered
    results back as one multicolumn trace after the sweep completes. The
    output remains on until :meth:`disconnect`.

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
        self._compliance: float | str = 10.0
        self._compliance_mode: ComplianceMode = ComplianceMode.FIXED
        self._compliance_resistance: float | str = 1000.0
        self._nplc: float = 1.0
        self._source_delay: float | str = 0.01
        self._trigger_delay: float | str = 0.0
        self._enable_output_during_measurement: bool = True
        self._differential_mode: bool = False
        self._differential_conductance: bool = False
        self._delta_current: float | str = 1e-6

        self._trigger_routing: TriggerRouting = TriggerRouting.IMMEDIATE
        self._trigger_count_override: int = 0
        self._arm_count: int = 1
        self._timer_interval: float | str = 0.1
        self._enable_trigger_out: bool = True
        self._trigger_out_line: int = 2
        self._trigger_in_line: int = 1
        self._source_range_mode: RangeMode = RangeMode.AUTO
        self._source_range: float | str = 1.0
        self._sense_range_mode: RangeMode = RangeMode.AUTO
        self._sense_range: float | str = 1.0
        self._connection_mode: ConnectionMode = ConnectionMode.FOUR_WIRE
        self._terminal_mode: TerminalMode = TerminalMode.FRONT
        self._filter_enabled: bool = False
        self._filter_count: int = 10
        self._filter_type: FilterType = FilterType.REPEAT
        self._median_filter_enabled: bool = False

        self._secondary_enabled: bool = False
        self._secondary_driver: str = "keithley_2182a"
        self._secondary_resource: str = "GPIB0::8::INSTR"
        self._secondary_prefix: str = "secondary"
        self._secondary_nplc: float = 1.0
        self._secondary_voltage_range: float = 0.0
        self._secondary_filter_type: str = "OFF"
        self._secondary_filter_count: int = 10
        self._secondary_trigger_delay: float | str = 0.0
        self._secondary_line_sync: bool = False
        self._secondary_autozero: bool = True
        self._secondary_analog_filter: bool = False
        self._secondary_relative_enabled: bool = False
        self._secondary_relative_value: float | str = 0.0
        self._secondary_digits: int = 8
        self._secondary_nanovoltmeter: Nanovoltmeter | None = None
        self._secondary_voltages: tuple[float, ...] | None = None

        self._sweep_values: tuple[float, ...] | None = None
        self._nominal_sweep_values: tuple[float, ...] | None = None
        self.scan_generator = FunctionScanGenerator(parent=self)
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
    def trace_names(self) -> list[str]:
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
        response_column = (
            "Conductance"
            if self._differential_mode and self._differential_conductance
            else "Resistance"
        )
        for column in ("Current", "Voltage", response_column, "Power", "Timestamp"):
            key = f"IV {column}"
            values[f"{var}:{key} mean"] = f"{var}.get_channel_statistic({key!r}, 'mean')"
            values[f"{var}:{key} std"] = f"{var}.get_channel_statistic({key!r}, 'std')"
        if self._secondary_enabled:
            prefix = self._secondary_prefix.strip() or "secondary"
            response_symbol = "G" if response_column == "Conductance" else "R"
            for column in (f"{prefix} V", f"{prefix} {response_symbol}", f"{prefix} P"):
                key = f"IV {column}"
                values[f"{var}:{key} mean"] = f"{var}.get_channel_statistic({key!r}, 'mean')"
                values[f"{var}:{key} std"] = f"{var}.get_channel_statistic({key!r}, 'std')"
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
        secondary_transport: GpibTransport | None = None
        try:
            transport = GpibTransport.from_resource_string(self._resource, timeout=10.0)
            self._smu = Keithley2400(transport)
            self._smu.connect()
            self._smu.confirm_identity()
            if self._secondary_enabled:
                driver_class = NANOVOLTMETER_DRIVERS[self._secondary_driver]
                secondary_transport = GpibTransport.from_resource_string(
                    self._secondary_resource, timeout=10.0
                )
                self._secondary_nanovoltmeter = driver_class(secondary_transport)  # type: ignore[call-arg]
                self._secondary_nanovoltmeter.connect()
                self._secondary_nanovoltmeter.confirm_identity()
        except Exception:
            for opened_transport in (secondary_transport, transport):
                if opened_transport is None:
                    continue
                try:
                    opened_transport.close()
                except _CLEANUP_EXCEPTIONS:
                    pass
            self._smu = None
            self._secondary_nanovoltmeter = None
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
        if self._secondary_enabled and self._secondary_nanovoltmeter is None:
            raise RuntimeError("Secondary nanovoltmeter is enabled but not connected.")

        self._set_status(TraceStatus.CONFIGURING)
        try:
            compliance = self.eval_float(self._compliance)
            compliance_resistance = self.eval_float(self._compliance_resistance)
            source_delay = self.eval_float(self._source_delay)
            trigger_delay = self.eval_float(self._trigger_delay)
            delta_current = self.eval_float(self._delta_current)
            source_range = self.eval_float(self._source_range)
            sense_range = self.eval_float(self._sense_range)
            timer_interval = self.eval_float(self._timer_interval)
            nominal_values = tuple(float(v) for v in self.scan_generator.generate())
            if not nominal_values:
                raise ValueError("Scan generator produced no points.")
            if self._differential_mode and self._source_mode is not SweepSourceMode.CURRENT:
                raise ValueError("Differential mode requires a current-source sweep.")

            self._nominal_sweep_values = nominal_values
            self._sweep_values = (
                tuple(modulate_current_sweep(np.asarray(nominal_values), delta_current))
                if self._differential_mode
                else nominal_values
            )
            values = self._sweep_values
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
                TerminalSelection.FRONT
                if self._terminal_mode is TerminalMode.FRONT
                else TerminalSelection.REAR
            )
            self._smu.set_remote_sense(self._connection_mode is ConnectionMode.FOUR_WIRE)
            self._smu.set_source_autorange(
                self._source_range_mode is RangeMode.AUTO, instrument_mode
            )
            if self._source_range_mode is RangeMode.FIXED:
                self._smu.set_source_range(source_range, instrument_mode)
            self._smu.set_sense_autorange(self._sense_range_mode is RangeMode.AUTO, instrument_mode)
            if self._sense_range_mode is RangeMode.FIXED:
                self._smu.set_sense_range(sense_range, instrument_mode)
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
                    delay=source_delay,
                )
            )
            if self._compliance_mode is ComplianceMode.RESISTANCE:
                if compliance_resistance <= 0.0:
                    raise ValueError("Compliance resistance must be positive.")
                if self._source_mode is SweepSourceMode.CURRENT:
                    compliance_limit = (
                        max(abs(float(v)) for v in values) * compliance_resistance
                    )
                else:
                    min_abs_voltage = min(
                        abs(float(v))
                        for v in values
                        if not math.isclose(float(v), 0.0, abs_tol=1e-30)
                    )
                    compliance_limit = min_abs_voltage / compliance_resistance
                self._smu.set_compliance(compliance_limit)
            else:
                self._smu.set_compliance(compliance)
            self._smu.configure_buffer(n_points, elements=_BUFFER_ELEMENTS)

            if self._secondary_enabled:
                assert self._secondary_nanovoltmeter is not None
                self._configure_secondary_nanovoltmeter(self._secondary_nanovoltmeter, n_points)

            trigger_source = (
                TriggerSource.TLIN
                if self._secondary_enabled
                else {
                    TriggerRouting.IMMEDIATE: TriggerSource.IMM,
                    TriggerRouting.BUS: TriggerSource.IMM,
                    TriggerRouting.EXTERNAL: TriggerSource.IMM,
                    TriggerRouting.TRIGGER_LINK: TriggerSource.TLIN,
                    TriggerRouting.TIMER: TriggerSource.IMM,
                }[self._trigger_routing]
            )

            trigger_count = (
                n_points
                if self._secondary_enabled
                else self._trigger_count_override
                if self._trigger_count_override > 0
                else n_points
            )
            self._smu.configure_trigger_model(
                TriggerModelConfiguration(
                    trigger_source=trigger_source,
                    trigger_count=trigger_count,
                    trigger_delay=trigger_delay,
                    arm_source=TriggerSource.IMM,
                    arm_count=1 if self._secondary_enabled else self._arm_count,
                )
            )

            if self._secondary_enabled:
                self._smu.write(":ARM:SOUR IMM")
                self._smu.configure_trigger_link_source_handshake(
                    input_line=self._trigger_in_line,
                    output_line=self._trigger_out_line,
                )
            elif self._trigger_routing is TriggerRouting.BUS:
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
                self._smu.write(f":ARM:TIM {timer_interval}")
            else:
                self._smu.write(":ARM:SOUR IMM")

            if not self._secondary_enabled:
                if self._enable_trigger_out:
                    self._smu.write(":TRIG:TCON:DIR SOUR")
                    self._smu.write(f":TRIG:TCON:OLIN {self._trigger_out_line}")
                    self._smu.write(":TRIG:TCON:OUTP DEL")
                else:
                    self._smu.write(":TRIG:TCON:OUTP NONE")
            self._smu.configure_buffer_full_srq()
            self._smu.check_error_queue()
            if self._enable_output_during_measurement:
                self._smu.enable_output(True)

        except Exception:
            self._set_status(TraceStatus.ERROR)
            raise
        self._set_status(TraceStatus.IDLE)

    def _configure_secondary_nanovoltmeter(self, meter: Nanovoltmeter, count: int) -> None:
        """Configure a capability-described meter for buffered external triggers."""
        capabilities = meter.get_capabilities()
        if capabilities.max_buffer_points is not None and count > capabilities.max_buffer_points:
            raise ValueError(
                f"{type(meter).__name__} supports at most "
                f"{capabilities.max_buffer_points} buffered readings; requested {count}."
            )
        if capabilities.supports_safe_reset:
            meter.reset()
        meter.set_digits(self._secondary_digits)
        meter.set_nplc(self._secondary_nplc)
        if capabilities.supports_line_sync:
            meter.set_line_sync_enabled(self._secondary_line_sync)  # type: ignore[attr-defined]
        if capabilities.supports_autozero:
            meter.set_autozero_enabled(self._secondary_autozero)  # type: ignore[attr-defined]
        meter.set_autorange(self._secondary_voltage_range <= 0.0)
        if self._secondary_voltage_range > 0.0:
            meter.set_range(self._secondary_voltage_range)
        filter_enabled = self._secondary_filter_type != "OFF"
        meter.set_filter_enabled(filter_enabled)
        if filter_enabled:
            if capabilities.supports_filter_count:
                meter.set_filter_count(self._secondary_filter_count)
            meter.set_filter_type(self._secondary_filter_type)  # type: ignore[attr-defined]
        if capabilities.supports_analog_filter:
            meter.set_analog_filter_enabled(self._secondary_analog_filter)
        if capabilities.supports_relative:
            meter.set_relative_value(  # type: ignore[attr-defined]
                self.eval_float(self._secondary_relative_value)
            )
            meter.set_relative_enabled(self._secondary_relative_enabled)
        meter.clear_buffer()
        meter.set_buffer_size(count)
        meter.set_buffer_feed_sense()
        meter.set_buffer_feed_continuous_next()
        meter.set_trigger_source(NanovoltmeterTriggerSource.EXT)
        meter.set_trigger_delay(  # type: ignore[attr-defined]
            self.eval_float(self._secondary_trigger_delay)
        )
        meter.set_trigger_count(count)

    def _secondary_measurement_time(self) -> float:
        """Estimate one secondary conversion from its declared capabilities."""
        capabilities = NANOVOLTMETER_DRIVERS[self._secondary_driver].CAPABILITIES
        filter_multiplier = (
            self._secondary_filter_count
            if self._secondary_filter_type in capabilities.counted_filter_types
            else 1
        )
        analog_multiplier = (
            capabilities.analog_filter_time_multiplier if self._secondary_analog_filter else 1.0
        )
        return (
            self.eval_float(self._secondary_trigger_delay)
            + self._secondary_nplc * _LINE_PERIOD_50HZ * filter_multiplier * analog_multiplier
        )

    def _acquire_buffer_records(self, parameters: dict[str, Any]) -> tuple[Any, ...]:
        """Run the configured sweep once and return its buffered readings."""
        del parameters
        if self._smu is None:
            raise RuntimeError("Not connected — call connect() before measure().")
        if self._secondary_enabled and self._secondary_nanovoltmeter is None:
            raise RuntimeError("Secondary nanovoltmeter is enabled but not connected.")
        if self._sweep_values is None:
            raise RuntimeError("Not configured — call configure() before measure().")

        n_points = len(self._sweep_values)
        point_time = (
            _LINE_PERIOD_50HZ * self._nplc
            + self.eval_float(self._source_delay)
            + self.eval_float(self._trigger_delay)
        )
        if self._secondary_enabled:
            point_time += self._secondary_measurement_time()
        timeout = max(_TIMEOUT_MIN, n_points * point_time * _TIMEOUT_FACTOR)

        try:
            self._smu.clear_buffer_full_event()
            self._smu.clear_buffer()
            self._smu.set_trace_feed_continuous_next()
            self._secondary_voltages = None
            if self._secondary_enabled:
                assert self._secondary_nanovoltmeter is not None
                self._secondary_nanovoltmeter.set_buffer_feed_continuous_next()
                self._secondary_nanovoltmeter.initiate()
            self._smu.initiate()

            if self._trigger_routing is TriggerRouting.BUS:
                self._smu.transport.send_group_execute_trigger()
            if not self._smu.wait_for_buffer_full_srq(timeout):
                raise RuntimeError(
                    f"Timeout waiting for Keithley 2400 sweep-complete SRQ after {timeout:.1f} s."
                )

            records = self._smu.read_buffer_records(_BUFFER_ELEMENTS, count=n_points)
            if self._secondary_enabled:
                assert self._secondary_nanovoltmeter is not None
                post_sweep_delay = max(
                    _SECONDARY_POST_SWEEP_DELAY_MIN,
                    self._secondary_measurement_time(),
                )
                time.sleep(post_sweep_delay)
                self._secondary_voltages = self._read_secondary_buffer(
                    self._secondary_nanovoltmeter,
                    n_points,
                    post_sweep_delay=post_sweep_delay,
                )
            self._smu.set_trace_feed_continuous_never()
            self._smu.check_error_queue()
        except Exception:
            try:
                self._smu.abort()
                if self._secondary_nanovoltmeter is not None:
                    self._secondary_nanovoltmeter.abort()
                self._smu.safe_output_off()
            except _CLEANUP_EXCEPTIONS:
                pass
            raise
        if records is None:
            raise RuntimeError("Sweep completed without buffered readings.")
        return records

    @staticmethod
    def _read_secondary_buffer(
        meter: Nanovoltmeter,
        count: int,
        *,
        post_sweep_delay: float,
    ) -> tuple[float, ...]:
        """Read a complete secondary buffer, allowing its final value to settle."""
        deadline = time.monotonic() + max(_TIMEOUT_MIN / 2.0, post_sweep_delay * 4.0)
        while True:
            readings = meter.read_buffer(count=count)
            if len(readings) == count:
                return readings
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"Secondary nanovoltmeter returned {len(readings)} readings but "
                    f"expected {count}."
                )
            time.sleep(_SECONDARY_READ_POLL)

    def _measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Acquire the sweep and return a single multicolumn trace."""
        records = self._acquire_buffer_records(parameters)
        if self._sweep_values is None:
            raise RuntimeError("Sweep completed without an active sweep definition.")

        current, voltage, resistance, power, timestamp = self._records_to_arrays(
            records, self._sweep_values
        )
        response_name = "Resistance"
        response_unit = "Ω"
        response_symbol = "R"
        if self._differential_mode:
            if self._nominal_sweep_values is None:
                raise RuntimeError("Differential sweep completed without nominal scan values.")
            reduced = reduce_differential_readings(
                np.asarray(self._nominal_sweep_values),
                voltage,
                self.eval_float(self._delta_current),
                conductance=self._differential_conductance,
            )
            current = reduced.current
            voltage = reduced.voltage
            resistance = reduced.response
            power = reduced.power
            if self._differential_conductance:
                response_name = "Conductance"
                response_unit = "S"
                response_symbol = "G"
            x_arr = reduced.current
        else:
            x_arr = np.asarray(self._sweep_values, dtype=float)

        columns = {
            "x": x_arr,
            "Current": current,
            "Voltage": voltage,
            response_name: resistance,
            "Power": power,
            "Timestamp": timestamp,
        }
        column_roles = {
            "Current": COLUMN_ROLE_Y
            if self._source_mode is SweepSourceMode.VOLTAGE
            else COLUMN_ROLE_Z,
            "Voltage": COLUMN_ROLE_Y
            if self._source_mode is SweepSourceMode.CURRENT
            else COLUMN_ROLE_Z,
            response_name: COLUMN_ROLE_Z,
            "Power": COLUMN_ROLE_Z,
            "Timestamp": COLUMN_ROLE_Z,
        }
        names = {
            "x": self.x_label,
            "Current": "Current",
            "Voltage": "Voltage",
            response_name: response_name,
            "Power": "Power",
            "Timestamp": "Timestamp",
        }
        units = {
            "x": self.x_units,
            "Current": "A",
            "Voltage": "V",
            response_name: response_unit,
            "Power": "W",
            "Timestamp": "s",
        }
        if self._secondary_enabled:
            secondary_voltage = np.asarray(self._secondary_voltages or (), dtype=float)
            if len(secondary_voltage) != len(self._sweep_values):
                raise RuntimeError(
                    "Secondary nanovoltmeter returned an unexpected number of readings."
                )
            if self._differential_mode:
                assert self._nominal_sweep_values is not None
                secondary_reduced = reduce_differential_readings(
                    np.asarray(self._nominal_sweep_values),
                    secondary_voltage,
                    self.eval_float(self._delta_current),
                    conductance=self._differential_conductance,
                )
                secondary_voltage = secondary_reduced.voltage
                secondary_resistance = secondary_reduced.response
                secondary_power = secondary_reduced.power
            else:
                with np.errstate(invalid="ignore", divide="ignore"):
                    secondary_resistance = np.where(
                        np.abs(current) > 1e-30,
                        secondary_voltage / current,
                        float("nan"),
                    )
                secondary_power = current * secondary_voltage
            prefix = self._secondary_prefix.strip() or "secondary"
            for column, values, unit, role in zip(
                (f"{prefix} V", f"{prefix} {response_symbol}", f"{prefix} P"),
                (secondary_voltage, secondary_resistance, secondary_power),
                ("V", response_unit, "W"),
                (COLUMN_ROLE_Y, COLUMN_ROLE_Z, COLUMN_ROLE_Z),
                strict=True,
            ):
                columns[column] = values
                column_roles[column] = role
                names[column] = column
                units[column] = unit
        df = pd.DataFrame(columns)
        return {"IV": TraceData(df=df, column_roles=column_roles, names=names, units=units)}

    def _records_to_arrays(
        self,
        records: tuple[Any, ...],
        sweep_values: tuple[float, ...],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Convert structured buffer records into NumPy arrays."""
        n_points = len(sweep_values)
        if len(records) != n_points:
            raise RuntimeError(
                f"Expected {n_points} buffered readings but received {len(records)}."
            )

        voltage = np.array(
            [
                float(record.voltage) if record.voltage is not None else float("nan")
                for record in records
            ],
            dtype=float,
        )
        current = np.array(
            [
                float(record.current) if record.current is not None else float("nan")
                for record in records
            ],
            dtype=float,
        )
        resistance = np.array(
            [
                float(record.resistance) if record.resistance is not None else float("nan")
                for record in records
            ],
            dtype=float,
        )
        power = voltage * current
        if np.isnan(resistance).all():
            with np.errstate(invalid="ignore", divide="ignore"):
                resistance = np.where(np.abs(current) > 1e-30, voltage / current, float("nan"))
        raw_time = [
            float(record.time) if record.time is not None else float("nan") for record in records
        ]
        timestamp = np.array(raw_time, dtype=float)
        if np.isnan(timestamp).all():
            point_time = (
                self._nplc * _LINE_PERIOD_50HZ
                + self.eval_float(self._source_delay)
                + self.eval_float(self._trigger_delay)
            )
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
        if self._secondary_nanovoltmeter is not None:
            try:
                self._secondary_nanovoltmeter.abort()
            except _CLEANUP_EXCEPTIONS:
                pass
            try:
                self._secondary_nanovoltmeter.disconnect()
            except _CLEANUP_EXCEPTIONS:
                pass
        self._smu = None
        self._secondary_nanovoltmeter = None
        self._secondary_voltages = None
        self._sweep_values = None
        self._nominal_sweep_values = None
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
                "differential_mode": self._differential_mode,
            }
        )
        if self._differential_mode:
            data["differential_conductance"] = self._differential_conductance
            data["delta_current"] = self._delta_current
        secondary: dict[str, Any] = {"enabled": self._secondary_enabled}
        if self._secondary_enabled:
            secondary.update(
                {
                    "driver": self._secondary_driver,
                    "resource": self._secondary_resource,
                    "prefix": self._secondary_prefix.strip() or "secondary",
                    "nplc": self._secondary_nplc,
                    "voltage_range": self._secondary_voltage_range,
                    "filter_type": self._secondary_filter_type.lower(),
                    "filter_count": self._secondary_filter_count,
                    "trigger_delay": self._secondary_trigger_delay,
                    "line_sync": self._secondary_line_sync,
                    "autozero": self._secondary_autozero,
                    "analog_filter": self._secondary_analog_filter,
                    "relative_enabled": self._secondary_relative_enabled,
                    "relative_value": self._secondary_relative_value,
                    "digits": self._secondary_digits,
                }
            )
        data["secondary_nanovoltmeter"] = secondary
        return data

    def _restore_from_json(self, data: dict) -> None:
        """Restore plugin state from serialised data."""
        super()._restore_from_json(data)
        self._resource = str(data.get("resource", self._resource))
        self._source_mode = SweepSourceMode(str(data.get("source_mode", self._source_mode.value)))
        self._compliance_mode = ComplianceMode(
            str(data.get("compliance_mode", self._compliance_mode.value))
        )
        self._compliance = data.get("compliance", self._compliance)
        self._compliance_resistance = data.get(
            "compliance_resistance", self._compliance_resistance
        )
        self._nplc = float(data.get("nplc", self._nplc))
        self._source_delay = data.get("source_delay", self._source_delay)
        self._trigger_delay = data.get("trigger_delay", self._trigger_delay)
        self._enable_output_during_measurement = bool(
            data.get("enable_output_during_measurement", self._enable_output_during_measurement)
        )
        self._trigger_routing = TriggerRouting(
            str(data.get("trigger_routing", self._trigger_routing.value))
        )
        self._trigger_count_override = int(
            data.get("trigger_count_override", self._trigger_count_override)
        )
        self._arm_count = int(data.get("arm_count", self._arm_count))
        self._timer_interval = data.get("timer_interval", self._timer_interval)
        self._enable_trigger_out = bool(data.get("enable_trigger_out", self._enable_trigger_out))
        self._trigger_out_line = int(data.get("trigger_out_line", self._trigger_out_line))
        self._trigger_in_line = int(data.get("trigger_in_line", self._trigger_in_line))
        self._source_range_mode = RangeMode(
            str(data.get("source_range_mode", self._source_range_mode.value))
        )
        self._source_range = data.get("source_range", self._source_range)
        self._sense_range_mode = RangeMode(
            str(data.get("sense_range_mode", self._sense_range_mode.value))
        )
        self._sense_range = data.get("sense_range", self._sense_range)
        self._connection_mode = ConnectionMode(
            str(data.get("connection_mode", self._connection_mode.value))
        )
        self._terminal_mode = TerminalMode(
            str(data.get("terminal_mode", self._terminal_mode.value))
        )
        self._filter_enabled = bool(data.get("filter_enabled", self._filter_enabled))
        self._filter_count = int(data.get("filter_count", self._filter_count))
        self._filter_type = FilterType(str(data.get("filter_type", self._filter_type.value)))
        self._median_filter_enabled = bool(
            data.get("median_filter_enabled", self._median_filter_enabled)
        )
        self._differential_mode = bool(data.get("differential_mode", self._differential_mode))
        if self._differential_mode:
            self._differential_conductance = bool(
                data.get("differential_conductance", self._differential_conductance)
            )
            self._delta_current = data.get("delta_current", self._delta_current)
        secondary = data.get("secondary_nanovoltmeter", {})
        if not isinstance(secondary, dict):
            return
        self._secondary_enabled = bool(secondary.get("enabled", False))
        if not self._secondary_enabled:
            return
        driver = str(secondary.get("driver", self._secondary_driver))
        if driver in NANOVOLTMETER_DRIVERS:
            self._secondary_driver = driver
        self._secondary_resource = str(secondary.get("resource", self._secondary_resource))
        self._secondary_prefix = (
            str(secondary.get("prefix", self._secondary_prefix)).strip() or "secondary"
        )
        self._secondary_nplc = float(secondary.get("nplc", self._secondary_nplc))
        self._secondary_voltage_range = float(
            secondary.get("voltage_range", self._secondary_voltage_range)
        )
        capabilities = NANOVOLTMETER_DRIVERS[self._secondary_driver].CAPABILITIES
        filter_type = str(secondary.get("filter_type", self._secondary_filter_type)).upper()
        self._secondary_filter_type = (
            filter_type
            if filter_type in capabilities.filter_types
            else capabilities.default_filter_type or capabilities.filter_types[0]
        )
        self._secondary_filter_count = int(
            secondary.get("filter_count", self._secondary_filter_count)
        )
        self._secondary_trigger_delay = secondary.get(
            "trigger_delay", self._secondary_trigger_delay
        )
        self._secondary_line_sync = bool(secondary.get("line_sync", self._secondary_line_sync))
        self._secondary_autozero = bool(secondary.get("autozero", self._secondary_autozero))
        self._secondary_analog_filter = bool(
            secondary.get("analog_filter", self._secondary_analog_filter)
        )
        self._secondary_relative_enabled = bool(
            secondary.get("relative_enabled", self._secondary_relative_enabled)
        )
        self._secondary_relative_value = secondary.get(
            "relative_value", self._secondary_relative_value
        )
        self._secondary_digits = int(secondary.get("digits", self._secondary_digits))

    def _plugin_config_tabs(self) -> QWidget:
        """Return the plugin settings widget."""
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(4, 4, 4, 4)

        tab_widget = FontAwareTabWidget()
        root_layout.addWidget(tab_widget)

        basic_page = QWidget()
        basic_layout = QVBoxLayout(basic_page)
        basic_layout.setContentsMargins(0, 0, 0, 0)
        conn_group = QGroupBox("Connection")
        conn_form = QFormLayout(conn_group)
        resource_combo = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        resource_combo.setCurrentText(self._resource)
        resource_combo.currentTextChanged.connect(
            lambda text: setattr(self, "_resource", text.strip())
        )
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
            "Compliance current:"
            if self._source_mode is SweepSourceMode.VOLTAGE
            else "Compliance voltage:"
        )
        compliance_mode_combo = QComboBox()
        compliance_mode_combo.addItem("Fixed limit", ComplianceMode.FIXED)
        compliance_mode_combo.addItem("Resistance-derived", ComplianceMode.RESISTANCE)
        compliance_mode_combo.setCurrentIndex(
            0 if self._compliance_mode is ComplianceMode.FIXED else 1
        )

        compliance_label = QLabel(compliance_text)
        compliance_sb = SISpinBox(
            allow_expressions=True,
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
        compliance_r_sb = SISpinBox(
            suffix="Ω", value=self._compliance_resistance, allow_expressions=True
        )
        compliance_r_sb.setMinimum(1e-9)
        compliance_r_sb.setMaximum(1e12)
        compliance_r_sb.valueChanged.connect(
            lambda value: setattr(self, "_compliance_resistance", value)
        )
        compliance_r_sb.setVisible(self._compliance_mode is ComplianceMode.RESISTANCE)
        compliance_r_label.setVisible(self._compliance_mode is ComplianceMode.RESISTANCE)

        def _on_mode_changed(index: int) -> None:
            self._source_mode = mode_combo.itemData(index)
            current_mode = self._source_mode is SweepSourceMode.CURRENT
            differential_enabled.setEnabled(current_mode)
            if not current_mode:
                differential_enabled.setChecked(False)
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
            if math.isclose(
                float(nplc_combo.itemData(idx)), self._nplc, rel_tol=0.0, abs_tol=1e-12
            ):
                nplc_index = idx
                break
        nplc_combo.setCurrentIndex(nplc_index)
        nplc_combo.currentIndexChanged.connect(
            lambda idx: setattr(self, "_nplc", float(nplc_combo.itemData(idx)))
        )

        source_delay_sb = SISpinBox(
            suffix="s", value=self._source_delay, allow_expressions=True
        )
        source_delay_sb.setMinimum(0.0)
        source_delay_sb.setMaximum(9999.0)
        source_delay_sb.valueChanged.connect(lambda value: setattr(self, "_source_delay", value))

        trigger_delay_sb = SISpinBox(
            suffix="s", value=self._trigger_delay, allow_expressions=True
        )
        trigger_delay_sb.setMinimum(0.0)
        trigger_delay_sb.setMaximum(9999.0)
        trigger_delay_sb.valueChanged.connect(lambda value: setattr(self, "_trigger_delay", value))

        output_chk = QCheckBox()
        output_chk.setChecked(self._enable_output_during_measurement)
        output_chk.toggled.connect(
            lambda state: setattr(self, "_enable_output_during_measurement", state)
        )

        differential_enabled = QCheckBox("Enable alternating delta-current mode")
        differential_enabled.setObjectName("differential_mode")
        differential_enabled.setChecked(self._differential_mode)
        differential_enabled.setEnabled(self._source_mode is SweepSourceMode.CURRENT)
        differential_conductance = QCheckBox(
            "Report differential conductance (otherwise differential resistance)"
        )
        differential_conductance.setObjectName("differential_conductance")
        differential_conductance.setChecked(self._differential_conductance)
        differential_conductance.setEnabled(self._differential_mode)
        delta_current = SISpinBox(
            suffix="A", value=self._delta_current, allow_expressions=True
        )
        delta_current.setObjectName("delta_current")
        delta_current.setMinimum(1e-15)
        delta_current.setMaximum(10.0)
        delta_current.setEnabled(self._differential_mode)

        def _on_differential_mode_toggled(enabled: bool) -> None:
            self._differential_mode = enabled
            differential_conductance.setEnabled(enabled)
            delta_current.setEnabled(enabled)

        differential_enabled.toggled.connect(_on_differential_mode_toggled)
        differential_conductance.toggled.connect(
            lambda enabled: setattr(self, "_differential_conductance", enabled)
        )
        delta_current.valueChanged.connect(lambda value: setattr(self, "_delta_current", value))

        src_form.addRow("Sweep mode:", mode_combo)
        src_form.addRow("Compliance mode:", compliance_mode_combo)
        src_form.addRow(compliance_label, compliance_sb)
        src_form.addRow(compliance_r_label, compliance_r_sb)
        src_form.addRow("Integration time (NPLC):", nplc_combo)
        src_form.addRow("Source delay:", source_delay_sb)
        src_form.addRow("Trigger delay:", trigger_delay_sb)
        src_form.addRow("Enable output during sweep:", output_chk)
        src_form.addRow("Differential mode:", differential_enabled)
        src_form.addRow("Delta current:", delta_current)
        src_form.addRow("Differential result:", differential_conductance)
        basic_layout.addWidget(src_group)

        ranges_group = QGroupBox("Ranges")
        ranges_form = QFormLayout(ranges_group)

        source_range_mode_combo = QComboBox()
        source_range_mode_combo.addItem("Auto", RangeMode.AUTO)
        source_range_mode_combo.addItem("Fixed", RangeMode.FIXED)
        source_range_mode_combo.setCurrentIndex(
            0 if self._source_range_mode is RangeMode.AUTO else 1
        )
        source_range_sb = SISpinBox(
            allow_expressions=True,
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
            allow_expressions=True,
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
        trig_combo.setObjectName("trigger_routing")
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

        timer_sb = SISpinBox(
            suffix="s", value=self._timer_interval, allow_expressions=True
        )
        timer_sb.setMinimum(1e-6)
        timer_sb.setMaximum(9999.0)
        timer_sb.setEnabled(self._trigger_routing is TriggerRouting.TIMER)

        trig_in_sb = QSpinBox()
        trig_in_sb.setObjectName("trigger_in_line")
        trig_in_sb.setMinimum(1)
        trig_in_sb.setMaximum(6)
        trig_in_sb.setValue(self._trigger_in_line)
        trig_in_sb.setEnabled(
            self._trigger_routing in (TriggerRouting.EXTERNAL, TriggerRouting.TRIGGER_LINK)
        )

        trig_out_chk = QCheckBox()
        trig_out_chk.setObjectName("enable_trigger_out")
        trig_out_chk.setChecked(self._enable_trigger_out)

        trig_out_sb = QSpinBox()
        trig_out_sb.setObjectName("trigger_out_line")
        trig_out_sb.setMinimum(1)
        trig_out_sb.setMaximum(6)
        trig_out_sb.setValue(self._trigger_out_line)
        trig_out_sb.setEnabled(self._enable_trigger_out)

        def _on_trigger_changed(index: int) -> None:
            self._trigger_routing = trig_combo.itemData(index)
            timer_sb.setEnabled(self._trigger_routing is TriggerRouting.TIMER)
            trig_in_sb.setEnabled(
                self._trigger_routing in (TriggerRouting.EXTERNAL, TriggerRouting.TRIGGER_LINK)
            )

        def _on_trigger_out_toggled(state: bool) -> None:
            self._enable_trigger_out = state
            trig_out_sb.setEnabled(state)

        trig_combo.currentIndexChanged.connect(_on_trigger_changed)
        trigger_count_sb.valueChanged.connect(
            lambda value: setattr(self, "_trigger_count_override", value)
        )
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
        connection_combo.setCurrentIndex(
            0 if self._connection_mode is ConnectionMode.TWO_WIRE else 1
        )
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
        median_filter_chk.toggled.connect(
            lambda state: setattr(self, "_median_filter_enabled", state)
        )

        filter_form.addRow("Enable digital filter:", filter_enabled_chk)
        filter_form.addRow("Digital filter count:", filter_count_sb)
        filter_form.addRow("Digital filter type:", filter_type_combo)
        filter_form.addRow("Enable median filter:", median_filter_chk)
        advanced_layout.addWidget(filter_group)
        advanced_layout.addStretch()

        tab_widget.addTab(basic_page, "Basic")
        tab_widget.addTab(advanced_page, "Advanced")
        tab_widget.addTab(
            self._secondary_config_page(
                trigger_routing=trig_combo,
                trigger_input=trig_in_sb,
                trigger_output_enabled=trig_out_chk,
                trigger_output=trig_out_sb,
            ),
            "Secondary nanovoltmeter",
        )
        return root

    def _secondary_config_page(
        self,
        *,
        trigger_routing: QComboBox,
        trigger_input: QSpinBox,
        trigger_output_enabled: QCheckBox,
        trigger_output: QSpinBox,
    ) -> QWidget:
        """Build the capability-driven secondary nanovoltmeter settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)

        enabled = QCheckBox("Use a second nanovoltmeter")
        enabled.setObjectName("secondary_enabled")
        enabled.setChecked(self._secondary_enabled)
        layout.addWidget(enabled)

        controls = QGroupBox("Secondary nanovoltmeter")
        controls.setObjectName("secondary_controls")
        controls.setEnabled(self._secondary_enabled)
        form = QFormLayout(controls)

        driver = QComboBox()
        driver.setObjectName("secondary_driver")
        for key, label in NANOVOLTMETER_DRIVER_LABELS.items():
            driver.addItem(label, key)
        driver.setCurrentIndex(driver.findData(self._secondary_driver))

        resource = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        resource.setObjectName("secondary_resource")
        resource.setCurrentText(self._secondary_resource)
        form.addRow("Driver:", driver)
        form.addRow("GPIB resource:", resource)

        prefix = QLineEdit(self._secondary_prefix)
        prefix.setObjectName("secondary_prefix")
        form.addRow("Column prefix:", prefix)

        nplc = QComboBox()
        nplc.setObjectName("secondary_nplc")
        trigger_delay = SISpinBox(
            suffix="s", value=self._secondary_trigger_delay, allow_expressions=True
        )
        trigger_delay.setObjectName("secondary_trigger_delay")
        trigger_delay.setMinimum(0.0)
        trigger_delay.setMaximum(999.999)
        timing_row = QWidget()
        timing_layout = QHBoxLayout(timing_row)
        timing_layout.setContentsMargins(0, 0, 0, 0)
        timing_layout.addWidget(QLabel("NPLC:"))
        timing_layout.addWidget(nplc)
        timing_layout.addWidget(QLabel("Trigger delay:"))
        timing_layout.addWidget(trigger_delay)
        form.addRow("Timing:", timing_row)

        voltage_range = QComboBox()
        voltage_range.setObjectName("secondary_voltage_range")
        digits = QComboBox()
        digits.setObjectName("secondary_digits")
        input_row = QWidget()
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(QLabel("Range:"))
        input_layout.addWidget(voltage_range)
        input_layout.addWidget(QLabel("Digits:"))
        input_layout.addWidget(digits)
        form.addRow("Input:", input_row)

        autozero = QCheckBox("Autozero")
        autozero.setObjectName("secondary_autozero")
        autozero.setChecked(self._secondary_autozero)
        line_sync = QCheckBox("Line sync")
        line_sync.setObjectName("secondary_line_sync")
        line_sync.setChecked(self._secondary_line_sync)
        accuracy_row = QWidget()
        accuracy_layout = QHBoxLayout(accuracy_row)
        accuracy_layout.setContentsMargins(0, 0, 0, 0)
        accuracy_layout.addWidget(autozero)
        accuracy_layout.addWidget(line_sync)
        form.addRow("Accuracy:", accuracy_row)

        filter_type = QComboBox()
        filter_type.setObjectName("secondary_filter_type")
        filter_count = QSpinBox()
        filter_count.setObjectName("secondary_filter_count")
        filter_count.setRange(1, 100)
        filter_count.setValue(self._secondary_filter_count)
        filter_row = QWidget()
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.addWidget(filter_type)
        filter_count_label = QLabel("Count:")
        filter_layout.addWidget(filter_count_label)
        filter_layout.addWidget(filter_count)
        form.addRow("Digital filter:", filter_row)

        analog_filter = QCheckBox()
        analog_filter.setObjectName("secondary_analog_filter")
        analog_filter.setChecked(self._secondary_analog_filter)
        form.addRow("Analogue filter:", analog_filter)

        relative_enabled = QCheckBox("Enabled")
        relative_enabled.setObjectName("secondary_relative_enabled")
        relative_enabled.setChecked(self._secondary_relative_enabled)
        relative_value = SISpinBox(
            suffix="V", value=self._secondary_relative_value, allow_expressions=True
        )
        relative_value.setObjectName("secondary_relative_value")
        relative_row = QWidget()
        relative_layout = QHBoxLayout(relative_row)
        relative_layout.setContentsMargins(0, 0, 0, 0)
        relative_layout.addWidget(relative_enabled)
        relative_layout.addWidget(QLabel("Level:"))
        relative_layout.addWidget(relative_value)
        form.addRow("Relative mode:", relative_row)

        trigger_note = QLabel(
            "When enabled, the 2400 bypasses the first trigger event, waits for "
            f"measurement-complete on Trigger Link line {self._trigger_in_line}, and "
            f"emits each source event on line {self._trigger_out_line}. Lines are set "
            "on the Advanced page."
        )
        trigger_note.setWordWrap(True)
        form.addRow("Trigger handshake:", trigger_note)
        layout.addWidget(controls)
        layout.addStretch()

        def apply_capabilities() -> None:
            capabilities = NANOVOLTMETER_DRIVERS[self._secondary_driver].CAPABILITIES
            for combo in (nplc, voltage_range, digits, filter_type):
                combo.blockSignals(True)
            nplc.clear()
            for nplc_value in capabilities.nplc_values:
                nplc.addItem(f"{nplc_value:g} PLC", nplc_value)
            if self._secondary_nplc not in capabilities.nplc_values:
                self._secondary_nplc = capabilities.default_nplc or capabilities.nplc_values[0]
            nplc.setCurrentIndex(nplc.findData(self._secondary_nplc))

            voltage_range.clear()
            voltage_range.addItem("Auto", 0.0)
            for range_value in capabilities.fixed_voltage_ranges:
                voltage_range.addItem(f"{range_value:g} V", range_value)
            if self._secondary_voltage_range not in (
                0.0,
                *capabilities.fixed_voltage_ranges,
            ):
                self._secondary_voltage_range = 0.0
            voltage_range.setCurrentIndex(voltage_range.findData(self._secondary_voltage_range))

            digits.clear()
            for digit_value in capabilities.digit_values:
                digits.addItem(f"{digit_value}.5 digits", digit_value)
            if self._secondary_digits not in capabilities.digit_values:
                self._secondary_digits = (
                    capabilities.default_digits or capabilities.digit_values[-1]
                )
            digits.setCurrentIndex(digits.findData(self._secondary_digits))

            filter_type.clear()
            for filter_value in capabilities.filter_types:
                filter_type.addItem(filter_value.title(), filter_value)
            if self._secondary_filter_type not in capabilities.filter_types:
                self._secondary_filter_type = (
                    capabilities.default_filter_type or capabilities.filter_types[0]
                )
            filter_type.setCurrentIndex(filter_type.findData(self._secondary_filter_type))
            for combo in (nplc, voltage_range, digits, filter_type):
                combo.blockSignals(False)

            autozero.setEnabled(capabilities.supports_autozero)
            line_sync.setEnabled(capabilities.supports_line_sync)
            filter_count_label.setEnabled(capabilities.supports_filter_count)
            filter_count.setEnabled(
                capabilities.supports_filter_count and self._secondary_filter_type != "OFF"
            )
            analog_filter.setEnabled(capabilities.supports_analog_filter)
            relative_enabled.setEnabled(capabilities.supports_relative)
            relative_value.setEnabled(
                capabilities.supports_relative and self._secondary_relative_enabled
            )
            if capabilities.relative_limits is not None:
                relative_value.setMinimum(capabilities.relative_limits[0])
                relative_value.setMaximum(capabilities.relative_limits[1])

        def set_enabled(state: bool) -> None:
            self._secondary_enabled = state
            trigger_routing.setEnabled(not state)
            trigger_output_enabled.setEnabled(not state)
            trigger_input.setEnabled(
                state
                or self._trigger_routing in (TriggerRouting.EXTERNAL, TriggerRouting.TRIGGER_LINK)
            )
            trigger_output.setEnabled(state or self._enable_trigger_out)

        enabled.toggled.connect(set_enabled)
        enabled.toggled.connect(controls.setEnabled)

        def set_driver(index: int) -> None:
            self._secondary_driver = driver.itemData(index)
            apply_capabilities()

        def set_filter(index: int) -> None:
            self._secondary_filter_type = filter_type.itemData(index)
            capabilities = NANOVOLTMETER_DRIVERS[self._secondary_driver].CAPABILITIES
            filter_count.setEnabled(
                capabilities.supports_filter_count and self._secondary_filter_type != "OFF"
            )

        driver.currentIndexChanged.connect(set_driver)
        resource.currentTextChanged.connect(
            lambda text: setattr(self, "_secondary_resource", text.strip())
        )
        prefix.textChanged.connect(lambda text: setattr(self, "_secondary_prefix", text.strip()))
        nplc.currentIndexChanged.connect(
            lambda index: setattr(self, "_secondary_nplc", nplc.itemData(index))
        )
        trigger_delay.valueChanged.connect(
            lambda value: setattr(self, "_secondary_trigger_delay", value)
        )
        voltage_range.currentIndexChanged.connect(
            lambda index: setattr(self, "_secondary_voltage_range", voltage_range.itemData(index))
        )
        digits.currentIndexChanged.connect(
            lambda index: setattr(self, "_secondary_digits", digits.itemData(index))
        )
        autozero.toggled.connect(lambda state: setattr(self, "_secondary_autozero", state))
        line_sync.toggled.connect(lambda state: setattr(self, "_secondary_line_sync", state))
        filter_type.currentIndexChanged.connect(set_filter)
        filter_count.valueChanged.connect(
            lambda value: setattr(self, "_secondary_filter_count", value)
        )
        analog_filter.toggled.connect(
            lambda state: setattr(self, "_secondary_analog_filter", state)
        )
        relative_enabled.toggled.connect(
            lambda state: setattr(self, "_secondary_relative_enabled", state)
        )
        relative_enabled.toggled.connect(relative_value.setEnabled)
        relative_value.valueChanged.connect(
            lambda value: setattr(self, "_secondary_relative_value", value)
        )
        set_enabled(self._secondary_enabled)
        apply_capabilities()
        return page

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
            "<p>An optional secondary nanovoltmeter uses a hardware handshake: the "
            "2400 bypasses the first trigger event, emits each source event on Trigger "
            "Link output line 2 by default, and waits for measurement-complete on input "
            "line 1 before advancing. Its voltage readings add prefixed V, R, and P "
            "columns to the trace.</p>"
            "<p>Compliance can be specified as a fixed current/voltage limit or "
            "derived from a resistance threshold.</p>"
        )
