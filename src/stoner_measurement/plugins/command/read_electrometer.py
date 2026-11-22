"""Single-reading command for Keithley electrometers and picoammeters."""

from __future__ import annotations

import math
from typing import Any

from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QSpinBox, QVBoxLayout, QWidget

from stoner_measurement.core.plugin_outputs import PluginOutputs, ScalarOutput
from stoner_measurement.core.validation import ValidationError, validate_expression
from stoner_measurement.instruments.electrometer import ElectrometerFunction
from stoner_measurement.instruments.keithley import Keithley6485, Keithley6514, Keithley6517
from stoner_measurement.instruments.transport import GpibTransport
from stoner_measurement.plugins._electrometer import ELECTROMETER_DRIVERS, FUNCTION_CHANNELS
from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.ui.widgets import FILTER_GPIB, SISpinBox, VisaResourceComboBox

_NUMERIC_SETTINGS = {
    "input_range": (1e-15, 1e18),
    "nplc": (0.01, 10.0),
    "trigger_delay": (0.0, 999.999),
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
    "zero_check",
    "trigger_delay",
    "timeout",
)


class ReadElectrometerCommand(CommandPlugin):
    """Take one fresh Keithley electrometer or picoammeter reading.

    Use **Read Electrometer** inside a scan or after a set command to acquire
    one scalar measurement. Choose a Keithley 6485, 6514 or 6517 and its GPIB
    resource on **General**. The 6485 measures current; the 6514 and 6517 can
    instead measure voltage, resistance or charge. Each execution measures
    only the selected function and publishes **Current**, **Voltage**,
    **Resistance** or **Charge**, in A, V, Ω or C respectively. These outputs
    can be selected for scan data collection, Plot Points, Save or later
    expressions. The latest result is also available as ``instance.value``.

    The General page provides autorange or a fixed input range in the selected
    function's SI unit, integration time in power-line cycles (NPLC), digital
    averaging and its count, zero check, trigger delay and communication
    timeout in seconds. Fixed range, NPLC, delay and timeout accept expressions
    evaluated at configuration time in the engine namespace. A filter may
    average several conversions into the single returned reading. Zero check
    is off by default; enabling it measures the zero-checked input.

    The plugin owns its connection. Sequence startup connects and configures
    it; repeated executions trigger fresh readings without reconnecting.
    Immediate triggering, one trigger and one arm are configured automatically,
    and buffer storage is disabled. No external trigger wiring is required.
    Sequence cleanup aborts and closes the session, leaving the latest result
    available for inspection. A failed execution clears that result to NaN.
    Reconfigure can defer setup until the command is reached. **About**
    describes these settings and outputs.

    Attributes:
        driver (str):
            Driver identifier: ``keithley_6485`` (default), ``keithley_6514``
            or ``keithley_6517``.
        resource (str):
            VISA/GPIB resource, initially ``GPIB0::14::INSTR``.
        function (str):
            Measurement function: ``CURR`` (default), ``VOLT``, ``RES`` or
            ``CHAR``. Available choices depend on the selected meter.
        autorange (bool):
            Whether to select the input range automatically; initially True.
        input_range (float | str):
            Fixed range or runtime expression in the selected SI unit;
            ignored when autorange is enabled.
        nplc (float | str):
            Integration time or expression in power-line cycles, 0.01 to 10;
            initially 1.0.
        filter_enabled (bool):
            Whether to enable digital averaging; initially False.
        filter_count (int):
            Number of averaging conversions, 1 to 100; initially 10.
        zero_check (bool):
            Whether to enable input zero check; initially False.
        trigger_delay (float | str):
            Delay or expression before conversion in seconds; initially zero.
        timeout (float | str):
            Communication timeout or expression in seconds; initially 30.
        value (float):
            Latest reading in the selected SI unit, initially NaN. Not saved
            as configuration.
        instance_name (str):
            Inherited Python identifier in the Script tab and QtConsole.
        comment (str):
            Inherited optional sequence-step note.
        sequence_engine (SequenceEngine | None):
            Inherited engine and its live expression namespace.
        has_lifecycle (bool):
            True: this command participates in sequence connection and cleanup.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        With an existing instance named ``read_electrometer``, edit settings
        before running the sequence. Results reflect the latest execution::

            read_electrometer.driver = "keithley_6514"
            read_electrometer.function = "VOLT"
            read_electrometer.nplc = "integration_cycles"
            read_electrometer.value
            read_electrometer.reported_value_units()
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.driver = "keithley_6485"
        self.resource = "GPIB0::14::INSTR"
        self.function = "CURR"
        self.autorange = True
        self.input_range: float | str = 2e-9
        self.nplc: float | str = 1.0
        self.filter_enabled = False
        self.filter_count = 10
        self.zero_check = False
        self.trigger_delay: float | str = 0.0
        self.timeout: float | str = 30.0
        self.value = math.nan
        self._meter: Keithley6485 | Keithley6514 | Keithley6517 | None = None
        self._connected_driver: str | None = None
        self._configured_function: str | None = None
        self._apply_initial_config()

    @property
    def name(self) -> str:
        return "Read Electrometer"

    @property
    def has_lifecycle(self) -> bool:
        return True

    def validate(self) -> bool:
        """Check model, function and numeric syntax without contacting hardware."""
        if self.driver not in ELECTROMETER_DRIVERS:
            raise ValidationError("Select a supported Keithley electrometer driver.")
        driver = ELECTROMETER_DRIVERS[self.driver]
        try:
            function = ElectrometerFunction(self.function)
        except ValueError as exc:
            raise ValidationError("Select an electrometer measurement function.") from exc
        if function not in driver.MEASURE_FUNCTIONS:
            raise ValidationError(f"{driver.__name__} does not support {function.name}.")
        if not self.resource.strip():
            raise ValidationError("An electrometer GPIB resource is required.")
        if not 1 <= self.filter_count <= 100:
            raise ValidationError("Electrometer filter count must be between 1 and 100.")
        namespace = self.engine_namespace if self.sequence_engine is not None else {}
        for name, (lower, upper) in _NUMERIC_SETTINGS.items():
            if name == "input_range" and self.autorange:
                continue
            value = getattr(self, name)
            if isinstance(value, str):
                validate_expression(value, namespace, label=f"{self.instance_name} {name}")
            else:
                self._check_numeric(name, float(value), lower, upper)
        return True

    @staticmethod
    def _check_numeric(name: str, value: float, lower: float, upper: float) -> None:
        """Reject non-finite or out-of-bounds numeric settings."""
        if not math.isfinite(value) or not lower <= value <= upper:
            raise ValidationError(f"Electrometer {name} must be between {lower:g} and {upper:g}.")

    def connect(self) -> None:
        """Open and identify an owned session, releasing a partial connection."""
        self.validate()
        transport = GpibTransport.from_resource_string(self.resource, timeout=30.0)
        try:
            self._meter = ELECTROMETER_DRIVERS[self.driver](transport)
            self._meter.connect()
            self._meter.confirm_identity()
        except Exception:
            self._meter = None
            transport.close()
            raise
        self._connected_driver = self.driver

    def configure(self) -> None:
        """Evaluate input settings and prepare one immediate fresh reading."""
        self._configured_function = None
        self.value = math.nan
        if self._meter is None:
            raise RuntimeError("Electrometer is not connected; call connect() first.")
        if self._connected_driver != self.driver:
            raise RuntimeError("Electrometer model changed; reconnect before configuring.")
        self.validate()
        numeric = {}
        for name, (lower, upper) in _NUMERIC_SETTINGS.items():
            if name == "input_range" and self.autorange:
                numeric[name] = 0.0
                continue
            numeric[name] = self.eval_float(getattr(self, name))
            self._check_numeric(name, numeric[name], lower, upper)
        self._meter.transport.timeout = numeric["timeout"]
        self._meter.reset()
        self._meter.configure_input(
            ElectrometerFunction(self.function),
            autorange=self.autorange,
            input_range=numeric["input_range"],
            nplc=numeric["nplc"],
            filter_enabled=self.filter_enabled,
            filter_count=self.filter_count,
            zero_check=self.zero_check,
        )
        self._meter.prepare_single_reading(trigger_delay=numeric["trigger_delay"])
        self._configured_function = self.function

    def execute(self) -> None:
        """Read one fresh sample and publish it as the command's scalar output."""
        self.value = math.nan
        if self._meter is None:
            raise RuntimeError("Electrometer is not connected; run sequence setup first.")
        if self._configured_function != self.function or self._connected_driver != self.driver:
            raise RuntimeError(
                "Electrometer is not configured for this function; reconfigure it first."
            )
        self.value = float(self._meter.read_measurement())

    def disconnect(self) -> None:
        """Abort and close this instance's session, preserving the last reading."""
        meter, self._meter = self._meter, None
        self._connected_driver = None
        self._configured_function = None
        if meter is not None:
            try:
                meter.abort()
            finally:
                meter.disconnect()

    def declared_outputs(self) -> PluginOutputs:
        """Declare configured outputs and their physical units together."""
        var = self.instance_name
        label, unit = FUNCTION_CHANNELS[ElectrometerFunction(self.function)]
        return PluginOutputs(values={f"{var}:{label}": ScalarOutput(f"{var}.value", unit)})

    def to_json(self) -> dict[str, Any]:
        """Persist editable settings without connections or acquired readings."""
        data = super().to_json()
        data.update({name: getattr(self, name) for name in _SAVED_SETTINGS})
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore saved settings while retaining defaults for missing fields."""
        super()._restore_from_json(data)
        for name in _SAVED_SETTINGS:
            if name in data:
                setattr(self, name, data[name])

    def config_widget(self, parent=None) -> QWidget:
        """Build the top-packed single-reading connection and input settings."""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        layout.addLayout(form)

        driver = QComboBox()
        driver.setObjectName("electrometer_driver")
        for key, cls in ELECTROMETER_DRIVERS.items():
            driver.addItem(cls.__name__.replace("Keithley", "Keithley "), key)
        driver.setCurrentIndex(driver.findData(self.driver))
        form.addRow("Model:", driver)
        resource = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        resource.setCurrentText(self.resource)
        resource.currentTextChanged.connect(lambda text: setattr(self, "resource", text.strip()))
        form.addRow("GPIB resource:", resource)
        function = QComboBox()
        function.setObjectName("electrometer_function")
        form.addRow("Measurement function:", function)

        def check(label: str, name: str) -> QCheckBox:
            control = QCheckBox()
            control.setObjectName(f"electrometer_{name}")
            control.setChecked(getattr(self, name))
            control.toggled.connect(lambda state: setattr(self, name, state))
            form.addRow(label, control)
            return control

        def number(label: str, name: str, unit: str = "") -> SISpinBox:
            control = SISpinBox(value=getattr(self, name), suffix=unit, allow_expressions=True)
            control.setObjectName(f"electrometer_{name}")
            control.setMinimum(_NUMERIC_SETTINGS[name][0])
            control.setMaximum(_NUMERIC_SETTINGS[name][1])
            control.valueChanged.connect(lambda value: setattr(self, name, value))
            form.addRow(label, control)
            return control

        autorange = check("Autorange:", "autorange")
        input_range = number("Input range:", "input_range")
        input_range.setEnabled(not self.autorange)
        autorange.toggled.connect(lambda state: input_range.setEnabled(not state))
        number("Integration time (PLC):", "nplc")
        filter_enabled = check("Digital averaging:", "filter_enabled")
        filter_count = QSpinBox()
        filter_count.setObjectName("electrometer_filter_count")
        filter_count.setRange(1, 100)
        filter_count.setValue(self.filter_count)
        filter_count.setEnabled(self.filter_enabled)
        filter_count.valueChanged.connect(lambda count: setattr(self, "filter_count", count))
        filter_enabled.toggled.connect(filter_count.setEnabled)
        form.addRow("Filter count:", filter_count)
        check("Zero check:", "zero_check")
        number("Trigger delay:", "trigger_delay", "s")
        number("Communication timeout:", "timeout", "s")

        def update_function() -> None:
            changed = self.function != function.currentData()
            self.function = function.currentData()
            if changed:
                self.value = math.nan
            input_range.setSuffix(FUNCTION_CHANNELS[ElectrometerFunction(self.function)][1])
            if self.sequence_engine is not None:
                self.sequence_engine.refresh_data_catalogs()

        def update_driver() -> None:
            if self.driver != driver.currentData():
                self.value = math.nan
            self.driver = driver.currentData()
            previous_function = self.function
            function.blockSignals(True)
            function.clear()
            for item in ELECTROMETER_DRIVERS[self.driver].MEASURE_FUNCTIONS:
                function.addItem(FUNCTION_CHANNELS[item][0], item.value)
            function.setCurrentIndex(max(0, function.findData(previous_function)))
            function.blockSignals(False)
            update_function()

        function.currentIndexChanged.connect(lambda _: update_function())
        driver.currentIndexChanged.connect(lambda _: update_driver())
        update_driver()
        layout.addStretch()
        return widget
