"""Dummy plugin — ships with the package for demonstration and testing.

The :class:`DummyPlugin` computes the DC I-V characteristic of a resistively
shunted Josephson junction (RSJ model).  It requires no hardware and is useful
as a smoke-test and worked example.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from qtpy.QtWidgets import QFormLayout, QWidget
from scipy.constants import Boltzmann as kb

from stoner_measurement.core.trace_data import COLUMN_ROLE_Y, TraceData
from stoner_measurement.plugins.trace.base import TracePlugin, TraceStatus
from stoner_measurement.scan import FunctionScanGenerator
from stoner_measurement.ui.widgets import SISpinBox


class DummyPlugin(TracePlugin):
    """Generate simulated I-V data without using real hardware.

    Use this plugin for demonstrations, testing, and learning how trace
    measurements work in the application. It produces synthetic current-voltage
    data based on a simple Josephson-junction RSJ model, so you can build and
    run sequences without connecting any instruments.

    In the configuration panel, set the scan generator to choose the current
    values, then adjust the model parameters for critical current, normal
    resistance, and noise level. The result is a trace titled **RSJ I-V** with
    current on the x-axis and voltage on the y-axis.

    The configuration tabs include the standard trace scan-generator controls
    plus settings for the RSJ model, noise, and trace-wide voltage offset. The
    Help/About tab uses this docstring to explain both the physical meaning of
    those parameters and the fact that the plugin is entirely hardware-free.

    More technically, scan points are interpreted as applied current values
    *I* (in A). The corresponding voltage is computed from the DC RSJ model:

    * ``V = 0`` when ``|I| < I_c``
    * ``V = sign(I) × R_n × √(I² − I_c²)`` when ``|I| ≥ I_c``
    * ``V += N(0, V_n)`` — independent Gaussian noise added to every sample
    * ``V += N(0, V_offset)`` — one constant random offset added to the trace

    where *I_c* is the critical current, *R_n* is the normal-state
    resistance, and *V_n* is the noise standard deviation.

    Attributes:
        _critical_current (str):
            Python expression string for the critical current parameter.
        _normal_resistance (str):
            Python expression string for the normal-state resistance.
        _noise_level (str):
            Python expression string for the additive Gaussian noise level.
        _voltage_offset_scale (str):
            Python expression string for the trace-wide voltage-offset scale.
        _rounding_level (str):
            Python expression string controlling current rounding behaviour used
            by the implementation.

    Keyword Parameters:
        parent (QObject | None):
            Optional Qt parent object.

    Examples:
        >>> from qtpy.QtWidgets import QApplication
        >>> _ = QApplication.instance() or QApplication([])
        >>> plugin = DummyPlugin()
        >>> plugin.name
        'Dummy'
    """

    def __init__(self, parent=None) -> None:
        """Initialise the plugin with default RSJ parameters."""
        super().__init__(parent)
        self._critical_current: str = "1.0"
        self._normal_resistance: str = "1.0"
        self._noise_level: str = "0.0"
        self._voltage_offset_scale: str = "0.0"
        self._rounding_level = "0.0"
        self.scan_generator = FunctionScanGenerator(parent=self)
        self._apply_initial_config()

    @property
    def name(self) -> str:
        """Unique identifier for the dummy plugin."""
        return "Dummy"

    @property
    def x_units(self) -> str:
        """Physical units for the applied-current axis.

        Returns:
            (str):
                ``"A"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> DummyPlugin().x_units
            'A'
        """
        return "A"

    @property
    def y_units(self) -> str:
        """Physical units for the voltage axis.

        Returns:
            (str):
                ``"V"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> DummyPlugin().y_units
            'V'
        """
        return "V"

    @property
    def x_label(self) -> str:
        """Axis label for the applied current.

        Returns:
            (str):
                ``"I"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> DummyPlugin().x_label
            'I'
        """
        return "I"

    @property
    def y_label(self) -> str:
        """Axis label for the measured voltage.

        Returns:
            (str):
                ``"V"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> DummyPlugin().y_label
            'V'
        """
        return "V"

    def connect(self) -> None:
        """Initialise the dummy plugin.

        No real hardware is required; this simply marks the plugin as ready.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = DummyPlugin()
            >>> plugin.connect()
            >>> plugin.status is TraceStatus.IDLE
            True
        """
        self._set_status(TraceStatus.IDLE)

    def _eval_expr(self, expr: str) -> float:
        """Evaluate *expr* as a float using the sequence engine namespace.

        If the plugin is currently attached to a sequence engine, the
        expression is evaluated using
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval` so that
        numpy functions and all engine variables are available (e.g.
        ``"sqrt(R_n)"`` or ``"1e-3 * I_max"``).  When not attached to an
        engine (e.g. in standalone tests), a plain :func:`float` conversion is
        used as a fallback, which handles simple numeric literals such as
        ``"1.0"`` or ``"1e-3"``.

        Args:
            expr (str):
                Python expression that evaluates to a float.

        Returns:
            (float):
                The evaluated result.
        """
        try:
            return self.eval_float(expr)
        except RuntimeError:
            return float(expr)

    def _measure(self, parameters: dict[str, Any]) -> dict[str, TraceData]:
        """Return one simulated RSJ I-V dataset with optional Gaussian noise.

        Iterates over the scan generator, treating each scan-point value as an
        applied current *I*, and collects ``(I, V)`` for every point whose
        *measure* flag is ``True``.  The noiseless voltage is:

        * ``V = 0`` when ``|I| < I_c``
        * ``V = sign(I) × R_n × √(I² − I_c²)`` when ``|I| ≥ I_c``

        After all points are collected, independent Gaussian noise is added to
        the full voltage array:

        * ``V += np.random.normal(0, V_n, V.size)``

        The noisy current and voltage arrays are returned as one complete
        :class:`TraceData` dataset.

        All three parameters are evaluated as Python expressions via
        :meth:`_eval_expr`, which delegates to the sequence engine's
        :meth:`~stoner_measurement.plugins.base_plugin.BasePlugin.eval` method
        when the plugin is attached to an engine.

        Args:
            parameters (dict[str, Any]):
                Step-specific configuration.  Recognised keys:

                * ``"I_c"`` *(str | float)* — critical current expression in A.
                  Defaults to the expression set on the *Settings* tab
                  (initially ``"1.0"``).
                * ``"R_n"`` *(str | float)* — normal-state resistance expression
                  in Ω.  Defaults to the expression set on the *Settings* tab
                  (initially ``"1.0"``).
                * ``"V_n"`` *(str | float)* — noise standard deviation
                  expression in V.  Defaults to the expression set on the
                  *Settings* tab (initially ``"0.0"``).  Set to ``"0.0"`` for
                  noiseless output.
                * ``"V_offset"`` *(str | float)* — standard deviation of the
                  one normally distributed voltage offset applied uniformly to
                  the complete trace. Defaults to ``"0.0"``.

        Returns:
            (dict[str, TraceData]):
                A single dataset keyed by :attr:`name`.
        """
        i_c = self._eval_expr(str(parameters.get("I_c", self._critical_current)))
        r_n = self._eval_expr(str(parameters.get("R_n", self._normal_resistance)))
        v_n_expr = str(parameters.get("V_n", self._noise_level))
        offset_scale_expr = str(parameters.get("V_offset", self._voltage_offset_scale))
        rounding = self._eval_expr(str(parameters.get("Rounding", self._rounding_level)))

        current_values = self.scan_generator.generate()
        if rounding > 0:
            d_ic = np.sqrt(4 * kb * rounding * 1e10 / r_n)
            data = np.empty((current_values.size, 100))
            for ix, ic_ix in enumerate(np.random.normal(loc=i_c, scale=d_ic, size=100)):
                data[:, ix] = np.where(
                    np.abs(current_values) < ic_ix,
                    0.0,
                    r_n * np.sign(current_values) * np.sqrt(np.abs(current_values**2 - ic_ix**2)),
                )
            voltage_values = data.mean(axis=1)
        else:
            voltage_values = np.where(
                np.abs(current_values) < i_c,
                0.0,
                r_n * np.sign(current_values) * np.sqrt(np.abs(current_values**2 - i_c**2)),
            )

        v_n = self._eval_expr(v_n_expr)
        if v_n > 0.0:
            voltage_values += np.random.normal(0, v_n, voltage_values.size)

        offset_scale = self._eval_expr(offset_scale_expr)
        if offset_scale > 0.0:
            voltage_values += np.random.normal(0.0, offset_scale)

        frame = pd.DataFrame(
            {"x": np.asarray(current_values, dtype=float), "V": voltage_values}
        )
        return {
            self.name: TraceData(
                df=frame,
                column_roles={"V": COLUMN_ROLE_Y},
                names={"x": self.x_label, "V": self.y_label},
                units={"x": self.x_units, "V": self.y_units},
            )
        }

    def to_json(self) -> dict[str, Any]:
        """Serialise this plugin's configuration, including RSJ model parameters.

        Extends the base :meth:`~stoner_measurement.plugins.trace.base.TracePlugin.to_json`
        dict with the RSJ, noise, and ``"voltage_offset_scale"`` expressions
        configured on the *Settings* tab.

        Returns:
            (dict[str, Any]):
                A JSON-serialisable dictionary with at least the keys produced
                by :meth:`~stoner_measurement.plugins.trace.base.TracePlugin.to_json`
                plus ``"critical_current"``, ``"normal_resistance"``,
                ``"noise_level"``, and ``"voltage_offset_scale"``.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = DummyPlugin()
            >>> d = plugin.to_json()
            >>> d["critical_current"]
            '1.0'
            >>> d["normal_resistance"]
            '1.0'
            >>> d["noise_level"]
            '0.0'
        """
        data = super().to_json()
        for attr in [
            "critical_current",
            "normal_resistance",
            "noise_level",
            "rounding_level",
            "voltage_offset_scale",
        ]:
            data[attr] = getattr(self, f"_{attr}")
        return data

    def _restore_from_json(self, data: dict[str, Any]) -> None:
        """Restore RSJ model parameters from *data*.

        Calls the base implementation to restore the scan generator, then
        restores the ``_critical_current``, ``_normal_resistance``, and
        ``_noise_level`` expression strings if present in *data*.

        Args:
            data (dict[str, Any]):
                Serialised plugin dict as produced by :meth:`to_json`.
        """
        super()._restore_from_json(data)
        for attr in [
            "critical_current",
            "normal_resistance",
            "noise_level",
            "rounding_level",
            "voltage_offset_scale",
        ]:
            if attr in data:
                setattr(self, f"_{attr}", data.get(attr))

    def _plugin_config_tabs(self) -> QWidget:
        """Return a settings widget with expression-string controls for *I_c*, *R_n*, and *V_n*.

        Creates a :class:`~PyQt6.QtWidgets.QFormLayout` with SI-aware spin
        boxes, each accepting either a physical value or a Python expression
        string that will be evaluated via the sequence engine namespace at
        measurement time:

        * **I_c** — critical current in A (default ``"1.0"``).
        * **R_n** — normal-state resistance in Ω (default ``"1.0"``).
        * **V_n** — noise standard deviation in V (default ``"0.0"``).

        Returns:
            (QWidget):
                Configured settings widget for the *Settings* tab.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> from qtpy.QtWidgets import QWidget
            >>> isinstance(DummyPlugin()._plugin_config_tabs(), QWidget)
            True
        """
        widget = QWidget()
        layout = QFormLayout(widget)

        tooltip = (
            "Python expression evaluated in the sequence engine namespace. "
            "Simple numeric literals (e.g. '1.0', '1e-3') and numpy functions "
            "are supported."
        )

        i_c_edit = SISpinBox(
            value=self._critical_current, suffix="A", siPrefix=True, allow_expressions=True
        )
        i_c_edit.setToolTip(tooltip)

        r_n_edit = SISpinBox(
            value=self._normal_resistance, suffix="Ω", siPrefix=True, allow_expressions=True
        )
        r_n_edit.setToolTip(tooltip)

        v_n_edit = SISpinBox(
            value=self._noise_level, suffix="V", siPrefix=True, allow_expressions=True
        )
        v_n_edit.setToolTip(tooltip + " Use '0.0' for noiseless output.")

        offset_scale_edit = SISpinBox(
            value=self._voltage_offset_scale,
            suffix="V",
            siPrefix=True,
            allow_expressions=True,
        )
        offset_scale_edit.setToolTip(
            tooltip
            + " One value is drawn per measurement and added to every trace point."
        )

        rounding_edit = SISpinBox(
            value=self._rounding_level, suffix="K", siPrefix=True, allow_expressions=True
        )
        rounding_edit.setToolTip(tooltip + " Set scale for Ic variation.")

        def _update_i_c() -> None:
            self._critical_current = str(i_c_edit.value())

        def _update_r_n() -> None:
            self._normal_resistance = str(r_n_edit.value())

        def _update_v_n() -> None:
            self._noise_level = str(v_n_edit.value())

        def _update_offset_scale() -> None:
            self._voltage_offset_scale = str(offset_scale_edit.value())

        def _update_rounding() -> None:
            self._rounding_level = str(rounding_edit.value())

        i_c_edit.editingFinished.connect(_update_i_c)
        r_n_edit.editingFinished.connect(_update_r_n)
        v_n_edit.editingFinished.connect(_update_v_n)
        offset_scale_edit.editingFinished.connect(_update_offset_scale)
        rounding_edit.editingFinished.connect(_update_rounding)

        layout.addRow("Critical current I_c (A):", i_c_edit)
        layout.addRow("Normal resistance R_n (\u03a9):", r_n_edit)
        layout.addRow("Noise level V_n (V):", v_n_edit)
        layout.addRow("Voltage offset scale (V):", offset_scale_edit)
        layout.addRow("Thermal noise (K):", rounding_edit)
        return widget

    def _about_html(self) -> str:
        """Return an HTML description of the RSJ model for the *About* tab.

        Returns:
            (str):
                HTML-formatted description string.

        Examples:
            >>> from qtpy.QtWidgets import QApplication
            >>> _ = QApplication.instance() or QApplication([])
            >>> plugin = DummyPlugin()
            >>> "<h3>" in plugin._about_html()
            True
        """
        return (
            "<h3>Dummy Plugin \u2013 RSJ Model</h3>"
            "<p><i>Simulates the DC I-V characteristic of a resistively "
            "shunted Josephson junction with optional Gaussian noise. "
            "No hardware is required.</i></p>"
            "<p>Configure the scan generator on the <b>Scan</b> tab to set "
            "the applied current values at which voltages are computed.</p>"
            "<p>The voltage at each current point <i>I</i> is:</p>"
            "<ul>"
            "<li><code>V = 0</code> when "
            "<code>|I| &lt; I<sub>c</sub></code></li>"
            "<li><code>V = sign(I) &times; R<sub>n</sub> &times; "
            "&radic;(I&sup2; &minus; I<sub>c</sub>&sup2;)</code> "
            "when <code>|I| &ge; I<sub>c</sub></code></li>"
            "<li><code>V += N(0, V<sub>n</sub>)</code> &mdash; "
            "independent Gaussian noise added to every sample</li>"
            "<li><code>V += N(0, V<sub>offset</sub>)</code> &mdash; one "
            "constant random offset added to every sample in a measurement</li>"
            "</ul>"
            "<p>Set <code>I<sub>c</sub></code> (critical current), "
            "<code>R<sub>n</sub></code> (normal-state resistance), and "
            "<code>V<sub>n</sub></code> (noise standard deviation, as a "
            "Python expression) on the <b>Settings</b> tab. "
            "Use <code>V<sub>n</sub> = 0.0</code> for noiseless output. "
            "Configure trace-wide offset variation on the <b>Settings</b> tab.</p>"
        )
