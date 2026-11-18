"""Buffered auxiliary electrometer acquisition for SourceMeter sweeps."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields
from typing import Any

from qtpy.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.electrometer import (
    ElectrometerDataFormat,
    ElectrometerFunction,
    ElectrometerTriggerConfiguration,
    ElectrometerTriggerSource,
)
from stoner_measurement.instruments.keithley import Keithley6485, Keithley6514, Keithley6517
from stoner_measurement.instruments.transport import GpibTransport
from stoner_measurement.plugins._electrometer import ELECTROMETER_DRIVERS, FUNCTION_CHANNELS
from stoner_measurement.ui.widgets import FILTER_GPIB, SISpinBox, VisaResourceComboBox


@dataclass
class ElectrometerSettings:
    """Persisted settings for the optional, independently connected meter.

    Counts and buffer size use zero for automatic sizing from the sweep.
    Trigger Link and immediate arming are required for point alignment; the
    controls show these derived sources alongside the editable model settings.
    """

    enabled: bool = False
    driver: str = "keithley_6485"
    resource: str = "GPIB0::14::INSTR"
    prefix: str = "electrometer"
    function: str = "CURR"
    autorange: bool = True
    input_range: float | str = 2e-9
    nplc: float | str = 1.0
    filter_enabled: bool = False
    filter_count: int = 10
    zero_check: bool = False
    trigger_delay: float | str = 0.0
    trigger_count: int = 0
    arm_count: int = 1
    buffer_size: int = 0
    data_format: str = "ASC"
    completion_line: int = 3

    def to_json(self) -> dict[str, Any]:
        """Return editable settings without runtime connections or readings."""
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ElectrometerSettings:
        """Restore known fields, with compatible defaults for older sequences."""
        return cls(**{field.name: data[field.name] for field in fields(cls) if field.name in data})

    @property
    def channel(self) -> tuple[str, str]:
        """Return the prefixed measurement column and its SI unit."""
        label, unit = FUNCTION_CHANNELS[ElectrometerFunction(self.function)]
        return f"{self.prefix.strip() or 'electrometer'} {label}", unit


class ElectrometerAcquisition:
    """Own an optional auxiliary meter and acquire one reading per source point."""

    def __init__(self) -> None:
        self.settings = ElectrometerSettings()
        self.meter: Keithley6485 | Keithley6514 | Keithley6517 | None = None
        self.readings: tuple[float, ...] | None = None

    def connect(self) -> None:
        """Open and identify this instance's meter, closing partial connections."""
        self.disconnect()
        if not self.settings.enabled:
            return
        factory = ELECTROMETER_DRIVERS[self.settings.driver]
        transport = GpibTransport.from_resource_string(self.settings.resource, timeout=10.0)
        try:
            self.meter = factory(transport)
            self.meter.connect()
            self.meter.confirm_identity()
        except Exception:
            self.meter = None
            transport.close()
            raise

    def validate(self, plugin: Any, count: int) -> tuple[int, int]:
        """Validate sizing and routing before any source is configured."""
        settings = self.settings
        driver = ELECTROMETER_DRIVERS[settings.driver]
        if ElectrometerFunction(settings.function) not in driver.MEASURE_FUNCTIONS:
            raise ValueError(
                "The selected electrometer does not support this measurement function."
            )
        if ElectrometerDataFormat(settings.data_format) not in driver.DATA_FORMATS:
            raise ValueError("The selected electrometer does not support this transfer format.")
        size, trigger_count = self._validate_buffer_counts(count)
        lines = {plugin._trigger_in_line, plugin._trigger_out_line, settings.completion_line}
        if len(lines) != 3 or any(not 1 <= line <= 6 for line in lines):
            raise ValueError(
                "Source, nanovoltmeter and electrometer completion lines must be distinct (1..6)."
            )
        self.validate_resources(plugin)
        nplc = plugin.eval_float(settings.nplc)
        delay = plugin.eval_float(settings.trigger_delay)
        if not math.isfinite(nplc) or not 0.01 <= nplc <= 10:
            raise ValueError("Electrometer NPLC must be between 0.01 and 10.")
        if not math.isfinite(delay) or not 0 <= delay <= 999.999:
            raise ValueError("Electrometer trigger delay must be between 0 and 999.999 seconds.")
        if not settings.autorange:
            value = plugin.eval_float(settings.input_range)
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Electrometer input range must be positive and finite.")
        if not 1 <= settings.filter_count <= 100:
            raise ValueError("Electrometer filter count must be between 1 and 100.")
        return size, trigger_count

    def _validate_buffer_counts(self, count: int) -> tuple[int, int]:
        """Require the meter buffer and trigger model to match the sweep length."""
        settings = self.settings
        driver = ELECTROMETER_DRIVERS[settings.driver]
        size = settings.buffer_size or count
        trigger_count = settings.trigger_count or count
        if not 2 <= size <= driver.MAX_BUFFER_POINTS or size != count:
            raise ValueError(
                "Electrometer buffer size must equal the sweep length and fit the meter's buffer."
            )
        if (
            settings.arm_count < 1
            or trigger_count < 1
            or trigger_count * settings.arm_count != count
        ):
            raise ValueError("Electrometer trigger count × arm count must equal the sweep length.")
        return size, trigger_count

    def validate_resources(self, plugin: Any) -> None:
        """Reject shared addresses before opening multiple owned sessions."""
        resources = [plugin._resource, self.settings.resource]
        if plugin._secondary_enabled:
            resources.append(plugin._secondary_resource)
        from stoner_measurement.instruments.lock_registry import canonical_resource_key

        if len({canonical_resource_key(resource) for resource in resources}) != len(resources):
            raise ValueError("Each sweep instrument must have a distinct GPIB resource.")

    def configure(self, plugin: Any, count: int) -> None:
        """Apply all input, buffer and trigger settings through the driver."""
        size, trigger_count = self.validate(plugin, count)
        if self.meter is None:
            raise RuntimeError("Secondary electrometer is enabled but not connected.")
        settings = self.settings
        meter = self.meter
        meter.reset()
        meter.prepare_buffer(size)
        meter.configure_input(
            ElectrometerFunction(settings.function),
            autorange=settings.autorange,
            input_range=plugin.eval_float(settings.input_range) if not settings.autorange else 0.0,
            nplc=plugin.eval_float(settings.nplc),
            filter_enabled=settings.filter_enabled,
            filter_count=settings.filter_count,
            zero_check=settings.zero_check,
        )
        meter.set_data_format(ElectrometerDataFormat(settings.data_format))
        meter.configure_trigger_model(
            ElectrometerTriggerConfiguration(
                trigger_source=ElectrometerTriggerSource.TLIN,
                trigger_count=trigger_count,
                trigger_delay=plugin.eval_float(settings.trigger_delay),
                arm_source=ElectrometerTriggerSource.IMM,
                arm_count=settings.arm_count,
            )
        )
        meter.configure_trigger_link(
            input_line=plugin._trigger_in_line
            if plugin._secondary_enabled
            else plugin._trigger_out_line,
            output_line=settings.completion_line,
        )

    def measurement_time(self, plugin: Any) -> float:
        """Estimate a conversion for sweep timeout and final-reading allowance."""
        settings = self.settings
        return plugin.eval_float(settings.trigger_delay) + 0.02 * plugin.eval_float(
            settings.nplc
        ) * (settings.filter_count if settings.filter_enabled else 1)

    def start(self) -> None:
        """Arm a fresh buffer before the source starts sending trigger pulses."""
        if self.meter is None:
            raise RuntimeError("Secondary electrometer is enabled but not connected.")
        self.readings = None
        self.meter.start_buffer()

    def read(self, count: int, timeout: float) -> None:
        """Retrieve the buffer and reject missing or extra measurements."""
        if self.meter is None:
            raise RuntimeError("Secondary electrometer is enabled but not connected.")
        self.meter.wait_for_buffer_complete(timeout)
        self.readings = tuple(self.meter.read_buffer())
        if len(self.readings) != count:
            raise RuntimeError(
                f"Secondary electrometer returned {len(self.readings)} readings; expected {count}."
            )

    def disconnect(self) -> None:
        """Abort and close owned resources, propagating cleanup failures."""
        meter, self.meter = self.meter, None
        self.readings = None
        if meter is not None:
            try:
                meter.abort()
            finally:
                meter.disconnect()


def _refresh_meter_choices(settings, function, data_format, input_range, filter_count) -> None:
    """Update function and transfer choices for the selected physical meter."""
    selected_driver = ELECTROMETER_DRIVERS[settings.driver]
    for widget, values, selected in (
        (function, selected_driver.MEASURE_FUNCTIONS, settings.function),
        (data_format, selected_driver.DATA_FORMATS, settings.data_format),
    ):
        widget.blockSignals(True)
        widget.clear()
        for value in values:
            text = (
                FUNCTION_CHANNELS[value][0]
                if isinstance(value, ElectrometerFunction)
                else value.name
            )
            widget.addItem(text, value.value)
        widget.setCurrentIndex(max(0, widget.findData(selected)))
        setattr(settings, "function" if widget is function else "data_format", widget.currentData())
        widget.blockSignals(False)
    input_range.setSuffix(FUNCTION_CHANNELS[ElectrometerFunction(settings.function)][1])
    input_range.setEnabled(not settings.autorange)
    filter_count.setEnabled(settings.filter_enabled)


def _refresh_catalogs(plugin: Any) -> None:
    """Refresh published outputs when an attached meter's settings change."""
    if plugin.sequence_engine is not None:
        plugin.sequence_engine.refresh_data_catalogs()


def electrometer_config_page(plugin: Any, on_enabled: Any) -> QWidget:
    """Build a bounded, scrollable setting/value table for the auxiliary meter."""
    settings = plugin._electrometer.settings
    page = QWidget()
    layout = QVBoxLayout(page)
    enabled = QCheckBox("Use a secondary electrometer / picoammeter")
    enabled.setObjectName("electrometer_enabled")
    enabled.setChecked(settings.enabled)
    layout.addWidget(enabled)
    table = QTableWidget(0, 2)
    table.setObjectName("electrometer_settings")
    table.setHorizontalHeaderLabels(["Setting", "Value"])
    table.verticalHeader().hide()
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    table.setEnabled(settings.enabled)

    def row(label: str, name: str, widget: QWidget) -> QWidget:
        index = table.rowCount()
        table.insertRow(index)
        table.setItem(index, 0, QTableWidgetItem(label))
        widget.setObjectName(f"electrometer_{name}")
        table.setCellWidget(index, 1, widget)
        table.setRowHeight(index, max(30, widget.sizeHint().height() + 6))
        return widget

    def combo(label: str, name: str, choices: dict[str, str]) -> QComboBox:
        widget = QComboBox()
        for value, text in choices.items():
            widget.addItem(text, value)
        widget.setCurrentIndex(widget.findData(getattr(settings, name)))
        widget.currentIndexChanged.connect(
            lambda index: setattr(settings, name, widget.itemData(index))
        )
        row(label, name, widget)
        return widget

    def check(label: str, name: str) -> QCheckBox:
        widget = QCheckBox()
        widget.setChecked(getattr(settings, name))
        widget.toggled.connect(lambda state: setattr(settings, name, state))
        row(label, name, widget)
        return widget

    def number(label: str, name: str, minimum: float, maximum: float, unit: str = "") -> SISpinBox:
        widget = SISpinBox(value=getattr(settings, name), allow_expressions=True, suffix=unit)
        widget.setMinimum(minimum)
        widget.setMaximum(maximum)
        widget.valueChanged.connect(lambda value: setattr(settings, name, value))
        row(label, name, widget)
        return widget

    def integer(label: str, name: str, minimum: int, maximum: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setSpecialValueText("Automatic (sweep length)" if minimum == 0 else "")
        widget.setValue(getattr(settings, name))
        widget.valueChanged.connect(lambda value: setattr(settings, name, value))
        row(label, name, widget)
        return widget

    driver = combo(
        "Model",
        "driver",
        {
            key: value.__name__.replace("Keithley", "Keithley ")
            for key, value in ELECTROMETER_DRIVERS.items()
        },
    )
    resource = VisaResourceComboBox(resource_filter=FILTER_GPIB)
    resource.setCurrentText(settings.resource)
    resource.currentTextChanged.connect(lambda text: setattr(settings, "resource", text.strip()))
    row("GPIB resource", "resource", resource)
    prefix = QLineEdit(settings.prefix)
    prefix.textChanged.connect(lambda text: (setattr(settings, "prefix", text), refresh_catalogs()))
    row("Column prefix", "prefix", prefix)
    function = combo(
        "Measurement function",
        "function",
        {key.value: value[0] for key, value in FUNCTION_CHANNELS.items()},
    )
    autorange = check("Autorange", "autorange")
    input_range = number("Input range", "input_range", 1e-15, 1e18)
    number("Integration time (PLC)", "nplc", 0.01, 10.0)
    filter_enabled = check("Digital averaging filter", "filter_enabled")
    filter_count = integer("Filter count", "filter_count", 1, 100)
    check("Zero check (zero input reading)", "zero_check")
    number("Trigger delay", "trigger_delay", 0.0, 999.999, "s")
    row("Trigger source", "trigger_source", QLabel("Trigger Link (one event per source point)"))
    integer("Trigger count (0 = automatic)", "trigger_count", 0, 50000)
    row("Arm source", "arm_source", QLabel("Immediate"))
    integer("Arm count", "arm_count", 1, 50000)
    integer("Buffer size (0 = automatic)", "buffer_size", 0, 50000)
    data_format = combo(
        "Buffer transfer format",
        "data_format",
        {item.value: item.name for item in ElectrometerDataFormat},
    )
    completion_line = integer("Completion Trigger Link line", "completion_line", 1, 6)
    completion_line.valueChanged.connect(lambda _: on_enabled())

    def refresh_catalogs() -> None:
        _refresh_catalogs(plugin)

    def apply_capabilities() -> None:
        _refresh_meter_choices(settings, function, data_format, input_range, filter_count)
        refresh_catalogs()

    def set_enabled(state: bool) -> None:
        settings.enabled = state
        table.setEnabled(state)
        on_enabled()
        refresh_catalogs()

    driver.currentIndexChanged.connect(lambda _: apply_capabilities())
    function.currentIndexChanged.connect(lambda _: apply_capabilities())
    autorange.toggled.connect(lambda state: input_range.setEnabled(not state))
    filter_enabled.toggled.connect(filter_count.setEnabled)
    enabled.toggled.connect(set_enabled)
    table.setMaximumHeight(
        table.horizontalHeader().sizeHint().height()
        + sum(table.rowHeight(index) for index in range(table.rowCount()))
        + 2 * table.frameWidth()
    )
    layout.addWidget(table, 1)
    note = QLabel(
        "The source holds each point until the electrometer completes. With a nanovoltmeter, "
        "the trigger chain is SMU → nanovoltmeter → electrometer → SMU. The electrometer "
        "completion line must be separate from the two Advanced-page lines. Counts must "
        "produce exactly one buffered reading per source point. Other trigger/arm sources "
        "are fixed here to preserve point alignment."
    )
    note.setWordWrap(True)
    note_policy = note.sizePolicy()
    note_policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
    note.setSizePolicy(note_policy)
    layout.addWidget(note)
    layout.addStretch()
    apply_capabilities()
    return page
