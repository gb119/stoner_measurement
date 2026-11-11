"""Native Lake Shore 340 input settings with conservative, field-specific writes."""

from dataclasses import fields

from qtpy.QtWidgets import QCheckBox, QComboBox, QLabel, QSizePolicy, QSpinBox, QWidget

from stoner_measurement.instruments.lakeshore import Lakeshore340InputSettings
from stoner_measurement.ui.temperature_panel import _InputSettingsTableWidget
from stoner_measurement.ui.widgets import SISpinBox

_SENSOR_TYPES = (
    "Special",
    "Silicon diode",
    "GaAlAs diode",
    "Platinum 100 (250 Ω)",
    "Platinum 100 (500 Ω)",
    "Platinum 1000",
    "Rhodium iron",
    "Carbon-glass",
    "Cernox",
    "RuOx",
    "Germanium",
)
_EXCITATIONS = (
    "Off",
    "30 nA",
    "100 nA",
    "300 nA",
    "1 µA",
    "3 µA",
    "10 µA",
    "30 µA",
    "100 µA",
    "300 µA",
    "1 mA",
    "10 mV",
    "1 mV",
)
_RANGES = (
    "1 mV",
    "2.5 mV",
    "5 mV",
    "10 mV",
    "25 mV",
    "50 mV",
    "100 mV",
    "250 mV",
    "500 mV",
    "1 V",
    "2.5 V",
    "5 V",
    "7.5 V",
)
_SPECIAL_FIELDS = ("sensor_units", "coefficient", "excitation", "range_")


def _choices(labels, start=0):
    """Create a native enumerated selector with hardware codes as item data."""
    combo = QComboBox()
    for code, label in enumerate(labels, start):
        combo.addItem(label, code)
    return combo


class Lakeshore340InputSettingsTable(_InputSettingsTableWidget):
    """Edit standard Model 340 A/B inputs using their native parameter layout.

    Read All establishes the hardware baseline. Write All sends only changed
    fields and reads successful writes back. A sensor preset leaves its implied
    units, coefficient, excitation and range to the instrument; those fields
    become editable when Special is selected. A failed or ambiguous write
    requires another Read All before writing again.

    Args:
        engine (TemperatureControllerEngine): Owning controller session.
        parent (QWidget | None): Optional parent widget.
    """

    _ROWS = (
        ("sensor_type", "Sensor type"),
        ("input_enabled", "Input enabled"),
        ("sensor_units", "Sensor units"),
        ("coefficient", "Temperature coefficient"),
        ("excitation", "Excitation"),
        ("range_", "Input voltage range"),
        ("compensation_mode", "Compensation"),
        ("filter_enabled", "Filter enabled"),
        ("filter_points", "Filter points"),
        ("filter_window", "Filter window"),
        ("curve_number", "Calibration curve"),
    )

    def __init__(self, engine, parent: QWidget | None = None) -> None:
        self._snapshots: dict[str, Lakeshore340InputSettings] = {}
        super().__init__(engine, parent)
        self._hint = QLabel(
            "Sensor presets load their defaults when written. Select Special to edit "
            "units, coefficient, excitation and range."
        )
        self._hint.setWordWrap(True)
        self._hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.layout().insertWidget(0, self._hint)
        self._read_status = QLabel()
        self._read_status.setWordWrap(True)
        self.layout().addWidget(self._read_status)
        self.layout().addStretch()
        self._update_readiness()

    def set_channels(self, channels: tuple[str, ...]) -> None:
        """Rebuild channel columns and require fresh hardware settings before writes."""
        self._snapshots.clear()
        super().set_channels(channels)
        self._update_readiness()

    def _make_channel_editors(self) -> dict[str, QWidget]:
        """Construct selectors and bounded values matching the native command fields."""
        sensor_type = _choices(_SENSOR_TYPES)
        input_enabled = QCheckBox("Enabled")
        sensor_units = _choices(("Volts", "Ohms"), start=1)
        coefficient = _choices(("Negative", "Positive"), start=1)
        excitation = _choices(_EXCITATIONS)
        voltage_range = _choices(_RANGES, start=1)
        compensation = _choices(("Off", "On", "Paused"))
        compensation.setToolTip(
            "Hardware compensation applies to NTC resistors and Special sensor inputs."
        )
        filter_enabled = QCheckBox("Enabled")
        points = QSpinBox()
        points.setRange(2, 64)
        window = SISpinBox()
        window.setOpts(bounds=(1, 10), value=1, step=1, decimals=1, suffix="%", siPrefix=False)
        curve = QComboBox()
        self._populate_curve_combo(curve)
        editors = {
            "sensor_type": sensor_type,
            "input_enabled": input_enabled,
            "sensor_units": sensor_units,
            "coefficient": coefficient,
            "excitation": excitation,
            "range_": voltage_range,
            "compensation_mode": compensation,
            "filter_enabled": filter_enabled,
            "filter_points": points,
            "filter_window": window,
            "curve_number": curve,
        }
        sensor_type.currentIndexChanged.connect(lambda _index: self._update_special_fields(editors))
        self._update_special_fields(editors)
        return editors

    @staticmethod
    def _update_special_fields(editors):
        """Allow native overrides only when the user explicitly chooses Special."""
        special = editors["sensor_type"].currentData() == 0
        for key in _SPECIAL_FIELDS:
            editors[key].setEnabled(special)
            editors[key].setToolTip(
                "Native Special sensor setting."
                if special
                else "Determined by the sensor preset; updated after Write All."
            )
        editors["compensation_mode"].setEnabled(
            editors["sensor_type"].currentData() in (0, 7, 8, 9, 10)
        )

    def _populate_channel(self, channel: str, settings: Lakeshore340InputSettings) -> None:
        """Populate all native fields and preserve exact compensation/unknown codes."""
        if not isinstance(settings, Lakeshore340InputSettings):
            raise TypeError("The Model 340 editor requires native Model 340 input settings.")
        editors = self._editors[channel]
        for key, _label in self._ROWS:
            value = getattr(settings, key)
            if value is None:
                continue
            editor = editors[key]
            if isinstance(editor, QComboBox):
                index = editor.findData(value)
                if index < 0:
                    editor.addItem(f"Unknown ({value})", value)
                    index = editor.count() - 1
                editor.setCurrentIndex(index)
            elif isinstance(editor, QCheckBox):
                editor.setChecked(value)
            else:
                editor.setValue(value)
        self._update_special_fields(editors)
        self._snapshots[channel] = settings
        self._update_readiness()

    def _collect_channel(self, channel: str) -> Lakeshore340InputSettings:
        """Collect changes only, leaving sensor-preset defaults implicit."""
        if channel not in self._snapshots:
            raise RuntimeError(
                f"Read input {channel} from the instrument before writing its settings."
            )
        baseline = self._snapshots[channel]
        editors = self._editors[channel]
        special = editors["sensor_type"].currentData() == 0
        changed = {}
        for key, _label in self._ROWS:
            if key in _SPECIAL_FIELDS and not special:
                continue
            if key == "compensation_mode" and not editors[key].isEnabled():
                continue
            editor = editors[key]
            if isinstance(editor, QComboBox):
                value = editor.currentData()
            elif isinstance(editor, QCheckBox):
                value = editor.isChecked()
            else:
                value = editor.value()
            if value != getattr(baseline, key):
                changed[key] = value
        return Lakeshore340InputSettings(**changed)

    def _update_readiness(self):
        """Keep Write All unavailable until every column has a known hardware baseline."""
        ready = bool(self._channels) and all(
            channel in self._snapshots for channel in self._channels
        )
        self._write_button.setEnabled(ready)
        self._read_status.setText(
            "" if ready else "Read All to load current input settings before writing."
        )
        self._read_status.setVisible(not ready)

    def read_all(self, *, show_warning: bool = True) -> bool:
        """Refresh native snapshots on explicit Read All or connection."""
        self._snapshots.clear()
        self._update_readiness()
        return super().read_all(show_warning=show_warning)

    def write_all(self) -> None:
        """Apply changed native fields, then read back instrument-selected defaults.

        Raises:
            RuntimeError: Settings have not been read, or post-write readback fails.
            Exception: A driver write fails; read settings again before retrying.
        """
        changes = {channel: self._collect_channel(channel) for channel in self._channels}
        for channel, settings in changes.items():
            if not any(getattr(settings, field.name) is not None for field in fields(settings)):
                continue
            self._snapshots.pop(channel)
            self._update_readiness()
            self._engine.set_input_channel_settings(channel, settings)
            readback = self._engine.get_input_channel_settings(channel)
            if readback is None:
                raise RuntimeError(
                    f"Input {channel} was written but could not be read back. Use Read All before retrying."
                )
            self._populate_channel(channel, readback)
