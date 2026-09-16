"""Measurement settings shared by the 6221 point scan and set command."""

from qtpy.QtWidgets import QCheckBox, QComboBox, QFormLayout, QSpinBox, QWidget

from stoner_measurement.instruments.nanovoltmeter import NanovoltmeterTriggerSource
from stoner_measurement.ui.widgets import SIComboBox, SISpinBox

METER_DEFAULTS = {
    "nplc": 1.0,
    "voltage_range": 0.0,
    "digits": 8,
    "trigger_delay": 0.0,
    "autozero": True,
    "line_sync": False,
    "filter_type": "OFF",
    "filter_count": 10,
    "analog_filter": False,
    "relative_enabled": False,
    "relative_value": 0.0,
}


def configure_meter(plugin, role, meter):
    """Apply supported measurement controls without configuring a trace buffer."""
    def get(key):
        return getattr(plugin, f"_{role}_{key}")

    caps = meter.get_capabilities()
    if caps.supports_safe_reset:
        meter.reset()
    meter.set_digits(get("digits"))
    meter.set_nplc(plugin.eval_float(get("nplc")))
    voltage_range = get("voltage_range")
    meter.set_autorange(voltage_range <= 0)
    if voltage_range > 0:
        meter.set_range(voltage_range)
    if caps.supports_autozero:
        meter.set_autozero_enabled(get("autozero"))
    if caps.supports_line_sync:
        meter.set_line_sync_enabled(get("line_sync"))
    filter_type = get("filter_type")
    meter.set_filter_enabled(filter_type != "OFF")
    if filter_type != "OFF":
        if caps.supports_filter_count:
            meter.set_filter_count(get("filter_count"))
        meter.set_filter_type(filter_type)
    if caps.supports_analog_filter:
        meter.set_analog_filter_enabled(get("analog_filter"))
    if caps.supports_relative:
        meter.set_relative_value(plugin.eval_float(get("relative_value")))
        meter.set_relative_enabled(get("relative_enabled"))
    meter.set_trigger_source(NanovoltmeterTriggerSource.IMM)
    meter.set_trigger_delay(plugin.eval_float(get("trigger_delay")))
    meter.set_trigger_count(1)


class PointVoltmeterSettings(QWidget):
    """Capability-aware, independently persisted controls for one voltmeter."""

    def __init__(self, plugin, role, capabilities):
        super().__init__()
        self.plugin = plugin
        self.role = role
        self.capabilities = capabilities
        self.controls = {}
        form = QFormLayout(self)
        for key, label in (
            ("nplc", "Integration (PLC)"),
            ("voltage_range", "Voltage range"),
            ("digits", "Digits"),
            ("filter_type", "Digital filter"),
        ):
            combo = QComboBox()
            self._add(form, key, label, combo)
            combo.currentIndexChanged.connect(
                lambda index, key=key, combo=combo: self._changed(key, combo.itemData(index))
            )
        count = QSpinBox()
        count.setRange(1, 100)
        count.setValue(self._get("filter_count"))
        count.valueChanged.connect(lambda value: self._changed("filter_count", value))
        self._add(form, "filter_count", "Filter count", count)
        for key, label in (
            ("autozero", "Autozero"), ("line_sync", "Line sync"),
            ("analog_filter", "Analogue filter"), ("relative_enabled", "Relative mode"),
        ):
            checkbox = QCheckBox()
            checkbox.setChecked(self._get(key))
            checkbox.toggled.connect(lambda value, key=key: self._changed(key, value))
            self._add(form, key, label, checkbox)
        for key, label, suffix, limits in (
            ("trigger_delay", "Trigger delay", "s", (0, 999.999)),
            ("relative_value", "Relative reference", "V", (-120, 120)),
        ):
            spin = SISpinBox(allow_expressions=True, suffix=suffix, value=self._get(key))
            spin.setMinimum(limits[0])
            spin.setMaximum(limits[1])
            spin.valueChanged.connect(lambda value, key=key: self._changed(key, value))
            self._add(form, key, label, spin)
        self.apply_capabilities(capabilities)

    def _get(self, key):
        return getattr(self.plugin, f"_{self.role}_{key}")

    def _changed(self, key, value):
        setattr(self.plugin, f"_{self.role}_{key}", value)
        self._update_enabled()

    def _add(self, form, key, label, widget):
        widget.setObjectName(f"{self.role}_{key}")
        self.controls[key] = widget
        form.addRow(label, widget)

    def apply_capabilities(self, caps):
        """Refresh supported choices when the secondary driver changes."""
        self.capabilities = caps
        options = {
            "nplc": (caps.nplc_values, caps.default_nplc, lambda value: f"{value:g} PLC"),
            "voltage_range": ((0.0, *caps.fixed_voltage_ranges), 0.0,
                              lambda value: "Auto" if value == 0 else SIComboBox.format_si(value, "V")),
            "digits": (caps.digit_values, caps.default_digits, lambda value: f"{value}.5"),
            "filter_type": (caps.filter_types, caps.default_filter_type, str.title),
        }
        for key, (values, default, label) in options.items():
            value = self._get(key)
            if value not in values:
                value = default if default in values else values[0]
                setattr(self.plugin, f"_{self.role}_{key}", value)
            combo = self.controls[key]
            combo.blockSignals(True)
            combo.clear()
            for option in values:
                combo.addItem(label(option), option)
            combo.setCurrentIndex(combo.findData(value))
            combo.blockSignals(False)
        if caps.relative_limits:
            self.controls["relative_value"].setMinimum(caps.relative_limits[0])
            self.controls["relative_value"].setMaximum(caps.relative_limits[1])
        self._update_enabled()

    def _update_enabled(self):
        if "relative_value" not in self.controls:
            return
        caps = self.capabilities
        for key, enabled in {
            "autozero": caps.supports_autozero,
            "line_sync": caps.supports_line_sync,
            "analog_filter": caps.supports_analog_filter,
            "filter_count": caps.supports_filter_count and self._get("filter_type") != "OFF",
            "relative_enabled": caps.supports_relative,
            "relative_value": caps.supports_relative and self._get("relative_enabled"),
        }.items():
            self.controls[key].setEnabled(enabled)
