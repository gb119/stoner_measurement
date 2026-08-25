"""One-off CW network-analyser set-and-measure command."""

from __future__ import annotations

from typing import Any

from qtpy.QtWidgets import QFormLayout, QGroupBox, QWidget

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
from stoner_measurement.plugins._network_analyser_support import s_parameter_units
from stoner_measurement.plugins.command.base import CommandPlugin
from stoner_measurement.ui.widgets import SISpinBox


class NetworkAnalyserSetCommand(CommandPlugin):
    """Perform one CW network-analyser set-and-measure operation.

    Use this command when a sequence needs one network-analyser reading rather
    than an analyser-controlled trace or a point-by-point scan loop. Each
    invocation connects to the selected Agilent E5062A or N5222A, evaluates
    the requested frequency, source power, and IF bandwidth, configures a
    short two-reading CW acquisition, averages each complex S-parameter, and
    disconnects after publishing the results.

    The configuration page contains expression-capable **Frequency**,
    **Source power**, **IF bandwidth**, and **Point timeout** controls. Each is
    evaluated in the live sequence namespace whenever the command executes.
    This makes the command suitable beneath an outer temperature, field,
    frequency, or power loop without creating another scan container. The
    remaining controls select the analyser model and GPIB resource, channel,
    averaging, existing correction state, S-parameters, and scalar output
    representation.

    The command publishes **Frequency** in hertz, **Source power** in dBm, and
    one output for each selected S-parameter. S-parameters may be represented
    as log magnitude in dB, linear magnitude, phase in degrees, real part, or
    imaginary part. **Apply error correction** uses the calibration already
    active in the selected channel; the command does not create or replace a
    calibration.

    This is a leaf command and cannot contain nested sequence steps. On an
    N5222A, external TTL RF gating applies only during the command's own CW
    acquisition and is disabled before disconnect. Use
    :class:`~stoner_measurement.plugins.state_scan.network_analyser.NetworkAnalyserPointScanPlugin`
    when the RF gate must remain active while a nested lock-in or other device
    measurement runs. The E5062A has no documented equivalent RF-gate input.

    Attributes:
        _frequency_hz (float | str):
            CW frequency or sequence expression in hertz.
        _power_dbm (float | str):
            Source power or sequence expression in dBm.
        _if_bandwidth_hz (float | str):
            IF bandwidth or sequence expression in hertz.
        _selected_parameters (tuple[str, ...]):
            S-parameters published by the most recent execution.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        Place this command inside a temperature scan and enter expressions
        such as ``measurement_frequency`` and ``rf_power`` for its frequency
        and power. Every outer-loop iteration then performs one CW acquisition
        using the current values of those sequence variables.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        initialise_point_measurement(self)
        self._frequency_hz: float | str = 1.0e9
        self._power_dbm: float | str = -10.0
        self._last_frequency_hz: float | None = None
        self._last_power_dbm: float | None = None
        self._apply_initial_config()

    @property
    def name(self) -> str:
        return "Set Network Analyser"

    def execute(self) -> None:
        """Perform one complete CW point measurement."""
        frequency_hz = self.eval_float(self._frequency_hz)
        power_dbm = self.eval_float(self._power_dbm)
        try:
            connect_point_analyser(self)
            configure_point_analyser(self, frequency_hz)
            acquire_point(self, frequency_hz, power_dbm)
            self._last_frequency_hz = frequency_hz
            self._last_power_dbm = power_dbm
        finally:
            disconnect_point_analyser(self)

    def get_s_parameter(self, parameter: str) -> float | None:
        """Return the most recently acquired formatted S-parameter."""
        return self._last_s_parameters.get(parameter.strip().upper())

    def reported_values(self) -> dict[str, str]:
        var = self.instance_name
        values = {
            f"{var}:Frequency": f"{var}._last_frequency_hz",
            f"{var}:Source power": f"{var}._last_power_dbm",
        }
        for parameter in self._selected_parameters:
            values[f"{var}:{parameter}"] = f"{var}.get_s_parameter({parameter!r})"
        return values

    def reported_value_units(self) -> dict[str, str]:
        var = self.instance_name
        units = {
            f"{var}:Frequency": "Hz",
            f"{var}:Source power": "dBm",
        }
        parameter_units = s_parameter_units(self._output_format)
        for parameter in self._selected_parameters:
            units[f"{var}:{parameter}"] = parameter_units
        return units

    def to_json(self) -> dict[str, Any]:
        data = super().to_json()
        data.update(
            {
                **common_point_json(self),
                "frequency_hz": self._frequency_hz,
                "power_dbm": self._power_dbm,
            }
        )
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        super()._restore_from_json(data)
        restore_common_point_json(self, data)
        self._frequency_hz = data.get("frequency_hz", self._frequency_hz)
        self._power_dbm = data.get("power_dbm", self._power_dbm)

    def config_widget(self, parent: QWidget | None = None) -> QWidget:
        stimulus = QGroupBox("Point stimulus", parent)
        form = QFormLayout(stimulus)
        frequency = SISpinBox(
            allow_expressions=True, suffix="Hz", value=self._frequency_hz
        )
        frequency.setObjectName("network_analyser_set_frequency")
        frequency.setMinimum(0.0)
        frequency.setMaximum(1.0e12)
        frequency.setToolTip(
            "Frequency or sequence expression evaluated when this command runs."
        )
        power = SISpinBox(
            allow_expressions=True, suffix="dBm", value=self._power_dbm
        )
        power.setObjectName("network_analyser_set_power")
        power.setMinimum(-200.0)
        power.setMaximum(100.0)
        power.setToolTip(
            "Source power or sequence expression evaluated when this command runs."
        )
        form.addRow("Frequency:", frequency)
        form.addRow("Source power:", power)
        frequency.valueChanged.connect(
            lambda value: setattr(self, "_frequency_hz", value)
        )
        power.valueChanged.connect(lambda value: setattr(self, "_power_dbm", value))
        return build_point_settings_widget(
            self, stimulus, object_prefix="network_analyser_set"
        )
