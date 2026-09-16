"""Single set-and-read commands sharing the Keithley point-scan implementations."""

from qtpy.QtWidgets import QFormLayout, QVBoxLayout, QWidget

from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.plugins.state_scan.k6221_2182a import Keithley6221PointScanPlugin
from stoner_measurement.plugins.state_scan.keithley_2400 import Keithley2400PointScanPlugin
from stoner_measurement.ui.widgets import SISpinBox


class _KeithleySetCommand(CommandPlugin):
    """Own a point-acquisition plugin for the duration of a sequence.

    Unlike stateless commands these commands opt into instrument lifecycle:
    startup connects/configures, execution sets and reads, and sequence cleanup
    disables output and closes the instrument. The setpoint supports runtime
    expressions. There is no scan generator or child-step loop.
    """

    point_class = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._point_plugin = self.point_class(parent=self)
        self._apply_initial_config()

    @property
    def has_lifecycle(self):
        return True

    def connect(self):
        self._point_plugin.sequence_engine = self.sequence_engine
        self._point_plugin.connect()

    def configure(self):
        self._point_plugin.sequence_engine = self.sequence_engine
        self._point_plugin.configure()

    def disconnect(self):
        self._point_plugin.disconnect()

    def execute(self):
        """Apply one source value, retaining output for subsequent steps."""
        self._point_plugin.sequence_engine = self.sequence_engine
        self._point_plugin.set_state(self.eval_float(self._value))

    def reported_values(self):
        point = self._point_plugin
        prefix = point.instance_name + "."
        return {
            self.instance_name + "." + key[len(prefix):]: expression.replace(
                prefix, self.instance_name + "._point_plugin.", 1
            )
            for key, expression in point.reported_values().items()
            if key.startswith(prefix)
        }

    def reported_value_units(self):
        prefix = self._point_plugin.instance_name + "."
        return {
            self.instance_name + "." + key[len(prefix):]: unit
            for key, unit in self._point_plugin.reported_value_units().items()
            if key.startswith(prefix)
        }

    def to_json(self):
        data = super().to_json()
        data.update(value=self._value, instrument=self._point_plugin.to_json())
        return data

    def _restore_from_json(self, data):
        super()._restore_from_json(data)
        self._value = data.get("value", self._value)
        self._point_plugin._restore_from_json(data.get("instrument", {}))

    def config_widget(self, parent=None):
        self._point_plugin.sequence_engine = self.sequence_engine
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        value = SISpinBox(allow_expressions=True, value=self._value)
        value.setObjectName("source_value")
        value.setMinimum(-1e12)
        value.setMaximum(1e12)
        value.setToolTip("Source setpoint or runtime expression, in A for current or V for voltage.")
        value.valueChanged.connect(lambda number: setattr(self, "_value", number))
        form.addRow("Source value (A or V)", value)
        layout.addLayout(form)
        layout.addWidget(self._point_plugin._plugin_config_tabs())
        layout.addStretch()
        return widget


class Keithley2400SetCommand(_KeithleySetCommand):
    """Set a 2400 current or voltage and publish its single-point readings.

    Settings match the 2400 point scan, including compliance, wiring, ranges
    and triggering. Output remains active for later steps until sequence
    cleanup. Source value accepts expressions evaluated on every execution.
    """

    point_class = Keithley2400PointScanPlugin

    @property
    def name(self):
        return "Set Keithley 2400"


class Keithley6221SetCommand(_KeithleySetCommand):
    """Set 6221 DC current with independently optional voltage measurements.

    Enable either, both or neither the primary 2182A and secondary voltmeter.
    With neither enabled only source_value is published. Measurements and
    resistance calculation match the 6221 point scan. Output remains active
    for later steps and is disabled during sequence cleanup.
    """

    point_class = Keithley6221PointScanPlugin

    @property
    def name(self):
        return "Set Keithley 6221"
