"""Per-sensor ITC503 software temperature scales imported from NI-DAQmx."""

from copy import deepcopy

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import QCheckBox, QComboBox, QLabel, QPushButton

from stoner_measurement.instruments.temperature_scales import (
    list_daqmx_scales,
    load_daqmx_temperature_scale,
)
from stoner_measurement.ui.temperature_panel import _InputSettingsTableWidget

_LEGACY = "__legacy_yaml__"


class ITC503InputSettingsTable(_InputSettingsTableWidget):
    """Select software temperature conversion independently for each ITC503 sensor.

    Args:
        engine (TemperatureControllerEngine): Owning controller session.
        parent (QWidget | None): Optional parent widget.
    """

    calibration_changed = Signal()
    _ROWS = (("scale", "NI-DAQmx scale"), ("direction", "Scale direction"))

    def __init__(self, engine, parent=None):
        self._snapshots = {}
        self._scale_names = ()
        super().__init__(engine, parent)
        self._write_button.setText("Apply")
        self._write_button.setToolTip("Apply software conversion and save YAML settings")
        hint = QLabel(
            "Scales convert temperatures in kelvin. Direction describes the NI table's "
            "pre-scaled → scaled columns. None leaves the sensor reading unchanged. "
            "Existing YAML lookup preserves the legacy shared calibration."
        )
        hint.setWordWrap(True)
        self.layout().insertWidget(0, hint)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self.layout().addWidget(self._status)
        refresh = QPushButton("Refresh NI Scale List")
        refresh.clicked.connect(self._refresh_scales)
        self.layout().addWidget(refresh, 0, Qt.AlignmentFlag.AlignLeft)
        self._reload_tables = QCheckBox("Reload selected tables from NI-DAQmx on Apply")
        self.layout().addWidget(self._reload_tables)
        self.layout().addStretch()

    def set_curve_names(self, curve_names):
        """Ignore hardware calibration curves; this editor uses software scales."""

    def _make_channel_editors(self):
        """Create scale and direction selectors for one sensor column."""
        scale = QComboBox()
        self._populate_scales(scale)
        direction = QComboBox()
        direction.addItem("ITC503 → Corrected", "nominal_to_corrected")
        direction.addItem("Corrected → ITC503", "corrected_to_nominal")
        scale.currentIndexChanged.connect(
            lambda _index: direction.setEnabled(scale.currentData() not in (None, _LEGACY))
        )
        direction.setEnabled(False)
        return {"scale": scale, "direction": direction}

    def _populate_scales(self, combo):
        """Retain saved names even when NI-DAQmx is unavailable."""
        selected = combo.currentData()
        combo.clear()
        combo.addItem("None", None)
        combo.addItem("Existing YAML lookup", _LEGACY)
        saved_names = {s["scale_name"] for s in self._snapshots.values() if s is not None}
        if selected not in (None, _LEGACY):
            saved_names.add(selected)
        for name in sorted(set(self._scale_names) | saved_names):
            combo.addItem(name, name)
        if selected is not None:
            combo.setCurrentIndex(max(0, combo.findData(selected)))

    def _refresh_scales(self):
        """Refresh the local scale names while preserving pending selections."""
        try:
            self._scale_names = list_daqmx_scales()
            self._status.setText("NI scale list refreshed. Saved tables remain available offline.")
        except RuntimeError as exc:
            self._status.setText(str(exc) + " Saved tables and None remain available.")
        for editors in self._editors.values():
            self._populate_scales(editors["scale"])

    def read_all(self, *, show_warning=True):
        """Load active software selections and discover saved NI scale names.

        Keyword Parameters:
            show_warning (bool): Retained for the common input-editor interface.

        Returns:
            (bool): Whether a connected ITC503 supplied its current settings.
        """
        self._table.setEnabled(False)
        self._write_button.setEnabled(False)
        try:
            self._snapshots = self._engine.get_itc503_temperature_scales()
        except RuntimeError as exc:
            self._status.setText(str(exc))
            return False
        self._refresh_scales()
        for channel, editors in self._editors.items():
            snapshot = self._snapshots.get(channel)
            selected = (
                _LEGACY
                if channel not in self._snapshots
                else (snapshot["scale_name"] if snapshot is not None else None)
            )
            editors["scale"].setCurrentIndex(editors["scale"].findData(selected))
            direction = snapshot["direction"] if snapshot is not None else "nominal_to_corrected"
            editors["direction"].setCurrentIndex(editors["direction"].findData(direction))
            editors["direction"].setEnabled(selected not in (None, _LEGACY))
        ready = bool(self._channels)
        self._table.setEnabled(ready)
        self._write_button.setEnabled(ready)
        return ready

    def write_all(self):
        """Validate every selection before applying and saving all sensor scales.

        Raises:
            RuntimeError: If NI-DAQmx cannot load a newly selected scale.
            ValueError: If a selected table is unsuitable for temperature conversion.
            OSError: If the YAML settings cannot be saved.
        """
        if not self._write_button.isEnabled():
            raise RuntimeError("Read input settings before applying software temperature scales.")
        scales = {}
        for channel, editors in self._editors.items():
            name = editors["scale"].currentData()
            if name == _LEGACY:
                continue
            if name is None:
                scales[channel] = None
                continue
            previous = self._snapshots.get(channel)
            reuse_saved = (
                previous and previous["scale_name"] == name and not self._reload_tables.isChecked()
            )
            snapshot = deepcopy(previous) if reuse_saved else load_daqmx_temperature_scale(name)
            snapshot["direction"] = editors["direction"].currentData()
            scales[channel] = snapshot
        self._engine.set_itc503_temperature_scales(scales)
        self._snapshots = deepcopy(scales)
        self._reload_tables.setChecked(False)
        self._status.setText("Software temperature scales applied and saved to YAML.")
        self.calibration_changed.emit()
