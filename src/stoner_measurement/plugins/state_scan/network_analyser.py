"""Direct-driver point scan for network-analyser S-parameter measurements."""

from __future__ import annotations

from typing import Any

import numpy as np
from qtpy.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QWidget,
)

from stoner_measurement.plugins._network_analyser_point import (
    acquire_point,
    build_point_settings_widget,
    common_point_json,
    configure_point_analyser,
    connect_point_analyser,
    disconnect_point_analyser,
    initialise_point_measurement,
    restore_common_point_json,
)
from stoner_measurement.plugins._network_analyser_support import (
    NetworkAnalyserSweepVariable,
    s_parameter_units,
)
from stoner_measurement.plugins.state_scan.base import StateScanPlugin
from stoner_measurement.scan import BaseScanGenerator
from stoner_measurement.ui.widgets import SISpinBox


class NetworkAnalyserPointScanPlugin(StateScanPlugin):
    """Scan frequency or source power point-by-point and publish S-parameters.

    Use this state-scan plugin when sequence steps must run at every network-
    analyser state. At each generated point it sets the selected frequency and
    power, performs a short two-reading CW acquisition, averages each complex
    S-parameter, and publishes the requested scalar representations. Nested
    steps run after this point measurement and may consume its outputs or make
    measurements with other instruments, such as a lock-in amplifier.

    The **Scan** tab supplies the frequency or power points using the normal
    state-scan generators, including ramps, lists, and expression-based
    generators. The **Settings** tab selects the Agilent E5062A or N5222A,
    GPIB resource, channel, scan variable, complementary fixed setting, IF
    bandwidth, averaging, correction state, timeout, S-parameters, and output
    representation.

    The complementary fixed setting accepts either a number or a sequence
    expression and is evaluated again at every scan point. An inner frequency
    scan can therefore use the source power from an outer loop, or an inner
    power scan can use an outer-loop frequency. IF bandwidth and timeout also
    accept expressions; bandwidth is evaluated during configuration, while
    timeout is evaluated for each point acquisition.

    Published scalar outputs comprise the scanned state, point index,
    complementary fixed value, and each selected S-parameter. S-parameters may
    be represented as log magnitude in dB, linear magnitude, phase in degrees,
    real part, or imaginary part. When data collection is enabled, these
    outputs and outputs from nested steps can be selected on the **Data** tab.
    **Apply error correction** uses the channel's existing calibration and
    does not perform a calibration.

    On an N5222A, **External TTL RF gating** connects the rear-panel
    ``RFPulseModIn`` signal to the selected source modulator. This is digital
    carrier on/off gating, not analogue amplitude modulation. The gate remains
    enabled while the scan and its nested steps execute and is disabled during
    disconnect. The E5062A has no documented equivalent RF-gate input, so this
    control is unavailable for that model.

    Attributes:
        scan_generator (BaseScanGenerator):
            Generator providing frequency values in hertz or source-power
            values in dBm.
        _scan_variable (NetworkAnalyserSweepVariable):
            Quantity controlled by the scan generator.
        _selected_parameters (tuple[str, ...]):
            S-parameters published after each point acquisition.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        To measure a lock-in response under gated RF, configure a frequency
        scan with fixed power, enable **External TTL RF gating** on an N5222A,
        and place the lock-in measurement beneath this plugin in the sequence
        tree. The lock-in step then runs once at every configured frequency.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        initialise_point_measurement(self)
        self._scan_variable = NetworkAnalyserSweepVariable.FREQUENCY
        self._fixed_power_dbm: float | str = -10.0
        self._fixed_frequency_hz: float | str = 1.0e9
        self._target_value = 0.0
        self._last_fixed_value: float | None = None
        self._sync_scan_units()
        self._apply_initial_config()
        self._sync_scan_units()

    @property
    def name(self) -> str:
        return "NetworkAnalyserPointScan"

    @property
    def state_name(self) -> str:
        return (
            "Frequency"
            if self._scan_variable is NetworkAnalyserSweepVariable.FREQUENCY
            else "Source power"
        )

    @property
    def units(self) -> str:
        return (
            "Hz"
            if self._scan_variable is NetworkAnalyserSweepVariable.FREQUENCY
            else "dBm"
        )

    @property
    def fixed_state_name(self) -> str:
        return (
            "Source power"
            if self._scan_variable is NetworkAnalyserSweepVariable.FREQUENCY
            else "Frequency"
        )

    @property
    def fixed_units(self) -> str:
        return "dBm" if self.units == "Hz" else "Hz"

    def _sync_scan_units(self) -> None:
        self.scan_generator.units = self.units

    def set_scan_generator_class(self, cls: type[BaseScanGenerator]) -> None:
        super().set_scan_generator_class(cls)
        self._sync_scan_units()

    def connect(self) -> None:
        """Open the selected analyser and verify its exact model."""
        connect_point_analyser(self)

    def configure(self) -> None:
        """Configure a short CW acquisition and the selected measurement slots."""
        points = np.asarray(self.scan_generator.generate(), dtype=float)
        if len(points) == 0:
            raise ValueError("Scan generator produced no points.")
        initial_frequency = (
            float(points[0])
            if self._scan_variable is NetworkAnalyserSweepVariable.FREQUENCY
            else self.eval_float(self._fixed_frequency_hz)
        )
        configure_point_analyser(self, initial_frequency)

    def disconnect(self) -> None:
        """Disable any gate enabled by this plugin, then close the analyser."""
        disconnect_point_analyser(self)

    def _fixed_value(self) -> float:
        expression = (
            self._fixed_power_dbm
            if self._scan_variable is NetworkAnalyserSweepVariable.FREQUENCY
            else self._fixed_frequency_hz
        )
        return self.eval_float(expression)

    def set_state(self, value: float) -> None:
        """Program one state point, evaluate the fixed expression, and acquire."""
        target = float(value)
        fixed = self._fixed_value()
        if self._scan_variable is NetworkAnalyserSweepVariable.FREQUENCY:
            frequency_hz, power_dbm = target, fixed
        else:
            frequency_hz, power_dbm = fixed, target
        measured = acquire_point(self, frequency_hz, power_dbm)
        self._target_value = target
        self._last_fixed_value = fixed
        self._last_s_parameters = measured
        self.state_changed.emit(target)

    def get_state(self) -> float:
        return self._target_value

    def is_at_target(self) -> bool:
        return True

    def get_s_parameter(self, parameter: str) -> float | None:
        """Return the most recently acquired formatted S-parameter value."""
        return self._last_s_parameters.get(parameter.strip().upper())

    def reported_values(self) -> dict[str, str]:
        values = super().reported_values()
        var = self.instance_name
        values[f"{var}:{self.fixed_state_name}"] = f"{var}._last_fixed_value"
        for parameter in self._selected_parameters:
            values[f"{var}:{parameter}"] = f"{var}.get_s_parameter({parameter!r})"
        return values

    def reported_value_units(self) -> dict[str, str]:
        units = super().reported_value_units()
        var = self.instance_name
        units[f"{var}:{self.fixed_state_name}"] = self.fixed_units
        parameter_units = s_parameter_units(self._output_format)
        for parameter in self._selected_parameters:
            units[f"{var}:{parameter}"] = parameter_units
        return units

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data.update(
            {
                **common_point_json(self),
                "scan_variable": self._scan_variable.value,
                "fixed_power_dbm": self._fixed_power_dbm,
                "fixed_frequency_hz": self._fixed_frequency_hz,
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        super()._restore_from_json(data)
        restore_common_point_json(self, data)
        self._scan_variable = NetworkAnalyserSweepVariable(
            data.get("scan_variable", self._scan_variable.value)
        )
        self._fixed_power_dbm = data.get("fixed_power_dbm", self._fixed_power_dbm)
        self._fixed_frequency_hz = data.get(
            "fixed_frequency_hz", self._fixed_frequency_hz
        )
        self._sync_scan_units()

    def _plugin_config_tabs(self) -> QWidget:
        stimulus = QGroupBox("Point stimulus")
        stimulus_form = QFormLayout(stimulus)
        variable = QComboBox()
        variable.setObjectName("network_analyser_state_variable")
        variable.addItem("Frequency", NetworkAnalyserSweepVariable.FREQUENCY)
        variable.addItem("Source power", NetworkAnalyserSweepVariable.POWER)
        variable.setCurrentIndex(variable.findData(self._scan_variable))
        fixed_label = QLabel()
        fixed = SISpinBox(allow_expressions=True)
        fixed.setObjectName("network_analyser_state_fixed_value")
        fixed.setMinimum(-1.0e12)
        fixed.setMaximum(1.0e12)
        stimulus_form.addRow("Scan variable:", variable)
        stimulus_form.addRow(fixed_label, fixed)

        def sync_variable(index: int) -> None:
            self._scan_variable = variable.itemData(index)
            if self._scan_variable is NetworkAnalyserSweepVariable.FREQUENCY:
                fixed_label.setText("Fixed source power:")
                fixed.setSuffix("dBm")
                fixed.setValue(self._fixed_power_dbm)
            else:
                fixed_label.setText("Fixed frequency:")
                fixed.setSuffix("Hz")
                fixed.setValue(self._fixed_frequency_hz)
            self._sync_scan_units()

        def fixed_changed(value: float | str) -> None:
            if self._scan_variable is NetworkAnalyserSweepVariable.FREQUENCY:
                self._fixed_power_dbm = value
            else:
                self._fixed_frequency_hz = value

        variable.currentIndexChanged.connect(sync_variable)
        fixed.valueChanged.connect(fixed_changed)
        sync_variable(variable.currentIndex())
        return build_point_settings_widget(
            self, stimulus, object_prefix="network_analyser_state"
        )
