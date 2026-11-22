"""Single-reading command for Keithley 2000 and 2700 multimeters."""

from __future__ import annotations

import math
from typing import Any

from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QSpinBox, QVBoxLayout, QWidget

from stoner_measurement.core.plugin_outputs import PluginOutputs, ScalarOutput
from stoner_measurement.core.validation import ValidationError, validate_expression
from stoner_measurement.instruments.dmm import DmmFunction
from stoner_measurement.instruments.keithley import Keithley2000, Keithley2700
from stoner_measurement.instruments.transport import GpibTransport
from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.ui.widgets import FILTER_GPIB, SISpinBox, VisaResourceComboBox

DMM_DRIVERS = {"keithley_2000": Keithley2000, "keithley_2700": Keithley2700}
DMM_CHANNELS = {
    DmmFunction.VOLT_DC: ("DC Voltage", "V"),
    DmmFunction.VOLT_AC: ("AC Voltage", "V"),
    DmmFunction.CURR_DC: ("DC Current", "A"),
    DmmFunction.CURR_AC: ("AC Current", "A"),
    DmmFunction.RES: ("Resistance", "Ω"),
    DmmFunction.FRES: ("Four-wire Resistance", "Ω"),
    DmmFunction.FREQ: ("Frequency", "Hz"),
    DmmFunction.PER: ("Period", "s"),
    DmmFunction.TEMP: ("Temperature", "K"),
}
_NUMERIC_SETTINGS = {
    "input_range": (1e-12, 1e12),
    "nplc": (0.01, 10.0),
    "gate_time": (0.01, 1.0),
    "trigger_delay": (0.0, 999999.999),
    "timeout": (0.01, 86400.0),
}
_SAVED_SETTINGS = (
    "driver",
    "resource",
    "function",
    "autorange",
    "input_range",
    "nplc",
    "filter_enabled",
    "filter_count",
    "filter_type",
    "ac_bandwidth",
    "gate_time",
    "trigger_delay",
    "timeout",
)


class ReadMultimeterCommand(CommandPlugin):
    """Take one fresh reading from a Keithley 2000 or 2700 multimeter.

    Add **Keithleys → Read Multimeter** beneath a scan or after a set command.
    **General** selects the model, GPIB resource and measurement function: DC
    or AC voltage/current, two- or four-wire resistance, frequency, period or
    temperature. The selected reading is a scalar output with its SI unit,
    also available as ``instance.value``. Temperature uses kelvin and the
    instrument's existing temperature sensor configuration.

    General also provides range/autorange, integration in power-line cycles,
    averaging enable/count/type, AC bandwidth, frequency/period gate time,
    trigger delay and communication timeout. Controls follow the function:
    temperature has no manual range, frequency/period use gate time rather
    than NPLC or averaging, and AC NPLC applies only at 300 Hz bandwidth.
    Numeric expressions are evaluated at configuration time; inactive controls
    are ignored. Averaging can combine conversions into the one returned
    reading. Immediate triggering and a sample count of one are automatic.

    Each execution also publishes the applicable numeric **Range**,
    **Autorange**, **NPLC**, **Filter Enabled**, **Filter Count**, **Filter Type**,
    **AC Bandwidth**, **Gate Time**, **Trigger Delay** and **Timeout** outputs.
    Settings are queried after the measurement, so Range follows autoranging.
    Filter Type is 0 for repeating and 1 for moving; booleans are 0 or 1.
    Timeout is the local transport timeout. Settings and readings can be used
    by scan data collection, Plot Points, Save and downstream expressions.

    The plugin owns its session: startup connects/configures, every execution
    requests a fresh conversion, and cleanup aborts/closes the connection.
    Successful cleanup retains the last reading and settings; a failed read
    clears them. Reconfigure may defer setup. The 2700 is used only as a
    multimeter with its currently selected input terminals. No reset, relay,
    route, scan-list or channel-list commands are sent. Put it in ordinary
    DMM mode before use; scanner/switching support is deferred. **About**
    documents these controls and outputs.

    Attributes:
        driver (str):
            ``keithley_2000`` (default) or ``keithley_2700``.
        resource (str):
            GPIB resource, initially ``GPIB0::16::INSTR``.
        function (str):
            SCPI measurement function, initially ``VOLT:DC``.
        autorange (bool):
            Automatic range selection, initially True.
        input_range (float | str):
            Fixed range in the function's SI unit, or expression.
        nplc (float | str):
            Integration in PLC, 0.01..10; initially 1.0.
        filter_enabled (bool):
            Whether to average conversions, initially False.
        filter_count (int):
            Averaging count, 1..100; initially 10.
        filter_type (str):
            ``REP`` (repeating, default) or ``MOV`` (moving).
        ac_bandwidth (float):
            AC lower bandwidth in Hz: 3, 30 or 300 (default).
        gate_time (float | str):
            Frequency/period gate time in seconds, 0.01..1; initially 0.1.
        trigger_delay (float | str):
            Conversion delay in seconds, initially zero.
        timeout (float | str):
            Communication timeout in seconds, initially 30.
        value (float):
            Last reading, initially NaN; not persisted.
        settings_readback (dict[str, float]):
            Queried numeric settings from the last execution, not persisted.
        instance_name (str):
            Inherited Python identifier in scripts and QtConsole.
        comment (str):
            Inherited optional step note.
        sequence_engine (SequenceEngine | None):
            Inherited owning engine and live expression namespace.
        has_lifecycle (bool):
            True: sequence setup and cleanup manage this session.

    Keyword Parameters:
        parent (QObject | None): Optional Qt parent object.

    Examples:
        With an existing sequence instance named ``read_multimeter``, edit
        settings before running and inspect the last completed reading::

            read_multimeter.driver = "keithley_2700"
            read_multimeter.function = "FRES"
            read_multimeter.nplc = "integration_cycles"
            read_multimeter.value
            read_multimeter.settings_readback
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.driver = "keithley_2000"
        self.resource = "GPIB0::16::INSTR"
        self.function = "VOLT:DC"
        self.autorange = True
        self.input_range: float | str = 10.0
        self.nplc: float | str = 1.0
        self.filter_enabled = False
        self.filter_count = 10
        self.filter_type = "REP"
        self.ac_bandwidth = 300.0
        self.gate_time: float | str = 0.1
        self.trigger_delay: float | str = 0.0
        self.timeout: float | str = 30.0
        self.value = math.nan
        self.settings_readback: dict[str, float] = {}
        self._meter: Keithley2000 | None = None
        self._connected_driver: str | None = None
        self._configured_function: str | None = None
        self._apply_initial_config()

    @property
    def name(self) -> str:
        return "Read Multimeter"

    @property
    def has_lifecycle(self) -> bool:
        return True

    def _active_numeric_settings(self) -> list[str]:
        function = DmmFunction(self.function)
        names = ["trigger_delay", "timeout"]
        if function in Keithley2000.RANGED_FUNCTIONS and not self.autorange:
            names.append("input_range")
        if Keithley2000.uses_nplc(function, self.ac_bandwidth):
            names.append("nplc")
        if function in Keithley2000.GATED_FUNCTIONS:
            names.append("gate_time")
        return names

    def validate(self) -> bool:
        """Check model, function and applicable literals/expressions without I/O."""
        if self.driver not in DMM_DRIVERS:
            raise ValidationError("Select a Keithley 2000 or 2700 driver.")
        try:
            function = DmmFunction(self.function)
        except ValueError as exc:
            raise ValidationError("Select a supported multimeter function.") from exc
        if not self.resource.strip():
            raise ValidationError("A multimeter GPIB resource is required.")
        if function in Keithley2000.AC_FUNCTIONS and self.ac_bandwidth not in (3.0, 30.0, 300.0):
            raise ValidationError("AC bandwidth must be 3, 30 or 300 Hz.")
        if function not in Keithley2000.GATED_FUNCTIONS:
            if self.filter_type not in ("REP", "MOV") or not 1 <= self.filter_count <= 100:
                raise ValidationError("Filter requires REP or MOV and a count of 1..100.")
        for name in self._active_numeric_settings():
            value = getattr(self, name)
            if isinstance(value, str):
                validate_expression(
                    value, self.engine_namespace, label=f"{self.instance_name} {name}"
                )
            else:
                self._check_numeric(name, float(value))
        return True

    @staticmethod
    def _check_numeric(name: str, value: float) -> None:
        lower, upper = _NUMERIC_SETTINGS[name]
        if not math.isfinite(value) or not lower <= value <= upper:
            raise ValidationError(f"Multimeter {name} must be between {lower:g} and {upper:g}.")

    def _clear_reading(self) -> None:
        self.value = math.nan
        self.settings_readback = {}

    def connect(self) -> None:
        """Connect and identify an owned meter, releasing partial connections."""
        self.validate()
        transport = GpibTransport.from_resource_string(self.resource, timeout=30.0)
        try:
            self._meter = DMM_DRIVERS[self.driver](transport)
            self._meter.connect()
            self._meter.confirm_identity()
        except Exception:
            self._meter = None
            transport.close()
            raise
        self._connected_driver = self.driver

    def configure(self) -> None:
        """Resolve runtime settings and configure one reading without scanner control."""
        self._configured_function = None
        self._clear_reading()
        if self._meter is None or self._connected_driver != self.driver:
            raise RuntimeError("Connect the selected multimeter model before configuring.")
        self.validate()
        values = {"input_range": 10.0, "nplc": 1.0, "gate_time": 0.1}
        for name in self._active_numeric_settings():
            values[name] = self.eval_float(getattr(self, name))
            self._check_numeric(name, values[name])
        self._meter.transport.timeout = values.pop("timeout")
        self._meter.configure_single_reading(
            DmmFunction(self.function),
            autorange=self.autorange,
            filter_enabled=self.filter_enabled,
            filter_count=self.filter_count,
            filter_type=self.filter_type,
            ac_bandwidth=self.ac_bandwidth,
            **values,
        )
        self._configured_function = self.function

    def execute(self) -> None:
        """Publish one fresh reading and its applicable numeric setting readbacks."""
        self._clear_reading()
        if self._meter is None or self._connected_driver != self.driver:
            raise RuntimeError("The selected multimeter is not connected.")
        if self._configured_function != self.function:
            raise RuntimeError("Reconfigure the multimeter for this measurement function.")
        value, settings = self._meter.read_single_snapshot(DmmFunction(self.function))
        self.value = float(value)
        self.settings_readback = settings

    def disconnect(self) -> None:
        """Abort and close this instance's session, retaining successful outputs."""
        meter, self._meter = self._meter, None
        self._connected_driver = self._configured_function = None
        if meter is not None:
            try:
                meter.abort()
            finally:
                meter.disconnect()

    def _setting_outputs(self) -> dict[str, tuple[str, str]]:
        function = DmmFunction(self.function)
        outputs = {"trigger_delay": ("Trigger Delay", "s"), "timeout": ("Timeout", "s")}
        if function in Keithley2000.RANGED_FUNCTIONS:
            outputs.update(range=("Range", DMM_CHANNELS[function][1]), autorange=("Autorange", ""))
        if Keithley2000.uses_nplc(function, self.ac_bandwidth):
            outputs["nplc"] = ("NPLC", "PLC")
        if function in Keithley2000.GATED_FUNCTIONS:
            outputs["gate_time"] = ("Gate Time", "s")
        else:
            outputs.update(
                filter_enabled=("Filter Enabled", ""),
                filter_count=("Filter Count", ""),
                filter_type=("Filter Type", ""),
            )
        if function in Keithley2000.AC_FUNCTIONS:
            outputs["ac_bandwidth"] = ("AC Bandwidth", "Hz")
        return outputs

    def declared_outputs(self) -> PluginOutputs:
        """Declare configured outputs and their physical units together."""
        var = self.instance_name
        label, unit = DMM_CHANNELS[DmmFunction(self.function)]
        outputs = PluginOutputs(values={f"{var}:{label}": ScalarOutput(f"{var}.value", unit)})
        for name, (label, unit) in self._setting_outputs().items():
            outputs.values[f"{var}:{label}"] = ScalarOutput(
                f"{var}.settings_readback.get({name!r}, float('nan'))", unit
            )
        return outputs

    def to_json(self) -> dict[str, Any]:
        """Persist editable settings, excluding sessions and acquired data."""
        data = super().to_json()
        data.update({name: getattr(self, name) for name in _SAVED_SETTINGS})
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore editable settings while retaining defaults for absent fields."""
        super()._restore_from_json(data)
        for name in _SAVED_SETTINGS:
            if name in data:
                setattr(self, name, data[name])

    def config_widget(self, parent=None) -> QWidget:
        """Build top-packed, function-aware multimeter controls."""
        page = QWidget(parent)
        layout = QVBoxLayout(page)
        form = QFormLayout()
        layout.addLayout(form)
        controls: dict[str, QWidget] = {}

        def combo(label: str, name: str, choices: dict) -> QComboBox:
            control = QComboBox()
            for value, text in choices.items():
                control.addItem(text, value)
            control.setCurrentIndex(control.findData(getattr(self, name)))
            control.currentIndexChanged.connect(
                lambda index: (setattr(self, name, control.itemData(index)), update_controls())
            )
            add(label, name, control)
            return control

        def add(label: str, name: str, control: QWidget) -> None:
            control.setObjectName(f"multimeter_{name}")
            controls[name] = control
            form.addRow(label, control)

        def check(label: str, name: str) -> None:
            control = QCheckBox()
            control.setChecked(getattr(self, name))
            control.toggled.connect(lambda value: (setattr(self, name, value), update_controls()))
            add(label, name, control)

        def number(label: str, name: str, unit: str = "") -> None:
            control = SISpinBox(value=getattr(self, name), suffix=unit, allow_expressions=True)
            control.setMinimum(_NUMERIC_SETTINGS[name][0])
            control.setMaximum(_NUMERIC_SETTINGS[name][1])
            control.valueChanged.connect(lambda value: setattr(self, name, value))
            add(label, name, control)

        combo(
            "Model:",
            "driver",
            {
                key: cls.__name__.replace("Keithley", "Keithley ")
                for key, cls in DMM_DRIVERS.items()
            },
        )
        resource = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        resource.setCurrentText(self.resource)
        resource.currentTextChanged.connect(lambda text: setattr(self, "resource", text.strip()))
        add("GPIB resource:", "resource", resource)
        combo(
            "Function:",
            "function",
            {item.value: label for item, (label, _) in DMM_CHANNELS.items()},
        )
        check("Autorange:", "autorange")
        number("Input range:", "input_range")
        number("Integration (PLC):", "nplc")
        check("Digital averaging:", "filter_enabled")
        count = QSpinBox()
        count.setRange(1, 100)
        count.setValue(self.filter_count)
        count.valueChanged.connect(lambda value: setattr(self, "filter_count", value))
        add("Filter count:", "filter_count", count)
        combo("Filter type:", "filter_type", {"REP": "Repeating", "MOV": "Moving"})
        combo("AC lower bandwidth:", "ac_bandwidth", {3.0: "3 Hz", 30.0: "30 Hz", 300.0: "300 Hz"})
        number("Frequency/period gate:", "gate_time", "s")
        number("Trigger delay:", "trigger_delay", "s")
        number("Communication timeout:", "timeout", "s")
        previous = (self.driver, self.function, self.ac_bandwidth)

        def update_controls() -> None:
            nonlocal previous
            function = DmmFunction(self.function)
            ranged = function in Keithley2000.RANGED_FUNCTIONS
            gated = function in Keithley2000.GATED_FUNCTIONS
            controls["autorange"].setEnabled(ranged)
            controls["input_range"].setEnabled(ranged and not self.autorange)
            controls["input_range"].setSuffix(DMM_CHANNELS[function][1])
            controls["nplc"].setEnabled(Keithley2000.uses_nplc(function, self.ac_bandwidth))
            controls["ac_bandwidth"].setEnabled(function in Keithley2000.AC_FUNCTIONS)
            controls["gate_time"].setEnabled(gated)
            controls["filter_enabled"].setEnabled(not gated)
            for name in ("filter_type", "filter_count"):
                controls[name].setEnabled(not gated and self.filter_enabled)
            current = (self.driver, self.function, self.ac_bandwidth)
            if current != previous:
                self._clear_reading()
            previous = current
            if self.sequence_engine is not None:
                self.sequence_engine.refresh_data_catalogs()

        update_controls()
        layout.addStretch()
        return page
