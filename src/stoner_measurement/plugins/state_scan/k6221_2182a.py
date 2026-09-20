"""Software-stepped 6221 sourcing with independently optional voltmeters."""

from __future__ import annotations

import math
import time

from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.instruments.keithley.k2182 import Keithley2182A
from stoner_measurement.instruments.keithley.k6221 import Keithley6221
from stoner_measurement.instruments.transport.gpib_transport import (
    GpibTransport,
    PassThroughGpibTransport,
)
from stoner_measurement.plugins._point_voltmeter import (
    METER_DEFAULTS,
    PointVoltmeterSettings,
    configure_meter,
)
from stoner_measurement.plugins.state_scan.base import StateScanPlugin
from stoner_measurement.plugins.trace._nanovoltmeter_support import NANOVOLTMETER_DRIVERS
from stoner_measurement.ui.font_aware_tabs import FontAwareTabWidget
from stoner_measurement.ui.widgets import FILTER_GPIB, SISpinBox, VisaResourceComboBox


class Keithley6221PointScanPlugin(StateScanPlugin):
    """Scan DC current with independently optional primary and secondary meters.

    The 2182A uses direct GPIB or 6221 serial pass-through. The secondary uses
    GPIB with a 182 or 2182A driver. Readings are sequential after settling;
    no Trigger Link wiring is required. Resistance uses programmed current
    and is NaN at zero current. With both meters disabled only source_value
    is published. Output remains on between points and is disabled on cleanup.

    Use this scan to hold each programmed DC current while nested measurements
    run. **Scan** defines currents in amperes and **Data** selects collected
    outputs. On **Settings**, the nested **General** page selects the 6221 GPIB
    resource, compliance voltage (0.1 to 10.5 V) and settling delay in seconds.
    Current must lie between -105 and +105 mA.

    **Primary** and **Secondary** independently enable meters, select their
    connections and configure integration, range, filtering and other options
    supported by the selected driver. Both meters are disabled by default.
    Compliance is evaluated during configuration and settling delay per point.
    After settling, enabled meters are read before child steps run.

    Published values are ``source_value``, primary ``voltage``/``resistance``
    and optional ``secondary_voltage``/``secondary_resistance``. Current stays
    at that level through child steps. No LIST sweep or trigger pulse is used.

    Attributes:
        _resource (str):
            6221 VISA/GPIB resource.
        _compliance (float | str):
            Configuration-time compliance voltage in volts.
        _source_delay (float | str):
            Settling time or per-point expression in seconds.
        _primary_enabled (bool):
            Read the primary 2182A.
        _primary_resource (str):
            Primary meter GPIB resource when not using serial pass-through.
        _primary_passthrough (bool):
            Connect the primary meter through the 6221 serial port.
        _secondary_enabled (bool):
            Read the independent secondary meter.
        _secondary_resource (str):
            Secondary meter GPIB resource.
        _secondary_driver (str):
            Secondary driver: keithley_182 or keithley_2182a.
        _readings (dict[str, float]):
            Latest enabled voltage and resistance readings.
        instance_name (str):
            Inherited Python identifier for this instance in the Script tab and
            QtConsole.
        comment (str):
            Inherited optional note displayed beside this step.
        sequence_engine (SequenceEngine | None):
            Inherited owning engine and its live namespace; None while
            detached.
        scan_generator (BaseScanGenerator):
            Inherited generator defining successive sequence points.
        value (float):
            Inherited current sequence control value.
        ix (int):
            Inherited zero-based iteration index.
        meas_flag (bool):
            Inherited flag indicating a measurement point.
        collect_data (bool):
            Inherited switch enabling collection of selected sequence outputs.
        data (TraceData):
            Inherited accumulated table; inspect data.df after collection.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        With an instance named ``k6221_point_scan`` in the sequence, use the
        QtConsole to inspect or edit it before running. Substitute your
        instance name if different; result data reflects completed steps::

            k6221_point_scan._source_delay = 0.05
            k6221_point_scan._primary_enabled = True
            k6221_point_scan.collect_data = True
    """

    _settings = (
        "resource", "compliance", "source_delay", "primary_enabled", "primary_resource",
        "primary_passthrough", "secondary_enabled", "secondary_resource", "secondary_driver",
    ) + tuple(f"{role}_{key}" for role in ("primary", "secondary") for key in METER_DEFAULTS)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._resource = "GPIB0::12::INSTR"
        self._compliance = 10.0
        self._source_delay = 0.01
        self._primary_enabled = False
        self._primary_resource = "GPIB0::7::INSTR"
        self._primary_passthrough = True
        self._secondary_enabled = False
        self._secondary_resource = "GPIB0::8::INSTR"
        self._secondary_driver = "keithley_2182a"
        for role in ("primary", "secondary"):
            for key, value in METER_DEFAULTS.items():
                setattr(self, f"_{role}_{key}", value)
        self._source = None
        self._meters = {}
        self._transports = []
        self._target_value = 0.0
        self._readings = {}
        self._apply_initial_config()

    @property
    def name(self):
        return "Keithley6221PointScan"

    @property
    def state_name(self):
        return "Current"

    @property
    def units(self):
        return "A"

    @property
    def limits(self):
        return (-0.105, 0.105)

    def _open_instrument(self, driver, resource, passthrough=False):
        transport_class = PassThroughGpibTransport if passthrough else GpibTransport
        transport = transport_class.from_resource_string(resource, timeout=10.0)
        self._transports.append(transport)
        instrument = driver(transport)
        instrument.connect()
        instrument.confirm_identity()
        return instrument

    def connect(self):
        """Open enabled instruments and clean up partial connections."""
        try:
            self._source = self._open_instrument(Keithley6221, self._resource)
            if self._primary_enabled:
                resource = self._resource if self._primary_passthrough else self._primary_resource
                self._meters["primary"] = self._open_instrument(
                    Keithley2182A, resource, self._primary_passthrough
                )
            if self._secondary_enabled:
                self._meters["secondary"] = self._open_instrument(
                    NANOVOLTMETER_DRIVERS[self._secondary_driver], self._secondary_resource
                )
        except Exception:
            self.disconnect()
            raise

    def configure(self):
        """Configure DC sourcing and immediate single voltage readings."""
        if self._source is None:
            raise RuntimeError("Connect the 6221 before configuring it.")
        compliance = self.eval_float(self._compliance)
        if not math.isfinite(compliance) or not 0.1 <= compliance <= 10.5:
            raise ValueError("Compliance must be between 0.1 and 10.5 V.")
        self._source.reset()
        self._source.enable_output(False)
        self._source.set_source_level(0.0)
        self._source.set_compliance_voltage(compliance)
        for role, meter in self._meters.items():
            configure_meter(self, role, meter)
        self._readings.clear()

    def disconnect(self):
        """Disable output and close all owned sessions, propagating failures."""
        errors = []
        if self._source is not None:
            try:
                self._source.enable_output(False)
            except Exception as error:
                errors.append(error)
        for transport in reversed(self._transports):
            try:
                transport.close()
            except Exception as error:
                errors.append(error)
        self._source = None
        self._meters.clear()
        self._transports.clear()
        if errors:
            raise errors[0]

    def set_state(self, value):
        """Apply current before enabling output, then read optional voltages."""
        self._readings.clear()
        if self._source is None:
            raise RuntimeError("Connect the 6221 before setting current.")
        target = float(value)
        delay = self.eval_float(self._source_delay)
        if not math.isfinite(target) or not self.limits[0] <= target <= self.limits[1]:
            raise ValueError("Current must be between -105 and 105 mA.")
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("Source delay must be finite and non-negative.")
        for role in ("primary", "secondary"):
            if getattr(self, f"_{role}_enabled") and role not in self._meters:
                raise RuntimeError(f"Connect the enabled {role} voltmeter first.")
        try:
            self._source.set_source_level(target)
            self._source.enable_output(True)
            self._target_value = target
            time.sleep(delay)
            readings = {}
            for role, meter in self._meters.items():
                voltage = meter.measure_voltage()
                prefix = "" if role == "primary" else "secondary_"
                readings[prefix + "voltage"] = voltage
                readings[prefix + "resistance"] = voltage / target if target else math.nan
            self._readings = readings
        except Exception:
            self._source.enable_output(False)
            raise
        self.state_changed.emit(target)

    def get_state(self):
        return self._target_value

    def is_at_target(self):
        return True

    def reported_values(self):
        prefix = self.instance_name
        values = {f"{prefix}.source_value": f"{prefix}.get_state()"}
        for name in self._measurement_units():
            values[f"{prefix}.{name}"] = f"{prefix}._readings.get({name!r})"
        return values

    def _measurement_units(self):
        units = {}
        for role in ("primary", "secondary"):
            if getattr(self, f"_{role}_enabled"):
                prefix = "" if role == "primary" else "secondary_"
                units.update({prefix + "voltage": "V", prefix + "resistance": "Ω"})
        return units

    def reported_value_units(self):
        prefix = self.instance_name
        units = {f"{prefix}.source_value": "A"}
        units.update({f"{prefix}.{key}": unit for key, unit in self._measurement_units().items()})
        return units

    def to_json(self):
        data = super().to_json()
        data.update({key: getattr(self, "_" + key) for key in self._settings})
        return data

    def _restore_from_json(self, data):
        super()._restore_from_json(data)
        for key in self._settings:
            if key in data:
                setattr(self, "_" + key, data[key])
        if self._secondary_driver not in NANOVOLTMETER_DRIVERS:
            raise ValueError(f"Unknown voltmeter driver: {self._secondary_driver}")
        # Older point-scan files have no digits/filter settings. Use the
        # selected driver's defaults, particularly for the lower-resolution 182.
        for role in ("primary", "secondary"):
            driver = Keithley2182A if role == "primary" else NANOVOLTMETER_DRIVERS[self._secondary_driver]
            for key in ("digits", "filter_type"):
                if f"{role}_{key}" not in data:
                    setattr(self, f"_{role}_{key}", getattr(driver.CAPABILITIES, f"default_{key}"))

    def _plugin_config_tabs(self):
        root = FontAwareTabWidget()
        general = QWidget()
        layout = QVBoxLayout(general)
        source = QGroupBox("6221 current source")
        form = QFormLayout(source)
        self._resource_control(form, "GPIB resource", "resource")
        self._number_control(form, "Compliance", "compliance", "V", 0.1, 10.5)
        self._number_control(form, "Settling delay", "source_delay", "s", 0, 3600)
        layout.addWidget(source)
        layout.addStretch()
        root.addTab(general, "General")
        for role in ("primary", "secondary"):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.addWidget(self._meter_controls(role))
            page_layout.addStretch()
            root.addTab(page, role.title())
        return root

    def _meter_controls(self, role):
        group = QGroupBox("2182A" if role == "primary" else "Second voltmeter")
        group.setObjectName(role)
        group.setCheckable(True)
        group.setChecked(getattr(self, f"_{role}_enabled"))
        group.toggled.connect(lambda enabled: self._set_meter_enabled(role, enabled))
        layout = QVBoxLayout(group)
        form = QFormLayout()
        layout.addLayout(form)
        driver_class = Keithley2182A if role == "primary" else NANOVOLTMETER_DRIVERS[self._secondary_driver]
        settings = PointVoltmeterSettings(self, role, driver_class.CAPABILITIES)
        resource = self._resource_control(form, "GPIB resource", f"{role}_resource")
        if role == "primary":
            passthrough = QCheckBox("Connect through 6221 serial port")
            passthrough.setChecked(self._primary_passthrough)
            resource.setEnabled(not self._primary_passthrough)
            passthrough.toggled.connect(lambda enabled: setattr(self, "_primary_passthrough", enabled))
            passthrough.toggled.connect(lambda enabled: resource.setEnabled(not enabled))
            form.addRow(passthrough)
        else:
            driver = QComboBox()
            for key, cls in NANOVOLTMETER_DRIVERS.items():
                driver.addItem(cls.display_name(), key)
            driver.setCurrentIndex(driver.findData(self._secondary_driver))
            def change_driver(index):
                self._secondary_driver = driver.itemData(index)
                settings.apply_capabilities(NANOVOLTMETER_DRIVERS[self._secondary_driver].CAPABILITIES)

            driver.setObjectName("secondary_driver")
            driver.currentIndexChanged.connect(change_driver)
            form.addRow("Driver", driver)
        layout.addWidget(settings)
        return group

    def _set_meter_enabled(self, role, enabled):
        setattr(self, f"_{role}_enabled", enabled)
        self._readings.clear()
        if self.sequence_engine is not None:
            self.sequence_engine.refresh_data_catalogs()

    def _resource_control(self, form, label, key):
        widget = VisaResourceComboBox(resource_filter=FILTER_GPIB)
        widget.setObjectName(key)
        widget.setCurrentText(getattr(self, "_" + key))
        widget.currentTextChanged.connect(lambda text: setattr(self, "_" + key, text.strip()))
        form.addRow(label, widget)
        return widget

    def _number_control(self, form, label, key, suffix, minimum, maximum):
        widget = SISpinBox(allow_expressions=True, suffix=suffix, value=getattr(self, "_" + key))
        widget.setObjectName(key)
        widget.setMinimum(minimum)
        widget.setMaximum(maximum)
        widget.valueChanged.connect(lambda value: setattr(self, "_" + key, value))
        form.addRow(label, widget)
